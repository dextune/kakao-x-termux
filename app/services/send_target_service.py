from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app import repository
from app.config import get_settings
from app.infra.memory_caches import ReplyTokenCache
from app.infra.runtime_resources import get_runtime_resources
from app.repositories.send_targets import get_latest_send_targets_for_room_keys, list_latest_send_targets
from app.schemas import (
    RoomType,
    SendTargetFilter,
    SendTargetGroupType,
    SendTargetItem,
    SendTargetListResponse,
    SendTargetSpec,
    SendTargetType,
    TargetSourceFilter,
    TargetStatus,
)
from app.time_utils import now_millis


@dataclass
class ResolvedTarget:
    """배치 생성에서 사용하는 내부 target 해석 결과다."""

    room_key: str
    room: str
    reply_token: str | None
    reply_token_expires_at: int | None
    last_seen_at: int
    source_type: str
    last_sender: str | None
    sender_count: int
    last_send_status: str | None
    last_send_at: int | None


@dataclass
class TargetResolution:
    """대상 해석 결과와 제외 사유를 함께 보관한다."""

    targets: list[ResolvedTarget]
    excluded_reasons: dict[str, int]
    total_count: int


def _mask_sender(value: str | None, include_raw: bool) -> str | None:
    if value is None:
        return None
    if include_raw:
        return value
    return "<redacted>"


def _target_status(reply_token: str | None, expires_at: int | None, now: int, safety_window_ms: int) -> TargetStatus:
    if reply_token is None:
        return TargetStatus.expired
    if expires_at is None:
        return TargetStatus.unknown
    if expires_at <= now:
        return TargetStatus.expired
    if expires_at <= now + max(safety_window_ms, 0):
        return TargetStatus.expiring
    return TargetStatus.available


def _room_type(sender_count: int) -> RoomType:
    if sender_count > 1:
        return RoomType.group
    if sender_count == 1:
        return RoomType.direct
    return RoomType.unknown


def _cursor_for_row(row) -> str:
    return f"{int(row['received_at'])}\t{int(row['message_id'])}\t{row['room_key']}"


def _allowed_source_types() -> list[str]:
    raw = get_settings().bulk_send_allowed_source_types
    return [item.strip() for item in raw.split(",") if item.strip()]


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _normalize_status(status: TargetStatus, for_send: bool) -> TargetStatus:
    if not for_send:
        return status
    if status in (TargetStatus.available, TargetStatus.expiring):
        return status
    return TargetStatus.expired


def _load_cached_token_cache() -> ReplyTokenCache | None:
    resources = get_runtime_resources()
    return getattr(resources, "reply_token_cache", None)


