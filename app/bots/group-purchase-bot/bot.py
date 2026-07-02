from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any

from app.chatbot.base_bot import StatefulBot
from app.chatbot.context import ChatContext
from app.chatbot.decision import ChatDecision
from app.chatbot.module import MatchPattern


_DATE_ALIASES = {
    "오늘": 0, "today": 0,
    "내일": 1, "tomorrow": 1,
    "모레": 2, "내일모레": 2,
}
_CANCEL_WORDS = {"취소", "그만", "중단", "cancel"}
_DONE_WORDS = {"완료", "다했다", "done", "ok"}
_YES_WORDS = {"네", "예", "그렇다", "yes", "y", "ok"}
_NO_WORDS = {"아니오", "아니", "no", "n"}
_DATE_RE = re.compile(
    r"^(?:(\d{4})[-/.])?(?:(\d{1,2})[월\-/.\s]\s*)?(\d{1,2})[일]\s*$"
)
_PRICE_RE = re.compile(r"(\d+)")


class GroupPurchaseBot(StatefulBot):
    """공동구매/폼 모집을 생성하고 참여를 관리하는 StatefulBot이다.

    /폼생성으로 품목, 가격, 마감일, 최소주문수량을 입력받고
    /폼참여, /폼변경, /폼취소로 참여를 관리하며
    /폼마감으로 집계를 출력한다.
    """

    key = "group_purchase_bot"
    name = "Group Purchase Bot"
    version = "0.1.0"
    description = "공동구매/폼 모집 생성, 참여, 변경, 취소, 마감을 처리한다."
    match_mode = "stateful"
    commands = [
        "/폼생성", "/폼참여", "/폼변경", "/폼취소",
        "/폼마감", "/폼목록",
    ]
    patterns = [
        MatchPattern(type="command", value="/폼생성"),
        MatchPattern(type="command", value="/폼참여"),
        MatchPattern(type="command", value="/폼변경"),
        MatchPattern(type="command", value="/폼취소"),
        MatchPattern(type="command", value="/폼마감"),
        MatchPattern(type="command", value="/폼목록"),
        MatchPattern(type="state_exists", value={"name": "form_session", "scope": "room"}),
    ]
    priority = 115
    session_name = "form_session"
    session_scope = "room"
    session_ttl_millis = 60 * 60 * 1000
    default_options = {
        "maxParticipants": 50,
        "minOrderDefault": 1,
    }
    option_schema = {
        "maxParticipants": {
            "type": "integer",
            "default": 50,
            "min": 2,
            "max": 200,
            "description": "최대 참여자 수.",
        },
        "minOrderDefault": {
            "type": "integer",
            "default": 1,
            "min": 1,
            "max": 100,
            "description": "기본 최소주문수량.",
        },
    }

    def can_handle(self, context: ChatContext) -> bool:
        return bool(
            context.command in {
                "/폼생성", "/폼참여", "/폼변경", "/폼취소",
                "/폼마감", "/폼목록",
            }
            or self.has_session(context)
        )

    def run(self, context: ChatContext) -> ChatDecision:
        if context.command == "/폼생성":
            return self._handle_create_form(context)
        if context.command == "/폼참여":
            return self._handle_join_form(context)
        if context.command == "/폼변경":
            return self._handle_change_form(context)
        if context.command == "/폼취소":
            return self._handle_leave_form(context)
        if context.command == "/폼마감":
            return self._handle_close_form(context)
        if context.command == "/폼목록":
            return self._handle_list_form(context)

        session = self.get_session(context)
        if not session:
            return self.reply(
                "진행 중인 폼이 없습니다. "
                "/폼생성으로 새 폼을 만들어주세요."
            )
        if self._is_cancel(context):
            self.end_session(context)
            return self.reply("폼 생성을 취소했습니다.")
        if context.command is not None:
            return self.pass_("other command during form creation")

        step = str(session.get("step", ""))
        if step == "item":
            return self._handle_item_input(context)
        if step == "price":
            return self._handle_price_input(context)
        if step == "deadline":
            return self._handle_deadline_input(context)
        if step == "min_order":
            return self._handle_min_order_input(context)

        self.end_session(context)
        return self.reply(
            "폼 상태를 이해하지 못했습니다. "
            "/폼생성으로 다시 시작해주세요."
        )

    def _handle_create_form(self, context: ChatContext) -> ChatDecision:
        existing = self.get_session(context)
        if existing and existing.get("step") != "completed":
            return self.reply(
                "이미 진행 중인 폼 생성이 있습니다. "
                "'취소'로 중단하고 /폼생성으로 다시 시작해주세요."
            )
        if existing and existing.get("step") == "completed":
            return self.reply(
                "이미 활성화된 폼이 있습니다. "
                "/폼마감으로 먼저 마감해주세요."
            )
        self.start_session(context, "item")
        return self.reply(
            "구매할 품목명을 입력해주세요.\n"
            "예: 치킨, 피자, 후드티\n"
            "취소하려면 '취소'를 입력해주세요."
        )

    def _handle_item_input(self, context: ChatContext) -> ChatDecision:
        item = self._clean_text(context.normalizedText, 100)
        if len(item) < 2:
            return self.reply("품목명을 두 글자 이상 입력해주세요.")
        self.advance_session(context, "price", {"item": item})
        return self.reply(f"품목 [{item}]의 가격을 입력해주세요. (숫자만, 예: 15000)")

    def _handle_price_input(self, context: ChatContext) -> ChatDecision:
        match = _PRICE_RE.search(context.normalizedText)
        if match is None:
            return self.reply("가격을 숫자로 입력해주세요. 예: 15000")
        price = int(match.group(1))
        if price < 100 or price > 10_000_000:
            return self.reply("가격은 100원부터 10,000,000원 사이로 입력해주세요.")
        self.advance_session(context, "deadline", {"price": price})
        return self.reply(
            "마감일을 알려주세요. 예: 오늘, 내일, 6월 30일\n"
            "마감이 없으면 '없음'을 입력해주세요."
        )

    def _handle_deadline_input(self, context: ChatContext) -> ChatDecision:
        text = context.normalizedText.strip()
        if text in {"없음", "없어요", "없다", "none", "-"}:
            self.advance_session(context, "min_order", {"deadline": ""})
        else:
            parsed = self._parse_date(text)
            if parsed is None:
                return self.reply(
                    "마감일을 다시 입력해주세요. "
                    "예: 오늘, 내일, 6월 30일, 2026-06-30"
                )
            self.advance_session(context, "min_order", {"deadline": parsed})
        min_default = self.int_option(context, "minOrderDefault", 1, min_value=1, max_value=100)
        return self.reply(
            f"최소주문수량을 입력해주세요. (기본 {min_default}개, 없으면 1)"
        )

    def _handle_min_order_input(self, context: ChatContext) -> ChatDecision:
        match = _PRICE_RE.search(context.normalizedText)
        min_order = int(match.group(1)) if match else 1
        if min_order < 1 or min_order > 1000:
            return self.reply("최소주문수량은 1부터 1000 사이로 입력해주세요.")
        self.advance_session(context, "completed", {"minOrder": min_order})
        return self._publish_form(context)

    def _publish_form(self, context: ChatContext) -> ChatDecision:
        session = self.get_session(context)
        item = session.get("item", "")
        price = session.get("price", 0)
        deadline = session.get("deadline", "")
        min_order = session.get("minOrder", 1)

        if not self.get_state(context, sender_scope=False):
            self.set_state(context, {"participants": {}}, sender_scope=False)

        lines = [
            f"✅ 폼 생성 완료: [{item}]",
            f"가격: {price:,}원",
            f"최소주문수량: {min_order}개",
        ]
        if deadline:
            lines.append(f"마감: {deadline}")
        else:
            lines.append("마감: 없음")
        lines.extend([
            "",
            "/폼참여 수량 - 참여하기 (예: /폼참여 2)",
            "/폼변경 수량 - 수량 변경하기",
            "/폼취소 - 참여 취소하기",
            "/폼목록 - 현재 참여 현황 보기",
            "/폼마감 - 폼 마감하고 집계 보기",
        ])
        return self.reply("\n".join(lines))

    def _handle_join_form(self, context: ChatContext) -> ChatDecision:
        session = self.get_session(context)
        if not session or session.get("step") != "completed":
            return self.reply(
                "활성화된 폼이 없습니다. "
                "/폼생성으로 새 폼을 만들어주세요."
            )
        item = session.get("item", "")
        price = session.get("price", 0)
        qty = self._parse_qty(context.args, 1, 1000)
        if qty is None:
            return self.reply(
                "수량을 숫자로 입력해주세요. 예: /폼참여 2"
            )
        sender = context.sender or "익명"
        max_participants = self.int_option(context, "maxParticipants", 50, min_value=2, max_value=200)

        def join(value: dict[str, Any]) -> dict[str, Any]:
            participants = dict(value.get("participants", {}))
            if len(participants) >= max_participants:
                value["joinError"] = f"참여자가 최대({max_participants}명)에 도달했습니다."
                return value
            if sender in participants:
                value["joinError"] = f"{sender}님은 이미 참여 중입니다. /폼변경으로 수량을 변경해주세요."
                return value
            participants[sender] = qty
            value["participants"] = participants
            value["updatedAt"] = self.runtime.nowMillis()
            return value

        updated = self.update_state(context, join, sender_scope=False)
        if "joinError" in updated:
            return self.reply(updated["joinError"])
        total_qty = sum(
            v for v in updated.get("participants", {}).values()
            if isinstance(v, int)
        )
        total_price = total_qty * price
        return self.reply(
            f"{sender}님 {item} {qty}개 참여 완료! "
            f"(현재 총 {total_qty}개, {total_price:,}원)"
        )

    def _handle_change_form(self, context: ChatContext) -> ChatDecision:
        session = self.get_session(context)
        if not session or session.get("step") != "completed":
            return self.reply("활성화된 폼이 없습니다.")
        qty = self._parse_qty(context.args, 1, 1000)
        if qty is None:
            return self.reply(
                "변경할 수량을 숫자로 입력해주세요. 예: /폼변경 3"
            )
        sender = context.sender or "익명"
        item = session.get("item", "")
        price = session.get("price", 0)

        def change(value: dict[str, Any]) -> dict[str, Any]:
            participants = dict(value.get("participants", {}))
            if sender not in participants:
                value["changeError"] = f"{sender}님은 아직 참여하지 않았습니다. /폼참여로 먼저 참여해주세요."
                return value
            participants[sender] = qty
            value["participants"] = participants
            value["updatedAt"] = self.runtime.nowMillis()
            return value

        updated = self.update_state(context, change, sender_scope=False)
        if "changeError" in updated:
            return self.reply(updated["changeError"])
        total_qty = sum(
            v for v in updated.get("participants", {}).values()
            if isinstance(v, int)
        )
        total_price = total_qty * price
        return self.reply(
            f"{sender}님 수량이 {qty}개로 변경되었습니다. "
            f"(현재 총 {total_qty}개, {total_price:,}원)"
        )

    def _handle_leave_form(self, context: ChatContext) -> ChatDecision:
        session = self.get_session(context)
        if not session or session.get("step") != "completed":
            return self.reply("활성화된 폼이 없습니다.")
        sender = context.sender or "익명"
        item = session.get("item", "")

        def leave(value: dict[str, Any]) -> dict[str, Any]:
            participants = dict(value.get("participants", {}))
            if sender not in participants:
                value["leaveError"] = f"{sender}님은 참여 중이 아닙니다."
                return value
            del participants[sender]
            value["participants"] = participants
            value["updatedAt"] = self.runtime.nowMillis()
            return value

        updated = self.update_state(context, leave, sender_scope=False)
        if "leaveError" in updated:
            return self.reply(updated["leaveError"])
        return self.reply(f"{sender}님, {item} 참여가 취소되었습니다.")

    def _handle_close_form(self, context: ChatContext) -> ChatDecision:
        session = self.get_session(context)
        if not session or session.get("step") != "completed":
            return self.reply("활성화된 폼이 없습니다.")

        state = self.get_state(context, sender_scope=False)
        participants = dict(state.get("participants", {}))
        item = session.get("item", "")
        price = session.get("price", 0)
        min_order = session.get("minOrder", 1)
        total_qty = sum(v for v in participants.values() if isinstance(v, int))
        total_price = total_qty * price
        participant_count = len(participants)

        self.end_session(context)
        self.clear_state(context, sender_scope=False)

        lines = [
            f"📋 폼 마감: [{item}]",
            f"가격: {price:,}원",
            f"총 참여: {participant_count}명",
            f"총 수량: {total_qty}개",
            f"총 금액: {total_price:,}원",
            f"최소주문수량: {min_order}개",
            "",
            "참여 내역:",
        ]
        sorted_participants = sorted(
            participants.items(),
            key=lambda kv: (-kv[1], kv[0]),
        )
        for sender_name, qty in sorted_participants:
            lines.append(f"  {sender_name}: {qty}개 ({qty * price:,}원)")

        if total_qty < min_order:
            lines.extend([
                "",
                f"⚠️ 최소주문수량({min_order}개)을 충족하지 못했습니다.",
            ])
        else:
            lines.extend([
                "",
                f"✅ 최소주문수량 충족! 주문을 진행해주세요.",
            ])

        return self.reply("\n".join(lines))

    def _handle_list_form(self, context: ChatContext) -> ChatDecision:
        session = self.get_session(context)
        if not session or session.get("step") != "completed":
            return self.reply("활성화된 폼이 없습니다.")

        state = self.get_state(context, sender_scope=False)
        participants = dict(state.get("participants", {}))
        item = session.get("item", "")
        price = session.get("price", 0)
        deadline = session.get("deadline", "")
        min_order = session.get("minOrder", 1)
        total_qty = sum(v for v in participants.values() if isinstance(v, int))
        participant_count = len(participants)

        lines = [
            f"현재 폼: [{item}]",
            f"가격: {price:,}원",
            f"최소주문수량: {min_order}개",
        ]
        if deadline:
            lines.append(f"마감: {deadline}")
        lines.extend([
            f"참여: {participant_count}명 / 총 {total_qty}개",
            "",
        ])
        if not participants:
            lines.append("아직 참여자가 없습니다.")
        else:
            sorted_participants = sorted(
                participants.items(),
                key=lambda kv: (-kv[1], kv[0]),
            )
            for sender_name, qty in sorted_participants:
                lines.append(f"  {sender_name}: {qty}개 ({qty * price:,}원)")

        return self.reply("\n".join(lines))

    def _parse_qty(self, text: str, min_qty: int, max_qty: int) -> int | None:
        match = _PRICE_RE.search(text)
        if match is None:
            return None
        qty = int(match.group(1))
        if qty < min_qty or qty > max_qty:
            return None
        return qty

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
        if month < 1 or month > 12 or day < 1:
            return None
        days_in_month = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        if day > days_in_month[month]:
            return None
        if month == 2 and day == 29:
            if year % 400 != 0 and (year % 100 == 0 or year % 4 != 0):
                return None
        return f"{year:04d}-{month:02d}-{day:02d}"

    def _is_cancel(self, context: ChatContext) -> bool:
        if context.command in {"/취소", "/cancel"}:
            return True
        return context.normalizedText.strip().lower() in _CANCEL_WORDS

    @staticmethod
    def _clean_text(value: str, max_chars: int) -> str:
        cleaned = " ".join(str(value or "").split())
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[:max_chars].rstrip()


def create_bot() -> GroupPurchaseBot:
    return GroupPurchaseBot()
