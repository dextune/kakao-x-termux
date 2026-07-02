from __future__ import annotations

import logging
from threading import RLock
from types import ModuleType
from typing import Any

from app.chatbot.legacy import LegacyBotAdapter
from app.chatbot.module import BotDefinition, BotHandler, BotRuntime

logger = logging.getLogger("app.chatbot.registry")


class RegisteredBot:
    """로더가 import한 봇 handler와 검증된 definition/runtime 묶음이다."""

    def __init__(
        self,
        definition: BotDefinition,
        runtime: BotRuntime,
        handler: BotHandler | None = None,
        sourceModule: ModuleType | Any | None = None,
        module: ModuleType | Any | None = None,
    ) -> None:
        self.definition = definition
        self.runtime = runtime
        self.sourceModule = sourceModule or module
        self.handler = handler or LegacyBotAdapter(module, definition)
        self.module = self.sourceModule


class ChatbotRegistry:
    """등록된 봇을 key와 priority 기준으로 관리한다."""

    def __init__(self) -> None:
        self._bots: dict[str, RegisteredBot] = {}
        self._sorted_cache: list[RegisteredBot] | None = None
        self._lock = RLock()

    def register(self, bot: RegisteredBot) -> bool:
        with self._lock:
            if bot.definition.key in self._bots:
                return False
            self._bots[bot.definition.key] = bot
            self._sorted_cache = None
            return True

    def replace(self, bot: RegisteredBot) -> RegisteredBot | None:
        """봇을 원자적으로 교체하고 이전 봇을 반환한다."""

        with self._lock:
            previous = self._bots.get(bot.definition.key)
            self._bots[bot.definition.key] = bot
            self._sorted_cache = None
            return previous

    def unregister(self, key: str) -> RegisteredBot | None:
        """등록된 봇을 제거하고 제거된 봇을 반환한다."""

        with self._lock:
            previous = self._bots.pop(key, None)
            if previous is not None:
                self._sorted_cache = None
            return previous

    def get(self, key: str) -> RegisteredBot | None:
        with self._lock:
            return self._bots.get(key)

    def all(self) -> list[RegisteredBot]:
        return self.snapshot()

    def snapshot(self) -> list[RegisteredBot]:
        """요청 처리 중 reload 영향을 받지 않도록 얕은 snapshot을 반환한다."""

        with self._lock:
            if self._sorted_cache is None:
                self._sorted_cache = sorted(
                    self._bots.values(),
                    key=lambda item: (item.definition.priority, item.definition.key),
                )
            return list(self._sorted_cache)

    def clear(self) -> None:
        with self._lock:
            self._bots.clear()
            self._sorted_cache = None

    def shutdown_all(self) -> None:
        with self._lock:
            bots = list(self._bots.values())
            self._bots.clear()
            self._sorted_cache = None
        for bot in bots:
            try:
                bot.handler.shutdown()
            except Exception as exc:
                logger.warning("bot shutdown failed botKey=%s error=%s", bot.definition.key, exc)
