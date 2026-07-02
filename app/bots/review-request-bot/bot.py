from __future__ import annotations

from typing import Any

from app.chatbot.base_bot import StatefulBot
from app.chatbot.context import ChatContext
from app.chatbot.decision import ChatDecision
from app.chatbot.module import MatchPattern


_CANCEL_WORDS = {"취소", "그만", "중단", "cancel"}
_EMPTY_WORDS = {"없음", "없어요", "없다", "none", "-", "skip"}

_REVIEW_TYPES = {
    "1": {"key": "proofread", "name": "맞춤법 검사"},
    "proofread": {"key": "proofread", "name": "맞춤법 검사"},
    "2": {"key": "translate", "name": "번역"},
    "translate": {"key": "translate", "name": "번역"},
    "3": {"key": "summarize", "name": "요약"},
    "summarize": {"key": "summarize", "name": "요약"},
    "summarise": {"key": "summarize", "name": "요약"},
}


class ReviewRequestBot(StatefulBot):
    """문서/메시지 검토 의뢰를 접수하는 StatefulBot이다.

    /검토 명령으로 시작하여 검토할 내용, 검토 유형(맞춤법/번역/요약),
    추가 요청사항을 차례로 입력받고 결과를 정리해 보여준다.
    """

    key = "review_request_bot"
    name = "Review Request Bot"
    version = "0.1.0"
    description = "검토 의뢰(맞춤법/번역/요약)를 접수하고 결과를 정리한다."
    match_mode = "stateful"
    commands = ["/검토"]
    patterns = [
        MatchPattern(type="command", value="/검토"),
        MatchPattern(type="state_exists", value={"name": "review_session", "scope": "sender"}),
    ]
    priority = 115
    session_name = "review_session"
    session_scope = "sender"
    session_ttl_millis = 30 * 60 * 1000

    def can_handle(self, context: ChatContext) -> bool:
        if context.command in {"/검토"}:
            return True
        return self.has_session(context)

    def run(self, context: ChatContext) -> ChatDecision:
        if context.command == "/검토":
            existing = self.get_session(context)
            if existing:
                return self.reply(
                    "이미 진행 중인 검토 의뢰가 있습니다. "
                    "취소하려면 '취소'를 입력해주세요."
                )
            args = context.args.strip()
            if args:
                return self._start_with_content(context, args)
            self.start_session(context, "content")
            return self.reply(
                "검토할 내용을 입력해주세요.\n"
                "취소하려면 '취소'를 입력해주세요."
            )

        session = self.get_session(context)
        if not session:
            return self.reply(
                "진행 중인 검토 의뢰가 없습니다. "
                "/검토로 새 의뢰를 시작해주세요."
            )
        if self._is_cancel(context):
            self.end_session(context)
            return self.reply("검토 의뢰를 취소했습니다.")
        if context.command is not None:
            return self.pass_("other command during review session")

        step = str(session.get("step", ""))
        if step == "content":
            return self._start_with_content(context, context.normalizedText)
        if step == "type":
            return self._handle_type(context)
        if step == "note":
            return self._handle_note(context)

        self.end_session(context)
        return self.reply(
            "검토 의뢰 상태를 이해하지 못했습니다. "
            "/검토로 다시 시작해주세요."
        )

    def _start_with_content(self, context: ChatContext, content_raw: str) -> ChatDecision:
        content = self._clean_text(content_raw, 2000)
        if len(content) < 5:
            return self.reply(
                "검토할 내용을 5자 이상 입력해주세요.\n"
                "예: /검토 오늘 회의록을 검토해줘"
            )
        self.advance_session(context, "type", {"content": content})
        return self.reply(
            "검토 유형을 선택해주세요.\n"
            "1. 맞춤법 검사\n"
            "2. 번역\n"
            "3. 요약\n"
            "(번호 또는 이름으로 입력)"
        )

    def _handle_type(self, context: ChatContext) -> ChatDecision:
        text = context.normalizedText.strip().lower()
        review_type = _REVIEW_TYPES.get(text)
        if review_type is None:
            return self.reply(
                "검토 유형을 다시 선택해주세요.\n"
                "1. 맞춤법 검사\n"
                "2. 번역\n"
                "3. 요약"
            )
        self.advance_session(context, "note", {"reviewType": review_type["key"], "reviewTypeName": review_type["name"]})
        return self.reply(
            "추가 요청사항이 있으면 입력해주세요.\n"
            "없으면 '없음'을 입력해주세요."
        )

    def _handle_note(self, context: ChatContext) -> ChatDecision:
        text = context.normalizedText.strip()
        note = "" if text.lower() in _EMPTY_WORDS else self._clean_text(text, 500)
        updated = self.advance_session(context, "done", {"note": note})
        return self._show_result(context, updated)

    def _show_result(self, context: ChatContext, session: dict[str, Any]) -> ChatDecision:
        content = session.get("content", "")
        review_type_name = session.get("reviewTypeName", "알 수 없음")
        note = session.get("note", "")
        sender = context.sender or "익명"

        lines = [
            f"✅ 검토 의뢰 접수 완료",
            f"보낸 사람: {sender}",
            f"검토 유형: {review_type_name}",
            f"",
            f"[검토할 내용]",
            f"{content}",
        ]
        if note:
            lines.extend(["", f"[추가 요청]", f"{note}"])
        lines.extend([
            "",
            "검토가 완료되면 결과를 알려드리겠습니다.",
        ])
        return self.reply("\n".join(lines))

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


def create_bot() -> ReviewRequestBot:
    return ReviewRequestBot()
