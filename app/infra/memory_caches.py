from __future__ import annotations

from typing import Any
from threading import RLock

from app import repository
from app.config import get_settings
from app.schemas import BridgeEvent, RoomRuleResponse
from app.time_utils import now_millis


class ReplyTokenCache:
    """room별 최신 reply token을 메모리에 보관한다.

    `/events`로 들어온 토큰을 즉시 갱신하고, miss 때만 SQLite의 최근 메시지로 fallback한다.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._by_room: dict[str, tuple[str | None, int | None]] = {}
        self._expires_by_token: dict[str, int | None] = {}

    def update_from_event(self, event: BridgeEvent) -> None:
        if event.replyToken is None:
            return
        with self._lock:
            self._by_room[event.roomKey] = (event.replyToken, event.replyTokenExpiresAt)
            self._expires_by_token[event.replyToken] = event.replyTokenExpiresAt

    def latest_for_room(self, room_key: str) -> tuple[str | None, int | None]:
        cached = self.peek_latest_for_room(room_key)
        if cached is not None:
            return cached
        token, expires_at = repository.latest_reply_token(room_key)
        if token is not None:
            with self._lock:
                self._by_room[room_key] = (token, expires_at)
                self._expires_by_token[token] = expires_at
        return token, expires_at

    def peek_latest_for_room(self, room_key: str) -> tuple[str | None, int | None] | None:
        with self._lock:
            cached = self._by_room.get(room_key)
        return cached

    def expires_at_for_token(self, reply_token: str) -> int | None:
        cached = self.peek_expires_at_for_token(reply_token)
        if cached is not None:
            return cached
        expires_at = repository.expires_at_for_token(reply_token)
        with self._lock:
            self._expires_by_token[reply_token] = expires_at
        return expires_at

    def peek_expires_at_for_token(self, reply_token: str) -> int | None:
        with self._lock:
            if reply_token in self._expires_by_token:
                return self._expires_by_token[reply_token]
        return None


class ConfigCache:
    """방별 rule 설정의 memory cache다.

    운영 API가 room rule을 변경하면 해당 roomKey만 무효화해서 다음 이벤트에서 DB 원본을 다시 읽는다.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._room_rules: dict[str, RoomRuleResponse | None] = {}
        self._module_rows: dict[str, dict[str, Any]] | None = None
        self._room_option_rows: dict[str, dict[str, dict[str, Any]]] = {}
        self._warmup_count = 0
        self._reconcile_count = 0
        self._last_warmup_at: int | None = None
        self._last_reconcile_at: int | None = None
        self._last_reconcile_error: str | None = None
        self._room_options_warmed = False
        self._room_options_capped = False

    def warmup(self) -> None:
        """프로세스 시작 시 전역 module과 room option snapshot을 미리 적재한다."""

        settings = get_settings()
        rows = {key: dict(row) for key, row in repository.list_chatbot_modules_by_key().items()}
        room_options = {}
        room_options_warmed = False
        room_options_capped = False
        if settings.memory_config_room_option_warmup_enabled:
            grouped = repository.list_room_bot_options_grouped(
                limit_rows=max(settings.memory_config_room_option_max_rows, 1) + 1
            )
            row_count = sum(len(rows_by_bot) for rows_by_bot in grouped.values())
            room_count = len(grouped)
            if (
                row_count <= max(settings.memory_config_room_option_max_rows, 1)
                and room_count <= max(settings.memory_config_room_option_max_rooms, 1)
            ):
                room_options = {
                    room_key: {bot_key: dict(row) for bot_key, row in rows_by_bot.items()}
                    for room_key, rows_by_bot in grouped.items()
                }
                room_options_warmed = True
            else:
                room_options_capped = True
        with self._lock:
            self._module_rows = rows
            self._room_option_rows = room_options
            self._room_options_warmed = room_options_warmed
            self._room_options_capped = room_options_capped
            self._warmup_count += 1
            self._last_warmup_at = now_millis()

    def reconcile(self) -> None:
        """이미 cache에 올라온 설정 key를 DB 원본으로 다시 동기화한다.

        room option은 roomKey별 lazy cache이므로 전체 테이블 scan 대신 현재 cache된 room만 갱신한다.
        """

        with self._lock:
            room_rule_keys = list(self._room_rules)
            room_option_keys = list(self._room_option_rows)
        try:
            module_rows = {key: dict(row) for key, row in repository.list_chatbot_modules_by_key().items()}
            room_rules = {room_key: repository.get_room_rule(room_key) for room_key in room_rule_keys}
            room_options = {
                room_key: {
                    bot_key: dict(row)
                    for bot_key, row in repository.list_room_bot_options_by_key(room_key).items()
                }
                for room_key in room_option_keys
            }
        except Exception as exc:
            with self._lock:
                self._last_reconcile_error = str(exc)
            raise
        with self._lock:
            self._module_rows = module_rows
            for room_key, rule in room_rules.items():
                self._room_rules[room_key] = rule
            for room_key, rows in room_options.items():
                self._room_option_rows[room_key] = rows
            self._reconcile_count += 1
            self._last_reconcile_at = now_millis()
            self._last_reconcile_error = None

    def get_room_rule(self, room_key: str) -> RoomRuleResponse | None:
        with self._lock:
            if room_key in self._room_rules:
                return self._room_rules[room_key]
        rule = repository.get_room_rule(room_key)
        with self._lock:
            self._room_rules[room_key] = rule
        return rule

    def invalidate_room_rule(self, room_key: str) -> None:
        with self._lock:
            self._room_rules.pop(room_key, None)

    def set_room_rule(self, rule: RoomRuleResponse) -> None:
        with self._lock:
            self._room_rules[rule.roomKey] = rule

    def get_module_rows_by_key(self) -> dict[str, dict[str, Any]]:
        """이벤트 처리에서 사용할 chatbot module 설정 row를 memory cache로 반환한다."""

        with self._lock:
            if self._module_rows is not None:
                return {key: dict(value) for key, value in self._module_rows.items()}
        rows = {key: dict(row) for key, row in repository.list_chatbot_modules_by_key().items()}
        with self._lock:
            self._module_rows = rows
            return {key: dict(value) for key, value in rows.items()}

    def set_module_row(self, row) -> None:
        with self._lock:
            if self._module_rows is None:
                return
            self._module_rows[row["bot_key"]] = dict(row)

    def invalidate_module_rows(self) -> None:
        with self._lock:
            self._module_rows = None

    def get_room_option_rows_by_key(self, room_key: str) -> dict[str, dict[str, Any]]:
        """roomKey별 room_bot_options row를 memory cache로 반환한다."""

        with self._lock:
            if room_key in self._room_option_rows:
                rows = self._room_option_rows[room_key]
                return {key: dict(value) for key, value in rows.items()}
        rows = {key: dict(row) for key, row in repository.list_room_bot_options_by_key(room_key).items()}
        with self._lock:
            self._room_option_rows[room_key] = rows
            return {key: dict(value) for key, value in rows.items()}

    def set_room_option_row(self, row) -> None:
        room_key = row["room_key"]
        with self._lock:
            rows = self._room_option_rows.get(room_key)
            if rows is None:
                return
            rows[row["bot_key"]] = dict(row)

    def invalidate_room_option_rows(self, room_key: str | None = None) -> None:
        with self._lock:
            if room_key is None:
                self._room_option_rows.clear()
            else:
                self._room_option_rows.pop(room_key, None)

    def stats(self) -> dict[str, int | str | None]:
        """health API에서 노출할 config cache 상태를 반환한다."""

        with self._lock:
            return {
                "moduleRows": len(self._module_rows or {}),
                "moduleRowsWarmed": 1 if self._module_rows is not None else 0,
                "roomRuleKeys": len(self._room_rules),
                "roomOptionRoomKeys": len(self._room_option_rows),
                "roomOptionRows": sum(len(rows) for rows in self._room_option_rows.values()),
                "roomOptionsWarmed": 1 if self._room_options_warmed else 0,
                "roomOptionsCapped": 1 if self._room_options_capped else 0,
                "warmupCount": self._warmup_count,
                "reconcileCount": self._reconcile_count,
                "lastWarmupAt": self._last_warmup_at,
                "lastReconcileAt": self._last_reconcile_at,
                "lastReconcileError": self._last_reconcile_error,
            }
