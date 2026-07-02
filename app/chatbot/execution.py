from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.chatbot.context import ChatContext
from app.schemas import RoomRuleResponse


@dataclass
class BotExecutionContext:
    """봇 1회 실행에 필요한 얕은 wrapper다.

    원본 `ChatContext`의 큰 문자열/room 정보는 공유하고, 봇별 mutable option만 따로 둔다.
    기존 봇 API와의 호환을 위해 주요 속성명을 그대로 제공한다.
    """

    base: ChatContext
    botOptions: dict[str, Any] = field(default_factory=dict)
    handled: bool = False
    state: dict[str, Any] = field(default_factory=dict)

    @property
    def eventId(self) -> str:
        return self.base.eventId

    @property
    def roomKey(self) -> str:
        return self.base.roomKey

    @property
    def room(self) -> str:
        return self.base.room

    @property
    def sender(self) -> str | None:
        return self.base.sender

    @property
    def text(self) -> str:
        return self.base.text

    @property
    def normalizedText(self) -> str:
        return self.base.normalizedText

    @property
    def messageType(self) -> str:
        return self.base.messageType

    @property
    def sourceType(self) -> str:
        return self.base.sourceType

    @property
    def replyToken(self) -> str | None:
        return self.base.replyToken

    @property
    def replyTokenExpiresAt(self) -> int | None:
        return self.base.replyTokenExpiresAt

    @property
    def receivedAt(self) -> int:
        return self.base.receivedAt

    @property
    def command(self) -> str | None:
        return self.base.command

    @property
    def args(self) -> str:
        return self.base.args

    @property
    def roomOptions(self) -> dict[str, Any]:
        return self.base.roomOptions

    @property
    def roomRule(self) -> RoomRuleResponse | None:
        return self.base.roomRule

    def model_copy(self, deep: bool = False) -> "BotExecutionContext":
        """기존 `ChatContext.model_copy()` 사용처와의 최소 호환을 제공한다."""

        return BotExecutionContext(
            base=self.base,
            botOptions=dict(self.botOptions),
            handled=self.handled,
            state=dict(self.state),
        )
