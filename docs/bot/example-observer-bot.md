# Bot Example: Observer

관찰형 봇은 메시지를 넓게 관찰하되 필요할 때만 응답하는 기능에 적합하다. 키워드 알림, 자연어 자동응답, 통계 수집, 안전 필터에 사용한다.

## 폴더 구조

```text
app/bots/mention-help-bot/
  bot.py
  bot.md
```

## `bot.py`

```python
from __future__ import annotations

from app.chatbot.base_bot import ObserverBot
from app.chatbot.context import ChatContext
from app.chatbot.decision import ChatDecision
from app.chatbot.module import MatchPattern


class MentionHelpBot(ObserverBot):
    """호출어가 포함된 일반 메시지에만 안내 답장을 반환한다."""

    key = "mention_help_bot"
    name = "Mention Help Bot"
    version = "0.1.0"
    description = "일반 메시지에서 도움 요청 호출어를 감지한다."
    patterns = [MatchPattern(type="mention", value=["봇아", "도움"])]
    priority = 300
    terminal = True
    default_options = {"replyText": "무엇을 도와드릴까요?"}
    option_schema = {
        "replyText": {
            "type": "string",
            "default": "무엇을 도와드릴까요?",
            "description": "호출어 감지 시 반환할 문구.",
        }
    }

    def can_handle(self, context: ChatContext) -> bool:
        if self.skip_command(context):
            return False
        return context.replyToken is not None

    def run(self, context: ChatContext) -> ChatDecision:
        reply_text = self.str_option(context, "replyText", "무엇을 도와드릴까요?")
        return self.reply(reply_text, reason="mention matched")


def create_bot() -> MentionHelpBot:
    """로더가 사용할 봇 인스턴스를 생성한다."""

    return MentionHelpBot()
```

## `bot.md`

```md
# Mention Help Bot

## 목적
일반 메시지에서 호출어를 감지해 도움 안내 문구를 반환한다.

## 명령어/트리거
- 명령어: 없음
- 자동 트리거: `봇아`, `도움` mention
- matcher: mention

## 입력
명령어가 아닌 일반 텍스트 메시지를 받는다.

## 출력
호출어가 있으면 replyText 옵션 문구를 reply한다.

## 옵션
| 이름 | 타입 | 기본값 | 설명 |
| --- | --- | --- | --- |
| replyText | string | 무엇을 도와드릴까요? | 호출어 감지 시 반환할 문구 |

## 상태
저장하는 state/session key가 없다.

## 외부 의존성
없음.

## 실패 조건
reply token이 없거나 명령 메시지이면 처리하지 않는다.

## 테스트
일반 mention 메시지는 reply하고 `/help` 같은 명령은 처리하지 않는지 검증한다.
```

## 테스트 포인트

- `봇아 도와줘`가 reply를 반환한다.
- `/help` 같은 command는 처리하지 않는다.
- 옵션 `replyText` override가 반영된다.
- 너무 넓은 observer가 fallback보다 먼저 모든 메시지를 가로채지 않는지 확인한다.
