from __future__ import annotations
import base64
import json
import subprocess

from app.config import get_settings
from app.schemas import AdapterResult, ReplyCommand, ReplyJobStatus


def dispatch(command: ReplyCommand) -> AdapterResult:
    """Host ADB를 통해 Redroid 안의 ReplyCommandReceiver를 호출한다.

    Redroid E2E 테스트 전용 adapter다. Termux 실기기 운영 경로는 `am_broadcast`를 사용한다.
    """

    settings = get_settings()
    payload = base64.b64encode(
        json.dumps(command.model_dump(), ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    args = [
        "adb",
        "-s",
        settings.adb_serial,
        "shell",
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
        completed = subprocess.run(args, capture_output=True, text=True, timeout=15, check=False)
    except FileNotFoundError:
        return AdapterResult(ok=False, status=ReplyJobStatus.failed, error="adb command not found")
    except Exception as exc:
        return AdapterResult(ok=False, status=ReplyJobStatus.failed, error=str(exc))
    if completed.returncode != 0:
        error = completed.stderr.strip() or completed.stdout.strip()
        return AdapterResult(ok=False, status=ReplyJobStatus.failed, error=error)
    return AdapterResult(ok=True, status=ReplyJobStatus.sent, externalId=f"adb_broadcast:{settings.adb_serial}")
