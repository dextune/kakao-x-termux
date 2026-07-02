# Bot Example: Termux Command

Termux command 봇은 Termux:API나 로컬 command를 실행해야 하는 기능에 적합하다. TTS, 진동, 카메라, 파일 처리, 로컬 스크립트 호출에 사용한다.

## 폴더 구조

```text
app/bots/vibrate-bot/
  bot.py
  bot.md
```

## `bot.py`

```python
from __future__ import annotations

from app.chatbot.base_bot import CommandBot
from app.chatbot.context import ChatContext
from app.chatbot.decision import ChatDecision
from app.chatbot.io_helpers import ExternalIOError


class VibrateBot(CommandBot):
    """Termux:API 진동 명령을 실행하는 봇이다."""

    key = "vibrate_bot"
    name = "Vibrate Bot"
    version = "0.1.0"
    description = "Termux:API 진동 명령을 실행한다."
    command = "/진동"
    priority = 80
    timeout_millis = 5_000
    default_options = {
        "durationMillis": 300,
        "timeoutSeconds": 5,
    }
    option_schema = {
        "durationMillis": {
            "type": "integer",
            "default": 300,
            "min": 100,
            "max": 5000,
            "description": "진동 지속 시간.",
        },
        "timeoutSeconds": {
            "type": "number",
            "default": 5,
            "min": 1,
            "max": 30,
            "description": "명령 실행 timeout.",
        },
    }

    def handle_command(self, context: ChatContext) -> ChatDecision:
        duration = self.int_option(context, "durationMillis", 300, min_value=100, max_value=5000)
        timeout_seconds = self.float_option(context, "timeoutSeconds", 5.0, min_value=1.0, max_value=30.0)
        try:
            self.termux_command(
                ["termux-vibrate", "-d", str(duration)],
                timeout_seconds=timeout_seconds,
                ref_id=context.eventId,
                error_prefix="진동 실행에 실패했습니다",
            )
        except FileNotFoundError:
            return self.reply("Termux:API 앱과 `pkg install termux-api` 설치를 확인해주세요.")
        except ExternalIOError:
            return self.reply("진동 실행 중 오류가 발생했습니다. 권한과 Termux:API 상태를 확인해주세요.")
        return self.reply("진동을 실행했습니다.")


def create_bot() -> VibrateBot:
    """로더가 사용할 봇 인스턴스를 생성한다."""

    return VibrateBot()
```

## `bot.md`

```md
# Vibrate Bot

## 목적
`/진동` 명령으로 Termux:API 진동 command를 실행한다.

## 명령어/트리거
- 명령어: `/진동`
- 자동 트리거: 없음
- matcher: command

## 입력
`/진동` 텍스트 메시지를 받는다.

## 출력
성공 시 `진동을 실행했습니다.`를 reply한다. command 실패 시 권한과 Termux:API 상태 확인 문구를 reply한다.

## 옵션
| 이름 | 타입 | 기본값 | 설명 |
| --- | --- | --- | --- |
| durationMillis | integer | 300 | 진동 지속 시간 |
| timeoutSeconds | number | 5 | 명령 실행 timeout |

## 상태
저장하는 state/session key가 없다.

## 외부 의존성
Termux:API 앱과 `termux-api` 패키지의 `termux-vibrate` 명령.

## 실패 조건
명령 없음, timeout, stderr 포함 실패를 사용자 친화 메시지로 변환한다.

## 테스트
`termux_command` helper를 monkeypatch해 command 인자와 실패 응답을 검증한다.
```

## 테스트 포인트

- `termux_command` monkeypatch로 `["termux-vibrate", "-d", "300"]` 인자를 검증한다.
- command 성공 시 reply를 반환한다.
- `FileNotFoundError`는 설치 안내 문구를 반환한다.
- `ExternalIOError`는 권한/상태 확인 문구를 반환한다.
- 사용자 입력을 shell string으로 조립하지 않는다.
