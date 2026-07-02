from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol, runtime_checkable

from app.pydantic_compat import BaseModel, Field

from app.chatbot.context import ChatContext
from app.chatbot.decision import ChatDecision
from app.chatbot.state_store import BotStateStore


class MatchPattern(BaseModel):
    """봇 후보 감지에 사용할 구조화된 패턴 설정이다."""

    type: str
    value: str | list[str] | dict[str, Any]
    flags: list[str] = Field(default_factory=list)
    weight: int = 1
    confidence: float = 1.0
    options: dict[str, Any] = Field(default_factory=dict)


class BotDefinition(BaseModel):
    """로더가 검증하고 registry에 등록하는 봇 메타데이터다."""

    key: str
    name: str
    version: str
    description: str = ""
    matchMode: Literal["command", "pattern", "stateful", "scheduled", "event", "observer", "fallback"] = "command"
    commands: list[str] = Field(default_factory=list)
    patterns: list[MatchPattern] = Field(default_factory=list)
    priority: int = 100
    enabled: bool = True
    terminal: bool = True
    timeoutMillis: int = 3_000
    stateTtlMillis: int | None = None
    defaultOptions: dict[str, Any] = Field(default_factory=dict)
    optionSchema: dict[str, dict[str, Any]] = Field(default_factory=dict)
    matchPolicy: Literal["any", "all", "score", "custom"] = "any"
    matchThreshold: float = 1.0


@dataclass(frozen=True)
class BotRuntime:
    """봇 생명주기와 실행 시점에 전달되는 공통 런타임 handle이다."""

    botKey: str
    logger: logging.Logger
    stateStore: BotStateStore
    optionStore: Any
    nowMillis: Callable[[], int]
    messageStore: Any | None = None
    botRegistry: Any | None = None
    externalRunner: Any | None = None
    httpClient: Any | None = None


@runtime_checkable
class BotHandler(Protocol):
    """로더와 프로세서가 실행하는 객체형 봇 공통 계약이다."""

    def get_definition(self) -> BotDefinition:
        """봇 metadata와 matcher 설정을 반환한다."""
        ...

    def initialize(self, runtime: BotRuntime) -> None:
        """봇 실행에 필요한 runtime handle을 주입한다."""
        ...

    def can_handle(self, context: ChatContext) -> bool:
        """현재 메시지를 이 봇이 처리할 수 있는지 판단한다."""
        ...

    def handle(self, context: ChatContext) -> ChatDecision:
        """현재 메시지에 대한 봇 실행 결과를 반환한다."""
        ...

    def shutdown(self) -> None:
        """hot reload나 서버 종료 시 봇 리소스를 정리한다."""
        ...


class BotModule(Protocol):
    """동적 import된 봇 모듈이 제공해야 하는 함수 계약이다."""

    def get_bot_definition(self) -> BotDefinition:
        ...
