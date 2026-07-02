from __future__ import annotations

import sqlite3
from typing import Any, Optional

from app.db import connect
from app.schemas import BridgeEvent
from app.time_utils import now_millis


MESSAGE_SELECT_COLUMNS = """
  m.id AS id, m.event_id AS event_id, m.schema_version AS schema_version,
  m.source AS source, m.source_package AS source_package, m.source_type AS source_type,
  m.room_key AS room_key, m.room AS room, m.sender AS sender, m.text AS text,
  m.message_type AS message_type, m.notification_key AS notification_key,
  m.reply_token AS reply_token, m.reply_token_expires_at AS reply_token_expires_at,
  m.received_at AS received_at, m.processed AS processed,
  m.created_at AS created_at, m.updated_at AS updated_at, m.deleted_at AS deleted_at
"""


def insert_message(event: BridgeEvent) -> bool:
    """수신 이벤트를 저장한다.

    Returns:
        새 이벤트면 True, eventId 중복이면 False.
    """

    current = now_millis()
    try:
        with connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO messages (
                  event_id, schema_version, source, source_package, source_type,
                  room_key, room, sender, text, message_type, notification_key,
                  reply_token, reply_token_expires_at, received_at, processed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    event.eventId,
                    event.schemaVersion,
                    event.source,
                    event.sourcePackage,
                    event.sourceType.value if hasattr(event.sourceType, "value") else event.sourceType,
                    event.roomKey,
                    event.room,
                    event.sender,
                    event.text,
                    event.messageType.value if hasattr(event.messageType, "value") else event.messageType,
                    event.notificationKey,
                    event.replyToken,
                    event.replyTokenExpiresAt,
                    event.receivedAt,
                    current,
                    current,
                ),
            )
            _upsert_fts(conn, int(cursor.lastrowid), event.text, event.room, event.sender)
            return True
    except sqlite3.IntegrityError:
        return False


def mark_message_processed(event_id: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE messages SET processed = 1 WHERE event_id = ?", (event_id,))


def list_unprocessed_messages(limit: int = 100) -> list:
    """재시작 recovery 대상인 미처리 메시지를 오래된 순서로 조회한다."""

    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT
                  event_id, schema_version, source, source_package, source_type,
                  room_key, room, sender, text, message_type, notification_key,
                  reply_token, reply_token_expires_at, received_at
                FROM messages
                WHERE processed = 0
                ORDER BY received_at ASC, id ASC
                LIMIT ?
                """,
                (max(min(limit, 1_000), 1),),
            ).fetchall()
        )


def latest_reply_token(room_key: str) -> tuple[Optional[str], Optional[int]]:
    """roomKey 기준 최신 답장 토큰과 만료 시각을 조회한다."""

    with connect() as conn:
        row = conn.execute(
            """
            SELECT reply_token, reply_token_expires_at
            FROM messages
            WHERE room_key = ? AND reply_token IS NOT NULL
            ORDER BY received_at DESC, id DESC
            LIMIT 1
            """,
            (room_key,),
        ).fetchone()
    if row is None:
        return None, None
    return row["reply_token"], row["reply_token_expires_at"]


def expires_at_for_token(reply_token: str) -> Optional[int]:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT reply_token_expires_at
            FROM messages
            WHERE reply_token = ?
            ORDER BY received_at DESC, id DESC
            LIMIT 1
            """,
            (reply_token,),
        ).fetchone()
    if row is None:
        return None
    return row["reply_token_expires_at"]


def get_message(event_id: str, *, include_deleted: bool = False) -> sqlite3.Row | None:
    clause = "" if include_deleted else "AND m.deleted_at IS NULL"
    with connect() as conn:
        return conn.execute(
            f"""
            SELECT {MESSAGE_SELECT_COLUMNS}
            FROM messages m
            WHERE m.event_id = ? {clause}
            LIMIT 1
            """,
            (event_id,),
        ).fetchone()


def list_messages(
    *,
    room_key: str | None = None,
    sender: str | None = None,
    source_type: str | None = None,
    message_type: str | None = None,
    received_after: int | None = None,
    received_before: int | None = None,
    include_deleted: bool = False,
    limit: int = 50,
    cursor: str | None = None,
) -> list[sqlite3.Row]:
    where, params = _message_filter_clause(
        room_key=room_key,
        sender=sender,
        source_type=source_type,
        message_type=message_type,
        received_after=received_after,
        received_before=received_before,
        include_deleted=include_deleted,
    )
    cursor_clause, cursor_params = _cursor_clause(cursor, alias="m")
    query = (
        f"SELECT {MESSAGE_SELECT_COLUMNS} FROM messages m "
        f"WHERE {where}{cursor_clause} "
        "ORDER BY m.received_at DESC, m.id DESC LIMIT ?"
    )
    with connect() as conn:
        return list(conn.execute(query, (*params, *cursor_params, _bounded_limit(limit))).fetchall())


