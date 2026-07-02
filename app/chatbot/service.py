from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from app import repository
from app.chatbot.file_state import BotLoadState, snapshot_bot_package, snapshot_changed
from app.chatbot.loader import ChatbotLoader
from app.chatbot.options import BotOptionStore
from app.chatbot.processor import ChatbotProcessor
from app.chatbot.registry import RegisteredBot
from app.chatbot.registry import ChatbotRegistry
from app.chatbot.state_store import BotStateStore
from app.config import get_settings
from app.infra.async_writes import enqueue_bridge_log
from app.infra.runtime_resources import (
    RuntimeResources,
    get_bot_external_runner_proxy,
    get_http_client_proxy,
    get_runtime_resources,
)
from app.schemas import BridgeEvent, EventResponse, RoomRuleResponse
from app.time_utils import now_millis


class ChatbotService:
    """챗봇 registry, loader, processor의 lifecycle과 운영 상태를 관리한다."""

    def __init__(self, resources_provider: Callable[[], RuntimeResources] = get_runtime_resources) -> None:
        self._resources_provider = resources_provider
        self.registry = ChatbotRegistry()
        self.state_store = BotStateStore(
            snapshot_writer_provider=lambda: self._resources_provider().memory_pipeline.writer,
        )
        self.option_store = BotOptionStore()
        self.processor = ChatbotProcessor(
            self.registry,
            option_store=self.option_store,
            config_cache_provider=lambda: self._resources_provider().config_cache,
        )
        self.last_reload_at: int | None = None
        self.last_loaded_count = 0
        self.last_scan_at: int | None = None
        self.last_scan_duration_ms: int | None = None
        self.last_scan_error: str | None = None
        self.reload_in_progress = False
        self._file_states: dict[str, BotLoadState] = {}
        self._reload_lock = threading.RLock()
        self._watcher_stop = threading.Event()
        self._watcher_thread: threading.Thread | None = None
        self._shutting_down = False
        self._logger = logging.getLogger("app.chatbot.service")

    def startup(self) -> int:
        self._shutting_down = False
        self.state_store.startup()
        count = self.reload()
        settings = get_settings()
        if settings.memory_config_warmup_enabled:
            self._resources_provider().config_cache.warmup()
        self._start_watcher()
        return count

    def shutdown(self) -> None:
        self._shutting_down = True
        self._stop_watcher()
        bots = self.registry.snapshot()
        self.registry.shutdown_all()
        for bot in bots:
            self._drop_module(bot)
        self._file_states.clear()
        self.state_store.shutdown()

    def reload(self) -> int:
        """설정된 bot directory를 스캔해 중앙 registry를 증분 갱신한다."""

        with self._reload_lock:
            return self._reload_locked()

    def reload_if_idle(self) -> int:
        """watcher tick에서 중복 reload를 피하기 위해 lock 획득 시에만 스캔한다."""

        acquired = self._reload_lock.acquire(blocking=False)
        if not acquired:
            return self.last_loaded_count
        try:
            return self._reload_locked()
        finally:
            self._reload_lock.release()

    def _reload_locked(self) -> int:
        settings = get_settings()
        self.reload_in_progress = True
        self.last_reload_at = now_millis()
        started = time.monotonic()
        try:
            if self._shutting_down:
                return self.last_loaded_count
            if not settings.chatbot_enabled:
                bots = self.registry.snapshot()
                self.registry.shutdown_all()
                for bot in bots:
                    self._drop_module(bot)
                self._file_states.clear()
                self.last_loaded_count = 0
                return 0
            loader = ChatbotLoader(
                settings.chatbot_bot_dir,
                self.registry,
                state_store=self.state_store,
                option_store=self.option_store,
                external_runner=get_bot_external_runner_proxy(),
                http_client=get_http_client_proxy(),
            )
            self._scan_incremental(loader, settings)
            self.last_loaded_count = len(self.registry.snapshot())
            self.last_scan_error = None
        except Exception as exc:
            self.last_scan_error = str(exc)
            enqueue_bridge_log("ERROR", "chatbot", f"chatbot reload failed: {exc}")
            self._logger.exception("chatbot reload failed")
        finally:
            self.last_scan_at = now_millis()
            self.last_scan_duration_ms = int((time.monotonic() - started) * 1000)
            self.reload_in_progress = False
            try:
                self._resources_provider().config_cache.invalidate_module_rows()
            except Exception:
                pass
        return self.last_loaded_count

    def process(self, event: BridgeEvent, room_rule: RoomRuleResponse | None) -> EventResponse:
        return self.processor.process(event, room_rule)

    def health(self) -> dict:
        loaded_count = len(self.registry.all())
        recent_errors = repository.count_bridge_logs(level="ERROR", category="chatbot", limit=200)
        failed_count = repository.count_chatbot_modules_with_errors()
        failed_files = repository.count_chatbot_module_files(status="failed")
        settings = get_settings()
        health = {
            "ok": True,
            "loadedBots": loaded_count,
            "failedBots": failed_count,
            "failedFiles": failed_files,
            "matchers": self.processor.matcher_registry.count(),
            "lastReloadAt": self.last_reload_at,
            "lastScanAt": self.last_scan_at,
            "lastScanDurationMs": self.last_scan_duration_ms,
            "lastScanError": self.last_scan_error,
            "recentErrorCount": recent_errors,
            "watcherEnabled": settings.chatbot_hot_reload_enabled,
            "watcherIntervalMs": settings.chatbot_hot_reload_interval_ms,
            "reloadInProgress": self.reload_in_progress,
        }
        health.update(self._resources_provider().stats())
        health["stateCache"] = self.state_store.stats()
        return health

    def module_files(self, status: str | None = None, limit: int = 100) -> list[dict]:
        """인증된 운영 API에서 노출할 봇 파일 상태를 반환한다."""

        return [
            {
                "path": row["path"],
                "fileName": row["file_name"],
                "sizeBytes": row["size_bytes"],
                "mtimeNs": row["mtime_ns"],
                "sha256": row["sha256"],
                "botKey": row["bot_key"],
                "status": row["status"],
                "lastError": row["last_error"],
                "loadedAt": row["loaded_at"],
                "updatedAt": row["updated_at"],
            }
            for row in repository.list_chatbot_module_files(status=status, limit=limit)
        ]

    def _scan_incremental(self, loader: ChatbotLoader, settings) -> None:
        paths = loader.iter_bot_files()
        if len(paths) > max(settings.chatbot_max_loaded_bots, 1):
            enqueue_bridge_log(
                "WARN",
                "chatbot",
                f"bot file count exceeds limit count={len(paths)} max={settings.chatbot_max_loaded_bots}",
            )
            paths = paths[: settings.chatbot_max_loaded_bots]

        current: dict[str, Path] = {str(path.resolve()): path for path in paths}
        current_snapshots = {
            resolved: snapshot_bot_package(path, include_hash=settings.chatbot_file_hash_enabled)
            for resolved, path in current.items()
        }

        for removed_path in sorted(set(self._file_states) - set(current)):
            self._remove_path(removed_path)

        processed = 0
        max_files = max(settings.chatbot_reload_max_files_per_tick, 1)
        initial_load = not self._file_states
        for resolved, path in sorted(current.items()):
            previous = self._file_states.get(resolved)
            snapshot = current_snapshots[resolved]
            retry_failed_duplicate = (
                previous is not None
                and previous.status == "failed"
                and previous.last_error is not None
                and "duplicate bot key" in previous.last_error
            )
            if not snapshot_changed(previous.snapshot if previous else None, snapshot) and not retry_failed_duplicate:
                continue
            if not initial_load and processed >= max_files:
                enqueue_bridge_log(
                    "WARN",
                    "chatbot",
                    f"reload file limit reached maxFiles={max_files}; remaining changes deferred",
                )
                break
            processed += 1
            self._load_changed_path(loader, path, previous)

    def _load_changed_path(
        self,
        loader: ChatbotLoader,
        path: Path,
        previous: BotLoadState | None,
    ) -> None:
        result = loader.load_candidate(path)
        if not result.ok or result.bot is None:
            bot_key = previous.bot_key if previous is not None else result.bot_key
            error = result.error or "unknown bot load failure"
            self._file_states[result.snapshot.path] = BotLoadState(
                snapshot=result.snapshot,
                bot_key=bot_key,
                status="failed",
                last_error=error,
            )
            loader._record_failure(result.snapshot, bot_key, error)
            return

        existing_path = self._path_for_bot_key(result.bot.definition.key)
        if existing_path is not None and existing_path != result.snapshot.path:
            error = f"duplicate bot key: {result.bot.definition.key}"
            retained_key = previous.bot_key if previous is not None and previous.bot_key else result.bot.definition.key
            self._file_states[result.snapshot.path] = BotLoadState(
                snapshot=result.snapshot,
                bot_key=retained_key,
                status="failed",
                last_error=error,
            )
            loader._record_failure(result.snapshot, retained_key, error, mark_module=False)
            self._shutdown_bot(result.bot)
            self._drop_module(result.bot)
            return

        old_bots: list[RegisteredBot] = []
        if previous is not None and previous.bot_key and previous.bot_key != result.bot.definition.key:
            removed = self.registry.unregister(previous.bot_key)
            if removed is not None:
                old_bots.append(removed)
        replaced = self.registry.replace(result.bot)
        if replaced is not None and replaced is not result.bot:
            old_bots.append(replaced)
        for old_bot in old_bots:
            self._shutdown_bot(old_bot)
            self._drop_module(old_bot)

        loaded_at = now_millis()
        self._file_states[result.snapshot.path] = BotLoadState(
            snapshot=result.snapshot,
            bot_key=result.bot.definition.key,
            status="loaded",
            last_error=None,
            loaded_at=loaded_at,
        )
        loader._record_success(result.snapshot, result.bot)

    def _remove_path(self, path: str) -> None:
        state = self._file_states.pop(path, None)
        if state is None:
            return
        if state.bot_key:
            should_unregister = state.status == "loaded" or self._path_for_bot_key(state.bot_key, exclude_path=path) is None
            if should_unregister:
                removed = self.registry.unregister(state.bot_key)
                if removed is not None:
                    self._shutdown_bot(removed)
                    self._drop_module(removed)
        repository.upsert_chatbot_module_file(
            path=state.snapshot.path,
            file_name=state.snapshot.file_name,
            size_bytes=state.snapshot.size_bytes,
            mtime_ns=state.snapshot.mtime_ns,
            sha256=state.snapshot.sha256,
            bot_key=state.bot_key,
            status="removed",
            last_error=None,
            loaded_at=state.loaded_at,
        )

    def _path_for_bot_key(self, bot_key: str, exclude_path: str | None = None) -> str | None:
        for path, state in self._file_states.items():
            if path != exclude_path and state.status == "loaded" and state.bot_key == bot_key:
                return path
        return None

    def _shutdown_bot(self, bot: RegisteredBot) -> None:
        try:
            bot.handler.shutdown()
        except Exception as exc:
            enqueue_bridge_log("WARN", "chatbot", f"bot shutdown failed botKey={bot.definition.key}: {exc}")
            self._logger.warning("bot shutdown failed botKey=%s error=%s", bot.definition.key, exc)

    def _drop_module(self, bot: RegisteredBot) -> None:
        """registry에서 빠진 동적 봇 모듈의 sys.modules 참조를 제거한다."""

        module_name = getattr(bot.module, "__name__", None)
        if module_name:
            sys.modules.pop(module_name, None)

    def _start_watcher(self) -> None:
        settings = get_settings()
        if not settings.chatbot_enabled:
            return
        if not settings.chatbot_hot_reload_enabled and not settings.memory_config_reconcile_enabled:
            return
        if self._watcher_thread is not None and self._watcher_thread.is_alive():
            return
        self._watcher_stop.clear()
        self._watcher_thread = threading.Thread(
            target=self._watcher_loop,
            name="chatbot-hot-reload",
            daemon=True,
        )
        self._watcher_thread.start()

    def _stop_watcher(self) -> None:
        self._watcher_stop.set()
        thread = self._watcher_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
        self._watcher_thread = None

    def _watcher_loop(self) -> None:
        next_config_reconcile = 0.0
        while True:
            settings = get_settings()
            waits = []
            if settings.chatbot_hot_reload_enabled:
                waits.append(max(settings.chatbot_hot_reload_interval_ms, 100))
            if settings.memory_config_reconcile_enabled:
                waits.append(max(settings.memory_config_reconcile_interval_ms, 100))
            wait_ms = min(waits) if waits else 1_000
            if self._watcher_stop.wait(wait_ms / 1000):
                return
            try:
                if self._shutting_down:
                    return
                settings = get_settings()
                if settings.chatbot_hot_reload_enabled:
                    self.reload_if_idle()
                now = time.monotonic()
                if settings.memory_config_reconcile_enabled and now >= next_config_reconcile:
                    self._resources_provider().config_cache.reconcile()
                    next_config_reconcile = now + max(settings.memory_config_reconcile_interval_ms, 100) / 1000
            except Exception as exc:
                self.last_scan_error = str(exc)
                enqueue_bridge_log("ERROR", "chatbot", f"chatbot maintenance tick failed: {exc}")
                self._logger.exception("chatbot watcher tick failed")
