from __future__ import annotations

import random
from typing import Any

from app.chatbot.base_bot import StatefulBot
from app.chatbot.context import ChatContext
from app.chatbot.decision import ChatDecision
from app.chatbot.module import MatchPattern


class RandomDrawBot(StatefulBot):
    """방 단위 추첨을 생성, 참여, 실행하는 StatefulBot이다.

    `/추첨 제목`으로 추첨을 생성하고 `/추첨 참여`로 참가자를 모은 뒤
    `/추첨 실행`으로 무작위 당첨자를 선정한다. 생성 후 5분 내에
    `/추첨 실행`하지 않으면 세션이 만료된다. 실행은 생성자만 가능하다.
    """

    key = "random_draw_bot"
    name = "Random Draw Bot"
    version = "0.1.0"
    description = "방 단위 추첨 생성, 참여, 무작위 당첨자 선정."
    match_mode = "stateful"
    commands = ["/추첨"]
    patterns = [
        MatchPattern(type="command", value="/추첨"),
    ]
    priority = 115
    session_name = "random_draw_session"
    session_scope = "room"
    session_ttl_millis = 5 * 60 * 1000
    default_options = {
        "drawTtlMillis": 5 * 60 * 1000,
    }
    option_schema = {
        "drawTtlMillis": {
            "type": "integer",
            "default": 300_000,
            "min": 60_000,
            "max": 600_000,
            "description": "추첨 세션 TTL. 기본 5분.",
        },
    }

    def can_handle(self, context: ChatContext) -> bool:
        return context.command in {"/추첨"}

    def run(self, context: ChatContext) -> ChatDecision:
        command = context.command

        if command == "/추첨":
            args = context.args.strip()
            if args in {"참여", "join"}:
                return self._handle_join(context)
            if args in {"실행", "execute", "draw"}:
                return self._handle_draw(context)
            return self._handle_create(context)

        return self.pass_(f"unknown command: {command}")

    def _handle_create(self, context: ChatContext) -> ChatDecision:
        existing = self.get_session(context)
        if existing:
            title = existing.get("title", "")
            return self.reply(f"이미 진행 중인 추첨이 있습니다: [{title}]")

        title = context.args.strip() or "추첨"
        creator = context.sender or "익명"
        now = self.runtime.nowMillis()
        self.start_session(context, "active", {
            "title": title,
            "creator": creator,
            "createdAt": now,
            "participants": [],
        })
        return self.reply(
            f"추첨 [{title}]이(가) 생성되었습니다!\n"
            f"/추첨 참여로 참가하고 /추첨 실행으로 추첨을 진행하세요. (5분 제한)"
        )

    def _handle_join(self, context: ChatContext) -> ChatDecision:
        session = self.get_session(context)
        if not session:
            return self.reply("진행 중인 추첨이 없습니다. /추첨으로 새 추첨을 생성해주세요.")

        sender = context.sender or "익명"
        title = session.get("title", "")
        existing_participants = session.get("participants", [])
        already_joined = any(p.get("name") == sender for p in existing_participants if isinstance(p, dict))

        if already_joined:
            count = len(existing_participants)
            return self.reply(f"{sender}님은 이미 참여 중입니다! (현재 {count}명)")

        def update(value: dict[str, Any]) -> dict[str, Any]:
            participants = list(value.get("participants", []))
            participants.append({"name": sender, "joinedAt": self.runtime.nowMillis()})
            value["participants"] = participants
            value["updatedAt"] = self.runtime.nowMillis()
            return value

        updated = self.update_session(context, update)
        count = len(updated.get("participants", []))
        return self.reply(f"{sender}님 참여 완료! (현재 {count}명)\n[{title}]")

    def _handle_draw(self, context: ChatContext) -> ChatDecision:
        session = self.get_session(context)
        if not session:
            return self.reply("진행 중인 추첨이 없습니다. /추첨으로 새 추첨을 생성해주세요.")

        creator = session.get("creator", "")
        sender = context.sender or ""
        if sender != creator:
            return self.reply(f"추첨은 생성자({creator})만 실행할 수 있습니다.")

        participants = [p for p in session.get("participants", []) if isinstance(p, dict)]
        if not participants:
            self.end_session(context)
            return self.reply("참여자가 없어 추첨을 실행할 수 없습니다. /추첨으로 새 추첨을 생성해주세요.")

        names = [p.get("name", "익명") for p in participants]
        winner = random.choice(names)
        title = session.get("title", "추첨")
        count = len(names)

        self.end_session(context)

        return self.reply(
            f"추첨 결과 [{title}]\n"
            f"참여: {count}명\n"
            f"🎉 당첨: {winner}님!"
        )


def create_bot() -> RandomDrawBot:
    """로더가 사용할 봇 인스턴스를 생성한다."""

    return RandomDrawBot()
