from __future__ import annotations

import logging
from typing import Optional

from app import repository
from app.time_utils import now_millis

logger = logging.getLogger("app.infra.async_writes")
_last_state_prune_at: dict[str, int] = {}


def enqueue_bridge_log(
    level: str,
    category: str,
    message: str,
    ref_id: Optional[str] = None,
    *,
    prune: bool = False,
) -> bool:
    """운영 로그를 runtime writer queue에 기록한다.

    RuntimeResources가 아직 시작되지 않은 단위 테스트/초기화 경로에서는 기존 동기 저장을
    fallback으로 사용한다. runtime writer가 존재할 때 queue full로 drop되면 hot path 보호를
    위해 동기 DB 쓰기로 되돌아가지 않는다.
    """

    writer = _current_writer()
    if writer is not None:
        return writer.enqueue_bridge_log(level, category, message, ref_id, prune=prune)
    try:
        repository.insert_bridge_log(level, category, message, ref_id)
        if prune:
            settings = _settings()
            repository.prune_bridge_logs_throttled(
                max_rows=settings.bridge_log_max_rows,
                retention_millis=settings.bridge_log_retention_millis,
                interval_millis=settings.bridge_log_prune_interval_millis,
            )
        return True
    except Exception as exc:  # pragma: no cover - logging fallback only
        logger.warning("bridge log write failed category=%s ref_id=%s error=%s", category, ref_id, exc)
        return False


def enqueue_chatbot_run(
    event_id: str,
    bot_key: str,
    action: str,
    reason: Optional[str] = None,
    duration_ms: Optional[int] = None,
    error: Optional[str] = None,
) -> bool:
    """챗봇 실행 기록을 runtime writer queue에 기록한다."""

    writer = _current_writer()
    if writer is not None:
        return writer.enqueue_chatbot_run(event_id, bot_key, action, reason, duration_ms, error)
    try:
        repository.insert_chatbot_run(event_id, bot_key, action, reason, duration_ms, error)
        return True
    except Exception as exc:  # pragma: no cover - logging fallback only
        logger.warning("chatbot run write failed event_id=%s bot_key=%s error=%s", event_id, bot_key, exc)
        return False


def enqueue_state_prune_throttled(interval_millis: int, now: int | None = None) -> bool:
    """만료 state pruning을 DB path별 interval 기준으로 writer queue에 적재한다."""

    settings = _settings()
    current = now if now is not None else now_millis()
    last = _last_state_prune_at.get(settings.db_path)
    if last is not None and current - last < max(interval_millis, 0):
        return True
    _last_state_prune_at[settings.db_path] = current
    writer = _current_writer()
    if writer is not None:
        return writer.enqueue_state_prune(current)
    try:
        repository.prune_bot_states(now=current)
        return True
    except Exception as exc:  # pragma: no cover - logging fallback only
        logger.warning("state prune failed error=%s", exc)
        return False


def _current_writer():
    try:
        from app.infra.runtime_resources import get_existing_runtime_resources

        resources = get_existing_runtime_resources()
    except Exception:
        return None
    if resources is None:
        return None
    return resources.memory_pipeline.writer


def _settings():
    from app.config import get_settings

    return get_settings()
