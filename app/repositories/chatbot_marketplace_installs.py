from __future__ import annotations

import sqlite3

from app.db import connect
from app.time_utils import now_millis


def get_marketplace_install(bot_key: str) -> sqlite3.Row | None:
    """botKey 기준 marketplace 설치 이력을 반환한다."""

    with connect() as conn:
        return conn.execute(
            """
            SELECT bot_key, marketplace_bot_id, marketplace_base_url, package_sha256,
                   version, folder_name, installed_at, updated_at
            FROM chatbot_marketplace_installs
            WHERE bot_key = ?
            """,
            (bot_key,),
        ).fetchone()


def upsert_marketplace_install(
    *,
    bot_key: str,
    marketplace_bot_id: str | None,
    marketplace_base_url: str | None,
    package_sha256: str,
    version: str,
    folder_name: str,
) -> sqlite3.Row:
    """설치 또는 업데이트 성공 후 로컬 이력을 갱신한다."""

    now = now_millis()
    with connect() as conn:
        current = conn.execute(
            "SELECT installed_at FROM chatbot_marketplace_installs WHERE bot_key = ?",
            (bot_key,),
        ).fetchone()
        installed_at = int(current["installed_at"]) if current is not None else now
        conn.execute(
            """
            INSERT INTO chatbot_marketplace_installs (
              bot_key, marketplace_bot_id, marketplace_base_url, package_sha256,
              version, folder_name, installed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bot_key) DO UPDATE SET
              marketplace_bot_id = excluded.marketplace_bot_id,
              marketplace_base_url = excluded.marketplace_base_url,
              package_sha256 = excluded.package_sha256,
              version = excluded.version,
              folder_name = excluded.folder_name,
              updated_at = excluded.updated_at
            """,
            (
                bot_key,
                marketplace_bot_id,
                marketplace_base_url,
                package_sha256,
                version,
                folder_name,
                installed_at,
                now,
            ),
        )
    row = get_marketplace_install(bot_key)
    assert row is not None
    return row
