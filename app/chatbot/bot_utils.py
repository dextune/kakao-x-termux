from __future__ import annotations

import subprocess
from typing import Any

from app.chatbot.context import ChatContext


def option(context: ChatContext, key: str, default: Any = None) -> Any:
    """병합된 봇 옵션에서 값을 조회한다."""

    return (getattr(context, "botOptions", None) or {}).get(key, default)


class CommandExecutionError(RuntimeError):
    """외부 명령 실행 실패를 사용자 친화 오류로 변환하기 위한 예외다."""


def run_command(args: list[str], timeout_seconds: float, error_prefix: str) -> subprocess.CompletedProcess[str]:
    """외부 명령을 timeout과 함께 실행하고 실패 세부 정보를 짧게 정규화한다."""

    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout_seconds, check=True)
    except subprocess.TimeoutExpired as exc:
        raise CommandExecutionError(f"{error_prefix}: timeout") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        if len(detail) > 200:
            detail = detail[:200]
        raise CommandExecutionError(f"{error_prefix}: {detail or exc.returncode}") from exc
