from __future__ import annotations

from pathlib import Path

from app import repository
from app.config import get_settings
from app.chatbot.service import ChatbotService


class OperationsService:
    """운영/진단 API 응답 조립을 담당한다."""

    def __init__(self, chatbot_service: ChatbotService) -> None:
        self.chatbot_service = chatbot_service

    def list_modules(self, include_file_details: bool = False, file_status: str | None = None, limit: int = 100) -> dict:
        definitions = {bot.definition.key: bot.definition for bot in self.chatbot_service.registry.all()}
        file_rows = (
            self.chatbot_service.module_files(status=file_status, limit=limit)
            if include_file_details
            else []
        )
        files_by_key = {row["botKey"]: row for row in file_rows if row["botKey"]}
        modules = []
        for row in repository.list_chatbot_modules(limit=limit):
            definition = definitions.get(row["bot_key"])
            file_row = files_by_key.get(row["bot_key"])
            item = {
                "key": row["bot_key"],
                "name": row["name"],
                "version": row["version"],
                "enabled": bool(row["enabled"]),
                "commands": definition.commands if definition is not None else [],
                "matchMode": definition.matchMode if definition is not None else None,
                "optionSchema": definition.optionSchema if definition is not None else {},
                "priority": row["priority"],
                "loaded": definition is not None,
                "lastError": row["last_error"] if include_file_details else None,
            }
            if include_file_details:
                item.update(
                    {
                        "status": file_row["status"] if file_row else ("loaded" if definition is not None else "unknown"),
                        "sourcePath": file_row["path"] if file_row else None,
                        "sizeBytes": file_row["sizeBytes"] if file_row else None,
                        "mtimeNs": file_row["mtimeNs"] if file_row else None,
                    }
                )
            modules.append(item)
        response = {"modules": modules}
        if include_file_details:
            response["files"] = file_rows
        return response

    def module_document(self, bot_key: str) -> dict | None:
        """봇 패키지의 bot.md 문서를 운영 화면 표시용으로 반환한다."""

        module = repository.get_chatbot_module(bot_key)
        file_row = repository.get_chatbot_module_file_by_key(bot_key)
        if module is None or file_row is None or file_row["status"] != "loaded":
            return None

        settings = get_settings()
        bot_root = self._resolve_bot_root(Path(settings.chatbot_bot_dir)).resolve()
        bot_py = Path(file_row["path"])
        if not bot_py.is_absolute():
            bot_py = bot_root / bot_py
        bot_py = bot_py.resolve()
        markdown_path = (bot_py.parent / "bot.md").resolve()

        if not self._is_relative_to(markdown_path, bot_root):
            raise ValueError("bot document path escapes bot directory")
        if not markdown_path.exists() or not markdown_path.is_file():
            return None

        size_bytes = markdown_path.stat().st_size
        if size_bytes > settings.chatbot_max_bot_file_bytes:
            raise ValueError("bot document is too large")

        try:
            markdown = markdown_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("bot document must be UTF-8") from exc

        definition = self.chatbot_service.registry.get(bot_key)
        return {
            "key": bot_key,
            "name": module["name"],
            "version": module["version"],
            "loaded": definition is not None,
            "markdown": markdown,
            "sizeBytes": size_bytes,
            "updatedAt": int(markdown_path.stat().st_mtime * 1000),
        }

    def list_runs(self, event_id: str | None = None, bot_key: str | None = None, limit: int = 100) -> dict:
        rows = repository.list_chatbot_runs(event_id=event_id, bot_key=bot_key, limit=limit)
        return {
            "runs": [
                {
                    "eventId": row["event_id"],
                    "botKey": row["bot_key"],
                    "action": row["action"],
                    "reason": row["reason"],
                    "durationMs": row["duration_ms"],
                    "error": row["error"],
                    "createdAt": row["created_at"],
                }
                for row in rows
            ]
        }

    def list_states(
        self,
        bot_key: str | None = None,
        room_key: str | None = None,
        limit: int = 100,
        include_raw: bool = False,
    ) -> dict:
        self.chatbot_service.state_store.flush_dirty()
        rows = repository.list_bot_states(bot_key=bot_key, room_key=room_key, limit=limit)
        states = []
        for row in rows:
            state_json = row["state_json"]
            item = {
                "stateKey": row["state_key"],
                "roomKey": row["room_key"],
                "sender": row["sender"],
                "botKey": row["bot_key"],
                "stateBytes": len(state_json.encode("utf-8")),
                "expiresAt": row["expires_at"],
                "updatedAt": row["updated_at"],
                "state": state_json if include_raw else "<redacted>",
            }
            states.append(item)
        return {"states": states}

    @staticmethod
    def _resolve_bot_root(path: Path) -> Path:
        if path.exists():
            return path
        if str(path) == "app/bots":
            return Path(__file__).resolve().parents[1] / "bots"
        return path

    @staticmethod
    def _is_relative_to(path: Path, base: Path) -> bool:
        try:
            path.relative_to(base)
            return True
        except ValueError:
            return False
