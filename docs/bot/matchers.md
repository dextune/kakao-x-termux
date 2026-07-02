# Matcher와 라우팅

Matcher는 processor가 `can_handle()`을 호출하기 전에 후보 봇을 줄이는 단계다. `patterns`가 비어 있으면 matcher 단계는 통과한다.

## MatchPattern

```python
from app.chatbot.module import MatchPattern

MatchPattern(
    type="command",
    value="/help",
    flags=[],
    weight=1,
    confidence=1.0,
    options={},
)
```

| field | 타입 | 설명 |
| --- | --- | --- |
| `type` | `str` | matcher 이름 |
| `value` | `str | list[str] | dict` | matcher 입력 |
| `flags` | `list[str]` | matcher별 옵션 flag |
| `weight` | `int` | score policy에서 가중치 |
| `confidence` | `float` | score policy에서 신뢰도 |
| `options` | `dict` | matcher별 세부 옵션 |

## Match policy

| policy | 의미 |
| --- | --- |
| `any` | pattern 중 하나라도 match되면 통과 |
| `all` | 모든 pattern이 match되어야 통과 |
| `score` | matched pattern의 `weight * confidence` 합이 threshold 이상이면 통과 |
| `custom` | matcher 결과와 무관하게 통과하고 `can_handle()`에서 직접 판단 |

## command

```python
patterns = [MatchPattern(type="command", value="/sample")]
```

`CommandBot`은 보통 이 pattern을 자동 생성하므로 직접 선언하지 않아도 된다.

## contains

```python
patterns = [MatchPattern(type="contains", value="상담")]
```

정규식이 필요 없는 단순 포함 검사에 사용한다.

## any_keywords

```python
patterns = [MatchPattern(type="any_keywords", value=["환불", "반품", "취소"])]
```

목록 중 하나라도 포함되면 match된다.

## all_keywords

```python
patterns = [MatchPattern(type="all_keywords", value=["상담", "필요"])]
```

목록 전체가 포함되어야 match된다.

## regex

```python
patterns = [MatchPattern(type="regex", value=r"(영업|운영).?시간")]
```

형태가 다양한 문장을 감지할 때 사용한다. 복잡한 정규식은 과도한 match를 만들 수 있으므로 테스트를 추가한다.

## starts_with / ends_with

```python
patterns = [MatchPattern(type="starts_with", value="공지")]
patterns = [MatchPattern(type="ends_with", value="?")]
```

고정 접두/접미 패턴에 사용한다.

## mention

```python
patterns = [MatchPattern(type="mention", value=["봇아", "관리자"])]
```

호출어 기반 자동 응답에 사용한다.

## state_exists

```python
patterns = [
    MatchPattern(type="state_exists", value={"name": "request_session", "scope": "sender"})
]
```

진행 중인 stateful 대화가 있을 때 다음 메시지를 후보로 올린다.

| value 형태 | 의미 |
| --- | --- |
| `"session"` | sender scope의 `session` state 확인 |
| `{"name": "session", "scope": "sender"}` | sender별 state 확인 |
| `{"name": "session", "scope": "room"}` | room별 state 확인 |
| `{"name": "session", "senderScope": false}` | room별 state 확인 |

## sender_rate / room_rate

```python
patterns = [MatchPattern(type="sender_rate", value={"windowMillis": 10_000, "limit": 5})]
patterns = [MatchPattern(type="room_rate", value={"windowMillis": 60_000, "limit": 100})]
```

rate matcher는 후보 감지만 수행한다. timestamp 저장, 경고 횟수, 사용자 응답 정책은 봇 본문에서 처리한다.

## fallback

```python
patterns = [MatchPattern(type="fallback", value="default")]
```

앞선 봇이 처리하지 않은 경우를 감지한다. fallback 봇은 일반 봇 평가 후 별도로 실행된다.

## Priority 권장 범위

| 범위 | 용도 |
| --- | --- |
| `1-49` | 안전, 차단, 운영 제어 |
| `50-199` | 명령형 사용자 기능 |
| `200-499` | 자연어 패턴, 자동 응답 |
| `500+` | fallback 또는 낮은 우선순위 기능 |
