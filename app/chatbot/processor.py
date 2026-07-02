from __future__ import annotations

import time
from collections.abc import Callable

from app import repository
from app.chatbot.context import ChatContext, build_chat_context
from app.chatbot.decision import ChatDecision, to_event_response
from app.chatbot.execution import BotExecutionContext
from app.chatbot.matchers.registry import MatcherRegistry, default_matcher_registry
from app.chatbot.options_cache import BotOptionView
from app.chatbot.options import BotOptionStore
from app.chatbot.reply_rate_limiter import ReplyRateLimiter
from app.chatbot.registry import ChatbotRegistry, RegisteredBot
from app.config import get_settings
from app.infra.async_writes import enqueue_bridge_log, enqueue_chatbot_run, enqueue_state_prune_throttled
from app.rule_engine import decide_event_response
from app.schemas import BridgeEvent, EventAction, EventResponse, RoomRuleMode, RoomRuleResponse


class ChatbotProcessor:
    """수신 메시지를 등록된 챗봇으로 라우팅하고 기존 응답 계약으로 변환한다."""

    def __init__(
        self,
        registry: ChatbotRegistry,
        matcher_registry: MatcherRegistry | None = None,
        option_store: BotOptionStore | None = None,
        config_cache_provider: Callable | None = None,
        reply_rate_limiter: ReplyRateLimiter | None = None,
    ) -> None:
        self.registry = registry
        self.matcher_registry = matcher_registry or default_matcher_registry()
        self.option_store = option_store or BotOptionStore()
        self._config_cache_provider = config_cache_provider
        self._reply_rate_limiter = reply_rate_limiter or ReplyRateLimiter()

    def process(self, event: BridgeEvent, room_rule: RoomRuleResponse | None = None) -> EventResponse:
        settings = get_settings()
        if not settings.chatbot_enabled:
            return decide_event_response(event, room_rule)
        registered_bots = self.registry.all()
        if not registered_bots:
            return decide_event_response(event, room_rule)
        if room_rule is not None and (not room_rule.enabled or room_rule.mode in (RoomRuleMode.disabled, RoomRuleMode.manual)):
            return EventResponse(ack=True, action=EventAction.none)
        enqueue_state_prune_throttled(settings.chatbot_state_prune_interval_millis)
        context = build_chat_context(event, room_rule)
        config_cache = self._config_cache_provider() if self._config_cache_provider is not None else None
        if config_cache is None:
            module_rows = repository.list_chatbot_modules_by_key()
            room_option_rows = repository.list_room_bot_options_by_key(context.roomKey)
        else:
            module_rows = config_cache.get_module_rows_by_key()
            room_option_rows = config_cache.get_room_option_rows_by_key(context.roomKey)
        option_view = BotOptionView(module_rows, room_option_rows, self.option_store)
        bots = self._enabled_bots(registered_bots, option_view)
        normal_bots = [bot for bot in bots if bot.definition.matchMode != "fallback"]
        fallback_bots = [bot for bot in bots if bot.definition.matchMode == "fallback"]
        decision = self._process_bots(normal_bots, context, option_view) or self._process_bots(
            fallback_bots,
            context,
            option_view,
        )
        if decision is None:
            return EventResponse(ack=True, action=EventAction.none)
        return to_event_response(decision)

    def _process_bots(
        self,
        bots: list[RegisteredBot],
        context: ChatContext,
        option_view: BotOptionView,
    ) -> ChatDecision | None:
        for bot in bots:
            start = time.monotonic()
            try:
                bot_context = BotExecutionContext(
                    base=context,
                    botOptions=option_view.options_for(bot),
                    handled=context.handled,
                )
                if not self._matches(bot, bot_context):
                    continue
                if not bool(bot.handler.can_handle(bot_context)):
                    continue
                decision = ChatDecision.model_validate(bot.handler.handle(bot_context))
                duration_ms = int((time.monotonic() - start) * 1000)
                self._record_timeout_if_needed(bot, bot_context, duration_ms)
                if decision.is_pass():
                    enqueue_chatbot_run(
                        bot_context.eventId,
                        bot.definition.key,
                        "pass",
                        decision.reason,
                        duration_ms,
                    )
                    continue
                decision.botKey = decision.botKey or bot.definition.key
                decision.replyToken = decision.replyToken or bot_context.replyToken
                decision.text = self._truncate_reply(decision.text)
                self._apply_reply_rate_limit(bot, bot_context, decision)
                context.handled = True
                enqueue_chatbot_run(
                    bot_context.eventId,
                    bot.definition.key,
                    str(decision.action.value if hasattr(decision.action, "value") else decision.action),
                    decision.reason,
                    duration_ms,
                )
                if decision.terminal and bot.definition.terminal:
                    return decision
            except Exception as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                enqueue_chatbot_run(
                    context.eventId,
                    bot.definition.key,
                    "error",
                    duration_ms=duration_ms,
                    error=str(exc),
                )
                enqueue_bridge_log("ERROR", "chatbot", f"{bot.definition.key} failed: {exc}", context.eventId)
                on_error = getattr(bot.handler, "on_error", None)
                if callable(on_error):
                    try:
                        error_context = BotExecutionContext(
                            base=context,
                            botOptions=option_view.options_for(bot),
                            handled=context.handled,
                        )
                        decision = ChatDecision.model_validate(on_error(error_context, exc))
                        if not decision.is_pass():
                            decision.botKey = decision.botKey or bot.definition.key
                            decision.replyToken = decision.replyToken or context.replyToken
                            return decision
                    except Exception:
                        pass
        return None

    def _apply_reply_rate_limit(
        self,
        bot: RegisteredBot,
        context: ChatContext,
        decision: ChatDecision,
    ) -> None:
        """봇 옵션이 명시한 경우에만 답장 간격을 봇별로 제한한다."""

        action = decision.action.value if hasattr(decision.action, "value") else decision.action
        if action != EventAction.reply.value:
            return
        interval_millis = _int_option(getattr(context, "botOptions", {}).get("replyRateLimitMillis"), 0)
        if interval_millis <= 0:
            return
        scope = str(getattr(context, "botOptions", {}).get("replyRateLimitScope", "room")).strip().lower()
        if scope not in {"global", "room", "sender"}:
            scope = "room"
        waited_millis = self._reply_rate_limiter.wait(
            bot_key=bot.definition.key,
            room_key=context.roomKey,
            sender=context.sender,
            interval_millis=interval_millis,
            scope=scope,
        )
        if waited_millis > 0:
            enqueue_bridge_log(
                "INFO",
                "chatbot",
                f"{bot.definition.key} reply rate limit waitedMs={waited_millis} scope={scope}",
                context.eventId,
            )

    def _enabled_bots(
        self,
        registered_bots: list[RegisteredBot],
        option_view: BotOptionView,
    ) -> list[RegisteredBot]:
        entries: list[tuple[int, str, RegisteredBot]] = []
        for bot in registered_bots:
            if not option_view.is_enabled(bot):
                continue
            entries.append((option_view.priority(bot), bot.definition.key, bot))
        return [item[2] for item in sorted(entries, key=lambda item: (item[0], item[1]))]

    def _bot_options(self, context: ChatContext, bot: RegisteredBot) -> dict:
        _, options = self.option_store.merged_options(
            context.roomKey,
            bot.definition.key,
            bot.definition.defaultOptions,
        )
        return options

    def _matches(self, bot: RegisteredBot, context: ChatContext | BotExecutionContext) -> bool:
        if not bot.definition.enabled:
            return False
        patterns = bot.definition.patterns
        if not patterns:
            return True
        results = self.matcher_registry.match_all(patterns, context, bot.runtime)
        if bot.definition.matchPolicy == "all":
            return all(result.matched for result in results)
        if bot.definition.matchPolicy == "score":
            score = sum(pattern.weight * result.confidence for pattern, result in zip(patterns, results) if result.matched)
            return score >= bot.definition.matchThreshold
        if bot.definition.matchPolicy == "custom":
            return True
        return any(result.matched for result in results)

    def _truncate_reply(self, text: str | None) -> str | None:
        if text is None:
            return None
        max_chars = max(get_settings().chatbot_max_reply_chars, 1)
        if len(text) <= max_chars:
            return text
        return text[:max_chars]

    def _record_timeout_if_needed(self, bot: RegisteredBot, context: ChatContext, duration_ms: int) -> None:
        settings = get_settings()
        bot_threshold = int(bot.definition.timeoutMillis or 0)
        global_threshold = int(settings.chatbot_bot_handle_timeout_ms or 0)
        candidates = [value for value in (bot_threshold, global_threshold) if value > 0]
        threshold = min(candidates) if candidates else 1
        if duration_ms <= threshold:
            return
        message = f"{bot.definition.key} exceeded handle timeout target durationMs={duration_ms} thresholdMs={threshold}"
        enqueue_bridge_log("WARN", "chatbot", message, context.eventId)


def _int_option(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
