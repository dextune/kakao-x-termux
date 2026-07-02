from __future__ import annotations

from types import ModuleType
from typing import Any

from app.chatbot.context import ChatContext
from app.chatbot.decision import ChatDecision
from app.chatbot.module import BotDefinition, BotRuntime


class LegacyBotAdapter:
    """기존 함수형 봇 모듈을 객체형 `BotHandler` 계약으로 감싸는 adapter다."""

    def __init__(self, module: ModuleType | Any, definition: BotDefinition | None = None) -> None:
        self.module = module
        self._definition = definition

    def get_definition(self) -> BotDefinition:
        if self._definition is not None:
            return self._definition
        return BotDefinition.model_validate(self.module.get_bot_definition())

    def initialize(self, runtime: BotRuntime) -> None:
        initialize = getattr(self.module, "initialize", None)
        if callable(initialize):
            initialize(runtime)

    def can_handle(self, context: ChatContext) -> bool:
        return bool(self.module.can_handle(context))

    def handle(self, context: ChatContext) -> ChatDecision:
        return ChatDecision.model_validate(self.module.handle(context))

    def shutdown(self) -> None:
        shutdown = getattr(self.module, "shutdown", None)
        if callable(shutdown):
            shutdown()

    def on_error(self, context: ChatContext, exc: Exception) -> ChatDecision:
        on_error = getattr(self.module, "on_error", None)
        if callable(on_error):
            return ChatDecision.model_validate(on_error(context, exc))
        return ChatDecision.pass_("legacy error")
