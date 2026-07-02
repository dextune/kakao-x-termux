from __future__ import annotations

import sqlite3
from typing import Any, Optional

from app.db import connect
from app.time_utils import now_millis

_last_bridge_log_prune_at: dict[str, int] = {}


def insert_bridge_log(
    level: str,
    category: str,
    message: str,
    ref_id: Optional[str] = None,
    created_at: Optional[int] = None,
) -> None:
    """운영 진단 로그를 저장한다.

    Args:
        level: `INFO`, `WARN`, `ERROR` 같은 심각도 문자열.
        category: `event`, `send`, `security` 같은 로그 분류.
        message: PII 정책 적용이 끝난 진단 메시지.
        ref_id: eventId 또는 jobId처럼 원문 없이 추적 가능한 참조값.
        created_at: 테스트와 보관 정책 검증용 epoch millis override.
    """

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO bridge_logs (level, category, message, ref_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (level, category, message, ref_id, created_at or now_millis()),
        )


def prune_bridge_logs(max_rows: int, retention_millis: int, now: Optional[int] = None) -> None:
    """bridge_logs를 기간과 최대 개수 기준으로 정리한다.

    Args:
        max_rows: 최신순으로 남길 최대 로그 수. 0이면 모두 삭제한다.
        retention_millis: 현재 시각 기준 보관할 기간.
        now: 테스트용 기준 시각.
    """

    current = now if now is not None else now_millis()
    cutoff = current - max(retention_millis, 0)
    with connect() as conn:
        conn.execute("DELETE FROM bridge_logs WHERE created_at < ?", (cutoff,))
        if max_rows <= 0:
            conn.execute("DELETE FROM bridge_logs")
        else:
            conn.execute(
                """
                DELETE FROM bridge_logs
                WHERE id NOT IN (
                  SELECT id FROM bridge_logs
                  ORDER BY created_at DESC, id DESC
                  LIMIT ?
                )
                """,
                (max_rows,),
            )


def prune_bridge_logs_throttled(
    max_rows: int,
    retention_millis: int,
    interval_millis: int,
    now: Optional[int] = None,
) -> None:
    """운영 로그 pruning을 DB path별 interval 기준으로 제한한다."""

    from app.config import get_settings

    db_path = get_settings().db_path
    current = now if now is not None else now_millis()
    last = _last_bridge_log_prune_at.get(db_path)
    if last is not None and current - last < max(interval_millis, 0):
        return
    _last_bridge_log_prune_at[db_path] = current
    prune_bridge_logs(max_rows=max_rows, retention_millis=retention_millis, now=current)


def list_bridge_logs(limit: int = 100) -> list[sqlite3.Row]:
    """테스트와 진단 화면에서 사용할 최신 로그 목록을 반환한다."""

    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT id, level, category, message, ref_id, created_at
                FROM bridge_logs
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )


def count_bridge_logs(level: Optional[str] = None, category: Optional[str] = None, limit: int | None = None) -> int:
    """조건에 맞는 bridge log 수를 반환한다.

    limit이 주어지면 최신 N건만 대상으로 count한다.
    """

    clauses = []
    params: list[Any] = []
    if level is not None:
        clauses.append("level = ?")
        params.append(level)
    if category is not None:
        clauses.append("category = ?")
        params.append(category)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as conn:
        if limit is None:
            row = conn.execute(f"SELECT COUNT(*) AS count FROM bridge_logs {where}", params).fetchone()
        else:
            capped = max(min(limit, 10_000), 1)
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM (
                  SELECT id
                  FROM bridge_logs
                  {where}
                  ORDER BY created_at DESC, id DESC
                  LIMIT ?
                )
                """,
                (*params, capped),
            ).fetchone()
    return int(row["count"]) if row is not None else 0
