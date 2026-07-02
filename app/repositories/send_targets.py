from __future__ import annotations

import sqlite3
from typing import Any, Optional

from app.db import connect
from app.schemas import ReplyJobStatus, RoomType, TargetSourceFilter, TargetStatus

FAILED_REPLY_STATUSES = {
    ReplyJobStatus.failed.value,
    ReplyJobStatus.token_expired.value,
    ReplyJobStatus.handle_expired.value,
}


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _base_latest_target_query() -> str:
    return """
    WITH latest_messages AS (
      SELECT
        m.id AS message_id,
        m.room_key,
        m.room,
        m.sender,
        m.source_type,
        m.reply_token,
        m.reply_token_expires_at,
        m.received_at,
        (
          SELECT COUNT(DISTINCT m2.sender)
          FROM messages m2
          WHERE m2.room_key = m.room_key
            AND m2.sender IS NOT NULL
            AND m2.sender != ''
        ) AS sender_count
      FROM messages m
      WHERE m.id = (
        SELECT m1.id
        FROM messages m1
        WHERE m1.room_key = m.room_key
        ORDER BY m1.received_at DESC, m1.id DESC
        LIMIT 1
      )
    ),
    latest_jobs AS (
      SELECT j.room_key, j.status AS last_send_status, j.created_at AS last_send_at
      FROM reply_jobs j
      WHERE j.id = (
        SELECT j1.id
        FROM reply_jobs j1
        WHERE j1.room_key = j.room_key
        ORDER BY j1.created_at DESC, j1.id DESC
        LIMIT 1
      )
    )
    SELECT
      lm.message_id,
      lm.room_key,
      lm.room,
      lm.sender,
      lm.source_type,
      lm.reply_token,
      lm.reply_token_expires_at,
      lm.received_at,
      lm.sender_count,
      lj.last_send_status,
      lj.last_send_at
    FROM latest_messages lm
    LEFT JOIN latest_jobs lj ON lj.room_key = lm.room_key
    """


def _status_clause(status: TargetStatus, now: int, safety_window_ms: int) -> tuple[str, list[Any]]:
    safety_cutoff = now + max(safety_window_ms, 0)
    if status == TargetStatus.available:
        return (
            "lm.reply_token IS NOT NULL AND lm.reply_token_expires_at IS NOT NULL AND lm.reply_token_expires_at > ?",
            [safety_cutoff],
        )
    if status == TargetStatus.expiring:
        return (
            "lm.reply_token IS NOT NULL AND lm.reply_token_expires_at IS NOT NULL AND lm.reply_token_expires_at > ? AND lm.reply_token_expires_at <= ?",
            [now, safety_cutoff],
        )
    if status == TargetStatus.expired:
        return ("(lm.reply_token IS NULL OR lm.reply_token_expires_at IS NULL OR lm.reply_token_expires_at <= ?)", [now])
    if status == TargetStatus.unknown:
        return ("lm.reply_token IS NOT NULL AND lm.reply_token_expires_at IS NULL", [])
    return ("1 = 1", [])


