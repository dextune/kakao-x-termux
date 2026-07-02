from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable, Optional

from app.config import get_settings
from app.db import connect
from app.repositories.bridge_logs import insert_bridge_log
from app.repositories.common import decode_json_dict
from app.time_utils import now_millis

_last_state_prune_at: dict[str, int] = {}


def get_bot_state(state_key: str) -> Optional[dict[str, Any]]:
    """만료되지 않은 챗봇 상태를 조회한다."""

    snapshot = get_bot_state_snapshot(state_key)
    if snapshot is None:
        return None
    return dict(snapshot["value"])


def get_bot_state_snapshot(state_key: str) -> Optional[dict[str, Any]]:
    """만료되지 않은 챗봇 상태와 checkpoint metadata를 함께 조회한다."""

    now = now_millis()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT state_key, room_key, sender, bot_key, state_json, expires_at, updated_at
            FROM chatbot_states
            WHERE state_key = ?
            """,
            (state_key,),
        ).fetchone()
        if row is not None and row["expires_at"] is not None and int(row["expires_at"]) <= now:
            conn.execute("DELETE FROM chatbot_states WHERE state_key = ?", (state_key,))
            return None
    if row is None:
        return None
    return {
        "state_key": row["state_key"],
        "room_key": row["room_key"],
        "sender": row["sender"],
        "bot_key": row["bot_key"],
        "value": decode_json_dict(row["state_json"]),
        "expires_at": row["expires_at"],
        "updated_at": row["updated_at"],
    }


def set_bot_state(
    state_key: str,
    bot_key: str,
    room_key: str,
    sender: Optional[str],
    value: dict[str, Any],
    expires_at: Optional[int] = None,
) -> bool:
    """챗봇 상태를 upsert한다."""

    now = now_millis()
    state_json = json.dumps(value, ensure_ascii=False, sort_keys=True)
    max_bytes = max(get_settings().chatbot_max_state_bytes, 0)
    if max_bytes and len(state_json.encode("utf-8")) > max_bytes:
        insert_bridge_log(
            "ERROR",
            "chatbot_state",
            f"state too large botKey={bot_key} stateKey={state_key} bytes={len(state_json.encode('utf-8'))} maxBytes={max_bytes}",
            state_key,
        )
        return False
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO chatbot_states (
              state_key, room_key, sender, bot_key, state_json, expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(state_key) DO UPDATE SET
              room_key = excluded.room_key,
              sender = excluded.sender,
              bot_key = excluded.bot_key,
              state_json = excluded.state_json,
              expires_at = excluded.expires_at,
              updated_at = excluded.updated_at
            """,
            (
                state_key,
                room_key,
                sender,
                bot_key,
                state_json,
                expires_at,
                now,
                now,
            ),
        )
    return True


def update_bot_state(
    state_key: str,
    bot_key: str,
    room_key: str,
    sender: Optional[str],
    updater: Callable[[dict[str, Any]], dict[str, Any]],
    expires_at: Optional[int] = None,
) -> dict[str, Any]:
    """챗봇 상태를 한 transaction 안에서 읽고 갱신한다."""

    updated, _ = update_bot_state_with_result(
        state_key=state_key,
        bot_key=bot_key,
        room_key=room_key,
        sender=sender,
        updater=updater,
        expires_at=expires_at,
    )
    return updated


def update_bot_state_with_result(
    state_key: str,
    bot_key: str,
    room_key: str,
    sender: Optional[str],
    updater: Callable[[dict[str, Any]], dict[str, Any]],
    expires_at: Optional[int] = None,
) -> tuple[dict[str, Any], bool]:
    """챗봇 상태를 transaction 안에서 갱신하고 저장 성공 여부를 함께 반환한다."""

    now = now_millis()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT state_json, expires_at
            FROM chatbot_states
            WHERE state_key = ?
            """,
            (state_key,),
        ).fetchone()
        if row is None or (row["expires_at"] is not None and int(row["expires_at"]) <= now):
            current: dict[str, Any] = {}
        else:
            current = decode_json_dict(row["state_json"])
        updated = updater(dict(current))
        state_json = json.dumps(updated, ensure_ascii=False, sort_keys=True)
        max_bytes = max(get_settings().chatbot_max_state_bytes, 0)
        if max_bytes and len(state_json.encode("utf-8")) > max_bytes:
            conn.execute(
                """
                INSERT INTO bridge_logs (level, category, message, ref_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "ERROR",
                    "chatbot_state",
                    f"state too large botKey={bot_key} stateKey={state_key} bytes={len(state_json.encode('utf-8'))} maxBytes={max_bytes}",
                    state_key,
                    now,
                ),
            )
            return current, False
        conn.execute(
            """
            INSERT INTO chatbot_states (
              state_key, room_key, sender, bot_key, state_json, expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(state_key) DO UPDATE SET
              room_key = excluded.room_key,
              sender = excluded.sender,
              bot_key = excluded.bot_key,
              state_json = excluded.state_json,
              expires_at = excluded.expires_at,
              updated_at = excluded.updated_at
            """,
            (state_key, room_key, sender, bot_key, state_json, expires_at, now, now),
        )
        return updated, True


def delete_bot_state(state_key: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM chatbot_states WHERE state_key = ?", (state_key,))


def prune_bot_states(now: Optional[int] = None) -> int:
    """만료된 챗봇 상태를 삭제하고 삭제 건수를 반환한다."""

    current = now if now is not None else now_millis()
    with connect() as conn:
        cursor = conn.execute(
            "DELETE FROM chatbot_states WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (current,),
        )
        return int(cursor.rowcount)


def prune_bot_states_throttled(interval_millis: int, now: Optional[int] = None) -> int:
    """DB path별 interval 안에서는 만료 상태 전체 삭제를 건너뛴다."""

    db_path = get_settings().db_path
    current = now if now is not None else now_millis()
    last = _last_state_prune_at.get(db_path)
    if last is not None and current - last < max(interval_millis, 0):
        return 0
    _last_state_prune_at[db_path] = current
    return prune_bot_states(now=current)


def list_bot_states(
    bot_key: Optional[str] = None,
    room_key: Optional[str] = None,
    limit: int = 100,
) -> list[sqlite3.Row]:
    """테스트와 운영 진단에 사용할 상태 목록을 반환한다."""

    limit = max(min(limit, 1_000), 1)
    clauses = []
    params: list[Any] = []
    if bot_key is not None:
        clauses.append("bot_key = ?")
        params.append(bot_key)
    if room_key is not None:
        clauses.append("room_key = ?")
        params.append(room_key)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as conn:
        return list(
            conn.execute(
                f"""
                SELECT state_key, room_key, sender, bot_key, state_json, expires_at, updated_at
                FROM chatbot_states
                {where}
                ORDER BY updated_at DESC, state_key ASC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        )


def list_bot_state_snapshots(limit: int = 1000) -> list[sqlite3.Row]:
    """memory state cache warmup용 최신 상태 snapshot을 반환한다."""

    current = now_millis()
    capped = max(min(limit, 50_000), 1)
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT state_key, room_key, sender, bot_key, state_json, expires_at, updated_at
                FROM chatbot_states
                WHERE expires_at IS NULL OR expires_at > ?
                ORDER BY updated_at DESC, state_key ASC
                LIMIT ?
                """,
                (current, capped),
            ).fetchall()
        )
