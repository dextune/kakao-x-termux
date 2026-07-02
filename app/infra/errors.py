from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
from typing import Optional

from app.infra.async_writes import enqueue_bridge_log

logger = logging.getLogger("app.infra.errors")


class ErrorSeverity(str, Enum):
    """운영 로그 심각도 분류다."""

    warn = "WARN"
    error = "ERROR"


class ErrorCode(str, Enum):
    """코어 service 계층에서 분류하는 오류 코드다."""

    processing_failed = "PROCESSING_FAILED"
    send_failed = "SEND_FAILED"
    db_update_failed = "DB_UPDATE_FAILED"
    log_failed = "LOG_FAILED"


@dataclass
class AppError(Exception):
    """route/service 경계에서 public message와 운영 로그 상세를 분리하는 오류다."""

    code: ErrorCode
    public_message: str
    log_detail: str
    severity: ErrorSeverity = ErrorSeverity.error
    ref_id: Optional[str] = None


def safe_bridge_log(level: str, category: str, message: str, ref_id: Optional[str] = None) -> None:
    """운영 로그를 best-effort로 저장한다.

    로그 저장 실패가 원래 요청 처리 예외를 덮지 않도록 방어한다.
    """

    if not enqueue_bridge_log(level, category, message, ref_id):
        logger.debug("bridge log skipped category=%s ref_id=%s", category, ref_id)


def log_app_error(error: AppError, category: str) -> None:
    """분류된 AppError를 bridge_logs에 기록한다."""

    safe_bridge_log(error.severity.value, category, f"{error.code.value}: {error.log_detail}", error.ref_id)
