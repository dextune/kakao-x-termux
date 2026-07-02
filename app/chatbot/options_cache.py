from __future__ import annotations

from typing import Any

from app.chatbot.options import BotOptionStore, _json_dict
from app.chatbot.registry import RegisteredBot


class BotOptionView:
    """요청 1건에서 사용하는 봇 옵션/활성화 lazy view다."""

    def __init__(
        self,
        module_rows: dict[str, Any],
        room_option_rows: dict[str, Any],
        option_store: BotOptionStore | None = None,
    ) -> None:
        self.module_rows = module_rows
        self.room_option_rows = room_option_rows
        self.option_store = option_store or BotOptionStore()
        self._options_cache: dict[str, dict[str, Any]] = {}

    def is_enabled(self, bot: RegisteredBot) -> bool:
        row = self.module_rows.get(bot.definition.key)
        if row is not None and not bool(row["enabled"]):
            return False
        room_row = self.room_option_rows.get(bot.definition.key)
        if room_row is not None and not bool(room_row["enabled"]):
            return False
        return True

    def priority(self, bot: RegisteredBot) -> int:
        row = self.module_rows.get(bot.definition.key)
        return int(row["priority"]) if row is not None else bot.definition.priority

    def options_for(self, bot: RegisteredBot) -> dict[str, Any]:
        cached = self._options_cache.get(bot.definition.key)
        if cached is not None:
            return dict(cached)
        options = dict(bot.definition.defaultOptions)
        row = self.module_rows.get(bot.definition.key)
        if row is not None:
            options.update(_json_dict(row["options_json"]))
        room_row = self.room_option_rows.get(bot.definition.key)
        if room_row is not None:
            options.update(_json_dict(room_row["options_json"]))
        self._options_cache[bot.definition.key] = options
        return dict(options)
