from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from app.db import connect
from app.repositories.common import decode_json_dict
from app.time_utils import now_millis


def upsert_chatbot_module(
    bot_key: str,
    name: str,
    version: str,
    enabled: bool,
    priority: int,
    options: dict[str, Any] | None = None,
    last_error: Optional[str] = None,
) -> None:
    """로딩된 챗봇 모듈의 전역 메타데이터를 저장한다."""

    now = now_millis()
    options_json = json.dumps(options or {}, ensure_ascii=False, sort_keys=True)
    with connect() as conn:
        row = conn.execute(
            "SELECT enabled, priority, options_json FROM chatbot_modules WHERE bot_key = ?",
            (bot_key,),
        ).fetchone()
        persisted_enabled = int(row["enabled"]) if row is not None else (1 if enabled else 0)
        persisted_priority = int(row["priority"]) if row is not None else priority
        persisted_options = row["options_json"] if row is not None and row["options_json"] else options_json
        conn.execute(
            """
            INSERT INTO chatbot_modules (
              bot_key, name, version, enabled, priority, options_json,
              loaded_at, last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bot_key) DO UPDATE SET
              name = excluded.name,
              version = excluded.version,
              loaded_at = excluded.loaded_at,
              last_error = excluded.last_error,
              updated_at = excluded.updated_at
            """,
            (
                bot_key,
                name,
                version,
                persisted_enabled,
                persisted_priority,
                persisted_options,
                now,
                last_error,
                now,
                now,
            ),
        )


def mark_chatbot_module_error(bot_key: str, last_error: str) -> None:
    """로딩 또는 실행 중 확인된 봇 단위 오류를 module row에 기록한다."""

    with connect() as conn:
        conn.execute(
            """
            UPDATE chatbot_modules
            SET last_error = ?, updated_at = ?
            WHERE bot_key = ?
            """,
            (last_error, now_millis(), bot_key),
        )


def upsert_chatbot_module_file(
    path: str,
    file_name: str,
    size_bytes: int,
    mtime_ns: int,
    sha256: Optional[str],
    bot_key: Optional[str],
    status: str,
    last_error: Optional[str] = None,
    loaded_at: Optional[int] = None,
) -> None:
    """봇 파일 단위 로딩 상태를 저장한다.

    bot key를 얻기 전 발생하는 syntax/import 오류도 파일 기준으로 추적한다.
    """

    now = now_millis()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO chatbot_module_files (
              path, file_name, size_bytes, mtime_ns, sha256, bot_key,
              status, last_error, loaded_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
              file_name = excluded.file_name,
              size_bytes = excluded.size_bytes,
              mtime_ns = excluded.mtime_ns,
              sha256 = excluded.sha256,
              bot_key = excluded.bot_key,
              status = excluded.status,
              last_error = excluded.last_error,
              loaded_at = excluded.loaded_at,
              updated_at = excluded.updated_at
            """,
            (
                path,
                file_name,
                size_bytes,
                mtime_ns,
                sha256,
                bot_key,
                status,
                last_error,
                loaded_at,
                now,
                now,
            ),
        )


def list_chatbot_module_files(status: Optional[str] = None, limit: int = 100) -> list[sqlite3.Row]:
    """봇 파일별 hot reload 상태를 path 순서로 반환한다."""

    limit = max(min(limit, 1_000), 1)
    clauses = []
    params: list[Any] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as conn:
        return list(
            conn.execute(
                f"""
                SELECT path, file_name, size_bytes, mtime_ns, sha256, bot_key,
                       status, last_error, loaded_at, updated_at
                FROM chatbot_module_files
                {where}
                ORDER BY path ASC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        )


def get_chatbot_module_file_by_key(bot_key: str) -> Optional[sqlite3.Row]:
    """bot key에 대응하는 최신 봇 파일 상태를 반환한다."""

    with connect() as conn:
        return conn.execute(
            """
            SELECT path, file_name, size_bytes, mtime_ns, sha256, bot_key,
                   status, last_error, loaded_at, updated_at
            FROM chatbot_module_files
            WHERE bot_key = ?
            ORDER BY updated_at DESC, path ASC
            LIMIT 1
            """,
            (bot_key,),
        ).fetchone()


def count_chatbot_module_files(status: Optional[str] = None) -> int:
    """상태별 봇 파일 수를 반환한다."""

    clauses = []
    params: list[Any] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as conn:
        row = conn.execute(f"SELECT COUNT(*) AS count FROM chatbot_module_files {where}", params).fetchone()
    return int(row["count"]) if row is not None else 0


