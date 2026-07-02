# 응답과 발송

봇은 `ChatDecision`을 반환한다. processor는 이를 `/events` 응답 계약으로 변환한다.

## Decision helper

| helper | action | 설명 |
| --- | --- | --- |
| `self.reply(text, reason=None)` | `reply` | 현재 이벤트의 reply token으로 즉시 답장 |
| `self.queued(reason=None)` | `queued` | 작업을 접수했고 후속 처리가 예정됨 |
| `self.none(reason=None, terminal=True)` | `none` | 응답 없이 종료 |
| `self.pass_(reason=None)` | `pass` | 이 봇은 처리하지 않고 다음 후보 봇으로 이동 |

`pass`는 외부 API 응답으로 노출되지 않는 내부 action이다.

## 즉시 답장

```python
def handle_command(self, context):
    if not context.args:
        return self.reply("값을 입력해주세요.")
    return self.reply(f"처리했습니다: {context.args}")
```

`replyToken`이 없으면 최종 `/events` 응답은 `none`과 오류 사유로 변환된다. reply token이 없을 가능성이 큰 자동 작업은 `self.none()` 또는 `/send` helper 사용을 검토한다.

## pass와 fallback

외부 backend 실패나 대상이 아닌 입력은 `pass_()`로 넘기면 fallback 또는 다른 봇이 처리할 수 있다.

```python
if not self._looks_relevant(context):
    return self.pass_("not relevant")
```

## `/send` 기반 답장 helper

여러 메시지, 지연 발송, 최신 room token 선택이 필요한 경우 `/send` 계약을 직접 조립하지 말고 helper를 사용한다.

```python
response = self.send_reply(context, "첫 번째 안내")
```

```python
responses = self.send_replies(
    context,
    ["첫 번째 메시지", "두 번째 메시지"],
    dedupe_key_prefix=f"notice:{context.eventId}",
)
```

```python
return self.queue_reply(
    context,
    "잠시 후 보내는 메시지",
    delay_millis=3_000,
)
```

helper는 다음을 공통 처리한다.

- roomKey/room/text 구성.
- reply token 선택. 명시하지 않으면 현재 context token을 우선 사용한다.
- dedupe key 생성.
- `/send` service 호출.
- dispatch 실패 로그.

## Dedupe key

기본 dedupe key는 봇 key, eventId, text hash를 사용한다.

```python
dedupe = self.reply_dedupe_key(context, text, suffix="step-1")
```

반복 실행될 수 있는 지연 작업은 업무적으로 안정적인 key를 직접 지정하는 것이 좋다.

```python
self.send_reply(
    context,
    "접수 완료",
    dedupe_key=f"request:{ticket_id}:complete",
)
```

## Reply rate limit

시스템 기본 전송 간격은 `0ms`다. 봇별 제한은 옵션으로 opt-in한다.

```json
{
  "replyRateLimitMillis": 50,
  "replyRateLimitScope": "room"
}
```

scope:

- `global`: 봇 전체에서 간격 공유.
- `room`: 봇과 roomKey 단위.
- `sender`: 봇, roomKey, sender 단위.

## Terminal 정책

두 값이 모두 영향을 준다.

- `bot.definition.terminal`
- `decision.terminal`

non-pass decision이 terminal이면 후속 봇 실행을 멈춘다. 관찰형 봇은 기본적으로 `terminal=False`이므로 기록 후 `pass_()`를 반환하는 방식이 자연스럽다.
