from __future__ import annotations

from typing import Any

from app.chatbot.state_store import BotStateStore, StateWriteResult


def increment_counter(
    store: BotStateStore,
    key: str,
    amount: int = 1,
    ttlMillis: int | None = None,
    botKey: str | None = None,
    roomKey: str | None = None,
    sender: str | None = None,
) -> StateWriteResult:
    """카운터 상태를 원자적으로 증가시킨다."""

    def update(value: dict[str, Any]) -> dict[str, Any]:
        value["count"] = int(value.get("count", 0)) + amount
        return value

    return store.mutate_result(
        key,
        update,
        ttlMillis=ttlMillis,
        botKey=botKey,
        roomKey=roomKey,
        sender=sender,
    )


def update_rolling_window(
    store: BotStateStore,
    key: str,
    now: int,
    windowMillis: int,
    limit: int,
    ttlMillis: int | None = None,
    botKey: str | None = None,
    roomKey: str | None = None,
    sender: str | None = None,
) -> StateWriteResult:
    """timestamp rolling window를 원자적으로 갱신한다."""

    capped_limit = max(limit, 1)

    def update(value: dict[str, Any]) -> dict[str, Any]:
        timestamps = [
            int(ts)
            for ts in value.get("timestamps", [])
            if now - int(ts) <= max(windowMillis, 0)
        ]
        timestamps.append(now)
        capped = timestamps[-capped_limit:]
        value["timestamps"] = capped
        value["count"] = len(capped)
        return value

    return store.mutate_result(
        key,
        update,
        ttlMillis=ttlMillis,
        botKey=botKey,
        roomKey=roomKey,
        sender=sender,
    )


def set_session_step(
    store: BotStateStore,
    key: str,
    step: str,
    payload: dict[str, Any] | None = None,
    ttlMillis: int | None = None,
    botKey: str | None = None,
    roomKey: str | None = None,
    sender: str | None = None,
) -> StateWriteResult:
    """세션형 상태의 step과 payload를 원자적으로 저장한다."""

    def update(value: dict[str, Any]) -> dict[str, Any]:
        value.update(payload or {})
        value["step"] = step
        return value

    return store.mutate_result(
        key,
        update,
        ttlMillis=ttlMillis,
        botKey=botKey,
        roomKey=roomKey,
        sender=sender,
    )
