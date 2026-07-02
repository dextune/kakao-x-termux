# 빠른 시작

이 문서는 가장 작은 명령형 봇을 만들고 로딩과 테스트까지 확인하는 절차를 설명한다.

## 유형별 예시

처음 만들 봇의 성격이 정해져 있다면 아래 예시를 먼저 보는 것이 빠르다.

| 유형 | 예시 문서 | 사용 시점 |
| --- | --- | --- |
| 명령형 | [example-command-bot.md](example-command-bot.md) | `/lookup 값`처럼 한 번의 명령과 답장으로 끝나는 기능 |
| 상태형 | [example-stateful-bot.md](example-stateful-bot.md) | 여러 턴으로 입력을 받아 접수, 예약, 설문을 처리하는 기능 |
| 관찰형 | [example-observer-bot.md](example-observer-bot.md) | 일반 메시지를 관찰하다가 특정 조건에서만 답장하는 기능 |
| 외부 HTTP | [example-http-bot.md](example-http-bot.md) | 외부 API, 모델 서버, webhook 조회가 필요한 기능 |
| Termux command | [example-termux-command-bot.md](example-termux-command-bot.md) | Termux:API나 로컬 command를 실행하는 기능 |

## 1. 폴더 생성

```text
kakao-termux-back/app/bots/sample-bot/
  bot.py
  bot.md
```

폴더명은 kebab-case를 사용한다. 봇 key는 Python 코드 안에서 snake_case로 선언한다.

## 2. `bot.py` 작성

```python
from __future__ import annotations

from app.chatbot.base_bot import CommandBot
from app.chatbot.context import ChatContext
from app.chatbot.decision import ChatDecision


class SampleBot(CommandBot):
    """`/sample 값` 명령을 처리하는 예제 봇이다."""

    key = "sample_bot"
    name = "Sample Bot"
    version = "0.1.0"
    description = "샘플 명령을 처리한다."
    command = "/sample"
    aliases = ["/샘플"]
    priority = 100

    def handle_command(self, context: ChatContext) -> ChatDecision:
        value = context.args.strip()
        if not value:
            return self.reply("값을 함께 입력해주세요. 예: /sample hello")
        return self.reply(f"처리했습니다: {value}")


def create_bot() -> SampleBot:
    """로더가 사용할 봇 인스턴스를 생성한다."""

    return SampleBot()
```

## 3. `bot.md` 작성

```md
# Sample Bot

## 목적
샘플 명령 입력을 받아 확인 답장을 반환한다.

## 명령어/트리거
- 명령어: `/sample`, `/샘플`
- 자동 트리거: 없음
- matcher: command

## 입력
`/sample 값` 형식의 텍스트 메시지를 받는다.

## 출력
값이 있으면 처리 결과를 reply하고, 값이 없으면 사용법을 reply한다.

## 옵션
| 이름 | 타입 | 기본값 | 설명 |
| --- | --- | --- | --- |

## 상태
저장하는 state/session key가 없다.

## 외부 의존성
없음.

## 실패 조건
입력값이 없으면 사용법 안내를 답장한다.

## 테스트
`/sample hello`가 reply를 반환하는지 확인한다.
```

## 4. 컴파일과 로딩 확인

```bash
cd kakao-termux-back
. ../.venv/bin/activate
python -m compileall -q app/chatbot app/bots
python -m pytest tests/test_chatbot_module.py -q
```

서버 실행 중이면 수동 reload로 확인할 수 있다.

```bash
curl -s -X POST http://127.0.0.1:8787/chatbot/reload \
  -H 'content-type: application/json' \
  -d '{"token":"shared-secret"}'
```

모듈 목록에서 `loaded=true`인지 확인한다.

```bash
curl -s 'http://127.0.0.1:8787/chatbot/modules?token=shared-secret'
```

## 5. 작성 체크리스트

- `app/bots/{kebab-case}/bot.py`와 `bot.md`가 모두 있는가.
- `create_bot()`이 매번 새 봇 인스턴스를 반환하는가.
- `key`가 전역에서 유일한 snake_case인가.
- import 시점에 외부 I/O나 DB write가 없는가.
- `replyToken`이 없을 수 있는 경로를 고려했는가.
- 옵션이 있으면 `default_options`와 `option_schema`를 함께 선언했는가.
- 재시작 후 유지할 값은 `StatefulBot` state/session helper로 저장하고 `bot.md`에 scope와 TTL을 적었는가.
- 외부 I/O가 있으면 timeout과 실패 메시지가 있는가.
