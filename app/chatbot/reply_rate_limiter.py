from __future__ import annotations

import threading
import time
from collections.abc import Callable


class ReplyRateLimiter:
    """봇별 opt-in 답장 간격을 프로세스 메모리에서 관리한다.

    기본 시스템 전송 경로에는 지연을 넣지 않고, 봇 옵션으로 명시한 경우에만
    bot/room/sender scope별 다음 발송 가능 시각을 예약한다.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or time.sleep
        self._lock = threading.Lock()
        self._next_at: dict[str, float] = {}

    def wait(
        self,
        *,
        bot_key: str,
        room_key: str,
        sender: str | None,
        interval_millis: int,
        scope: str = "room",
    ) -> int:
        """다음 답장 slot까지 필요한 만큼 대기하고 실제 대기 ms를 반환한다."""

        if interval_millis <= 0:
            return 0
        interval_seconds = interval_millis / 1000
        key = self._key(bot_key=bot_key, room_key=room_key, sender=sender, scope=scope)
        with self._lock:
            now = self._clock()
            next_at = self._next_at.get(key, 0.0)
            wait_seconds = max(next_at - now, 0.0)
            self._next_at[key] = max(now, next_at) + interval_seconds
        if wait_seconds > 0:
            self._sleeper(wait_seconds)
        return int(wait_seconds * 1000)

    def clear(self) -> None:
        """테스트와 reload 경계에서 예약 상태를 비운다."""

        with self._lock:
            self._next_at.clear()

    def _key(self, *, bot_key: str, room_key: str, sender: str | None, scope: str) -> str:
        if scope == "global":
            return f"{bot_key}|*|*"
        if scope == "sender":
            return f"{bot_key}|{room_key}|{sender or '_'}"
        return f"{bot_key}|{room_key}|*"
