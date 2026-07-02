from __future__ import annotations

import json
from typing import Optional

from app.db import connect
from app.schemas import RoomRuleConfig, RoomRuleMode, RoomRuleResponse, RoomRuleUpsertRequest
from app.time_utils import now_millis


def upsert_room_rule(request: RoomRuleUpsertRequest) -> RoomRuleResponse:
    """방별 자동 응답 룰을 생성하거나 갱신한다.

    Args:
        request: shared secret 검증이 끝난 룰 upsert 요청.

    Returns:
        DB에 저장된 최신 룰 상태.
    """

    now = now_millis()
    rule_json = request.rule.model_dump_json()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO room_rules (room_key, room, enabled, mode, rule_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(room_key) DO UPDATE SET
              room = excluded.room,
              enabled = excluded.enabled,
              mode = excluded.mode,
              rule_json = excluded.rule_json,
              updated_at = excluded.updated_at
            """,
            (
                request.roomKey,
                request.room,
                1 if request.enabled else 0,
                request.mode.value,
                rule_json,
                now,
                now,
            ),
        )
    return get_room_rule(request.roomKey) or RoomRuleResponse(
        roomKey=request.roomKey,
        room=request.room,
        enabled=request.enabled,
        mode=request.mode,
        rule=request.rule,
    )


def get_room_rule(room_key: str) -> Optional[RoomRuleResponse]:
    """roomKey 기준 저장된 방별 룰을 조회한다."""

    with connect() as conn:
        row = conn.execute(
            """
            SELECT room_key, room, enabled, mode, rule_json
            FROM room_rules
            WHERE room_key = ?
            """,
            (room_key,),
        ).fetchone()
    if row is None:
        return None
    return RoomRuleResponse(
        roomKey=row["room_key"],
        room=row["room"],
        enabled=bool(row["enabled"]),
        mode=RoomRuleMode(row["mode"]),
        rule=_decode_rule_config(row["rule_json"]),
    )


def _decode_rule_config(rule_json: Optional[str]) -> RoomRuleConfig:
    if not rule_json:
        return RoomRuleConfig()
    try:
        return RoomRuleConfig.model_validate(json.loads(rule_json))
    except (ValueError, TypeError):
        return RoomRuleConfig()
