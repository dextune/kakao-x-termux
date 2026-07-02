from __future__ import annotations

import sqlite3
from typing import Optional

from app.db import connect
from app.schemas import ReplyJobStatus
from app.time_utils import now_millis

TERMINAL_STATUSES = (
    ReplyJobStatus.sent,
    ReplyJobStatus.failed,
    ReplyJobStatus.token_expired,
    ReplyJobStatus.handle_expired,
    ReplyJobStatus.duplicate,
)


def insert_reply_job(
    job_id: str,
    room_key: str,
    room: str,
    text: str,
    dedupe_key: Optional[str],
    reply_token: Optional[str],
    bridge_mode: str,
) -> bool:
    """답장 작업을 PENDING으로 저장한다.

    Returns:
        새 작업이면 True, jobId/dedupeKey 중복이면 False.
    """

    try:
        with connect() as conn:
            now = now_millis()
            conn.execute(
                """
                INSERT INTO reply_jobs (
                  job_id, room_key, room, text, status, dedupe_key, reply_token,
                  attempt_count, bridge_mode, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'PENDING', ?, ?, 0, ?, ?, ?)
                """,
                (job_id, room_key, room, text, dedupe_key, reply_token, bridge_mode, now, now),
            )
            return True
    except sqlite3.IntegrityError:
        return False


def update_reply_job(job_id: str, status: ReplyJobStatus, error: Optional[str] = None) -> None:
    _update_reply_job(job_id, status, error)


def update_reply_job_if_status(
    job_id: str,
    expected_statuses: tuple[ReplyJobStatus, ...],
    status: ReplyJobStatus,
    error: Optional[str] = None,
) -> bool:
    """현재 status가 기대값 중 하나일 때만 reply job을 전이한다."""

    return _update_reply_job(job_id, status, error, expected_statuses=expected_statuses) == 1


def claim_reply_job_for_dispatch(
    job_id: str,
    owner: str,
    lease_millis: int,
    now: int | None = None,
) -> bool:
    """dispatch worker가 미완료 reply job을 lease와 함께 소유한다."""

    current = now if now is not None else now_millis()
    lease_expires_at = current + max(lease_millis, 1)
    with connect() as conn:
        cursor = conn.execute(
            """
            UPDATE reply_jobs
            SET status = ?, dispatch_owner = ?, dispatch_lease_expires_at = ?,
                dispatch_started_at = ?, updated_at = ?
            WHERE job_id = ?
              AND (
                status IN (?, ?, ?)
                OR (
                  status = ?
                  AND dispatch_lease_expires_at IS NOT NULL
                  AND dispatch_lease_expires_at <= ?
                )
              )
            """,
            (
                ReplyJobStatus.dispatching.value,
                owner,
                lease_expires_at,
                current,
                current,
                job_id,
                ReplyJobStatus.pending.value,
                ReplyJobStatus.queued.value,
                ReplyJobStatus.retrying.value,
                ReplyJobStatus.dispatching.value,
                current,
            ),
        )
        return int(cursor.rowcount) == 1


def mark_reply_job_retrying_if_owned(job_id: str, owner: str, error: Optional[str] = None) -> bool:
    """소유한 dispatch job만 retrying 상태로 전이한다."""

    current = now_millis()
    with connect() as conn:
        cursor = conn.execute(
            """
            UPDATE reply_jobs
            SET status = ?, last_error = ?, attempt_count = attempt_count + 1,
                updated_at = ?, dispatch_owner = NULL, dispatch_lease_expires_at = NULL
            WHERE job_id = ? AND status = ? AND dispatch_owner = ?
            """,
            (
                ReplyJobStatus.retrying.value,
                error,
                current,
                job_id,
                ReplyJobStatus.dispatching.value,
                owner,
            ),
        )
        return int(cursor.rowcount) == 1


