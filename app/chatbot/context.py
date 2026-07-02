from __future__ import annotations

from typing import Any

from app.pydantic_compat import BaseModel, Field

from app.schemas import BridgeEvent, RoomRuleResponse


class ChatContext(BaseModel):
    """`BridgeEvent`를 챗봇 처리에 필요한 값으로 정규화한 모델이다."""

    eventId: str
    roomKey: str
    room: str
    sender: str | None
    text: str
    normalizedText: str
    messageType: str
    sourceType: str
    replyToken: str | None
    replyTokenExpiresAt: int | None
    receivedAt: int
    command: str | None
    args: str
    roomOptions: dict[str, Any] = Field(default_factory=dict)
    botOptions: dict[str, Any] = Field(default_factory=dict)
    state: dict[str, Any] = Field(default_factory=dict)
    roomRule: RoomRuleResponse | None = None
    handled: bool = False


def build_chat_context(
    event: BridgeEvent,
    room_rule: RoomRuleResponse | None = None,
    room_options: dict[str, Any] | None = None,
) -> ChatContext:
    """수신 이벤트를 챗봇 프로세서 입력 모델로 변환한다."""

    normalized = " ".join(event.text.strip().split())
    command = None
    args = normalized
    if normalized.startswith("/"):
        parts = normalized.split(maxsplit=1)
        command = parts[0]
        args = parts[1] if len(parts) > 1 else ""
    return ChatContext(
        eventId=event.eventId,
        roomKey=event.roomKey,
        room=event.room,
        sender=event.sender,
        text=event.text,
        normalizedText=normalized,
        messageType=str(event.messageType),
        sourceType=str(event.sourceType),
        replyToken=event.replyToken,
        replyTokenExpiresAt=event.replyTokenExpiresAt,
        receivedAt=event.receivedAt,
        command=command,
        args=args,
        roomOptions=room_options or {},
        roomRule=room_rule,
    )
