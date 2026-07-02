from __future__ import annotations

from typing import Any

from app import repository
from app.infra.runtime_resources import get_runtime_resources


def update_chatbot_module_config(
    bot_key: str,
    enabled: bool | None = None,
    priority: int | None = None,
    options: dict[str, Any] | None = None,
):
    """전역 챗봇 모듈 설정을 저장하고 memory config cache를 즉시 갱신한다.

    Args:
        bot_key: 갱신할 봇 식별자.
        enabled: 전역 활성화 여부. None이면 기존 값을 유지한다.
        priority: 실행 우선순위. None이면 기존 값을 유지한다.
        options: 병합할 전역 옵션 dict. None이면 기존 옵션을 유지한다.

    Returns:
        갱신된 DB row. 대상 봇이 없으면 None을 반환한다.
    """

    row = repository.update_chatbot_module_config(
        bot_key,
        enabled=enabled,
        priority=priority,
        options=options,
    )
    if row is not None:
        get_runtime_resources().config_cache.set_module_row(row)
    return row


def upsert_room_bot_options(
    room_key: str,
    bot_key: str,
    enabled: bool,
    options: dict[str, Any] | None = None,
):
    """방별 챗봇 옵션을 저장하고 해당 roomKey의 memory config cache를 갱신한다.

    Args:
        room_key: 카카오톡 방 식별자.
        bot_key: 갱신할 봇 식별자.
        enabled: 방별 활성화 여부.
        options: 방별 override 옵션 dict.

    Returns:
        저장된 room_bot_options DB row.
    """

    row = repository.upsert_room_bot_options(room_key, bot_key, enabled, options)
    get_runtime_resources().config_cache.set_room_option_row(row)
    return row
