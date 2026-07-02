from __future__ import annotations
import base64
import json
import subprocess

from app.schemas import AdapterResult, ReplyCommand, ReplyJobStatus


def dispatch(command: ReplyCommand) -> AdapterResult:
    """Termux의 `am broadcast`로 Android ReplyCommandReceiver를 호출한다."""

    payload = base64.b64encode(
        json.dumps(command.model_dump(), ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    args = [
        "am",
        "broadcast",
        "-n",
        "com.dex.kakaobridge/.receiver.ReplyCommandReceiver",
        "-a",
        "com.dex.kakaobridge.REPLY",
        "--es",
        "payload_base64",
        payload,
    ]
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=10, check=False)
    except FileNotFoundError:
        return AdapterResult(ok=False, status=ReplyJobStatus.failed, error="am command not found")
    except Exception as exc:
        return AdapterResult(ok=False, status=ReplyJobStatus.failed, error=str(exc))
    if completed.returncode != 0:
        error = completed.stderr.strip() or completed.stdout.strip()
        return AdapterResult(ok=False, status=ReplyJobStatus.failed, error=error)
    return AdapterResult(ok=True, status=ReplyJobStatus.sent, externalId="am_broadcast")