def complete_reply_job_if_owned(
    job_id: str,
    owner: str,
    status: ReplyJobStatus,
    error: Optional[str] = None,
) -> bool:
    """소유한 dispatch job만 terminal 상태로 완료한다."""

    if status not in TERMINAL_STATUSES:
        status = ReplyJobStatus.failed
    current = now_millis()
    sent_at = current if status == ReplyJobStatus.sent else None
    with connect() as conn:
        cursor = conn.execute(
            """
            UPDATE reply_jobs
            SET status = ?, last_error = ?, attempt_count = attempt_count + 1,
                updated_at = ?, sent_at = ?, dispatch_owner = NULL,
                dispatch_lease_expires_at = NULL
            WHERE job_id = ? AND status = ? AND dispatch_owner = ?
            """,
            (
                status.value,
                error,
                current,
                sent_at,
                job_id,
                ReplyJobStatus.dispatching.value,
                owner,
            ),
        )
        return int(cursor.rowcount) == 1


def _update_reply_job(
    job_id: str,
    status: ReplyJobStatus,
    error: Optional[str] = None,
    expected_statuses: tuple[ReplyJobStatus, ...] | None = None,
) -> int:
    sent_at = now_millis() if status == ReplyJobStatus.sent else None
    counted_statuses = {
        ReplyJobStatus.retrying,
        ReplyJobStatus.sent,
        ReplyJobStatus.failed,
        ReplyJobStatus.token_expired,
        ReplyJobStatus.handle_expired,
    }
    attempt_sql = "attempt_count + 1" if status in counted_statuses else "attempt_count"
    current = now_millis()
    owner_sql = ""
    if status != ReplyJobStatus.dispatching:
        owner_sql = ", dispatch_owner = NULL, dispatch_lease_expires_at = NULL"
    where = "job_id = ?"
    params: list = [status.value, error, current, sent_at, job_id]
    if expected_statuses is not None:
        placeholders = ", ".join("?" for _ in expected_statuses)
        where += f" AND status IN ({placeholders})"
        params.extend(item.value for item in expected_statuses)
    with connect() as conn:
        cursor = conn.execute(
            f"""
            UPDATE reply_jobs
            SET status = ?, last_error = ?, attempt_count = {attempt_sql}, updated_at = ?, sent_at = ?
                {owner_sql}
            WHERE {where}
            """,
            params,
        )
        return int(cursor.rowcount)


def get_reply_job(job_id: str):
    """jobId 기준 답장 작업의 현재 상태를 조회한다."""

    with connect() as conn:
        return conn.execute(
            """
            SELECT job_id, room_key, room, status, dedupe_key, attempt_count,
                   last_error, bridge_mode, created_at, updated_at,
                   dispatch_owner, dispatch_lease_expires_at, dispatch_started_at, sent_at
            FROM reply_jobs
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()


def list_recoverable_reply_jobs(limit: int = 100, stale_dispatching_before: int | None = None) -> list:
    """재시작 후 dispatch queue로 복원할 미완료 reply job을 조회한다."""

    recoverable = (
        ReplyJobStatus.pending.value,
        ReplyJobStatus.queued.value,
        ReplyJobStatus.retrying.value,
    )
    cutoff = stale_dispatching_before if stale_dispatching_before is not None else -1
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT job_id, room_key, room, text, dedupe_key, reply_token, bridge_mode, status, created_at, updated_at
                FROM reply_jobs
                WHERE status IN (?, ?, ?)
                   OR (
                     status = ?
                     AND (
                       (dispatch_lease_expires_at IS NOT NULL AND dispatch_lease_expires_at <= ?)
                       OR (dispatch_lease_expires_at IS NULL AND updated_at <= ?)
                     )
                   )
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (
                    *recoverable,
                    ReplyJobStatus.dispatching.value,
                    cutoff,
                    cutoff,
                    max(min(limit, 1_000), 1),
                ),
            ).fetchall()
        )


def queued_reply_job_metrics(now: int | None = None) -> dict[str, int]:
    """DB에 남아 있는 QUEUED reply job 수와 가장 오래된 대기 시간을 반환한다."""

    current = now if now is not None else now_millis()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count, MIN(updated_at) AS oldest_updated_at
            FROM reply_jobs
            WHERE status = ?
            """,
            (ReplyJobStatus.queued.value,),
        ).fetchone()
    count = int(row["count"]) if row is not None else 0
    oldest = row["oldest_updated_at"] if row is not None else None
    oldest_age = max(current - int(oldest), 0) if oldest is not None else 0
    return {"count": count, "oldestAgeMs": oldest_age}
