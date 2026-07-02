from __future__ import annotations
from app.schemas import AdapterResult, ReplyCommand, ReplyJobStatus


def dispatch(command: ReplyCommand) -> AdapterResult:
    """외부 전송 없이 payload 생성과 상태 전이만 검증한다."""

    return AdapterResult(ok=True, status=ReplyJobStatus.sent, externalId="noop")
