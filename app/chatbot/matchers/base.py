from __future__ import annotations

from typing import Any, Protocol

from app.pydantic_compat import BaseModel, Field

from app.chatbot.context import ChatContext
from app.chatbot.module import BotRuntime, MatchPattern


class MatchResult(BaseModel):
    """matcher가 반환하는 후보 감지 결과다."""

    matched: bool
    confidence: float = 0.0
    matchedText: str | None = None
    captures: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


class PatternMatcher(Protocol):
    type: str

    def match(self, pattern: MatchPattern, context: ChatContext, runtime: BotRuntime) -> MatchResult:
        ...


def text_value(pattern: MatchPattern) -> str:
    return str(pattern.value).strip()


def normalized_text(value: str) -> str:
    return value.strip().lower()
