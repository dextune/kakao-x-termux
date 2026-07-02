from __future__ import annotations
import re
from typing import Optional

from app.config import get_settings
from app.infra.async_writes import enqueue_bridge_log
from app.repository import list_bridge_logs
from app.schemas import BridgeEvent, EventResponse, SendRequest, SendResponse

PII_EXPORT_PATTERN = re.compile(r"\b(room|sender|text)='(?:\\'|[^'])*'")


def _safe_value(name: str, value: Optional[str], allow_pii: bool) -> str:
    if value is None:
        return "null"
    if allow_pii:
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    return f"<redacted:{name}:chars={len(value)}>"


def _record(level: str, category: str, message: str, ref_id: Optional[str]) -> None:
    enqueue_bridge_log(level=level, category=category, message=message, ref_id=ref_id, prune=True)


def log_event_result(event: BridgeEvent, response: EventResponse, duplicate: bool = False) -> None:
    """`/events` 처리 결과를 PII 정책에 맞춰 bridge_logs에 남긴다.

    Args:
        event: 수신 계약 모델.
        response: 룰 엔진 또는 중복 처리 응답.
        duplicate: eventId 중복으로 신규 저장하지 않은 경우 True.
    """

    allow_pii = get_settings().log_pii
    state = "duplicate" if duplicate else "processed"
    message = (
        f"{state} sourceType={event.sourceType} action={response.action.value} "
        f"room={_safe_value('room', event.room, allow_pii)} "
        f"sender={_safe_value('sender', event.sender, allow_pii)} "
        f"text={_safe_value('text', event.text, allow_pii)}"
    )
    _record("WARN" if duplicate else "INFO", "event", message, event.eventId)


def log_send_result(
    request: SendRequest,
    response: SendResponse,
    reply_token_found: bool,
) -> None:
    """`/send` 처리 결과를 PII 정책에 맞춰 bridge_logs에 남긴다.

    Args:
        request: 수동/지연 답장 요청.
        response: 저장 및 dispatch 결과.
        reply_token_found: dispatch에 사용할 답장 토큰을 찾았는지 여부.
    """

    allow_pii = get_settings().log_pii
    message = (
        f"status={response.status.value} bridgeMode={response.bridgeMode.value} "
        f"replyTokenFound={str(reply_token_found).lower()} "
        f"room={_safe_value('room', request.room, allow_pii)} "
        f"text={_safe_value('text', request.text, allow_pii)}"
    )
    level = "INFO" if response.ok else "WARN"
    _record(level, "send", message, response.jobId)


def sanitize_export_message(message: str) -> str:
    """공유/export 로그에서 개인정보 필드 원문을 제거한다."""

    return PII_EXPORT_PATTERN.sub(lambda match: f"{match.group(1)}=<redacted:{match.group(1)}>", message)


def export_bridge_logs(limit: int = 100) -> list[dict[str, object]]:
    """공유용 bridge_logs를 반환한다.

    저장 시점에 `LOG_PII=true`였던 로그도 export에서는 room/sender/text 원문을 제거한다.
    """

    exported = []
    for row in list_bridge_logs(limit=limit):
        exported.append(
            {
                "id": row["id"],
                "level": row["level"],
                "category": row["category"],
                "message": sanitize_export_message(row["message"]),
                "refId": row["ref_id"],
                "createdAt": row["created_at"],
            }
        )
    return exported
