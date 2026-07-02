# Bot Example: Command

명령형 봇은 사용자가 `/command args` 형태로 직접 호출하는 기능에 적합하다. 조회, 등록, 변환, 도움말처럼 입력과 응답이 한 번에 끝나는 작업에 사용한다.

## 폴더 구조

```text
app/bots/lookup-bot/
  bot.py
  bot.md
```

## `bot.py`

```python
from __future__ import annotations

from app.chatbot.base_bot import CommandBot
from app.chatbot.context import ChatContext
from app.chatbot.decision import ChatDecision


class LookupBot(CommandBot):
    """`/lookup 값` 명령을 처리하는 명령형 봇이다."""

    key = "lookup_bot"
    name = "Lookup Bot"
    version = "0.1.0"
    description = "사용자가 입력한 값을 조회 형식으로 확인한다."
    command = "/lookup"
    aliases = ["/조회"]
    priority = 100

    def handle_command(self, context: ChatContext) -> ChatDecision:
        query = context.args.strip()
        if not query:
            return self.reply("조회할 값을 함께 입력해주세요. 예: /lookup 주문123")
        return self.reply(f"조회 요청을 받았습니다: {query}")


def create_bot() -> LookupBot:
    """로더가 사용할 봇 인스턴스를 생성한다."""

    return LookupBot()
```

## `bot.md`

```md
# Lookup Bot

## 목적
사용자가 명령 뒤에 입력한 조회어를 확인하고 조회 요청 접수 문구를 반환한다.

## 명령어/트리거
- 명령어: `/lookup`, `/조회`
- 자동 트리거: 없음
- matcher: command

## 입력
`/lookup 조회어` 형식의 텍스트 메시지를 받는다.

## 출력
조회어가 있으면 접수 문구를 reply한다. 조회어가 없으면 사용법을 reply한다.

## 옵션
| 이름 | 타입 | 기본값 | 설명 |
| --- | --- | --- | --- |

## 상태
저장하는 state/session key가 없다.

## 외부 의존성
없음.

## 실패 조건
조회어가 없으면 사용법 안내를 반환한다.

## 테스트
`/lookup 주문123`은 reply를 반환하고, `/lookup`은 사용법을 반환한다.
```

## 테스트 포인트

- `/lookup 주문123`이 reply를 반환한다.
- `/조회 주문123` alias가 같은 결과를 반환한다.
- `/lookup`처럼 인자가 없을 때 사용법을 반환한다.
- unrelated command는 이 봇이 처리하지 않는다.
