from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any

from app.chatbot.base_bot import StatefulBot
from app.chatbot.context import ChatContext
from app.chatbot.decision import ChatDecision
from app.chatbot.module import MatchPattern

_CANCEL_COMMANDS = {"/취소", "/cancel"}
_CANCEL_WORDS = {"취소", "그만", "중단", "cancel"}
_CONFIRM_YES = {"네", "예", "응", "확인", "완료", "예약", "yes", "y"}
_CONFIRM_NO = {"아니", "아니오", "no", "n", "다시", "수정"}
_EMPTY_NOTE = {"없음", "없어요", "아니오", "아니", "skip", "-"}
_TIME_RE = re.compile(r"^(오전|오후)?\s*(\d{1,2})(?:[:시]\s*(\d{1,2})?)?(?:\s*분)?$")
_PHONE_RE = re.compile(r"^[0-9+\-\s().]{7,30}$")
_DATE_ALIASES = {
    "오늘": 0,
    "today": 0,
    "내일": 1,
    "tomorrow": 1,
    "모레": 2,
    "내일모레": 2,
}
_DATE_RE = re.compile(
    r"^(?:(\d{4})[-\/.])?(?:(\d{1,2})[월\-\/.]\s*)?(\d{1,2})[일]?\s*$"
)


class RestaurantReservationBot(StatefulBot):
    """식당 예약을 여러 턴으로 받고 사용자별 예약 확인과 취소를 처리한다."""

    key = "restaurant_reservation_bot"
    name = "Restaurant Reservation Bot"
    version = "0.1.0"
    description = "식당 예약 진행, 확인, 취소를 사용자별로 처리한다."
    match_mode = "stateful"
    commands = ["/예약", "/식당예약", "/예약확인", "/예약조회", "/예약목록", "/예약취소", "/예약도움말"]
    patterns = [
        MatchPattern(type="command", value="/예약"),
        MatchPattern(type="command", value="/식당예약"),
        MatchPattern(type="command", value="/예약확인"),
        MatchPattern(type="command", value="/예약조회"),
        MatchPattern(type="command", value="/예약목록"),
        MatchPattern(type="command", value="/예약취소"),
        MatchPattern(type="command", value="/예약도움말"),
        MatchPattern(type="state_exists", value={"name": "restaurant_reservation_session", "scope": "sender"}),
    ]
    priority = 115
    state_name = "reservations"
    session_name = "restaurant_reservation_session"
    session_scope = "sender"
    session_ttl_millis = 30 * 60 * 1000
    default_options = {
        "maxReservations": 30,
        "listSize": 5,
        "maxPeople": 20,
        "maxNoteChars": 120,
        "requirePhone": True,
    }
    option_schema = {
        "maxReservations": {
            "type": "integer",
            "default": 30,
            "min": 5,
            "max": 200,
            "description": "방별 보관할 최근 예약 레코드 수.",
        },
        "listSize": {
            "type": "integer",
            "default": 5,
            "min": 1,
            "max": 20,
            "description": "예약 확인 답장에 표시할 최대 예약 수.",
        },
        "maxPeople": {
            "type": "integer",
            "default": 20,
            "min": 1,
            "max": 100,
            "description": "한 예약에서 허용할 최대 인원.",
        },
        "maxNoteChars": {
            "type": "integer",
            "default": 120,
            "min": 20,
            "max": 500,
            "description": "요청사항 최대 길이.",
        },
        "requirePhone": {
            "type": "boolean",
            "default": True,
            "description": "예약 확정 전 연락처 입력을 필수로 요구할지 여부.",
        },
    }

    def can_handle(self, context: ChatContext) -> bool:
        """예약 명령 또는 진행 중인 sender 예약 세션만 처리한다."""

        return context.command in set(self.commands) or self.has_session(context)

    def run(self, context: ChatContext) -> ChatDecision:
        """예약 생성, 확인, 취소 세션을 명령과 현재 step에 따라 처리한다."""

        if context.command in {"/예약", "/식당예약"}:
            return self._start_reservation(context)
        if context.command in {"/예약확인", "/예약조회", "/예약목록"}:
            return self._list_reservations(context)
        if context.command == "/예약취소":
            return self._start_or_run_cancel(context)
        if context.command == "/예약도움말":
            return self._help()

        session = self.get_session(context)
        if not session:
            return self.reply("진행 중인 예약 입력이 없거나 시간이 초과되었습니다. /예약으로 다시 시작해주세요.")
        if self._is_cancel(context):
            self.end_session(context)
            return self.reply("예약 진행을 취소했습니다. 다시 시작하려면 /예약을 입력해주세요.")
        if context.command is not None:
            return self.pass_("other command during reservation session")

        step = str(session.get("step", ""))
        if step == "date":
            return self._handle_date(context)
        if step == "time":
            return self._handle_time(context)
        if step == "people":
            return self._handle_people(context)
        if step == "name":
            return self._handle_name(context)
        if step == "phone":
            return self._handle_phone(context)
        if step == "note":
            return self._handle_note(context)
        if step == "confirm":
            return self._handle_confirm(context, session)
        if step == "cancel_select":
            return self._handle_cancel_selection(context, session)

        self.end_session(context)
        return self.reply("진행 중인 예약 상태를 이해하지 못했습니다. /예약으로 다시 시작해주세요.")

    def _start_reservation(self, context: ChatContext) -> ChatDecision:
        existing = self.get_session(context)
        if existing:
            step = existing.get("step", "")
            return self.reply(f"이미 진행 중인 예약이 있습니다. (현재 단계: {step}) /예약을 다시 입력하려면 먼저 '취소'를 입력해주세요.")

        self.start_session(context, "date")
        return self.reply("예약 날짜를 알려주세요. 예: 오늘, 내일, 6월 25일, 2026-06-25")

    def _handle_date(self, context: ChatContext) -> ChatDecision:
        value = self._clean_text(context.normalizedText, 40)
        parsed = self._parse_date(value)
        if parsed is None:
            return self.reply("날짜를 다시 알려주세요. 예: 오늘, 내일, 6월 25일, 2026-06-25")
        self.advance_session(context, "time", {"date": parsed})
        return self.reply("예약 시간을 알려주세요. 예: 19:00, 오후 7시")

    def _handle_time(self, context: ChatContext) -> ChatDecision:
        value = self._normalize_time(context.normalizedText)
        if value is None:
            return self.reply("예약 시간을 다시 알려주세요. 예: 19:00, 오후 7시")
        self.advance_session(context, "people", {"time": value})
        return self.reply(f"몇 명으로 예약할까요? 최대 {self._max_people(context)}명까지 가능합니다.")

    def _handle_people(self, context: ChatContext) -> ChatDecision:
        people = self._parse_people(context.normalizedText)
        max_people = self._max_people(context)
        if people is None or people < 1 or people > max_people:
            return self.reply(f"예약 인원을 1명부터 {max_people}명 사이 숫자로 입력해주세요. 예: 4명")
        self.advance_session(context, "name", {"people": people})
        return self.reply("예약자 성함을 알려주세요.")

    def _handle_name(self, context: ChatContext) -> ChatDecision:
        value = self._clean_text(context.normalizedText, 40)
        if len(value) < 2:
            return self.reply("예약자 성함을 두 글자 이상 입력해주세요.")
        next_step = "phone" if self.bool_option(context, "requirePhone", True) else "note"
        self.advance_session(context, next_step, {"name": value})
        if next_step == "phone":
            return self.reply("연락처를 알려주세요. 예: 010-1234-5678")
        return self.reply("요청사항이 있으면 적어주세요. 없으면 '없음'이라고 입력해주세요.")

    def _handle_phone(self, context: ChatContext) -> ChatDecision:
        value = self._clean_text(context.normalizedText, 40)
        if not _PHONE_RE.match(value):
            return self.reply("연락처를 다시 입력해주세요. 예: 010-1234-5678")
        self.advance_session(context, "note", {"phone": value})
        return self.reply("요청사항이 있으면 적어주세요. 없으면 '없음'이라고 입력해주세요.")

    def _handle_note(self, context: ChatContext) -> ChatDecision:
        note = self._clean_text(context.normalizedText, self._max_note_chars(context))
        if note.strip().lower() in _EMPTY_NOTE:
            note = ""
        updated = self.advance_session(context, "confirm", {"note": note})
        return self.reply(self._summary_prompt(updated))

    def _handle_confirm(self, context: ChatContext, session: dict[str, Any]) -> ChatDecision:
        normalized = context.normalizedText.strip().lower()
        if normalized in _CONFIRM_NO:
            self.end_session(context)
            return self.reply("예약을 취소했습니다. 다시 시작하려면 /예약을 입력해주세요.")
        if normalized not in _CONFIRM_YES:
            return self.reply("예약하려면 '네', 취소하려면 '아니오'라고 입력해주세요.")

        duplicate = self._find_duplicate(context, session)
        if duplicate:
            self.end_session(context)
            return self.reply(
                f"동일한 날짜와 시간({session.get('date', '')} {session.get('time', '')})에 "
                f"이미 예약({duplicate.get('reservationId', '')})이 존재합니다.\n"
                f"/예약취소 {duplicate.get('reservationId', '')}로 먼저 취소 후 다시 시도해주세요."
            )

        reservation = self._build_reservation(context, session)
        self._record_reservation(context, reservation)
        self.end_session(context)
        return self.reply(self._reservation_completed_text(reservation))

    def _start_or_run_cancel(self, context: ChatContext) -> ChatDecision:
        reservations = self._active_reservations_for_sender(context)
        if not reservations:
            return self.reply("현재 취소할 수 있는 예약이 없습니다.")

        target = self._select_reservation(context.args, reservations)
        if target is not None:
            return self._cancel_reservation(context, target)
        if context.args.strip():
            return self.reply("취소할 예약을 찾지 못했습니다. /예약확인으로 예약 번호를 확인해주세요.")
        if len(reservations) == 1:
            return self._cancel_reservation(context, reservations[0])

        self.start_session(
            context,
            "cancel_select",
            payload={"candidateIds": [str(item.get("reservationId", "")) for item in reservations]},
        )
        return self.reply(self._cancel_select_prompt(reservations))

    def _handle_cancel_selection(self, context: ChatContext, session: dict[str, Any]) -> ChatDecision:
        reservations = self._active_reservations_for_sender(context)
        allowed = {str(item) for item in session.get("candidateIds", []) if str(item)}
        candidates = [item for item in reservations if str(item.get("reservationId", "")) in allowed]
        target = self._select_reservation(context.normalizedText, candidates)
        if target is None:
            return self.reply(self._cancel_select_prompt(candidates or reservations))
        self.end_session(context)
        return self._cancel_reservation(context, target)

    def _list_reservations(self, context: ChatContext) -> ChatDecision:
        reservations = self._active_reservations_for_sender(context)
        if not reservations:
            return self.reply("현재 확인 가능한 예약이 없습니다.")
        limit = min(self.int_option(context, "listSize", 5, min_value=1, max_value=20), len(reservations))
        lines = ["현재 예약:"]
        for index, item in enumerate(reservations[:limit], start=1):
            lines.append(self._format_reservation_line(index, item))
        if len(reservations) > limit:
            lines.append(f"외 {len(reservations) - limit}건이 더 있습니다.")
        lines.append("취소하려면 /예약취소 또는 /예약취소 예약번호를 입력해주세요.")
        return self.reply("\n".join(lines))

    def _record_reservation(self, context: ChatContext, reservation: dict[str, Any]) -> None:
        limit = self.int_option(context, "maxReservations", 30, min_value=5, max_value=200)

        def update(value: dict[str, Any]) -> dict[str, Any]:
            items = [item for item in value.get("items", []) if isinstance(item, dict)]
            items.append(dict(reservation))
            value["items"] = items[-limit:]
            value["updatedAt"] = self.runtime.nowMillis()
            return value

        self.update_state(context, update, sender_scope=False)

    def _cancel_reservation(self, context: ChatContext, target: dict[str, Any]) -> ChatDecision:
        reservation_id = str(target.get("reservationId", ""))
        sender = context.sender or ""
        now = self.runtime.nowMillis()
        canceled: dict[str, Any] = {}

        def update(value: dict[str, Any]) -> dict[str, Any]:
            items = [item for item in value.get("items", []) if isinstance(item, dict)]
            for item in items:
                if (
                    str(item.get("reservationId", "")) == reservation_id
                    and str(item.get("sender", "")) == sender
                    and item.get("status") == "active"
                ):
                    item["status"] = "canceled"
                    item["canceledAt"] = now
                    item["updatedAt"] = now
                    canceled.update(item)
                    break
            value["items"] = items
            value["updatedAt"] = now
            return value

        self.update_state(context, update, sender_scope=False)
        if not canceled:
            return self.reply("취소할 예약을 찾지 못했습니다. /예약확인으로 현재 예약을 확인해주세요.")
        return self.reply(self._reservation_canceled_text(canceled))

    def _active_reservations_for_sender(self, context: ChatContext) -> list[dict[str, Any]]:
        state = self.get_state(context, sender_scope=False)
        sender = context.sender or ""
        items = [item for item in state.get("items", []) if isinstance(item, dict)]
        active = [
            item
            for item in items
            if item.get("status") == "active" and str(item.get("sender", "")) == sender
        ]
        return sorted(active, key=lambda item: int(item.get("createdAt", 0)), reverse=True)

    def _find_duplicate(self, context: ChatContext, session: dict[str, Any]) -> dict[str, Any] | None:
        date = session.get("date", "")
        time = session.get("time", "")
        if not date or not time:
            return None
        sender = context.sender or ""
        state = self.get_state(context, sender_scope=False)
        items = [item for item in state.get("items", []) if isinstance(item, dict)]
        for item in items:
            if (
                item.get("status") == "active"
                and str(item.get("sender", "")) == sender
                and str(item.get("date", "")) == date
                and str(item.get("time", "")) == time
            ):
                return item
        return None

    def _build_reservation(self, context: ChatContext, session: dict[str, Any]) -> dict[str, Any]:
        now = self.runtime.nowMillis()
        return {
            "reservationId": f"RSV-{now}",
            "status": "active",
            "sender": context.sender or "",
            "date": str(session.get("date", "")),
            "time": str(session.get("time", "")),
            "people": int(session.get("people", 1)),
            "name": str(session.get("name", "")),
            "phone": str(session.get("phone", "")),
            "note": str(session.get("note", "")),
            "createdAt": now,
            "updatedAt": now,
        }

    def _select_reservation(self, value: str, reservations: list[dict[str, Any]]) -> dict[str, Any] | None:
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.isdigit():
            index = int(normalized) - 1
            if 0 <= index < len(reservations):
                return reservations[index]
        for item in reservations:
            reservation_id = str(item.get("reservationId", ""))
            if normalized == reservation_id or normalized.upper() == reservation_id.upper():
                return item
        return None

    def _summary_prompt(self, session: dict[str, Any]) -> str:
        lines = [
            "아래 내용으로 예약할까요?",
            f"날짜: {session.get('date', '')}",
            f"시간: {session.get('time', '')}",
            f"인원: {session.get('people', 1)}명",
            f"예약자: {session.get('name', '')}",
        ]
        phone = str(session.get("phone", ""))
        if phone:
            lines.append(f"연락처: {phone}")
        note = str(session.get("note", ""))
        if note:
            lines.append(f"요청: {note}")
        lines.append("예약하려면 '네', 취소하려면 '아니오'라고 입력해주세요.")
        return "\n".join(lines)

    def _reservation_completed_text(self, reservation: dict[str, Any]) -> str:
        lines = [
            f"예약 완료: {reservation['reservationId']}",
            f"날짜: {reservation['date']}",
            f"시간: {reservation['time']}",
            f"인원: {reservation['people']}명",
            f"예약자: {reservation['name']}",
        ]
        if reservation.get("phone"):
            lines.append(f"연락처: {reservation['phone']}")
        if reservation.get("note"):
            lines.append(f"요청: {reservation['note']}")
        return "\n".join(lines)

    def _reservation_canceled_text(self, reservation: dict[str, Any]) -> str:
        return "\n".join(
            [
                f"예약 취소 완료: {reservation.get('reservationId', '')}",
                f"날짜: {reservation.get('date', '')}",
                f"시간: {reservation.get('time', '')}",
                f"인원: {reservation.get('people', 1)}명",
            ]
        )

    def _cancel_select_prompt(self, reservations: list[dict[str, Any]]) -> str:
        lines = ["취소할 예약을 선택해주세요."]
        for index, item in enumerate(reservations, start=1):
            lines.append(self._format_reservation_line(index, item))
        lines.append("번호 또는 예약번호를 입력해주세요. 중단하려면 '취소'라고 입력해주세요.")
        return "\n".join(lines)

    def _format_reservation_line(self, index: int, item: dict[str, Any]) -> str:
        note = f" / {item.get('note')}" if item.get("note") else ""
        return (
            f"{index}. {item.get('reservationId', 'RSV')} / {item.get('date', '')} "
            f"{item.get('time', '')} / {item.get('people', 1)}명 / {item.get('name', '')}{note}"
        )

    def _help(self) -> ChatDecision:
        return self.reply(
            "\n".join(
                [
                    "식당 예약 명령:",
                    "/예약 - 새 예약을 진행합니다.",
                    "/예약확인 - 내 현재 예약을 확인합니다.",
                    "/예약취소 - 내 예약을 취소합니다.",
                    "/예약취소 예약번호 - 특정 예약을 바로 취소합니다.",
                ]
            )
        )

    def _now_date(self) -> str:
        now = datetime.fromtimestamp(self.runtime.nowMillis() / 1000, tz=timezone.utc)
        return now.strftime("%Y-%m-%d")

    def _parse_date(self, value: str) -> str | None:
        text = " ".join(value.strip().split())
        if not text:
            return None

        alias = text.lower()
        if alias in _DATE_ALIASES:
            delta = _DATE_ALIASES[alias]
            dt = datetime.fromtimestamp(self.runtime.nowMillis() / 1000, tz=timezone.utc) + timedelta(days=delta)
            return dt.strftime("%Y-%m-%d")

        match = _DATE_RE.match(text)
        if match is None:
            return None

        year_str, month_str, day_str = match.groups()
        now = datetime.fromtimestamp(self.runtime.nowMillis() / 1000, tz=timezone.utc)
        year = int(year_str) if year_str else now.year
        month = int(month_str) if month_str else now.month
        day = int(day_str) if day_str else now.day

        if not self._validate_date(year, month, day):
            return None

        return f"{year:04d}-{month:02d}-{day:02d}"

    @staticmethod
    def _validate_date(year: int, month: int, day: int) -> bool:
        if month < 1 or month > 12 or day < 1:
            return False
        days_in_month = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        if day > days_in_month[month]:
            return False
        if month == 2 and day == 29:
            if year % 400 != 0 and (year % 100 == 0 or year % 4 != 0):
                return False
        return True

    def _normalize_time(self, value: str) -> str | None:
        text = " ".join(value.strip().split())
        if text in {"점심", "런치"}:
            return "12:00"
        if text in {"저녁", "디너"}:
            return "18:00"
        match = _TIME_RE.match(text)
        if match is None:
            return None
        period, hour_text, minute_text = match.groups()
        hour = int(hour_text)
        minute = int(minute_text or 0)
        if period == "오후" and 1 <= hour <= 11:
            hour += 12
        if period == "오전" and hour == 12:
            hour = 0
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None
        return f"{hour:02d}:{minute:02d}"

    def _parse_people(self, value: str) -> int | None:
        match = re.search(r"\d+", value)
        if match is None:
            return None
        return int(match.group(0))

    def _clean_text(self, value: str, max_chars: int) -> str:
        cleaned = " ".join(str(value or "").split())
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[:max_chars].rstrip()

    def _max_people(self, context: ChatContext) -> int:
        return self.int_option(context, "maxPeople", 20, min_value=1, max_value=100)

    def _max_note_chars(self, context: ChatContext) -> int:
        return self.int_option(context, "maxNoteChars", 120, min_value=20, max_value=500)

    def _is_cancel(self, context: ChatContext) -> bool:
        if context.command in _CANCEL_COMMANDS:
            return True
        return context.normalizedText.strip().lower() in _CANCEL_WORDS


def create_bot() -> RestaurantReservationBot:
    """로더가 사용할 객체형 봇 인스턴스를 생성한다."""

    return RestaurantReservationBot()