class SendTargetService:
    """발송 가능한 방 검색과 batch 대상 해석을 담당한다."""

    def list_targets(
        self,
        *,
        q: Optional[str] = None,
        status: TargetStatus = TargetStatus.all,
        source_type: TargetSourceFilter = TargetSourceFilter.all,
        room_type: Optional[RoomType] = None,
        seen_after: Optional[int] = None,
        seen_before: Optional[int] = None,
        expires_after: Optional[int] = None,
        expires_before: Optional[int] = None,
        has_recent_failure: Optional[bool] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
        include_raw: bool = False,
    ) -> SendTargetListResponse:
        """검색 필터를 적용한 target 목록을 반환한다."""

        settings = get_settings()
        now = now_millis()
        effective_limit = max(min(limit, settings.bulk_send_target_max_page_size), 1)
        rows = list_latest_send_targets(
            limit=effective_limit,
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
            safety_window_ms=settings.bulk_send_token_safety_window_ms,
            allowed_source_types=_allowed_source_types(),
        )
        cache = _load_cached_token_cache()
        items = []
        for row in rows:
            reply_token = row["reply_token"]
            expires_at = row["reply_token_expires_at"]
            if cache is not None:
                cached = cache.peek_latest_for_room(row["room_key"])
                if cached is not None:
                    cached_token, cached_expires = cached
                    if cached_token is not None:
                        reply_token = cached_token
                        expires_at = cached_expires
            item_status = _target_status(reply_token, expires_at, now, settings.bulk_send_token_safety_window_ms)
            items.append(
                SendTargetItem(
                    roomKey=row["room_key"],
                    room=row["room"],
                    roomAlias=None,
                    lastSender=_mask_sender(row["sender"], include_raw),
                    sourceType=row["source_type"],
                    roomType=_room_type(int(row["sender_count"] or 0)),
                    targetStatus=item_status,
                    replyTokenExpiresAt=expires_at,
                    lastSeenAt=int(row["received_at"]),
                    lastSendStatus=row["last_send_status"],
                    hasRecentFailure=bool(row["last_send_status"] in {"FAILED", "TOKEN_EXPIRED", "HANDLE_EXPIRED"}),
                )
            )
        next_cursor = _cursor_for_row(rows[-1]) if len(rows) == effective_limit and rows else None
        return SendTargetListResponse(items=items, nextCursor=next_cursor)

    def preview_target_spec(self, target: SendTargetSpec, max_targets: Optional[int] = None) -> dict[str, object]:
        """발송 대상 미리보기 집계와 샘플을 반환한다."""

        resolution = self.resolve_target_spec(target, max_targets=max_targets, for_send=False)
        sample = [
            {
                "roomKey": item.room_key,
                "room": item.room,
                "targetStatus": self._item_status(item).value,
            }
            for item in resolution.targets[:3]
        ]
        return {
            "ok": True,
            "targetCount": len(resolution.targets),
            "excludedCount": sum(resolution.excluded_reasons.values()),
            "excludedReasons": resolution.excluded_reasons,
            "sample": sample,
        }

    def resolve_target_spec(
        self,
        target: SendTargetSpec,
        max_targets: Optional[int] = None,
        *,
        for_send: bool = True,
    ) -> TargetResolution:
        """단건/그룹/전체 선택을 실제 room 목록으로 해석한다."""

        settings = get_settings()
        effective_max = max_targets if max_targets is not None else settings.bulk_send_max_targets
        target_type = _enum_value(target.type)
        if target_type == SendTargetType.group.value:
            target = self._resolve_group_target_spec(target)
            target_type = _enum_value(target.type)
        if target_type == SendTargetType.rooms.value:
            resolution = self._resolve_rooms_target(target.roomKeys, effective_max, for_send=for_send)
            if target.filter and self._has_filter_terms(target.filter):
                resolution = self._merge_resolutions(
                    resolution,
                    self._resolve_filter_target(target.filter, effective_max, for_send=for_send),
                    effective_max,
                )
            return resolution
        if target_type in (SendTargetType.filter.value, SendTargetType.all.value):
            return self._resolve_filter_target(target.filter, effective_max, for_send=for_send)
        return TargetResolution(targets=[], excluded_reasons={"unsupportedTarget": 1}, total_count=0)

    def _resolve_group_target_spec(self, target: SendTargetSpec) -> SendTargetSpec:
        if not target.groupKey:
            return target
        group = repository.get_send_target_group(target.groupKey)
        if group is None:
            return target
        group_type = str(group["type"])
        room_keys = repository.list_send_target_group_rooms(target.groupKey)
        filter_model = SendTargetFilter.model_validate_json(group["filter_json"]) if group["filter_json"] else SendTargetFilter()
        if group_type == SendTargetGroupType.static.value:
            return SendTargetSpec(type=SendTargetType.rooms, roomKeys=room_keys, filter=filter_model, groupKey=target.groupKey)
        if group_type == SendTargetGroupType.dynamic.value:
            return SendTargetSpec(type=SendTargetType.filter, roomKeys=[], filter=filter_model, groupKey=target.groupKey)
        return SendTargetSpec(type=SendTargetType.rooms, roomKeys=room_keys, filter=filter_model, groupKey=target.groupKey)

    def _resolve_rooms_target(
        self,
        room_keys: list[str],
        max_targets: int,
        *,
        for_send: bool,
    ) -> TargetResolution:
        rows = get_latest_send_targets_for_room_keys(room_keys)
        row_by_room = {row["room_key"]: row for row in rows}
        targets: list[ResolvedTarget] = []
        excluded_reasons: dict[str, int] = {}
        now = now_millis()
        settings = get_settings()
        for room_key in dict.fromkeys(room_keys):
            row = row_by_room.get(room_key)
            if row is None:
                excluded_reasons["missingRoom"] = excluded_reasons.get("missingRoom", 0) + 1
                continue
            target_status = _target_status(row["reply_token"], row["reply_token_expires_at"], now, settings.bulk_send_token_safety_window_ms)
            if for_send and target_status not in (TargetStatus.available, TargetStatus.expiring):
                excluded_reasons[target_status.value] = excluded_reasons.get(target_status.value, 0) + 1
                continue
            targets.append(self._row_to_target(row))
        if len(targets) > max_targets:
            excluded_reasons["maxTargets"] = excluded_reasons.get("maxTargets", 0) + (len(targets) - max_targets)
            targets = targets[:max_targets]
        return TargetResolution(targets=targets, excluded_reasons=excluded_reasons, total_count=len(rows))

    def _resolve_filter_target(
        self,
        target_filter: SendTargetFilter,
        max_targets: int,
        *,
        for_send: bool,
    ) -> TargetResolution:
        filter_model = target_filter
        settings = get_settings()
        now = now_millis()
        rows = list_latest_send_targets(
            limit=max_targets,
            cursor=None,
            q=filter_model.q,
            status=filter_model.status,
            source_type=filter_model.sourceType,
            room_type=filter_model.roomType,
            seen_after=filter_model.seenAfter,
            seen_before=filter_model.seenBefore,
            expires_after=filter_model.expiresAfter,
            expires_before=filter_model.expiresBefore,
            has_recent_failure=filter_model.hasRecentFailure,
            now=now,
            safety_window_ms=settings.bulk_send_token_safety_window_ms,
            allowed_source_types=_allowed_source_types(),
        )
        targets: list[ResolvedTarget] = []
        excluded_reasons: dict[str, int] = {}
        for row in rows:
            resolved = self._row_to_target(row)
            target_status = _target_status(
                resolved.reply_token,
                resolved.reply_token_expires_at,
                now,
                settings.bulk_send_token_safety_window_ms,
            )
            if for_send and target_status not in (TargetStatus.available, TargetStatus.expiring):
                excluded_reasons[target_status.value] = excluded_reasons.get(target_status.value, 0) + 1
                continue
            targets.append(resolved)
        if len(targets) > max_targets:
            excluded_reasons["maxTargets"] = excluded_reasons.get("maxTargets", 0) + (len(targets) - max_targets)
            targets = targets[:max_targets]
        return TargetResolution(targets=targets, excluded_reasons=excluded_reasons, total_count=len(rows))

    def _row_to_target(self, row) -> ResolvedTarget:
        cache = _load_cached_token_cache()
        reply_token = row["reply_token"]
        expires_at = row["reply_token_expires_at"]
        if cache is not None:
            cached = cache.peek_latest_for_room(row["room_key"])
            if cached is not None:
                cached_token, cached_expires = cached
                if cached_token is not None:
                    reply_token = cached_token
                    expires_at = cached_expires
        return ResolvedTarget(
            room_key=row["room_key"],
            room=row["room"],
            reply_token=reply_token,
            reply_token_expires_at=expires_at,
            last_seen_at=int(row["received_at"]),
            source_type=row["source_type"],
            last_sender=row["sender"],
            sender_count=int(row["sender_count"] or 0),
            last_send_status=row["last_send_status"],
            last_send_at=row["last_send_at"],
        )

    def _has_filter_terms(self, filter_model: SendTargetFilter) -> bool:
        return any(
            [
                filter_model.q,
                _enum_value(filter_model.status) != TargetStatus.all.value,
                _enum_value(filter_model.sourceType) != TargetSourceFilter.all.value,
                filter_model.roomType is not None,
                filter_model.seenAfter is not None,
                filter_model.seenBefore is not None,
                filter_model.expiresAfter is not None,
                filter_model.expiresBefore is not None,
                filter_model.hasRecentFailure is not None,
            ]
        )

    def _merge_resolutions(
        self,
        first: TargetResolution,
        second: TargetResolution,
        max_targets: int,
    ) -> TargetResolution:
        combined: list[ResolvedTarget] = []
        seen: set[str] = set()
        for item in [*first.targets, *second.targets]:
            if item.room_key in seen:
                continue
            seen.add(item.room_key)
            combined.append(item)
        excluded = dict(first.excluded_reasons)
        for key, value in second.excluded_reasons.items():
            excluded[key] = excluded.get(key, 0) + value
        if len(combined) > max_targets:
            excluded["maxTargets"] = excluded.get("maxTargets", 0) + (len(combined) - max_targets)
            combined = combined[:max_targets]
        return TargetResolution(targets=combined, excluded_reasons=excluded, total_count=first.total_count + second.total_count)

    def _item_status(self, target: ResolvedTarget) -> TargetStatus:
        settings = get_settings()
        return _target_status(target.reply_token, target.reply_token_expires_at, now_millis(), settings.bulk_send_token_safety_window_ms)

    def stats(self) -> dict[str, int | str | None]:
        """health API에서 사용할 target pool 요약을 반환한다."""

        settings = get_settings()
        counts = repository.count_latest_send_targets(
            q=None,
            status=TargetStatus.all,
            source_type=TargetSourceFilter.all,
            room_type=None,
            seen_after=None,
            seen_before=None,
            expires_after=None,
            expires_before=None,
            has_recent_failure=None,
            now=now_millis(),
            safety_window_ms=settings.bulk_send_token_safety_window_ms,
            allowed_source_types=_allowed_source_types(),
        )
        return {
            "available": counts["available"],
            "expiring": counts["expiring"],
            "expired": counts["expired"],
            "unknown": counts["unknown"],
            "total": counts["total"],
            "lastSweepAt": now_millis(),
        }
