from __future__ import annotations

import re

from app.chatbot.context import ChatContext
from app.chatbot.matchers.base import MatchResult, PatternMatcher, text_value
from app.chatbot.module import BotRuntime, MatchPattern


class RegexMatcher(PatternMatcher):
    type = "regex"

    def match(self, pattern: MatchPattern, context: ChatContext, runtime: BotRuntime) -> MatchResult:
        flags = re.IGNORECASE if "ignore_case" in pattern.flags else 0
        match = re.search(text_value(pattern), context.normalizedText, flags=flags)
        if match is None:
            return MatchResult(matched=False, reason="regex mismatch")
        return MatchResult(
            matched=True,
            confidence=pattern.confidence,
            matchedText=match.group(0),
            captures=match.groupdict(),
        )
