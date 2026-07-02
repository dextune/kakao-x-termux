from __future__ import annotations

from app.chatbot.context import ChatContext
from app.chatbot.matchers.base import MatchResult, PatternMatcher
from app.chatbot.matchers.command import CommandMatcher
from app.chatbot.matchers.keyword import (
    AllKeywordsMatcher,
    AnyKeywordsMatcher,
    ContainsMatcher,
    EndsWithMatcher,
    MentionMatcher,
    StartsWithMatcher,
)
from app.chatbot.matchers.regex import RegexMatcher
from app.chatbot.matchers.sequence import FallbackMatcher, RoomRateMatcher, SenderRateMatcher, StateExistsMatcher
from app.chatbot.module import BotRuntime, MatchPattern


class MatcherRegistry:
    """MatchPattern.type별 matcher 구현체를 관리한다."""

    def __init__(self) -> None:
        self._matchers: dict[str, PatternMatcher] = {}

    def register(self, matcher: PatternMatcher) -> None:
        self._matchers[matcher.type] = matcher

    def get(self, matcher_type: str) -> PatternMatcher | None:
        return self._matchers.get(matcher_type)

    def count(self) -> int:
        """운영 진단에서 사용할 등록 matcher 개수를 반환한다."""

        return len(self._matchers)

    def match_all(
        self,
        patterns: list[MatchPattern],
        context: ChatContext,
        runtime: BotRuntime,
    ) -> list[MatchResult]:
        results: list[MatchResult] = []
        for pattern in patterns:
            matcher = self.get(pattern.type)
            if matcher is None:
                results.append(MatchResult(matched=False, reason=f"unknown matcher: {pattern.type}"))
                continue
            try:
                results.append(matcher.match(pattern, context, runtime))
            except Exception as exc:
                results.append(MatchResult(matched=False, reason=str(exc)))
        return results


def default_matcher_registry() -> MatcherRegistry:
    registry = MatcherRegistry()
    for matcher in (
        CommandMatcher(),
        ContainsMatcher(),
        AnyKeywordsMatcher(),
        AllKeywordsMatcher(),
        RegexMatcher(),
        StartsWithMatcher(),
        EndsWithMatcher(),
        MentionMatcher(),
        SenderRateMatcher(),
        RoomRateMatcher(),
        StateExistsMatcher(),
        FallbackMatcher(),
    ):
        registry.register(matcher)
    return registry
