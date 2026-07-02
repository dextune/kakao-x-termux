from __future__ import annotations

from app.chatbot.context import ChatContext
from app.chatbot.matchers.base import MatchResult, PatternMatcher, normalized_text, text_value
from app.chatbot.module import BotRuntime, MatchPattern


class CommandMatcher(PatternMatcher):
    type = "command"

    def match(self, pattern: MatchPattern, context: ChatContext, runtime: BotRuntime) -> MatchResult:
        expected = text_value(pattern)
        if context.command and normalized_text(context.command) == normalized_text(expected):
            return MatchResult(matched=True, confidence=pattern.confidence, matchedText=context.command)
        return MatchResult(matched=False, reason="command mismatch")
