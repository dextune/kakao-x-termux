from __future__ import annotations

from typing import Any

from app.chatbot.base_bot import StatefulBot
from app.chatbot.context import ChatContext
from app.chatbot.decision import ChatDecision
from app.chatbot.module import MatchPattern

_CANCEL_COMMANDS = {"/취소", "/cancel"}
_CANCEL_WORDS = {"취소", "그만", "중단", "cancel"}
_CONFIRM_YES = {"네", "예", "응", "확인", "완료", "등록", "접수", "yes", "y"}
_CONFIRM_NO = {"아니", "아니오", "no", "n", "다시", "수정"}
_URGENCY_ALIASES = {
    "1": "긴급",
    "긴급": "긴급",
    "급함": "긴급",
    "높음": "긴급",
    "2": "보통",
    "보통": "보통",
    "일반": "보통",
    "3": "낮음",
    "낮음": "낮음",
    "낮게": "낮음",
}


class RequestIntakeBot(StatefulBot):
    """사용자의 요청을 여러 턴으로 접수하고 방별 최근 접수 목록을 관리한다."""

    key = "request_intake_bot"
    name = "Request Intake Bot"
    version = "0.1.0"
    description = "유형, 내용, 긴급도를 단계적으로 받아 요청을 접수한다."
    match_mode = "stateful"
    commands = ["/접수", "/접수목록"]
    patterns = [
        MatchPattern(type="command", value="/접수"),
        MatchPattern(type="command", value="/접수목록"),
        MatchPattern(type="state_exists", value={"name": "request_session", "scope": "sender"}),
    ]
    priority = 120
    state_name = "request_session"
    session_name = "request_session"
    session_scope = "sender"
    session_ttl_millis = 30 * 60 * 1000
    default_options = {
        "categories": ["상담", "예약", "주문", "기타"],
        "maxDetailChars": 300,
        "recentLimit": 20,
        "recentTtlMillis": 7 * 24 * 60 * 60 * 1000,
    }
    option_schema = {
        "categories": {
            "type": "array",
            "default": ["상담", "예약", "주문", "기타"],
            "description": "접수 유형 목록.",
        },
        "maxDetailChars": {"type": "integer", "default": 300, "min": 20, "max": 1000, "description": "요청 내용 최대 길이."},
        "recentLimit": {"type": "integer", "default": 20, "min": 1, "max": 100, "description": "저장할 최근 접수 수."},
        "recentTtlMillis": {
            "type": "integer",
            "default": 7 * 24 * 60 * 60 * 1000,
            "min": 60_000,
            "max": 30 * 24 * 60 * 60 * 1000,
            "description": "최근 접수 보관 TTL.",
        },
        "recentListSize": {"type": "integer", "default": 5, "min": 1, "max": 10, "description": "목록 답장 표시 개수."},
    }

    def can_handle(self, context: ChatContext) -> bool:
        """명령 또는 진행 중인 sender 세션이 있는 메시지만 처리한다."""

        return context.command in {"/접수", "/접수목록"} or self.has_session(context)

    def run(self, context: ChatContext) -> ChatDecision:
        """요청 접수 세션을 시작, 진행, 완료 또는 취소한다."""

        if context.command == "/접수목록":
            return self._list_recent(context)
        if context.command == "/접수":
            return self._start_intake(context)

        session = self.get_session(context)
        if not session:
            return self.pass_("request session not found")
        if self._is_cancel(context):
            self.end_session(context)
            return self.reply("접수를 취소했습니다. 다시 시작하려면 /접수를 입력해주세요.")
        if context.command is not None:
            return self.pass_("other command during request session")

        step = str(session.get("step", ""))
        if step == "category":
            return self._handle_category(context, session)
        if step == "detail":
            return self._handle_detail(context, session)
        if step == "urgency":
            return self._handle_urgency(context, session)
        if step == "confirm":
            return self._handle_confirm(context, session)

        self.end_session(context)
        return self.reply("진행 중인 접수 상태를 이해하지 못했습니다. /접수로 다시 시작해주세요.")

    def _start_intake(self, context: ChatContext) -> ChatDecision:
        detail = self._clean_detail(context, context.args)
        payload = {"detail": detail} if detail else {}
        self.start_session(context, "category", payload=payload)
        prefix = "내용은 임시 저장했습니다.\n" if detail else ""
        return self.reply(prefix + self._category_prompt(context))

    def _handle_category(self, context: ChatContext, session: dict[str, Any]) -> ChatDecision:
        category = self._select_category(context, context.normalizedText)
        if category is None:
            return self.reply(self._category_prompt(context))
        if session.get("detail"):
            self.advance_session(context, "urgency", {"category": category})
            return self.reply(self._urgency_prompt())
        self.advance_session(context, "detail", {"category": category})
        return self.reply("요청 내용을 한 문장으로 적어주세요. 취소하려면 '취소'라고 입력해주세요.")

    def _handle_detail(self, context: ChatContext, session: dict[str, Any]) -> ChatDecision:
        detail = self._clean_detail(context, context.normalizedText)
        if len(detail) < 2:
            return self.reply("요청 내용을 조금 더 구체적으로 적어주세요.")
        self.advance_session(context, "urgency", {"detail": detail})
        return self.reply(self._urgency_prompt())

    def _handle_urgency(self, context: ChatContext, session: dict[str, Any]) -> ChatDecision:
        urgency = _URGENCY_ALIASES.get(context.normalizedText.strip().lower())
        if urgency is None:
            return self.reply(self._urgency_prompt())
        updated = self.advance_session(context, "confirm", {"urgency": urgency})
        return self.reply(self._summary_prompt(updated))

    def _handle_confirm(self, context: ChatContext, session: dict[str, Any]) -> ChatDecision:
        normalized = context.normalizedText.strip().lower()
        if normalized in _CONFIRM_NO:
            self.end_session(context)
            return self.reply("접수를 취소했습니다. 다시 시작하려면 /접수를 입력해주세요.")
        if normalized not in _CONFIRM_YES:
            return self.reply("접수하려면 '네', 취소하려면 '아니오'라고 입력해주세요.")

        ticket = {
            "ticketId": f"REQ-{self.runtime.nowMillis()}",
            "category": str(session.get("category", "기타")),
            "detail": self._clip(str(session.get("detail", "")), self._max_detail_chars(context)),
            "urgency": str(session.get("urgency", "보통")),
            "sender": context.sender or "",
            "createdAt": self.runtime.nowMillis(),
        }
        self._record_submission(context, ticket)
        self.end_session(context)
        return self.reply(
            "\n".join(
                [
                    f"접수 완료: {ticket['ticketId']}",
                    f"유형: {ticket['category']}",
                    f"긴급도: {ticket['urgency']}",
                    f"내용: {ticket['detail']}",
                ]
            )
        )

    def _list_recent(self, context: ChatContext) -> ChatDecision:
        state = self.runtime.stateStore.get(self.state_key(context, "submitted_requests", sender_scope=False), {})
        items = [item for item in state.get("items", []) if isinstance(item, dict)]
        if not items:
            return self.reply("최근 접수 내역이 없습니다.")
        limit = min(self.int_option(context, "recentListSize", 5, min_value=1, max_value=10), len(items))
        lines = ["최근 접수 내역:"]
        for item in reversed(items[-limit:]):
            detail = self._clip(str(item.get("detail", "")), 60)
            lines.append(
                f"- {item.get('ticketId', 'REQ')} / {item.get('category', '기타')} / {item.get('urgency', '보통')} / {detail}"
            )
        return self.reply("\n".join(lines))

    def _record_submission(self, context: ChatContext, ticket: dict[str, Any]) -> None:
        key = self.state_key(context, "submitted_requests", sender_scope=False)
        limit = self.int_option(context, "recentLimit", 20, min_value=1, max_value=100)
        ttl_millis = self.int_option(
            context,
            "recentTtlMillis",
            7 * 24 * 60 * 60 * 1000,
            min_value=60_000,
            max_value=30 * 24 * 60 * 60 * 1000,
        )

        def update(value: dict[str, Any]) -> dict[str, Any]:
            items = [item for item in value.get("items", []) if isinstance(item, dict)]
            items.append(dict(ticket))
            value["items"] = items[-limit:]
            value["updatedAt"] = self.runtime.nowMillis()
            return value

        self.runtime.stateStore.mutate(key, update, ttlMillis=ttl_millis)

    def _select_category(self, context: ChatContext, text: str) -> str | None:
        categories = self._categories(context)
        normalized = text.strip()
        if normalized.isdigit():
            index = int(normalized) - 1
            if 0 <= index < len(categories):
                return categories[index]
        for category in categories:
            if normalized == category or category in normalized:
                return category
        return None

    def _category_prompt(self, context: ChatContext) -> str:
        lines = ["접수 유형을 선택해주세요."]
        for index, category in enumerate(self._categories(context), start=1):
            lines.append(f"{index}. {category}")
        lines.append("취소하려면 '취소'라고 입력해주세요.")
        return "\n".join(lines)

    def _urgency_prompt(self) -> str:
        return "긴급도를 선택해주세요.\n1. 긴급\n2. 보통\n3. 낮음"

    def _summary_prompt(self, session: dict[str, Any]) -> str:
        return "\n".join(
            [
                "아래 내용으로 접수할까요?",
                f"유형: {session.get('category', '기타')}",
                f"긴급도: {session.get('urgency', '보통')}",
                f"내용: {session.get('detail', '')}",
                "접수하려면 '네', 취소하려면 '아니오'라고 입력해주세요.",
            ]
        )

    def _categories(self, context: ChatContext) -> list[str]:
        categories = [str(item).strip() for item in self.list_option(context, "categories", []) if str(item).strip()]
        return categories or ["상담", "예약", "주문", "기타"]

    def _clean_detail(self, context: ChatContext, value: str) -> str:
        return self._clip(" ".join(str(value or "").split()), self._max_detail_chars(context))

    def _max_detail_chars(self, context: ChatContext) -> int:
        return self.int_option(context, "maxDetailChars", 300, min_value=20, max_value=1000)

    def _clip(self, value: str, max_chars: int) -> str:
        if len(value) <= max_chars:
            return value
        return value[:max_chars].rstrip()

    def _is_cancel(self, context: ChatContext) -> bool:
        if context.command in _CANCEL_COMMANDS:
            return True
        return context.normalizedText.strip().lower() in _CANCEL_WORDS


def create_bot() -> RequestIntakeBot:
    """로더가 사용할 객체형 봇 인스턴스를 생성한다."""

    return RequestIntakeBot()
