from __future__ import annotations

from app.chatbot.context import ChatContext
from app.chatbot.matchers.base import MatchResult, PatternMatcher
from app.chatbot.module import BotRuntime, MatchPattern


class SenderRateMatcher(PatternMatcher):
    type = "sender_rate"

    def match(self, pattern: MatchPattern, context: ChatContext, runtime: BotRuntime) -> MatchResult:
        if not isinstance(pattern.value, dict):
            return MatchResult(matched=False, reason="invalid sender_rate value")
        window = int(pattern.value.get("windowMillis", 10_000))
        limit = int(pattern.value.get("limit", 8))
        scope = str(pattern.value.get("scope", "window"))
        key = runtime.stateStore.make_key(runtime.botKey, context.roomKey, context.sender, scope)
        state = runtime.stateStore.get(key, {"timestamps": []})
        now = runtime.nowMillis()
        timestamps = [int(ts) for ts in state.get("timestamps", []) if now - int(ts) <= window]
        matched = len(timestamps) + 1 >= limit
        return MatchResult(matched=matched, confidence=pattern.confidence if matched else 0.0, captures={"count": len(timestamps) + 1})


class RoomRateMatcher(PatternMatcher):
    type = "room_rate"

    def match(self, pattern: MatchPattern, context: ChatContext, runtime: BotRuntime) -> MatchResult:
        if not isinstance(pattern.value, dict):
            return MatchResult(matched=False, reason="invalid room_rate value")
        window = int(pattern.value.get("windowMillis", 60_000))
        limit = int(pattern.value.get("limit", 100))
        scope = str(pattern.value.get("scope", "room_window"))
        key = runtime.stateStore.make_key(runtime.botKey, context.roomKey, None, scope)
        state = runtime.stateStore.get(key, {"timestamps": []})
        now = runtime.nowMillis()
        timestamps = [int(ts) for ts in state.get("timestamps", []) if now - int(ts) <= window]
        matched = len(timestamps) + 1 >= limit
        return MatchResult(matched=matched, confidence=pattern.confidence if matched else 0.0, captures={"count": len(timestamps) + 1})


class StateExistsMatcher(PatternMatcher):
    type = "state_exists"

    def match(self, pattern: MatchPattern, context: ChatContext, runtime: BotRuntime) -> MatchResult:
        state_name, sender_scope = _parse_state_exists_value(pattern.value)
        if not state_name:
            return MatchResult(matched=False, reason="invalid state_exists value")
        sender = context.sender if sender_scope else None
        key = runtime.stateStore.make_key(runtime.botKey, context.roomKey, sender, state_name)
        state = runtime.stateStore.get(key)
        matched = bool(state)
        return MatchResult(matched=matched, confidence=pattern.confidence if matched else 0.0, captures=state)


class FallbackMatcher(PatternMatcher):
    type = "fallback"

    def match(self, pattern: MatchPattern, context: ChatContext, runtime: BotRuntime) -> MatchResult:
        return MatchResult(matched=not context.handled, confidence=pattern.confidence)


def _parse_state_exists_value(value) -> tuple[str, bool]:
    if isinstance(value, dict):
        state_name = str(
            value.get("name")
            or value.get("stateName")
            or value.get("state")
            or ""
        ).strip()
        scope_value = value.get("scope")
        if not state_name and scope_value is not None:
            scope_text = str(scope_value).strip()
            if scope_text.lower() not in {"sender", "room", "room_key", "roomkey"}:
                state_name = scope_text
        sender_scope = True
        if "senderScope" in value:
            sender_scope = _parse_bool(value.get("senderScope"), default=True)
        elif "sender_scope" in value:
            sender_scope = _parse_bool(value.get("sender_scope"), default=True)
        elif scope_value is not None:
            sender_scope = str(scope_value).strip().lower() not in {"room", "room_key", "roomkey"}
        return state_name, sender_scope
    return str(value).strip(), True


def _parse_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)