def update_chatbot_module_config(
    bot_key: str,
    enabled: Optional[bool] = None,
    priority: Optional[int] = None,
    options: dict[str, Any] | None = None,
) -> Optional[sqlite3.Row]:
    """전역 봇 옵션을 갱신하고 최신 row를 반환한다."""

    current = get_chatbot_module(bot_key)
    if current is None:
        return None
    merged_options = decode_json_dict(current["options_json"])
    if options is not None:
        merged_options.update(options)
    with connect() as conn:
        conn.execute(
            """
            UPDATE chatbot_modules
            SET enabled = ?, priority = ?, options_json = ?, updated_at = ?
            WHERE bot_key = ?
            """,
            (
                1 if (bool(current["enabled"]) if enabled is None else enabled) else 0,
                int(current["priority"]) if priority is None else priority,
                json.dumps(merged_options, ensure_ascii=False, sort_keys=True),
                now_millis(),
                bot_key,
            ),
        )
    return get_chatbot_module(bot_key)


def get_chatbot_module(bot_key: str) -> Optional[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            """
            SELECT bot_key, name, version, enabled, priority, options_json, loaded_at, last_error
            FROM chatbot_modules
            WHERE bot_key = ?
            """,
            (bot_key,),
        ).fetchone()


def list_chatbot_modules(limit: int = 100) -> list[sqlite3.Row]:
    """등록된 챗봇 모듈 목록을 priority 순서로 반환한다."""

    limit = max(min(limit, 1_000), 1)
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT bot_key, name, version, enabled, priority, options_json, loaded_at, last_error
                FROM chatbot_modules
                ORDER BY priority ASC, bot_key ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )


def list_chatbot_modules_by_key() -> dict[str, sqlite3.Row]:
    """이벤트 처리 1건에서 사용할 챗봇 모듈 설정을 한 번에 조회한다."""

    return {row["bot_key"]: row for row in list_chatbot_modules(limit=1_000)}


def count_chatbot_modules_with_errors() -> int:
    """last_error가 남아 있는 챗봇 모듈 수를 반환한다."""

    with connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM chatbot_modules
            WHERE last_error IS NOT NULL AND last_error != ''
            """
        ).fetchone()
    return int(row["count"]) if row is not None else 0


def upsert_room_bot_options(
    room_key: str,
    bot_key: str,
    enabled: bool,
    options: dict[str, Any] | None = None,
) -> sqlite3.Row:
    """방별 봇 활성화와 옵션을 저장한다."""

    now = now_millis()
    options_json = json.dumps(options or {}, ensure_ascii=False, sort_keys=True)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO room_bot_options (
              room_key, bot_key, enabled, options_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(room_key, bot_key) DO UPDATE SET
              enabled = excluded.enabled,
              options_json = excluded.options_json,
              updated_at = excluded.updated_at
            """,
            (room_key, bot_key, 1 if enabled else 0, options_json, now, now),
        )
    row = get_room_bot_options(room_key, bot_key)
    if row is None:
        raise RuntimeError("room bot option upsert failed")
    return row


def get_room_bot_options(room_key: str, bot_key: str) -> Optional[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            """
            SELECT room_key, bot_key, enabled, options_json
            FROM room_bot_options
            WHERE room_key = ? AND bot_key = ?
            """,
            (room_key, bot_key),
        ).fetchone()


def list_room_bot_options_by_key(room_key: str) -> dict[str, sqlite3.Row]:
    """roomKey의 봇별 옵션을 한 번에 조회한다."""

    with connect() as conn:
        return {
            row["bot_key"]: row
            for row in conn.execute(
                """
                SELECT room_key, bot_key, enabled, options_json
                FROM room_bot_options
                WHERE room_key = ?
                """,
                (room_key,),
            ).fetchall()
        }


def list_room_bot_options_grouped(limit_rows: int = 50_000) -> dict[str, dict[str, sqlite3.Row]]:
    """전체 room_bot_options를 roomKey/botKey 기준으로 묶어서 조회한다.

    Args:
        limit_rows: memory warmup 안전장치로 읽을 최대 row 수.
    """

    limit_rows = max(min(limit_rows, 200_000), 1)
    grouped: dict[str, dict[str, sqlite3.Row]] = {}
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT room_key, bot_key, enabled, options_json
            FROM room_bot_options
            ORDER BY room_key ASC, bot_key ASC
            LIMIT ?
            """,
            (limit_rows,),
        ).fetchall()
    for row in rows:
        grouped.setdefault(row["room_key"], {})[row["bot_key"]] = row
    return grouped
