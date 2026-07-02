from __future__ import annotations
import httpx

from app.config import get_settings
from app.schemas import AdapterResult, ReplyCommand, ReplyJobStatus


def dispatch(command: ReplyCommand, http_client=None) -> AdapterResult:
    """PC-only 테스트 앱의 `/bridge/replies`로 답장 명령을 전달한다."""

    settings = get_settings()
    url = settings.test_backend_url.rstrip("/") + "/bridge/replies"
    post = http_client.post if http_client is not None else httpx.post
    last_error = "request failed"
    for attempt in range(1, max(settings.adapter_max_attempts, 1) + 1):
        try:
            response = post(url, json=command.model_dump(), timeout=5.0)
            response.raise_for_status()
            data = response.json()
            break
        except httpx.HTTPStatusError as exc:
            last_error = str(exc)
            status_code = exc.response.status_code
            if status_code < 500 or attempt >= max(settings.adapter_max_attempts, 1):
                return AdapterResult(ok=False, status=ReplyJobStatus.failed, error=last_error)
        except Exception as exc:
            last_error = str(exc)
            if attempt >= max(settings.adapter_max_attempts, 1):
                return AdapterResult(ok=False, status=ReplyJobStatus.failed, error=last_error)
    else:
        return AdapterResult(ok=False, status=ReplyJobStatus.failed, error=last_error)

    status = ReplyJobStatus(data.get("status", "FAILED"))
    return AdapterResult(
        ok=bool(data.get("ok", False)),
        status=status,
        externalId=data.get("capturedReplyId"),
        error=data.get("error"),
    )
