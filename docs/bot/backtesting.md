# Python 채팅 백테스트

이 문서는 PC-only 통합 테스트로 올라가기 전에 `kakao-termux-back`의 Python pytest 안에서 실제 채팅에 가까운 봇 대화를 검증하는 방법을 정리한다. AI agent가 새 봇을 만들 때는 가능하면 직접 handler를 호출하지 말고 `ChatBacktest`로 `/events` 경로를 타게 만든다.

## 목적

`ChatBacktest`는 실제 FastAPI app, SQLite DB, chatbot loader, matcher, option store, state store를 사용한다. 따라서 봇 코드만 따로 호출하는 단위 테스트보다 실제 구동과 가까운 문제를 잡을 수 있다.

검증 대상:

- 여러 사용자가 같은 방에서 대화할 때 sender별 state가 분리되는지.
- 같은 사용자가 여러 방에서 대화할 때 roomKey별 state가 분리되는지.
- 여러 턴으로 진행되는 예약, 접수, 확인, 취소 흐름이 끝까지 동작하는지.
- eventId 중복, 잘못된 입력, 중간 취소, reload 후 상태 유지가 안전한지.
- 운영형 `memory_queue` 모드에서 큐 수락, DB 저장, 처리 완료, chatbot run 기록이 남는지.

## 기본 사용법

```python
def test_my_bot_chat_flow(chat_backtest):
    chat_backtest.disable_bots("ai_chatbot", "cooldown_bot")
    room = chat_backtest.room("room_my_bot", room="테스트방", sender="사용자A")

    room.send("/명령").expect_reply_contains("첫 질문")
    room.send("첫 답변").expect_reply_contains("두 번째 질문")
    room.send("완료").expect_reply_contains("처리 완료")
```

`chat_backtest`는 기본 `inline_wait` 프로파일이다. 실제 `/events` 응답의 `action`, `text`, `error`를 바로 검증할 수 있으므로 봇 대화 내용 검증의 기준으로 사용한다.

## 다중 사용자와 다중 방

```python
def test_sender_and_room_are_isolated(chat_backtest):
    chat_backtest.disable_bots("ai_chatbot", "cooldown_bot")
    room = chat_backtest.room("room_reservation", sender="사용자A")

    room.send("/예약").expect_reply_contains("예약 날짜")
    room.as_sender("사용자B").send("/예약확인").expect_reply_equals("현재 확인 가능한 예약이 없습니다.")

    other_room = room.in_room("room_reservation_other")
    other_room.send("/예약확인").expect_reply_equals("현재 확인 가능한 예약이 없습니다.")
```

AI agent가 사용자별 CRUD 봇을 만들 때는 최소한 다음을 검증한다.

- 사용자 A가 만든 데이터는 사용자 A에게 조회된다.
- 사용자 B에게는 사용자 A의 데이터가 조회 또는 취소되지 않는다.
- 같은 sender 이름이라도 다른 roomKey이면 데이터가 섞이지 않는다.

## 상태와 실행 로그 검증

```python
def test_state_and_run_log(chat_backtest):
    chat_backtest.disable_bots("ai_chatbot", "cooldown_bot")
    room = chat_backtest.room("room_stateful", sender="사용자A")

    turn = room.send("/예약도움말").expect_reply_contains("식당 예약 명령")

    runs = chat_backtest.runs(event_id=turn.event_id, bot_key="restaurant_reservation_bot")
    assert len(runs) == 1

    state = chat_backtest.state("restaurant_reservation_bot", "room_stateful", "reservations")
    assert state == {}
```

state key는 `bot_key|room_key|sender|name` 규칙을 사용한다. room scope state는 `sender=None`으로 조회한다.

## 중복 이벤트와 실패 입력

```python
def test_duplicate_event(chat_backtest):
    room = chat_backtest.room("room_dup", sender="사용자A")

    room.send("/예약도움말", event_id="dup_evt").expect_reply_contains("식당 예약 명령")
    room.send("/예약도움말", event_id="dup_evt").expect_action("none").expect_error_contains("duplicate eventId")
```

상태형 봇은 다음 실패 입력을 함께 검증한다.

- 잘못된 날짜, 시간, 숫자, 선택지 입력.
- 중간 `취소`, `그만`, `중단`.
- 이미 완료 또는 취소된 항목 재취소.
- 존재하지 않는 id 조회/취소.

## 운영형 memory_queue 프로파일

`memory_chat_backtest`는 운영형 큐 경로를 검증한다.

```python
import pytest


@pytest.mark.memory_backtest
def test_memory_queue_profile(memory_chat_backtest):
    memory_chat_backtest.disable_bots("ai_chatbot", "cooldown_bot")
    room = memory_chat_backtest.room("room_memory", sender="사용자A")

    turn = room.send("/예약도움말").expect_action("queued")

    memory_chat_backtest.wait_for_message_processed(turn.event_id)
    run = memory_chat_backtest.wait_for_run(event_id=turn.event_id, bot_key="restaurant_reservation_bot")
    assert run["action"] == "reply"
```

`memory_queue`에서는 `/events`가 즉시 답장 본문을 반환하지 않고 `queued`를 반환한다. 따라서 답장 문구 검증은 `chat_backtest`에서 하고, 운영형 큐 검증은 처리 완료와 실행 로그를 기준으로 한다.

## 새 봇 개발 시 최소 백테스트

AI agent는 새 봇을 추가할 때 아래 케이스를 기본으로 만든다.

- 성공 대화: 대표 명령이 끝까지 완료된다.
- 비대상 입력: 해당 봇이 처리하지 않을 입력은 fallback 또는 none 정책과 충돌하지 않는다.
- 다중 사용자: 같은 roomKey에서 sender별 데이터가 섞이지 않는다.
- 다중 방: 같은 sender라도 roomKey별 데이터가 섞이지 않는다.
- 실패 입력: 잘못된 값 입력 후 같은 step이 유지된다.
- 취소: 진행 중 세션이 명시적으로 종료된다.
- 중복 eventId: 저장/응답/state가 중복 생성되지 않는다.
- reload/state: 확정된 영속 state가 reload 후에도 유지된다.
- 옵션 override: module 또는 room option이 실제 운영 API로 반영된다.
- memory_queue: 운영형 큐 프로파일에서 processed와 chatbot run이 남는다.

## 실행 명령

```bash
cd kakao-termux-back
. ../.venv/bin/activate
python -m pytest -q tests/backtest
python -m pytest -q -m memory_backtest
python -m pytest
```

## 작성 원칙

- 직접 `bot.run()`이나 내부 handler를 호출하지 않는다. 특별한 단위 테스트가 아니면 `/events`를 경유한다.
- AI, cooldown, fallback처럼 결과를 간섭할 수 있는 봇은 테스트 시작 시 명시적으로 enable/disable한다.
- 외부 HTTP, LLM, Termux command는 mock/stub으로 대체하되 `/events` 진입점은 유지한다.
- 개인정보, 전화번호, token이 로그나 fixture에 과도하게 남지 않는지 확인한다.
- 실패 메시지가 충분히 읽히도록 `ChatBacktest` transcript를 사용한다.
