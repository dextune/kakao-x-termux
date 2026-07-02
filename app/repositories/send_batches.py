from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from app.db import connect
from app.time_utils import now_millis


def insert_send_batch(
    batch_id: str,
    target_type: str,
    target_json: dict[str, Any],
    text_hash: str,
    text_preview: str,
    status: str,
    target_count: int = 0,
    queued_count: int = 0,
    sent_count: int = 0,
    failed_count: int = 0,
    expired_count: int = 0,
    skipped_count: int = 0,
) -> sqlite3.Row:
    """batch row를 생성하고 저장된 row를 반환한다."""

    now = now_millis()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO send_batches (
              batch_id, target_type, target_json, text_hash, text_preview, status,
              target_count, queued_count, sent_count, failed_count, expired_count, skipped_count,
              created_at, updated_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                target_type,
                json.dumps(target_json, ensure_ascii=False, sort_keys=True),
                text_hash,
                text_preview,
                status,
                target_count,
                queued_count,
                sent_count,
                failed_count,
                expired_count,
                skipped_count,
                now,
                now,
                now if status in {"COMPLETED", "FAILED", "CANCELED"} else None,
            ),
        )
    return get_send_batch(batch_id)  # type: ignore[return-value]


def get_send_batch(batch_id: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            """
            SELECT batch_id, target_type, target_json, text_hash, text_preview, status,
                   target_count, queued_count, sent_count, failed_count, expired_count,
                   skipped_count, created_at, updated_at, completed_at
            FROM send_batches
            WHERE batch_id = ?
            """,
            (batch_id,),
        ).fetchone()


def update_send_batch_counts(
    batch_id: str,
    status: str,
    target_count: int,
    queued_count: int,
    sent_count: int,
    failed_count: int,
    expired_count: int,
    skipped_count: int,
    completed_at: int | None = None,
) -> None:
    now = now_millis()
    with connect() as conn:
        conn.execute(
            """
            UPDATE send_batches
            SET status = ?, target_count = ?, queued_count = ?, sent_count = ?,
                failed_count = ?, expired_count = ?, skipped_count = ?,
                updated_at = ?, completed_at = ?
            WHERE batch_id = ?
            """,
            (
                status,
                target_count,
                queued_count,
                sent_count,
                failed_count,
                expired_count,
                skipped_count,
                now,
                completed_at,
                batch_id,
            ),
        )


def insert_send_batch_item(
    batch_id: str,
    room_key: str,
    room: str,
    job_id: Optional[str],
    status: str,
    skip_reason: Optional[str] = None,
) -> None:
    now = now_millis()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO send_batch_items (
              batch_id, room_key, room, job_id, status, skip_reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(batch_id, room_key) DO UPDATE SET
              room = excluded.room,
              job_id = excluded.job_id,
              status = excluded.status,
              skip_reason = excluded.skip_reason,
              updated_at = excluded.updated_at
            """,
            (batch_id, room_key, room, job_id, status, skip_reason, now, now),
        )


def list_send_batch_items(
    batch_id: str,
    limit: int = 100,
    cursor: Optional[str] = None,
    status: Optional[str] = None,
) -> list[sqlite3.Row]:
    limit = max(min(limit, 1_000), 1)
    clauses = ["batch_id = ?"]
    params: list[Any] = [batch_id]
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if cursor:
        try:
            cursor_id = int(cursor)
        except ValueError:
            cursor_id = -1
        clauses.append("id > ?")
        params.append(cursor_id)
    where = " AND ".join(clauses)
    with connect() as conn:
        return list(
            conn.execute(
                f"""
                SELECT batch_id, room_key, room, job_id, status, skip_reason, created_at, updated_at, id
                FROM send_batch_items
                WHERE {where}
                ORDER BY id ASC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        )


def list_send_batch_items_by_job_ids(job_ids: list[str]) -> list[sqlite3.Row]:
    ids = [job_id for job_id in dict.fromkeys(job_ids) if job_id]
    if not ids:
        return []
    placeholders = ", ".join("?" for _ in ids)
    with connect() as conn:
        return list(
            conn.execute(
                f"""
                SELECT batch_id, room_key, room, job_id, status, skip_reason, created_at, updated_at, id
                FROM send_batch_items
                WHERE job_id IN ({placeholders})
                ORDER BY batch_id ASC, id ASC
                """,
                ids,
            ).fetchall()
        )


def list_send_batches(limit: int = 100, status: Optional[str] = None) -> list[sqlite3.Row]:
    limit = max(min(limit, 1_000), 1)
    clauses: list[str] = []
    params: list[Any] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as conn:
        return list(
            conn.execute(
                f"""
                SELECT batch_id, target_type, target_json, text_hash, text_preview, status,
                       target_count, queued_count, sent_count, failed_count, expired_count,
                       skipped_count, created_at, updated_at, completed_at
                FROM send_batches
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        )


def count_send_batches_by_status() -> dict[str, int]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM send_batches
            GROUP BY status
            """
        ).fetchall()
    counts = {"DRY_RUN": 0, "QUEUED": 0, "RUNNING": 0, "COMPLETED": 0, "FAILED": 0, "CANCELED": 0}
    for row in rows:
        counts[row["status"]] = int(row["count"])
    return counts


def get_send_batch_items_summary(batch_id: str) -> dict[str, int]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM send_batch_items
            WHERE batch_id = ?
            GROUP BY status
            """,
            (batch_id,),
        ).fetchall()
    summary = {
        "QUEUED": 0,
        "SENT": 0,
        "FAILED": 0,
        "TOKEN_EXPIRED": 0,
        "HANDLE_EXPIRED": 0,
        "SKIPPED": 0,
    }
    for row in rows:
        summary[row["status"]] = int(row["count"])
    return summary


def update_send_batch_item_status(
    batch_id: str,
    room_key: str,
    status: str,
    skip_reason: Optional[str] = None,
    job_id: Optional[str] = None,
) -> None:
    now = now_millis()
    with connect() as conn:
        conn.execute(
            """
            UPDATE send_batch_items
            SET status = ?, skip_reason = COALESCE(?, skip_reason), job_id = COALESCE(?, job_id), updated_at = ?
            WHERE batch_id = ? AND room_key = ?
            """,
            (status, skip_reason, job_id, now, batch_id, room_key),
        )
