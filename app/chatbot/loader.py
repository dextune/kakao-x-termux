from __future__ import annotations

import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from app.pydantic_compat import ValidationError

from app import repository
from app.chatbot.file_state import BotFileSnapshot, snapshot_bot_package
from app.chatbot.legacy import LegacyBotAdapter
from app.chatbot.message_store import ReadOnlyMessageStore
from app.chatbot.module import BotDefinition, BotHandler, BotRuntime
from app.chatbot.options import BotOptionStore, validate_default_options, validate_option_schema
from app.chatbot.registry import ChatbotRegistry, RegisteredBot
from app.chatbot.state_store import BotStateStore
from app.config import get_settings
from app.infra.async_writes import enqueue_bridge_log
from app.time_utils import now_millis


REQUIRED_FUNCTIONS = ("get_bot_definition", "initialize", "can_handle", "handle", "shutdown")
BOT_FOLDER_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass
class BotLoadResult:
    """봇 파일 하나를 로딩한 결과다."""

    path: Path
    snapshot: BotFileSnapshot
    bot: RegisteredBot | None
    bot_key: str | None
    error: str | None
    duration_ms: int

    @property
    def ok(self) -> bool:
        return self.bot is not None and self.error is None


class ChatbotLoader:
    """`app/bots` 폴더를 스캔해 유효한 봇 모듈만 registry에 등록한다."""

    def __init__(
        self,
        bot_dir: str | Path,
        registry: ChatbotRegistry,
        state_store: BotStateStore | None = None,
        option_store: BotOptionStore | None = None,
        external_runner=None,
        http_client=None,
    ) -> None:
        self.bot_dir = _resolve_bot_dir(Path(bot_dir))
        self.registry = registry
        self.state_store = state_store or BotStateStore()
        self.option_store = option_store or BotOptionStore()
        self.external_runner = external_runner
        self.http_client = http_client
        self.logger = logging.getLogger("app.chatbot.loader")

    def iter_bot_files(self) -> list[Path]:
        """로딩 대상 `app/bots/{kebab-case}/bot.py` 목록을 안정적인 순서로 반환한다."""

        if not self.bot_dir.exists():
            enqueue_bridge_log("WARN", "chatbot", f"bot dir not found: {self.bot_dir}")
            return []
        return [
            path / "bot.py"
            for path in sorted(self.bot_dir.iterdir())
            if path.is_dir()
            and not path.name.startswith("_")
            and not path.name.startswith(".")
            and path.name != "__pycache__"
        ]

    def scan(self) -> list[RegisteredBot]:
        loaded: list[RegisteredBot] = []
        for path in self.iter_bot_files():
            result = self.load_candidate(path)
            if result.ok and result.bot is not None:
                if not self.registry.register(result.bot):
                    self._record_failure(result.snapshot, result.bot_key, f"duplicate bot key: {result.bot_key}")
                    continue
                self._record_success(result.snapshot, result.bot)
                loaded.append(result.bot)
        return loaded

    def load_candidate(self, path: Path) -> BotLoadResult:
        """봇 파일을 import/검증/초기화하되 registry에는 연결하지 않는다."""

        started = time.monotonic()
        settings = get_settings()
        snapshot = snapshot_bot_package(path, include_hash=settings.chatbot_file_hash_enabled)
        module: ModuleType | None = None
        try:
            _validate_bot_package(path)
            bot_file_size = path.stat().st_size
            if bot_file_size > max(settings.chatbot_max_bot_file_bytes, 1):
                raise ValueError(
                    f"bot file too large: {bot_file_size} > {settings.chatbot_max_bot_file_bytes}"
                )
            module = _import_module(path, snapshot)
            handler = self._load_handler(module)
            definition = BotDefinition.model_validate(handler.get_definition())
            self._validate_definition(definition)
            runtime = BotRuntime(
                botKey=definition.key,
                logger=logging.getLogger(f"app.bots.{definition.key}"),
                stateStore=self.state_store,
                optionStore=self.option_store,
                nowMillis=now_millis,
                messageStore=ReadOnlyMessageStore(),
                botRegistry=self.registry,
                externalRunner=self.external_runner,
                httpClient=self.http_client,
            )
            handler.initialize(runtime)
            bot = RegisteredBot(definition=definition, handler=handler, sourceModule=module, runtime=runtime)
            duration_ms = int((time.monotonic() - started) * 1000)
            if duration_ms > max(settings.chatbot_bot_load_timeout_ms, 1):
                enqueue_bridge_log(
                    "WARN",
                    "chatbot",
                    f"bot load exceeded target botKey={definition.key} durationMs={duration_ms}",
                    definition.key,
                )
            return BotLoadResult(path, snapshot, bot, definition.key, None, duration_ms)
        except (ImportError, ValidationError, ValueError, RuntimeError) as exc:
            _drop_candidate_module(module)
            return self._failed_result(path, snapshot, started, exc, "load")
        except Exception as exc:
            _drop_candidate_module(module)
            return self._failed_result(path, snapshot, started, exc, "initialize")

    def _failed_result(
        self,
        path: Path,
        snapshot: BotFileSnapshot,
        started: float,
        exc: Exception,
        stage: str,
    ) -> BotLoadResult:
        display_path = _display_path(path)
        message = f"failed to {stage} bot {display_path}: {exc.__class__.__name__}: {exc}"
        enqueue_bridge_log("ERROR", "chatbot", message, ref_id=display_path)
        self.logger.exception(message)
        return BotLoadResult(
            path=path,
            snapshot=snapshot,
            bot=None,
            bot_key=None,
            error=message,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def _load_handler(self, module: ModuleType) -> BotHandler:
        create_bot = getattr(module, "create_bot", None)
        if callable(create_bot):
            handler = create_bot()
            if not isinstance(handler, BotHandler):
                raise ValueError("create_bot returned invalid bot handler")
            return handler
        for name in REQUIRED_FUNCTIONS:
            if not callable(getattr(module, name, None)):
                raise ValueError(f"required function missing: {name}")
        return LegacyBotAdapter(module)

    def _validate_definition(self, definition: BotDefinition) -> None:
        settings = get_settings()
        if len(definition.patterns) > max(settings.chatbot_max_pattern_count_per_bot, 1):
            raise ValueError(
                f"too many patterns: {len(definition.patterns)} > {settings.chatbot_max_pattern_count_per_bot}"
            )
        option_bytes = len(json.dumps(definition.defaultOptions, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        if option_bytes > max(settings.chatbot_max_option_bytes, 1):
            raise ValueError(f"default options too large: {option_bytes} > {settings.chatbot_max_option_bytes}")
        validate_option_schema(definition.optionSchema)
        validate_default_options(definition.defaultOptions, definition.optionSchema)

    def _record_success(self, snapshot: BotFileSnapshot, bot: RegisteredBot) -> None:
        repository.upsert_chatbot_module(
            bot_key=bot.definition.key,
            name=bot.definition.name,
            version=bot.definition.version,
            enabled=bot.definition.enabled,
            priority=bot.definition.priority,
            options=bot.definition.defaultOptions,
        )
        repository.upsert_chatbot_module_file(
            path=snapshot.path,
            file_name=snapshot.file_name,
            size_bytes=snapshot.size_bytes,
            mtime_ns=snapshot.mtime_ns,
            sha256=snapshot.sha256,
            bot_key=bot.definition.key,
            status="loaded",
            last_error=None,
            loaded_at=now_millis(),
        )

    def _record_failure(
        self,
        snapshot: BotFileSnapshot,
        bot_key: str | None,
        error: str,
        mark_module: bool = True,
    ) -> None:
        repository.upsert_chatbot_module_file(
            path=snapshot.path,
            file_name=snapshot.file_name,
            size_bytes=snapshot.size_bytes,
            mtime_ns=snapshot.mtime_ns,
            sha256=snapshot.sha256,
            bot_key=bot_key,
            status="failed",
            last_error=error,
            loaded_at=None,
        )
        if bot_key is not None and mark_module:
            repository.mark_chatbot_module_error(bot_key, error)


def _import_module(path: Path, snapshot: BotFileSnapshot) -> ModuleType:
    folder = path.parent.name.replace("-", "_")
    module_name = f"app.bots._loaded_{folder}_{abs(hash((snapshot.path, snapshot.mtime_ns, snapshot.size_bytes)))}"
    module = ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = "app.bots"
    try:
        sys.modules[module_name] = module
        source = path.read_text(encoding="utf-8")
        code = compile(source, str(path), "exec")
        exec(code, module.__dict__)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _drop_candidate_module(module: ModuleType | None) -> None:
    if module is not None:
        sys.modules.pop(module.__name__, None)


def _resolve_bot_dir(path: Path) -> Path:
    if path.exists():
        return path
    if str(path) == "app/bots":
        return Path(__file__).resolve().parents[1] / "bots"
    return path


def _validate_bot_package(path: Path) -> None:
    folder = path.parent.name
    if not BOT_FOLDER_RE.match(folder):
        raise ValueError(f"bot folder must be kebab-case: {folder}")
    if not path.exists():
        raise ValueError("bot.py missing")
    if not (path.parent / "bot.md").exists():
        raise ValueError("bot.md missing")


def _display_path(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"
