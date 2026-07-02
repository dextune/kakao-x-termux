from __future__ import annotations

from app.pydantic_compat import BaseModel

from app.schemas import EventAction, EventResponse


class ChatDecision(BaseModel):
    """봇 실행 결과와 프로세서 제어 정보를 함께 담는 내부 모델이다."""

    action: EventAction | str
    text: str | None = None
    replyToken: str | None = None
    botKey: str | None = None
    reason: str | None = None
    terminal: bool = True

    @classmethod
    def reply(cls, text: str, reply_token: str | None = None, reason: str | None = None) -> "ChatDecision":
        return cls(action=EventAction.reply, text=text, replyToken=reply_token, reason=reason, terminal=True)

    @classmethod
    def queued(cls, reason: str | None = None) -> "ChatDecision":
        return cls(action=EventAction.queued, reason=reason, terminal=True)

    @classmethod
    def none(cls, reason: str | None = None, terminal: bool = True) -> "ChatDecision":
        return cls(action=EventAction.none, reason=reason, terminal=terminal)

    @classmethod
    def pass_(cls, reason: str | None = None) -> "ChatDecision":
        return cls(action="pass", reason=reason, terminal=False)

    def is_pass(self) -> bool:
        return self.action == "pass"


def to_event_response(decision: ChatDecision) -> EventResponse:
    """내부 챗봇 결정을 기존 `/events` 응답 계약으로 변환한다."""

    if decision.action == EventAction.reply and decision.replyToken is None:
        return EventResponse(ack=True, action=EventAction.none, error="reply token not found")
    if decision.action == EventAction.reply:
        return EventResponse(
            ack=True,
            action=EventAction.reply,
            replyToken=decision.replyToken,
            text=decision.text,
        )
    if decision.action == EventAction.queued:
        return EventResponse(ack=True, action=EventAction.queued)
    return EventResponse(ack=True, action=EventAction.none)
