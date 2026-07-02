# Bot Example: Stateful

상태형 봇은 여러 메시지에 걸쳐 입력을 받는 기능에 적합하다. 예약 접수, 문의 등록, 설문, 확인/취소가 필요한 흐름에 사용한다.

## 폴더 구조

```text
app/bots/simple-intake-bot/
  bot.py
  bot.md
```

## `bot.py`

```python
from __future__ import annotations

from app.chatbot.base_bot import StatefulBot
from app.chatbot.context import ChatContext
from app.chatbot.decision import ChatDecision
from app.chatbot.module import MatchPattern


class SimpleIntakeBot(StatefulBot):
    """문의 내용을 두 단계로 접수하는 상태형 봇이다."""

    key = "simple_intake_bot"
    name = "Simple Intake Bot"
    version = "0.1.0"
    description = "문의 내용과 확인 응답을 받아 접수한다."
    match_mode = "stateful"
    commands = ["/문의"]
    patterns = [
        MatchPattern(type="command", value="/문의"),
        MatchPattern(type="state_exists", value={"name": "intake_session", "scope": "sender"}),
    ]
    priority = 120
    session_name = "intake_session"
    session_scope = "sender"
    session_ttl_millis = 30 * 60 * 1000
    default_options = {"maxDetailChars": 300}
    option_schema = {
        "maxDetailChars": {
            "type": "integer",
            "default": 300,
            "min": 20,
            "max": 1000,
            "description": "문의 내용 최대 길이.",
        }
    }

    def can_handle(self, context: ChatContext) -> bool:
        return context.command == "/문의" or self.has_session(context)

    def run(self, context: ChatContext) -> ChatDecision:
        if context.command == "/문의":
            detail = self._clean_detail(context.args, context)
            if detail:
                self.start_session(context, "confirm", {"detail": detail})
                return self.reply(f"아래 내용으로 접수할까요?\n{detail}\n네/아니오")
            self.start_session(context, "detail")
            return self.reply("문의 내용을 한 문장으로 입력해주세요. 취소하려면 '취소'라고 입력해주세요.")

        session = self.get_session(context)
        if not session:
            return self.pass_("session not found")
        if context.command is not None:
            return self.pass_("other command during session")
        if context.normalizedText in {"취소", "아니오", "아니"}:
            self.end_session(context)
            return self.reply("문의를 취소했습니다.")

        step = str(session.get("step", ""))
        if step == "detail":
            detail = self._clean_detail(context.normalizedText, context)
            if len(detail) < 2:
                return self.reply("문의 내용을 조금 더 구체적으로 입력해주세요.")
            self.advance_session(context, "confirm", {"detail": detail})
            return self.reply(f"아래 내용으로 접수할까요?\n{detail}\n네/아니오")

        if step == "confirm":
            if context.normalizedText not in {"네", "예", "응", "yes", "y"}:
                return self.reply("접수하려면 '네', 취소하려면 '아니오'라고 입력해주세요.")
            detail = str(session.get("detail", ""))
            ticket_id = f"INQ-{self.runtime.nowMillis()}"
            self.end_session(context)
            return self.reply(f"접수 완료: {ticket_id}\n내용: {detail}")

        self.end_session(context)
        return self.reply("진행 중인 문의 상태를 이해하지 못했습니다. /문의로 다시 시작해주세요.")

    def _clean_detail(self, value: str, context: ChatContext) -> str:
        limit = self.int_option(context, "maxDetailChars", 300, min_value=20, max_value=1000)
        text = " ".join(str(value or "").split())
        return text[:limit].rstrip()


def create_bot() -> SimpleIntakeBot:
    """로더가 사용할 봇 인스턴스를 생성한다."""

    return SimpleIntakeBot()
```

## `bot.md`

```md
# Simple Intake Bot

## 목적
사용자의 문의 내용을 여러 턴으로 받아 접수 완료 메시지를 반환한다.

## 명령어/트리거
- 명령어: `/문의`
- 자동 트리거: 진행 중인 sender session
- matcher: command, state_exists

## 입력
`/문의`로 시작한 뒤 문의 내용과 확인 응답을 순서대로 보낸다.

## 출력
단계별 안내를 reply하고, 확인되면 접수 번호와 내용을 reply한다.

## 옵션
| 이름 | 타입 | 기본값 | 설명 |
| --- | --- | --- | --- |
| maxDetailChars | integer | 300 | 문의 내용 최대 길이 |

## 상태
`simple_intake_bot|roomKey|sender|intake_session` 세션을 30분 TTL로 저장한다.

## 외부 의존성
없음.

## 실패 조건
취소 입력은 세션을 종료한다. 알 수 없는 단계는 세션을 종료하고 재시작 안내를 반환한다.

## 테스트
`/문의`, 내용 입력, `네` 확인 흐름과 취소 흐름을 검증한다.
```

## 테스트 포인트

- `/문의`가 세션을 시작한다.
- 다음 일반 메시지가 세션 입력으로 처리된다.
- `네` 입력이 접수 완료 reply를 반환한다.
- `취소` 입력이 세션을 종료한다.
- 진행 중 다른 `/` 명령은 `pass_()`로 넘긴다.
- reload 후에도 state store에 남은 세션이 이어진다.
