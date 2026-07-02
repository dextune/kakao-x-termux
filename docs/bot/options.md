# 옵션 스키마

봇 옵션은 `default_options`와 `option_schema`로 선언한다. 로더는 schema 구조를 검증하고, 운영 API는 실제 저장 값을 schema로 검증한다.

## 병합 순서

```text
BotDefinition.defaultOptions
-> chatbot_modules.options_json
-> room_bot_options.options_json
```

방별 옵션이 가장 강하다.

## 선언 예

```python
class VoiceBot(CommandBot):
    key = "voice_bot"
    command = "/voice"

    default_options = {
        "rate": 1.2,
        "pitch": 1.0,
        "maxTextChars": 300,
    }
    option_schema = {
        "rate": {
            "type": "number",
            "default": 1.2,
            "min": 0.1,
            "max": 4.0,
            "description": "TTS 속도.",
        },
        "pitch": {
            "type": "number",
            "default": 1.0,
            "min": 0.1,
            "max": 4.0,
            "description": "TTS pitch.",
        },
        "maxTextChars": {
            "type": "integer",
            "default": 300,
            "min": 1,
            "max": 1000,
            "description": "읽을 최대 글자 수.",
        },
    }
```

`default_options`의 값과 schema의 `default` 값이 다르면 로딩 실패로 처리된다.

## 지원 타입

| type | 허용 Python 값 |
| --- | --- |
| `string` | `str` |
| `integer` | `int`, 단 `bool` 제외 |
| `number` | `int | float`, 단 `bool` 제외 |
| `boolean` | `bool` |
| `array` | `list` |
| `object` | `dict` |

## Schema field

| field | 타입 | 설명 |
| --- | --- | --- |
| `type` | `str` | 필수. 지원 타입 중 하나 |
| `default` | any | 선택. 기본값 |
| `min` | `int | float` | 숫자 최소값 |
| `max` | `int | float` | 숫자 최대값 |
| `choices` | `list` | 허용 값 목록 |
| `nullable` | `bool` | `None` 허용 여부 |
| `description` | `str` | 운영 UI/API 설명 |

## 공통 옵션

모든 객체형 봇에는 아래 schema가 자동 추가된다.

| 옵션 | 타입 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `replyRateLimitMillis` | `integer` | `0` | 봇별 답장 간격 제한. 0이면 제한 없음 |
| `replyRateLimitScope` | `string` | `room` | `global`, `room`, `sender` 중 하나 |

이 옵션은 시스템 기본 전송 간격을 바꾸지 않는다. 해당 봇에 명시된 경우에만 reply decision 처리 시 적용된다.

## 운영 API

전역 옵션 변경:

```bash
curl -s -X POST http://127.0.0.1:8787/chatbot/modules/help_bot \
  -H 'content-type: application/json' \
  -d '{"enabled":true,"options":{"replyRateLimitMillis":50},"token":"shared-secret"}'
```

방별 옵션 변경:

```bash
curl -s -X POST http://127.0.0.1:8787/chatbot/rooms/room_a/modules/rate_limit_bot \
  -H 'content-type: application/json' \
  -d '{"enabled":true,"options":{"applyToAllMessages":true},"token":"shared-secret"}'
```

아래 요청은 거부된다.

- schema에 없는 옵션.
- 타입이 맞지 않는 값.
- `min`/`max` 범위를 벗어난 값.
- `choices`에 없는 값.
- `nullable=false`인 옵션의 `null`.

## 코드에서 조회

```python
timeout = self.float_option(context, "timeoutSeconds", 10.0, min_value=1.0, max_value=120.0)
enabled = self.bool_option(context, "enabled", True)
items = self.list_option(context, "items", [])
```

직접 `context.botOptions`를 읽을 수 있지만, 타입 변환과 기본값 처리는 helper를 우선 사용한다.
