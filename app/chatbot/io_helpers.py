from __future__ import annotations

import subprocess
from typing import Any

import httpx

from app.chatbot.module import BotRuntime
from app.infra.async_writes import enqueue_bridge_log


class ExternalIOError(RuntimeError):
    """봇 외부 I/O 실패를 사용자 응답 가능 오류로 변환하기 위한 예외다."""


def run_http_post_json(
    runtime: BotRuntime,
    url: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float,
    ref_id: str | None = None,
    error_prefix: str = "http request failed",
) -> httpx.Response:
    """runtime HTTP client와 external runner를 사용해 JSON POST를 실행한다."""

    client = runtime.httpClient
    post = client.post if client is not None else httpx.post

    try:
        if runtime.externalRunner is None:
            response = post(url, json=payload, timeout=timeout_seconds)
        else:
            result = runtime.externalRunner.run(
                lambda: post(url, json=payload, timeout=timeout_seconds),
                timeout_seconds=timeout_seconds,
            )
            if not result.ok:
                raise ExternalIOError(result.error or f"{error_prefix}: {result.status}")
            response = result.value
        response.raise_for_status()
        return response
    except ExternalIOError as exc:
        _log(runtime, "WARN", str(exc), ref_id)
        raise
    except Exception as exc:
        _log(runtime, "WARN", f"{error_prefix}: {exc}", ref_id)
        raise ExternalIOError(f"{error_prefix}: {_short_error(str(exc))}") from exc


def run_termux_command(
    runtime: BotRuntime,
    args: list[str],
    *,
    timeout_seconds: float,
    ref_id: str | None = None,
    error_prefix: str = "termux command failed",
) -> subprocess.CompletedProcess[str]:
    """Termux command를 실행하고 실패 세부 정보를 짧게 정규화한다."""

    try:
        if runtime.externalRunner is None:
            result = _run_command(args, timeout_seconds)
        else:
            external_result = runtime.externalRunner.run(
                lambda: _run_command(args, timeout_seconds),
                timeout_seconds=timeout_seconds,
            )
            if not external_result.ok:
                raise ExternalIOError(external_result.error or f"{error_prefix}: {external_result.status}")
            result = external_result.value
    except FileNotFoundError:
        raise
    except subprocess.TimeoutExpired as exc:
        _log(runtime, "WARN", f"{error_prefix}: timeout", ref_id)
        raise ExternalIOError(f"{error_prefix}: timeout") from exc
    except ExternalIOError as exc:
        _log(runtime, "WARN", str(exc), ref_id)
        raise
    except Exception as exc:
        _log(runtime, "WARN", f"{error_prefix}: {exc}", ref_id)
        raise ExternalIOError(f"{error_prefix}: {_short_error(str(exc))}") from exc

    if result.returncode != 0:
        detail = _stderr_summary(result)
        message = f"{error_prefix}: {detail or result.returncode}"
        _log(runtime, "WARN", message, ref_id)
        raise ExternalIOError(message)
    return result


def _run_command(args: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout_seconds, check=False)


def _stderr_summary(result: subprocess.CompletedProcess[str]) -> str:
    return _short_error((result.stderr or result.stdout or "").strip())


def _short_error(value: str, limit: int = 200) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _log(runtime: BotRuntime, level: str, message: str, ref_id: str | None) -> None:
    runtime.logger.warning(message)
    enqueue_bridge_log(level, "chatbot", message, ref_id)
