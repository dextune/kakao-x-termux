from __future__ import annotations

from app.chatbot.context import ChatContext
from app.chatbot.matchers.base import MatchResult, PatternMatcher, normalized_text, text_value
from app.chatbot.module import BotRuntime, MatchPattern


class ContainsMatcher(PatternMatcher):
    type = "contains"

    def match(self, pattern: MatchPattern, context: ChatContext, runtime: BotRuntime) -> MatchResult:
        needle = normalized_text(text_value(pattern))
        haystack = normalized_text(context.normalizedText)
        if needle and needle in haystack:
            return MatchResult(matched=True, confidence=pattern.confidence, matchedText=str(pattern.value))
        return MatchResult(matched=False, reason="contains mismatch")


class AnyKeywordsMatcher(PatternMatcher):
    type = "any_keywords"

    def match(self, pattern: MatchPattern, context: ChatContext, runtime: BotRuntime) -> MatchResult:
        values = _list_value(pattern)
        haystack = normalized_text(context.normalizedText)
        for value in values:
            if value and normalized_text(value) in haystack:
                return MatchResult(matched=True, confidence=pattern.confidence, matchedText=value)
        return MatchResult(matched=False, reason="keyword mismatch")


class AllKeywordsMatcher(PatternMatcher):
    type = "all_keywords"

    def match(self, pattern: MatchPattern, context: ChatContext, runtime: BotRuntime) -> MatchResult:
        values = [value for value in _list_value(pattern) if value]
        haystack = normalized_text(context.normalizedText)
        if values and all(normalized_text(value) in haystack for value in values):
            return MatchResult(matched=True, confidence=pattern.confidence, matchedText=",".join(values))
        return MatchResult(matched=False, reason="all keywords mismatch")


class StartsWithMatcher(PatternMatcher):
    type = "starts_with"

    def match(self, pattern: MatchPattern, context: ChatContext, runtime: BotRuntime) -> MatchResult:
        prefix = normalized_text(text_value(pattern))
        if prefix and normalized_text(context.normalizedText).startswith(prefix):
            return MatchResult(matched=True, confidence=pattern.confidence, matchedText=str(pattern.value))
        return MatchResult(matched=False, reason="starts_with mismatch")


class EndsWithMatcher(PatternMatcher):
    type = "ends_with"

    def match(self, pattern: MatchPattern, context: ChatContext, runtime: BotRuntime) -> MatchResult:
        suffix = normalized_text(text_value(pattern))
        if suffix and normalized_text(context.normalizedText).endswith(suffix):
            return MatchResult(matched=True, confidence=pattern.confidence, matchedText=str(pattern.value))
        return MatchResult(matched=False, reason="ends_with mismatch")


class MentionMatcher(PatternMatcher):
    type = "mention"

    def match(self, pattern: MatchPattern, context: ChatContext, runtime: BotRuntime) -> MatchResult:
        values = _list_value(pattern)
        haystack = normalized_text(context.normalizedText)
        for value in values:
            if value and normalized_text(value) in haystack:
                return MatchResult(matched=True, confidence=pattern.confidence, matchedText=value)
        return MatchResult(matched=False, reason="mention mismatch")


def _list_value(pattern: MatchPattern) -> list[str]:
    if isinstance(pattern.value, list):
        return [str(item).strip() for item in pattern.value]
    return [str(pattern.value).strip()]
