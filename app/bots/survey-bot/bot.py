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
_DONE_WORDS = {"완료", "다 했다", "꾸냈다", "그만", "done", "ok"}
_YES_WORDS = {"네", "예", "그렇다", "yes", "y", "ok"}
_NO_WORDS = {"아니오", "아니", "아나요", "no", "n", "sing"}
_DATE_RE = re.compile(
    r"^(?:(\d{4})[-/.])?(?:(\d{1,2})[월\-/.\s]\s*)?(\d{1,2})[일]\s*$"
)


class SurveyBot(StatefulBot):
    """설문을 생성하고 참여받아 결과를 집계하는 StatefulBot이다.

    /설문으로 시작하여 제목, 항목, 복수선택 여부,
    마감일을 차례로 입력받고 /설문참여로 투표한 뒤
    /설문결과로 집계를 확인한다.
    """

    key = "survey_bot"
    name = "Survey Bot"
    version = "0.1.0"
    description = "설문 생성, 참여, 결과 집계를 처리한다."
    match_mode = "stateful"
    commands = ["/설문", "/설문참여", "/설문결과"]
    patterns = [
        MatchPattern(type="command", value="/설문"),
        MatchPattern(type="command", value="/설문참여"),
        MatchPattern(type="command", value="/설문결과"),
        MatchPattern(type="state_exists", value={"name": "survey_session", "scope": "room"}),
    ]
    priority = 115
    session_name = "survey_session"
    session_scope = "room"
    session_ttl_millis = 30 * 60 * 1000
    default_options = {
        "maxItems": 20,
        "maxTitleChars": 80,
    }
    option_schema = {
        "maxItems": {
            "type": "integer",
            "default": 20,
            "min": 2,
            "max": 50,
            "description": "설문에 들어가는 최대 항목 수.",
        },
        "maxTitleChars": {
            "type": "integer",
            "default": 80,
            "min": 10,
            "max": 200,
            "description": "설문 제목 최대 길이.",
        },
    }

    def can_handle(self, context: ChatContext) -> bool:
        if context.command in {"/설문", "/설문참여", "/설문결과"}:
            return True
        return self.has_session(context)

    def run(self, context: ChatContext) -> ChatDecision:
        if context.command == "/설문":
            existing = self.get_session(context)
            if existing:
                return self.reply(
                    "이미 진행 중인 설문이 있습니다. "
                    "취소하려면 '취소'를 입력해주세요."
                )
            args = context.args.strip()
            if args:
                return self._handle_create_title_given(context, args)
            self.start_session(context, "title")
            return self.reply(
                "설문의 제목을 입력해주세요.\n"
                "취소하려면 '취소'를 입력해주세요."
            )

        if context.command == "/설문참여":
            return self._handle_vote(context)

        if context.command == "/설문결과":
            return self._handle_results(context)

        session = self.get_session(context)
        if not session:
            return self.reply(
                "진행 중인 설문이 없습니다. "
                "/설문으로 새 설문을 시작해주세요."
            )
        if self._is_cancel(context):
            self.end_session(context)
            return self.reply("설문 작성을 취소했습니다.")
        if context.command is not None:
            return self.pass_("other command during survey session")

        step = str(session.get("step", ""))
        if step == "title":
            return self._handle_create_title_given(context, context.normalizedText)
        if step == "items":
            return self._handle_items_input(context)
        if step == "multiple":
            return self._handle_multiple_choice(context)
        if step == "deadline":
            return self._handle_deadline(context)

        self.end_session(context)
        return self.reply(
            "설문 상태를 이해하지 못했습니다. "
            "/설문으로 다시 시작해주세요."
        )

    def _handle_create_title_given(self, context: ChatContext, title_raw: str) -> ChatDecision:
        title = self._clean_text(title_raw, self.int_option(context, "maxTitleChars", 80, min_value=10, max_value=200))
        if len(title) < 2:
            return self.reply(
                "제목을 두 글자 이상 입력해주세요.\n"
                "예: 감사회 메뉴 설문"
            )
        self.advance_session(context, "items", {"title": title, "items": []})
        max_items = self.int_option(context, "maxItems", 20, min_value=2, max_value=50)
        return self.reply(
            f"설문: [{title}]\n"
            f"항목을 한 줄에 하나씩 입력해주세요. "
            f"(다 입력했으면 '완료', 최대 {max_items}개)"
        )

    def _handle_items_input(self, context: ChatContext) -> ChatDecision:
        text = context.normalizedText.strip()
        if text.lower() in _DONE_WORDS:
            session = self.get_session(context)
            items = [i for i in session.get("items", []) if isinstance(i, str)]
            if len(items) < 2:
                return self.reply("항목이 부족합니다. 적어도 2개의 항목을 입력해주세요.")
            self.advance_session(context, "multiple", {"items": items})
            return self.reply("복수 선택을 허용하시겠습니까? (네/아니오)")
        text = self._clean_text(text, 120)
        if len(text) < 1:
            return self.reply("항목을 입력해주세요.")
        max_items = self.int_option(context, "maxItems", 20, min_value=2, max_value=50)

        def add_item(value: dict[str, Any]) -> dict[str, Any]:
            items = list(value.get("items", []))
            items.append(text)
            value["items"] = items
            value["updatedAt"] = self.runtime.nowMillis()
            return value

        updated = self.update_session(context, add_item)
        current_items = [i for i in updated.get("items", []) if isinstance(i, str)]
        count = len(current_items)
        if count >= max_items:
            self.advance_session(context, "multiple", {"items": current_items})
            return self.reply(self._items_summary(current_items))
        return self.reply(
            f"항목 추가됨: {text}\n"
            f"(현재 {count}개, '완료'로 마침)"
        )

    def _handle_multiple_choice(self, context: ChatContext) -> ChatDecision:
        text = context.normalizedText.strip().lower()
        if text in _YES_WORDS:
            self.advance_session(context, "deadline", {"allowMultiple": True})
        elif text in _NO_WORDS:
            self.advance_session(context, "deadline", {"allowMultiple": False})
        else:
            return self.reply("복수 선택을 허용하려면 '네', 하지 않으면 '아니오'라고 입력해주세요.")
        return self.reply(
            "마감일을 알려주세요. 예: 오늘, 내일, 6월 30일\n"
            "마감이 없으면 '없음'이라고 입력해주세요."
        )

    def _handle_deadline(self, context: ChatContext) -> ChatDecision:
        text = context.normalizedText.strip()
        if text in {"없음", "없어요", "없다", "none", "-"}:
            self.advance_session(context, "completed", {"deadline": ""})
        else:
            parsed = self._parse_date(text)
            if parsed is None:
                return self.reply(
                    "마감일을 다시 입력해주세요. "
                    "예: 오늘, 내일, 6월 30일, 2026-06-30"
                )
            self.advance_session(context, "completed", {"deadline": parsed})
        return self._publish_survey(context)

    def _publish_survey(self, context: ChatContext) -> ChatDecision:
        session = self.get_session(context)
        title = session.get("title", "설문")
        items = [i for i in session.get("items", []) if isinstance(i, str)]
        allow_multiple = session.get("allowMultiple", False)
        deadline = session.get("deadline", "")
        lines = [
            f"✅ 설문 완료: [{title}]",
            f"항목:",
        ]
        for idx, item in enumerate(items, start=1):
            lines.append(f"  {idx}. {item}")
        if allow_multiple:
            lines.append("복수 선택: 가능")
        if deadline:
            lines.append(f"마감: {deadline}")
        lines.append(f"\n/설문참여 번호로 투표하세요!")
        lines.append("/설문결과로 집계를 확인하세요.")
        return self.reply("\n".join(lines))

    def _handle_vote(self, context: ChatContext) -> ChatDecision:
        session = self.get_session(context)
        if not session:
            return self.reply(
                "진행 중인 설문이 없습니다. "
                "/설문으로 새 설문을 시작해주세요."
            )

        items = [i for i in session.get("items", []) if isinstance(i, str)]
        if not items:
            return self.reply("설문에 항목이 없습니다.")

        deadline = session.get("deadline", "")
        if deadline:
            now = datetime.fromtimestamp(self.runtime.nowMillis() / 1000, tz=timezone.utc)
            try:
                deadline_dt = datetime.strptime(deadline, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if now > deadline_dt:
                    return self.reply(f"이 설문은 {deadline}에 마감되었습니다.")
            except ValueError:
                pass

        raw = context.args.strip()
        if not raw:
            return self.reply(self._vote_usage(items))

        allow_multiple = session.get("allowMultiple", False)
        selections = [s.strip() for s in raw.replace(",", " ").split() if s.strip().isdigit()]
        if not selections:
            return self.reply(self._vote_usage(items))

        selected_indices = []
        for s in selections:
            idx = int(s) - 1
            if idx < 0 or idx >= len(items):
                return self.reply(f"번호 {s}가 올바르지 않습니다. 1부터 {len(items)}까지의 번호를 선택해주세요.")
            if not allow_multiple and len(selected_indices) >= 1:
                return self.reply(f"이 설문은 복수 선택이 허용되지 않습니다.")
            if idx not in selected_indices:
                selected_indices.append(idx)

        sender = context.sender or "익명"

        def check_and_vote(value: dict[str, Any]) -> dict[str, Any]:
            votes = dict(value.get("votes", {}))
            if sender in votes:
                value["voteError"] = f"{sender}님은 이미 투표했습니다."
                return value
            if allow_multiple:
                votes[sender] = selected_indices
            else:
                votes[sender] = selected_indices[0]
            value["votes"] = votes
            value["updatedAt"] = self.runtime.nowMillis()
            return value

        updated = self.update_session(context, check_and_vote)
        if "voteError" in updated:
            return self.reply(updated["voteError"])

        item_names = [items[i] for i in selected_indices]
        return self.reply(f"{sender}님 투표 완료! : {', '.join(item_names)}")

    def _handle_results(self, context: ChatContext) -> ChatDecision:
        session = self.get_session(context)
        if not session:
            return self.reply(
                "진행 중인 설문이 없습니다. "
                "/설문으로 새 설문을 시작해주세요."
            )

        title = session.get("title", "설문")
        items = [i for i in session.get("items", []) if isinstance(i, str)]
        votes = dict(session.get("votes", {}))
        total = len(votes)
        counts = [0] * len(items)

        for selection in votes.values():
            if isinstance(selection, list):
                for idx in selection:
                    if 0 <= idx < len(items):
                        counts[idx] += 1
            elif isinstance(selection, int):
                if 0 <= selection < len(items):
                    counts[selection] += 1

        lines = [f"현재 설문 결과: [{title}]", f"총 투표: {total}명", ""]
        for idx, (item_name, count) in enumerate(zip(items, counts), start=1):
            pct = (count / total * 100) if total > 0 else 0
            bar_len = int(pct / 5) if pct > 0 else 0
            bar = "█" * bar_len
            lines.append(f"  {idx}. {item_name}")
            lines.append(f"     {count}표 ({pct:.1f}%) {bar}")

        lines.append(f"\n/설문참여 번호로 투표하세요!")
        return self.reply("\n".join(lines))

    def _vote_usage(self, items: list[str]) -> str:
        lines = ["/설문참여 번호로 투표해주세요. 예: /설문참여 1"]
        for idx, item in enumerate(items, start=1):
            lines.append(f"  {idx}. {item}")
        return "\n".join(lines)

    def _items_summary(self, items: list[str]) -> str:
        lines = ["설문 항목이 최대수에 도달했습니다.", "입력된 항목:"]
        for idx, item in enumerate(items, start=1):
            lines.append(f"  {idx}. {item}")
        lines.append("복수 선택을 허용하시겠습니까? (네/아니오)")
        return "\n".join(lines)

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
        return context.normalizedText.strip().lower() in _CANCEL_WORDS

    @staticmethod
    def _clean_text(value: str, max_chars: int) -> str:
        cleaned = " ".join(str(value or "").split())
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[:max_chars].rstrip()


def create_bot() -> SurveyBot:
    return SurveyBot()
