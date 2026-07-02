# Bot Example: HTTP

HTTP 봇은 외부 API나 모델 서버를 호출해야 하는 기능에 적합하다. LLM, 검색, 사내 API, webhook 조회에 사용한다.

## 폴더 구조

```text
app/bots/http-lookup-bot/
  bot.py
  bot.md
```

## `bot.py`

```python
from __future__ import annotations

from typing import Any

from app.chatbot.base_bot import CommandBot
from app.chatbot.context import ChatContext
from app.chatbot.decision import ChatDecision
from app.chatbot.io_helpers import ExternalIOError


class HttpLookupBot(CommandBot):
    """외부 HTTP API에 조회 요청을 보내는 봇이다."""

    key = "http_lookup_bot"
    name = "HTTP Lookup Bot"
    version = "0.1.0"
    description = "외부 HTTP API로 조회어를 전달하고 결과를 답장한다."
    command = "/외부조회"
    priority = 110
    timeout_millis = 10_000
    default_options = {
        "endpoint": "http://127.0.0.1:8080/lookup",
        "timeoutSeconds": 5,
        "maxReplyChars": 300,
    }
    option_schema = {
        "endpoint": {
            "type": "string",
            "default": "http://127.0.0.1:8080/lookup",
            "description": "조회 API endpoint.",
        },
        "timeoutSeconds": {
            "type": "number",
            "default": 5,
            "min": 1,
            "max": 60,
            "description": "HTTP 호출 timeout.",
        },
        "maxReplyChars": {
            "type": "integer",
            "default": 300,
            "min": 1,
            "max": 1000,
            "description": "답장 최대 글자 수.",
        },
    }

    def handle_command(self, context: ChatContext) -> ChatDecision:
        query = context.args.strip()
        if not query:
            return self.reply("조회할 값을 입력해주세요. 예: /외부조회 주문123")

        endpoint = self.str_option(context, "endpoint")
        timeout_seconds = self.float_option(context, "timeoutSeconds", 5.0, min_value=1.0, max_value=60.0)
        try:
            response = self.http_post_json(
                endpoint,
                {"query": query, "roomKey": context.roomKey},
                timeout_seconds=timeout_seconds,
                ref_id=context.eventId,
                error_prefix="http_lookup_bot backend unavailable",
            )
        except ExternalIOError:
            return self.reply("조회 서버 응답이 지연되고 있습니다. 잠시 후 다시 시도해주세요.")

        reply = self._extract_reply(response.json(), context)
        if not reply:
            return self.reply("조회 결과가 없습니다.")
        return self.reply(reply)

    def _extract_reply(self, data: Any, context: ChatContext) -> str:
        if not isinstance(data, dict):
            return ""
        value = str(data.get("message") or data.get("text") or "").strip()
        limit = self.int_option(context, "maxReplyChars", 300, min_value=1, max_value=1000)
        return value[:limit].rstrip()


def create_bot() -> HttpLookupBot:
    """로더가 사용할 봇 인스턴스를 생성한다."""

    return HttpLookupBot()
```

## `bot.md`

```md
# HTTP Lookup Bot

## 목적
명령 인자를 외부 HTTP API로 조회하고 결과 메시지를 반환한다.

## 명령어/트리거
- 명령어: `/외부조회`
- 자동 트리거: 없음
- matcher: command

## 입력
`/외부조회 조회어` 형식의 텍스트 메시지를 받는다.

## 출력
HTTP 응답의 `message` 또는 `text`를 reply한다. 결과가 없으면 안내 문구를 reply한다.

## 옵션
| 이름 | 타입 | 기본값 | 설명 |
| --- | --- | --- | --- |
| endpoint | string | http://127.0.0.1:8080/lookup | 조회 API endpoint |
| timeoutSeconds | number | 5 | HTTP 호출 timeout |
| maxReplyChars | integer | 300 | 답장 최대 글자 수 |

## 상태
저장하는 state/session key가 없다.

## 외부 의존성
HTTP JSON API.

## 실패 조건
HTTP timeout, queue full, status error는 사용자에게 조회 서버 지연 문구로 노출한다.

## 테스트
HTTP client를 monkeypatch해 성공 응답과 실패 응답을 검증한다.
```

## 테스트 포인트

- `httpClient.post` monkeypatch로 payload와 timeout을 검증한다.
- HTTP 200 응답의 `message`가 reply로 변환된다.
- `ExternalIOError` 경로에서 사용자 친화 실패 문구가 반환된다.
- endpoint, timeout, maxReplyChars 옵션 schema가 잘못된 값을 거부한다.
