from __future__ import annotations

import json
import sqlite3
from typing import Optional

from app.db import connect
from app.time_utils import now_millis


def upsert_send_target_group(
    group_key: str,
    name: str,
    group_type: str,
    enabled: bool,
    filter_json: Optional[dict] = None,
) -> sqlite3.Row:
    """발송 대상 그룹을 생성하거나 갱신한다."""

    now = now_millis()
    filter_raw = json.dumps(filter_json or {}, ensure_ascii=False, sort_keys=True) if filter_json is not None else None
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO send_target_groups (
              group_key, name, type, filter_json, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(group_key) DO UPDATE SET
              name = excluded.name,
              type = excluded.type,
              filter_json = excluded.filter_json,
              enabled = excluded.enabled,
              updated_at = excluded.updated_at
            """,
            (group_key, name, group_type, filter_raw, 1 if enabled else 0, now, now),
        )
    return get_send_target_group(group_key)  # type: ignore[return-value]


def replace_send_target_group_rooms(group_key: str, room_keys: list[str]) -> None:
    """그룹에 연결된 static room 목록을 교체한다."""

    unique_room_keys = [room_key for room_key in dict.fromkeys(room_keys) if room_key]
    now = now_millis()
    with connect() as conn:
        conn.execute("DELETE FROM send_target_group_rooms WHERE group_key = ?", (group_key,))
        for room_key in unique_room_keys:
            conn.execute(
                """
                INSERT INTO send_target_group_rooms (group_key, room_key, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(group_key, room_key) DO UPDATE SET created_at = excluded.created_at
                """,
                (group_key, room_key, now),
            )


def get_send_target_group(group_key: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            """
            SELECT group_key, name, type, filter_json, enabled, created_at, updated_at
            FROM send_target_groups
            WHERE group_key = ?
            """,
            (group_key,),
        ).fetchone()


def list_send_target_groups(limit: int = 100) -> list[sqlite3.Row]:
    limit = max(min(limit, 1_000), 1)
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT group_key, name, type, filter_json, enabled, created_at, updated_at
                FROM send_target_groups
                ORDER BY updated_at DESC, group_key ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )


def list_send_target_group_rooms(group_key: str) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT room_key
            FROM send_target_group_rooms
            WHERE group_key = ?
            ORDER BY room_key ASC
            """,
            (group_key,),
        ).fetchall()
    return [row["room_key"] for row in rows]


def delete_send_target_group(group_key: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM send_target_group_rooms WHERE group_key = ?", (group_key,))
        conn.execute("DELETE FROM send_target_groups WHERE group_key = ?", (group_key,))
