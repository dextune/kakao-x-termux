from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from typing import Any

from app.chatbot.context import ChatContext
from app.chatbot.decision import ChatDecision
from app.chatbot.module import BotDefinition, BotRuntime, MatchPattern
from app.config import get_settings
from app.infra.async_writes import enqueue_bridge_log


COMMON_OPTION_SCHEMA: dict[str, dict[str, Any]] = {
    "replyRateLimitMillis": {
        "type": "integer",
        "default": 0,
        "min": 0,
        "description": "봇별 답장 전송 간격 제한. 기본값 0은 제한 없음.",
    },
    "replyRateLimitScope": {
        "type": "string",
        "default": "room",
        "choices": ["global", "room", "sender"],
        "description": "replyRateLimitMillis 적용 범위.",
    },
}


class BaseBot:
    """객체형 챗봇의 공통 생명주기와 응답/옵션/상태 helper를 제공한다."""

    key = ""
    name = ""
    version = "0.1.0"
    description = ""
    match_mode = "command"
    commands: list[str] = []
    patterns: list[MatchPattern] = []
    priority = 100
    enabled = True
    terminal = True
    timeout_millis = 3_000
    state_ttl_millis: int | None = None
    default_options: dict[str, Any] = {}
    option_schema: dict[str, dict[str, Any]] = {}
    match_policy = "any"
    match_threshold = 1.0

    def __init__(self) -> None:
        self._runtime: BotRuntime | None = None

    @property
    def runtime(self) -> BotRuntime:
        """initialize 이후 사용할 수 있는 봇 runtime을 반환한다."""

        if self._runtime is None:
            raise RuntimeError(f"{self.__class__.__name__} is not initialized")
        return self._runtime

    @property
    def messages(self):
        """봇이 원본 메시지를 읽을 때 사용하는 read-only store를 반환한다."""

        store = self.runtime.messageStore
        if store is None:
            raise RuntimeError(f"{self.__class__.__name__} message store is not initialized")
        return store

    def get_definition(self) -> BotDefinition:
        """class 필드로 선언한 metadata를 `BotDefinition`으로 변환한다."""

        commands = list(self.commands)
        patterns = list(self.patterns)
        return BotDefinition(
            key=self.key,
            name=self.name or self.key,
            version=self.version,
            description=self.description,
            matchMode=self.match_mode,  # type: ignore[arg-type]
            commands=commands,
            patterns=patterns,
            priority=self.priority,
            enabled=self.enabled,
            terminal=self.terminal,
            timeoutMillis=self.timeout_millis,
            stateTtlMillis=self.state_ttl_millis,
            defaultOptions=dict(self.default_options),
            optionSchema={**COMMON_OPTION_SCHEMA, **dict(self.option_schema)},
            matchPolicy=self.match_policy,  # type: ignore[arg-type]
            matchThreshold=self.match_threshold,
        )

    def initialize(self, runtime: BotRuntime) -> None:
        """runtime을 저장하고 봇별 초기화 hook을 호출한다."""

        self._runtime = runtime
        self.on_initialize(runtime)

    def on_initialize(self, runtime: BotRuntime) -> None:
        """봇별 초기화 hook이다. 기본 구현은 아무 작업도 하지 않는다."""

    def can_handle(self, context: ChatContext) -> bool:
        """기본 봇은 직접 메시지를 처리하지 않는다."""

        return False

    def handle(self, context: ChatContext) -> ChatDecision:
        """공통 실행 진입점이며 기본적으로 `run()`에 위임한다."""

        return self.run(context)

    def run(self, context: ChatContext) -> ChatDecision:
        """subclass가 구현해야 하는 실제 처리 본문이다."""

        raise NotImplementedError

    def shutdown(self) -> None:
        """봇별 종료 hook을 호출한다."""

        self.on_shutdown()

    def on_shutdown(self) -> None:
        """봇별 종료 hook이다. 기본 구현은 아무 작업도 하지 않는다."""

    def on_error(self, context: ChatContext, exc: Exception) -> ChatDecision:
        """처리 중 오류가 발생했을 때 processor가 호출하는 선택 hook이다."""

        self.log_error(f"{self.key} failed: {exc}", ref_id=getattr(context, "eventId", None))
        return self.pass_("error")

    def reply(self, text: str, reason: str | None = None) -> ChatDecision:
        """현재 메시지의 reply token으로 즉시 답장을 생성한다."""

        return ChatDecision.reply(text, reason=reason)

    def pass_(self, reason: str | None = None) -> ChatDecision:
        """다음 후보 봇으로 처리를 넘긴다."""

        return ChatDecision.pass_(reason)

    def none(self, reason: str | None = None, terminal: bool = True) -> ChatDecision:
        """응답 없이 처리를 종료하거나 계속 진행할 결정을 반환한다."""

        return ChatDecision.none(reason, terminal=terminal)

    def queued(self, reason: str | None = None) -> ChatDecision:
        """후속 비동기 작업으로 처리될 결정을 반환한다."""

        return ChatDecision.queued(reason)

    def send_reply(
        self,
        context: ChatContext,
        text: str,
        *,
        dedupe_key: str | None = None,
        reply_token: str | None = None,
    ):
        """현재 room의 reply token을 사용해 `/send` 경로로 답장 job을 생성한다.

        Args:
            context: 답장을 보낼 메시지 context.
            text: 전송할 답장 본문.
            dedupe_key: 중복 전송 방지 key. 없으면 event/bot/text 기반으로 생성한다.
            reply_token: 특정 reply token을 강제할 때 사용한다.

        Returns:
            `/send` 서비스가 반환한 `SendResponse`.
        """

        from app.schemas import SendRequest
        from app.services.send_service import SendService

        key = dedupe_key or self.reply_dedupe_key(context, text)
        request = SendRequest(
            roomKey=context.roomKey,
            room=context.room,
            text=text,
            dedupeKey=key,
            replyToken=reply_token or context.replyToken,
            token=get_settings().shared_secret,
        )
        return SendService().handle_send(request)

    def send_replies(
        self,
        context: ChatContext,
        texts: list[str],
        *,
        dedupe_key_prefix: str | None = None,
        reply_token: str | None = None,
    ) -> list:
        """여러 답장을 `/send` job으로 순서대로 생성한다."""

        responses = []
        prefix = dedupe_key_prefix or f"bot:{self.key}:{context.eventId}"
        for index, text in enumerate(texts, start=1):
            responses.append(
                self.send_reply(
                    context,
                    text,
                    dedupe_key=f"{prefix}:{index}",
                    reply_token=reply_token,
                )
            )
        return responses

    def queue_reply(
        self,
        context: ChatContext,
        text: str,
        *,
        delay_millis: int = 0,
        dedupe_key: str | None = None,
        reply_token: str | None = None,
    ) -> ChatDecision:
        """선택적 지연 뒤 `/send`로 답장을 발송하는 작업을 외부 runner에 등록한다."""

        def task() -> None:
            if delay_millis > 0:
                time.sleep(delay_millis / 1000)
            response = self.send_reply(context, text, dedupe_key=dedupe_key, reply_token=reply_token)
            if not response.ok:
                self.log_warn(
                    f"{self.key} queued reply failed status={response.status} error={response.error}",
                    context.eventId,
                )

        runner = self.runtime.externalRunner
        if runner is None:
            task()
        else:
            submitted = runner.submit(task)
            if submitted is None:
                self.log_warn(f"{self.key} queued reply rejected: external runner full", context.eventId)
                return self.none("external runner full")
        return self.queued("reply queued")

    def reply_dedupe_key(self, context: ChatContext, text: str, suffix: str | None = None) -> str:
        """봇 key, eventId, 답장 본문 길이를 포함한 안정적인 dedupe key를 만든다."""

        safe_suffix = f":{suffix}" if suffix else ""
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return f"bot:{self.key}:{context.eventId}:{digest}{safe_suffix}"

    def http_post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
        ref_id: str | None = None,
        error_prefix: str = "http request failed",
    ):
        """runtime HTTP client와 external runner를 통해 JSON POST를 수행한다."""

        from app.chatbot.io_helpers import run_http_post_json

        return run_http_post_json(
            self.runtime,
            url,
            payload,
            timeout_seconds=timeout_seconds,
            ref_id=ref_id,
            error_prefix=error_prefix,
        )

    def termux_command(
        self,
        args: list[str],
        *,
        timeout_seconds: float,
        ref_id: str | None = None,
        error_prefix: str = "termux command failed",
    ):
        """Termux command 실행을 공통 timeout/stderr 요약 정책으로 처리한다."""

        from app.chatbot.io_helpers import run_termux_command

        return run_termux_command(
            self.runtime,
            args,
            timeout_seconds=timeout_seconds,
            ref_id=ref_id,
            error_prefix=error_prefix,
        )

    def option(self, context: ChatContext, key: str, default: Any = None) -> Any:
        """병합된 봇 옵션에서 값을 조회한다."""

        options = getattr(context, "botOptions", None) or {}
        return options.get(key, default)

    def str_option(self, context: ChatContext, key: str, default: str = "") -> str:
        value = self.option(context, key, default)
        return value if isinstance(value, str) else str(value)

    def int_option(
        self,
        context: ChatContext,
        key: str,
        default: int,
        min_value: int | None = None,
        max_value: int | None = None,
    ) -> int:
        value = self.option(context, key, default)
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = int(default)
        return self._clamp(parsed, min_value, max_value)

    def float_option(
        self,
        context: ChatContext,
        key: str,
        default: float,
        min_value: float | None = None,
        max_value: float | None = None,
    ) -> float:
        value = self.option(context, key, default)
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = float(default)
        return self._clamp(parsed, min_value, max_value)

    def bool_option(self, context: ChatContext, key: str, default: bool = False) -> bool:
        value = self.option(context, key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return bool(value)

    def list_option(self, context: ChatContext, key: str, default: list[Any] | None = None) -> list[Any]:
        value = self.option(context, key, default or [])
        return list(value) if isinstance(value, list) else list(default or [])

    def dict_option(self, context: ChatContext, key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
        value = self.option(context, key, default or {})
        return dict(value) if isinstance(value, dict) else dict(default or {})

    def bounded_int(self, context: ChatContext, key: str, default: int, min_value: int, max_value: int) -> int:
        return self.int_option(context, key, default, min_value=min_value, max_value=max_value)

    def bounded_float(
        self,
        context: ChatContext,
        key: str,
        default: float,
        min_value: float,
        max_value: float,
    ) -> float:
        return self.float_option(context, key, default, min_value=min_value, max_value=max_value)

    def state_key(self, context: ChatContext, name: str, sender_scope: bool = True) -> str:
        """봇/방/발신자 기준 state key를 생성한다."""

        sender = getattr(context, "sender", None) if sender_scope else None
        return self.runtime.stateStore.make_key(self.key, context.roomKey, sender, name)

    def log(self, level: str, message: str, ref_id: str | None = None) -> None:
        """bridge log와 봇 logger에 같은 운영 메시지를 남긴다."""

        enqueue_bridge_log(level, "chatbot", message, ref_id)
        logger = self.runtime.logger if self._runtime is not None else None
        if logger is None:
            return
        method_name = "warning" if level.upper() == "WARN" else level.lower()
        log_method = getattr(logger, method_name, None)
        if callable(log_method):
            log_method(message)

    def log_warn(self, message: str, ref_id: str | None = None) -> None:
        self.log("WARN", message, ref_id)

    def log_error(self, message: str, ref_id: str | None = None) -> None:
        self.log("ERROR", message, ref_id)

    @staticmethod
    def _clamp(value, min_value, max_value):
        if min_value is not None and value < min_value:
            value = min_value
        if max_value is not None and value > max_value:
            value = max_value
        return value


class CommandBot(BaseBot):
    """명령어 기반 봇의 command metadata와 매칭을 공통 처리한다."""

    command = ""
    aliases: list[str] = []

    def get_definition(self) -> BotDefinition:
        commands = self._commands()
        original_commands = self.commands
        original_patterns = self.patterns
        self.commands = commands
        if not self.patterns:
            self.patterns = [MatchPattern(type="command", value=command) for command in commands]
        try:
            return super().get_definition()
        finally:
            self.commands = original_commands
            self.patterns = original_patterns

    def can_handle(self, context: ChatContext) -> bool:
        return getattr(context, "command", None) in set(self._commands())

    def handle(self, context: ChatContext) -> ChatDecision:
        return self.handle_command(context)

    def handle_command(self, context: ChatContext) -> ChatDecision:
        """명령 메시지를 처리한다. subclass가 구현한다."""

        raise NotImplementedError

    def _commands(self) -> list[str]:
        commands = list(self.commands)
        if not commands and self.command:
            commands.append(self.command)
        for alias in self.aliases:
            if alias not in commands:
                commands.append(alias)
        return commands


class StatefulBot(BaseBot):
    """영속 상태를 쓰는 봇의 state key와 TTL 처리를 공통화한다."""

    state_name = "state"
    session_name = "session"
    session_scope = "sender"
    session_ttl_millis: int | None = None

    def get_state(
        self,
        context: ChatContext,
        name: str | None = None,
        sender_scope: bool = True,
    ) -> dict[str, Any]:
        return self.runtime.stateStore.get(self.state_key(context, name or self.state_name, sender_scope=sender_scope))

    def set_state(
        self,
        context: ChatContext,
        value: dict[str, Any],
        name: str | None = None,
        ttl_millis: int | None = None,
        sender_scope: bool = True,
    ) -> None:
        self.runtime.stateStore.set(
            self.state_key(context, name or self.state_name, sender_scope=sender_scope),
            value,
            ttlMillis=ttl_millis if ttl_millis is not None else self.state_ttl_millis,
        )

    def update_state(
        self,
        context: ChatContext,
        updater: Callable[[dict[str, Any]], dict[str, Any]],
        name: str | None = None,
        ttl_millis: int | None = None,
        sender_scope: bool = True,
    ) -> dict[str, Any]:
        return self.runtime.stateStore.mutate(
            self.state_key(context, name or self.state_name, sender_scope=sender_scope),
            updater,
            ttlMillis=ttl_millis if ttl_millis is not None else self.state_ttl_millis,
        )

    def clear_state(
        self,
        context: ChatContext,
        name: str | None = None,
        sender_scope: bool = True,
    ) -> None:
        self.runtime.stateStore.delete(self.state_key(context, name or self.state_name, sender_scope=sender_scope))

    def session_state_key(
        self,
        context: ChatContext,
        name: str | None = None,
        scope: str | None = None,
    ) -> str:
        """대화 세션용 state key를 sender 또는 room scope로 생성한다."""

        return self.state_key(
            context,
            name or self.session_name,
            sender_scope=self._session_sender_scope(scope),
        )

    def get_session(
        self,
        context: ChatContext,
        name: str | None = None,
        scope: str | None = None,
    ) -> dict[str, Any]:
        """현재 대화 세션 상태를 반환한다. 없으면 빈 dict를 반환한다."""

        return self.runtime.stateStore.get(self.session_state_key(context, name=name, scope=scope))

    def has_session(
        self,
        context: ChatContext,
        name: str | None = None,
        scope: str | None = None,
    ) -> bool:
        """현재 context 기준으로 진행 중인 세션이 있는지 확인한다."""

        return bool(self.get_session(context, name=name, scope=scope))

    def start_session(
        self,
        context: ChatContext,
        step: str,
        payload: dict[str, Any] | None = None,
        name: str | None = None,
        scope: str | None = None,
        ttl_millis: int | None = None,
    ) -> dict[str, Any]:
        """새 세션을 시작하고 첫 step과 payload를 저장한다."""

        now = self.runtime.nowMillis()
        value = dict(payload or {})
        value["step"] = step
        value.setdefault("startedAt", now)
        value["updatedAt"] = now
        self.runtime.stateStore.set(
            self.session_state_key(context, name=name, scope=scope),
            value,
            ttlMillis=self._session_ttl(ttl_millis),
        )
        return value

    def advance_session(
        self,
        context: ChatContext,
        step: str,
        patch: dict[str, Any] | None = None,
        name: str | None = None,
        scope: str | None = None,
        ttl_millis: int | None = None,
    ) -> dict[str, Any]:
        """현재 세션 payload를 갱신하고 다음 step으로 이동한다."""

        def update(value: dict[str, Any]) -> dict[str, Any]:
            value.update(patch or {})
            value["step"] = step
            value["updatedAt"] = self.runtime.nowMillis()
            return value

        return self.update_session(
            context,
            update,
            name=name,
            scope=scope,
            ttl_millis=ttl_millis,
        )

    def update_session(
        self,
        context: ChatContext,
        updater: Callable[[dict[str, Any]], dict[str, Any]],
        name: str | None = None,
        scope: str | None = None,
        ttl_millis: int | None = None,
    ) -> dict[str, Any]:
        """세션 상태를 원자적으로 읽고 갱신한다."""

        return self.runtime.stateStore.mutate(
            self.session_state_key(context, name=name, scope=scope),
            updater,
            ttlMillis=self._session_ttl(ttl_millis),
        )

    def end_session(
        self,
        context: ChatContext,
        name: str | None = None,
        scope: str | None = None,
    ) -> None:
        """진행 중인 세션을 명시적으로 종료한다."""

        self.runtime.stateStore.delete(self.session_state_key(context, name=name, scope=scope))

    def _session_sender_scope(self, scope: str | None = None) -> bool:
        normalized = str(scope or self.session_scope or "sender").strip().lower()
        return normalized not in {"room", "room_key", "roomkey"}

    def _session_ttl(self, ttl_millis: int | None = None) -> int | None:
        if ttl_millis is not None:
            return ttl_millis
        if self.session_ttl_millis is not None:
            return self.session_ttl_millis
        return self.state_ttl_millis


class ObserverBot(BaseBot):
    """관찰형 봇의 비종단 기본 정책과 command skip helper를 제공한다."""

    match_mode = "observer"
    terminal = False

    def skip_command(self, context: ChatContext) -> bool:
        return bool(getattr(context, "command", None))
