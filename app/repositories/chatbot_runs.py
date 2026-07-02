from __future__ import annotations

import sqlite3
from typing import Any, Optional

from app.config import get_settings
from app.db import connect
from app.time_utils import now_millis

_last_run_prune_at: dict[str, int] = {}


def insert_chatbot_run(
    event_id: str,
    bot_key: str,
    action: str,
    reason: Optional[str] = None,
    duration_ms: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    """봇 실행 결과를 저장한다."""

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO chatbot_runs (event_id, bot_key, action, reason, duration_ms, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, bot_key, action, reason, duration_ms, error, now_millis()),
        )
    settings = get_settings()
    prune_chatbot_runs_throttled(
        max_rows=settings.chatbot_run_max_rows,
        retention_millis=settings.chatbot_run_retention_millis,
        interval_millis=settings.chatbot_run_prune_interval_millis,
    )


def prune_chatbot_runs(max_rows: int, retention_millis: int, now: Optional[int] = None) -> None:
    """chatbot_runs를 기간과 최대 개수 기준으로 정리한다."""

    current = now if now is not None else now_millis()
    cutoff = current - max(retention_millis, 0)
    with connect() as conn:
        conn.execute("DELETE FROM chatbot_runs WHERE created_at < ?", (cutoff,))
        if max_rows <= 0:
            conn.execute("DELETE FROM chatbot_runs")
        else:
            conn.execute(
                """
                DELETE FROM chatbot_runs
                WHERE id NOT IN (
                  SELECT id FROM chatbot_runs
                  ORDER BY created_at DESC, id DESC
                  LIMIT ?
                )
                """,
                (max_rows,),
            )


def prune_chatbot_runs_throttled(
    max_rows: int,
    retention_millis: int,
    interval_millis: int,
    now: Optional[int] = None,
) -> None:
    """실행 로그 pruning을 DB path별 interval 기준으로 제한한다."""

    db_path = get_settings().db_path
    current = now if now is not None else now_millis()
    last = _last_run_prune_at.get(db_path)
    if last is not None and current - last < max(interval_millis, 0):
        return
    _last_run_prune_at[db_path] = current
    prune_chatbot_runs(max_rows=max_rows, retention_millis=retention_millis, now=current)


def list_chatbot_runs(
    event_id: Optional[str] = None,
    bot_key: Optional[str] = None,
    limit: int = 100,
) -> list[sqlite3.Row]:
    """테스트와 운영 진단에서 봇 실행 기록을 조회한다."""

    limit = max(min(limit, 1_000), 1)
    clauses = []
    params: list[Any] = []
    if event_id is not None:
        clauses.append("event_id = ?")
        params.append(event_id)
    if bot_key is not None:
        clauses.append("bot_key = ?")
        params.append(bot_key)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as conn:
        return list(
            conn.execute(
                f"""
                SELECT event_id, bot_key, action, reason, duration_ms, error, created_at
                FROM chatbot_runs
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        )
