from __future__ import annotations

from app.repositories.send_groups import (
    delete_send_target_group,
    get_send_target_group,
    list_send_target_group_rooms,
    list_send_target_groups,
    replace_send_target_group_rooms,
    upsert_send_target_group,
)
from app.schemas import SendTargetFilter, SendTargetGroupResponse, SendTargetGroupType, SendTargetSpec, SendTargetType


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


class SendGroupService:
    """저장된 발송 그룹 CRUD를 담당한다."""

    def upsert_group(self, request) -> SendTargetGroupResponse:
        """그룹 정의와 room 목록을 저장한다."""

        upsert_send_target_group(
            group_key=request.groupKey,
            name=request.name,
            group_type=_enum_value(request.type),
            enabled=request.enabled,
            filter_json=request.filter.model_dump(mode="json") if request.filter is not None else None,
        )
        replace_send_target_group_rooms(request.groupKey, request.roomKeys)
        return self.get_group(request.groupKey)

    def list_groups(self, limit: int = 100) -> list[SendTargetGroupResponse]:
        """저장된 그룹 목록을 반환한다."""

        return [self._row_to_response(row) for row in list_send_target_groups(limit=limit)]

    def get_group(self, group_key: str) -> SendTargetGroupResponse | None:
        """단일 그룹을 반환한다."""

        row = get_send_target_group(group_key)
        if row is None:
            return None
        return self._row_to_response(row)

    def delete_group(self, group_key: str) -> None:
        """그룹과 연결된 room 목록을 삭제한다."""

        delete_send_target_group(group_key)

    def resolve_group_spec(self, group_key: str) -> SendTargetSpec | None:
        """저장 그룹을 발송 target spec으로 변환한다."""

        row = get_send_target_group(group_key)
        if row is None:
            return None
        if not bool(row["enabled"]):
            return None
        room_keys = list_send_target_group_rooms(group_key)
        filter_model = None
        if row["filter_json"]:
            filter_model = SendTargetFilter.model_validate_json(row["filter_json"])
        group_type = str(row["type"])
        if group_type == SendTargetGroupType.static.value:
            return SendTargetSpec(type=SendTargetType.rooms, roomKeys=room_keys, filter=filter_model or SendTargetFilter(), groupKey=group_key)
        if group_type == SendTargetGroupType.dynamic.value:
            return SendTargetSpec(type=SendTargetType.filter, roomKeys=[], filter=filter_model or SendTargetFilter(), groupKey=group_key)
        return SendTargetSpec(type=SendTargetType.rooms, roomKeys=room_keys, filter=filter_model or SendTargetFilter(), groupKey=group_key)

    def _row_to_response(self, row) -> SendTargetGroupResponse:
        filter_model = None
        if row["filter_json"]:
            filter_model = SendTargetFilter.model_validate_json(row["filter_json"])
        return SendTargetGroupResponse(
            groupKey=row["group_key"],
            name=row["name"],
            type=SendTargetGroupType(row["type"]),
            enabled=bool(row["enabled"]),
            roomKeys=list_send_target_group_rooms(row["group_key"]),
            filter=filter_model,
            createdAt=int(row["created_at"]),
            updatedAt=int(row["updated_at"]),
        )