def _where_clause(
    q: Optional[str],
    status: TargetStatus,
    source_type: TargetSourceFilter,
    room_type: Optional[RoomType],
    seen_after: Optional[int],
    seen_before: Optional[int],
    expires_after: Optional[int],
    expires_before: Optional[int],
    has_recent_failure: Optional[bool],
    now: int,
    safety_window_ms: int,
    allowed_source_types: list[str] | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    source_type_value = _enum_value(source_type)
    status_value = _enum_value(status)
    room_type_value = _enum_value(room_type) if room_type is not None else None
    if q:
        term = f"%{q.lower()}%"
        clauses.append(
            "(LOWER(lm.room_key) LIKE ? OR LOWER(lm.room) LIKE ? OR LOWER(COALESCE(lm.sender, '')) LIKE ?)"
        )
        params.extend([term, term, term])
    if source_type_value != TargetSourceFilter.all.value:
        clauses.append("lm.source_type = ?")
        params.append(source_type_value)
    if allowed_source_types:
        placeholders = ", ".join("?" for _ in allowed_source_types)
        clauses.append(f"lm.source_type IN ({placeholders})")
        params.extend(allowed_source_types)
    if room_type_value is not None:
        clauses.append(
            "CASE WHEN lm.sender_count > 1 THEN 'group' WHEN lm.sender_count = 1 THEN 'direct' ELSE 'unknown' END = ?"
        )
        params.append(room_type_value)
    if seen_after is not None:
        clauses.append("lm.received_at >= ?")
        params.append(seen_after)
    if seen_before is not None:
        clauses.append("lm.received_at <= ?")
        params.append(seen_before)
    if expires_after is not None:
        clauses.append("lm.reply_token_expires_at >= ?")
        params.append(expires_after)
    if expires_before is not None:
        clauses.append("lm.reply_token_expires_at <= ?")
        params.append(expires_before)
    if has_recent_failure is not None:
        if has_recent_failure:
            clauses.append("COALESCE(lj.last_send_status, '') IN (?, ?, ?)")
            params.extend(sorted(FAILED_REPLY_STATUSES))
        else:
            clauses.append("(lj.last_send_status IS NULL OR COALESCE(lj.last_send_status, '') NOT IN (?, ?, ?))")
            params.extend(sorted(FAILED_REPLY_STATUSES))
    status_clause, status_params = _status_clause(TargetStatus(status_value), now, safety_window_ms) if status_value in TargetStatus._value2member_map_ else _status_clause(TargetStatus.all, now, safety_window_ms)
    if status_clause != "1 = 1":
        clauses.append(status_clause)
        params.extend(status_params)
    if not clauses:
        return "1 = 1", []
    return " AND ".join(clauses), params


def _cursor_clause(cursor: Optional[str]) -> tuple[str, list[Any]]:
    if not cursor:
        return "", []
    try:
        cursor_received_at_str, cursor_message_id_str, cursor_room_key = cursor.split("\t", 2)
        cursor_received_at = int(cursor_received_at_str)
        cursor_message_id = int(cursor_message_id_str)
    except ValueError:
        return "", []
    return (
        " AND (lm.received_at < ? OR (lm.received_at = ? AND lm.room_key > ?) "
        "OR (lm.received_at = ? AND lm.room_key = ? AND lm.message_id < ?))",
        [cursor_received_at, cursor_received_at, cursor_room_key, cursor_received_at, cursor_room_key, cursor_message_id],
    )


def _query_latest_targets(
    *,
    limit: int,
    cursor: Optional[str],
    q: Optional[str],
    status: TargetStatus,
    source_type: TargetSourceFilter,
    room_type: Optional[RoomType],
    seen_after: Optional[int],
    seen_before: Optional[int],
    expires_after: Optional[int],
    expires_before: Optional[int],
    has_recent_failure: Optional[bool],
    now: int,
    safety_window_ms: int,
    allowed_source_types: list[str] | None,
) -> list[sqlite3.Row]:
    where_clause, params = _where_clause(
        q=q,
        status=status,
        source_type=source_type,
        room_type=room_type,
        seen_after=seen_after,
        seen_before=seen_before,
        expires_after=expires_after,
        expires_before=expires_before,
        has_recent_failure=has_recent_failure,
        now=now,
        safety_window_ms=safety_window_ms,
        allowed_source_types=allowed_source_types,
    )
    cursor_clause, cursor_params = _cursor_clause(cursor)
    query = (
        _base_latest_target_query()
        + f" WHERE {where_clause}"
        + cursor_clause
        + " ORDER BY lm.received_at DESC, lm.room_key ASC, lm.message_id DESC LIMIT ?"
    )
    with connect() as conn:
        return list(conn.execute(query, (*params, *cursor_params, max(min(limit, 10_000), 1))).fetchall())


def list_latest_send_targets(
    limit: int,
    cursor: Optional[str],
    q: Optional[str],
    status: TargetStatus,
    source_type: TargetSourceFilter,
    room_type: Optional[RoomType],
    seen_after: Optional[int],
    seen_before: Optional[int],
    expires_after: Optional[int],
    expires_before: Optional[int],
    has_recent_failure: Optional[bool],
    now: int,
    safety_window_ms: int,
    allowed_source_types: list[str] | None,
) -> list[sqlite3.Row]:
    return _query_latest_targets(
        limit=limit,
        cursor=cursor,
        q=q,
        status=status,
        source_type=source_type,
        room_type=room_type,
        seen_after=seen_after,
        seen_before=seen_before,
        expires_after=expires_after,
        expires_before=expires_before,
        has_recent_failure=has_recent_failure,
        now=now,
        safety_window_ms=safety_window_ms,
        allowed_source_types=allowed_source_types,
    )


def get_latest_send_targets_for_room_keys(room_keys: list[str]) -> list[sqlite3.Row]:
    keys = [room_key for room_key in dict.fromkeys(room_keys) if room_key]
    if not keys:
        return []
    placeholders = ", ".join("?" for _ in keys)
    query = _base_latest_target_query() + f" WHERE lm.room_key IN ({placeholders}) ORDER BY lm.received_at DESC, lm.room_key ASC, lm.message_id DESC"
    with connect() as conn:
        return list(conn.execute(query, keys).fetchall())


def get_latest_send_target_for_room_key(room_key: str) -> sqlite3.Row | None:
    rows = get_latest_send_targets_for_room_keys([room_key])
    return rows[0] if rows else None


def count_latest_send_targets(
    q: Optional[str],
    status: TargetStatus,
    source_type: TargetSourceFilter,
    room_type: Optional[RoomType],
    seen_after: Optional[int],
    seen_before: Optional[int],
    expires_after: Optional[int],
    expires_before: Optional[int],
    has_recent_failure: Optional[bool],
    now: int,
    safety_window_ms: int,
    allowed_source_types: list[str] | None,
) -> dict[str, int]:
    rows = _query_latest_targets(
        limit=10_000,
        cursor=None,
        q=q,
        status=TargetStatus.all,
        source_type=source_type,
        room_type=room_type,
        seen_after=seen_after,
        seen_before=seen_before,
        expires_after=expires_after,
        expires_before=expires_before,
        has_recent_failure=has_recent_failure,
        now=now,
        safety_window_ms=safety_window_ms,
        allowed_source_types=allowed_source_types,
    )
    counts = {"total": 0, "available": 0, "expiring": 0, "expired": 0, "unknown": 0}
    for row in rows:
        counts["total"] += 1
        counts[_classify_target_status(row["reply_token"], row["reply_token_expires_at"], now, safety_window_ms)] += 1
    return counts


def _classify_target_status(reply_token: str | None, expires_at: int | None, now: int, safety_window_ms: int) -> str:
    if reply_token is None or expires_at is None:
        if reply_token is not None and expires_at is None:
            return "unknown"
        return "expired"
    if expires_at <= now:
        return "expired"
    if expires_at <= now + max(safety_window_ms, 0):
        return "expiring"
    return "available"