def search_messages(
    *,
    query_text: str,
    room_key: str | None = None,
    sender: str | None = None,
    source_type: str | None = None,
    message_type: str | None = None,
    received_after: int | None = None,
    received_before: int | None = None,
    include_deleted: bool = False,
    limit: int = 50,
    cursor: str | None = None,
) -> list[sqlite3.Row]:
    fts_query = _fts_query(query_text)
    if not fts_query:
        return []
    where, params = _message_filter_clause(
        room_key=room_key,
        sender=sender,
        source_type=source_type,
        message_type=message_type,
        received_after=received_after,
        received_before=received_before,
        include_deleted=include_deleted,
    )
    cursor_clause, cursor_params = _cursor_clause(cursor, alias="m")
    query = (
        f"SELECT {MESSAGE_SELECT_COLUMNS} "
        "FROM messages m "
        "JOIN messages_fts fts ON fts.rowid = m.id "
        f"WHERE messages_fts MATCH ? AND {where}{cursor_clause} "
        "ORDER BY m.received_at DESC, m.id DESC LIMIT ?"
    )
    with connect() as conn:
        return list(conn.execute(query, (fts_query, *params, *cursor_params, _bounded_limit(limit))).fetchall())


def update_message(event_id: str, updates: dict[str, Any]) -> sqlite3.Row | None:
    allowed = {
        "room": "room",
        "sender": "sender",
        "text": "text",
        "messageType": "message_type",
        "message_type": "message_type",
    }
    assignments: list[str] = []
    params: list[Any] = []
    for key, value in updates.items():
        column = allowed.get(key)
        if column is None:
            continue
        assignments.append(f"{column} = ?")
        params.append(value.value if hasattr(value, "value") else value)
    if not assignments:
        return get_message(event_id)

    current = now_millis()
    assignments.append("updated_at = ?")
    params.append(current)
    params.append(event_id)
    with connect() as conn:
        cursor = conn.execute(
            f"""
            UPDATE messages
            SET {", ".join(assignments)}
            WHERE event_id = ? AND deleted_at IS NULL
            """,
            params,
        )
        if cursor.rowcount < 1:
            return None
        row = conn.execute(
            f"SELECT {MESSAGE_SELECT_COLUMNS} FROM messages m WHERE m.event_id = ? LIMIT 1",
            (event_id,),
        ).fetchone()
        if row is not None:
            _upsert_fts(conn, int(row["id"]), row["text"], row["room"], row["sender"])
        return row


def soft_delete_message(event_id: str) -> sqlite3.Row | None:
    current = now_millis()
    with connect() as conn:
        cursor = conn.execute(
            """
            UPDATE messages
            SET deleted_at = COALESCE(deleted_at, ?),
                updated_at = ?,
                text = ''
            WHERE event_id = ?
            """,
            (current, current, event_id),
        )
        if cursor.rowcount < 1:
            return None
        row = conn.execute(
            f"SELECT {MESSAGE_SELECT_COLUMNS} FROM messages m WHERE m.event_id = ? LIMIT 1",
            (event_id,),
        ).fetchone()
        if row is not None:
            _delete_fts(conn, int(row["id"]))
        return row


def recent_message_records(room_key: str, *, limit: int = 20, before: int | None = None) -> list[sqlite3.Row]:
    params: list[Any] = [room_key]
    before_clause = ""
    if before is not None:
        before_clause = "AND m.received_at < ?"
        params.append(before)
    params.append(max(min(limit, 100), 1))
    with connect() as conn:
        return list(
            conn.execute(
                f"""
                SELECT {MESSAGE_SELECT_COLUMNS}
                FROM messages m
                WHERE m.room_key = ? AND m.deleted_at IS NULL {before_clause}
                ORDER BY m.received_at DESC, m.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        )


def _message_filter_clause(
    *,
    room_key: str | None,
    sender: str | None,
    source_type: str | None,
    message_type: str | None,
    received_after: int | None,
    received_before: int | None,
    include_deleted: bool,
) -> tuple[str, list[Any]]:
    clauses = ["1 = 1"]
    params: list[Any] = []
    if not include_deleted:
        clauses.append("m.deleted_at IS NULL")
    if room_key is not None:
        clauses.append("m.room_key = ?")
        params.append(room_key)
    if sender is not None:
        clauses.append("m.sender = ?")
        params.append(sender)
    if source_type is not None:
        clauses.append("m.source_type = ?")
        params.append(source_type)
    if message_type is not None:
        clauses.append("m.message_type = ?")
        params.append(message_type)
    if received_after is not None:
        clauses.append("m.received_at >= ?")
        params.append(received_after)
    if received_before is not None:
        clauses.append("m.received_at <= ?")
        params.append(received_before)
    return " AND ".join(clauses), params


def _cursor_clause(cursor: str | None, *, alias: str) -> tuple[str, list[Any]]:
    if not cursor:
        return "", []
    try:
        received_at_raw, id_raw = cursor.split("\t", 1)
        received_at = int(received_at_raw)
        row_id = int(id_raw)
    except ValueError:
        return "", []
    return (
        f" AND ({alias}.received_at < ? OR ({alias}.received_at = ? AND {alias}.id < ?))",
        [received_at, received_at, row_id],
    )


def _fts_query(query_text: str) -> str:
    tokens = [token for token in query_text.strip().split() if token]
    return " ".join(f'"{token.replace(chr(34), chr(34) + chr(34))}"' for token in tokens)


def _bounded_limit(limit: int) -> int:
    return max(min(limit, 200), 1)


def _upsert_fts(conn: sqlite3.Connection, row_id: int, text: str, room: str, sender: str | None) -> None:
    _delete_fts(conn, row_id)
    conn.execute(
        "INSERT INTO messages_fts(rowid, text, room, sender) VALUES (?, ?, ?, ?)",
        (row_id, text, room, sender or ""),
    )


def _delete_fts(conn: sqlite3.Connection, row_id: int) -> None:
    conn.execute("DELETE FROM messages_fts WHERE rowid = ?", (row_id,))
