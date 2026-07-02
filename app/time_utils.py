from __future__ import annotations
from time import time


def now_millis() -> int:
    """현재 시각을 epoch millis 정수로 반환한다."""

    return int(time() * 1000)
