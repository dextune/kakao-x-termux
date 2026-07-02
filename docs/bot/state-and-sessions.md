# 상태와 세션

상태는 JSON 직렬화 가능한 작은 dict로 유지한다. 원문 메시지 무제한 누적, 큰 binary 데이터, 외부 응답 전문 저장은 피한다.

## 영속성 범위

`StatefulBot`의 state/session helper로 저장한 값은 백엔드 SQLite의 `chatbot_states` 테이블에 checkpoint된다. DB 파일이 유지되고 TTL이 만료되지 않았으면 백엔드 프로세스 재시작, Termux 재시작, 휴대폰 재부팅 후에도 다시 조회할 수 있다.

기본 실행은 memory state cache를 먼저 갱신하고 dirty state를 SQLite writer로 flush한다. 기본 flush 간격은 `MEMORY_STATE_FLUSH_INTERVAL_MS=1000`이며, 정상 종료 시에도 남은 dirty state를 flush한다. 전원 차단이나 강제 종료가 state 갱신 직후 flush 전에 발생하면 마지막 변경분은 유실될 수 있다.

아래 경우에는 state가 유지되지 않거나 조회되지 않는다.

- `ttl_millis` 또는 `state_ttl_millis`로 지정한 만료 시각이 지났다.
- 백엔드 DB 파일(`BACKEND_DB_PATH`, 기본 `data/backend.sqlite3`)을 삭제했다.
- Termux 앱 데이터 또는 백엔드 설치 디렉터리를 삭제했다.
- state JSON이 `CHATBOT_MAX_STATE_BYTES` 기본 8192 bytes를 넘어 저장이 거부됐다.
- Python 인스턴스 변수나 전역 변수에만 보관하고 state helper로 저장하지 않았다.

봇이 임의 SQLite 테이블에 직접 CRUD하는 방식은 기본 계약이 아니다. 작은 봇별 비휘발성 자료는 state helper를 사용하고, 관계형 모델이나 대량 데이터가 필요하면 별도 repository/table을 추가한다.

## State key

`BaseBot.state_key()`는 봇 key, roomKey, sender, 이름을 조합한다.

```python
key = self.state_key(context, "profile", sender_scope=True)
```

형식은 내부 구현 세부지만, 의미상 아래 구성을 따른다.

```text
{bot_key}|{room_key}|{sender_or_}|{name}
```

sender별 상태는 `sender_scope=True`, 방 전체 상태는 `sender_scope=False`를 사용한다.

## 기본 state helper

```python
class CounterBot(StatefulBot):
    key = "counter_bot"
    command = "/count"
    state_ttl_millis = 86_400_000

    def handle_command(self, context):
        state = self.get_state(context, "counter")
        count = int(state.get("count", 0)) + 1
        self.set_state(context, {"count": count}, "counter")
        return self.reply(f"{count}회")
```

| helper | 설명 |
| --- | --- |
| `get_state(context, name=None, sender_scope=True)` | state dict 조회 |
| `set_state(context, value, name=None, ttl_millis=None, sender_scope=True)` | state 저장 또는 덮어쓰기 |
| `update_state(context, updater, name=None, ttl_millis=None, sender_scope=True)` | 기존 state를 읽고 갱신 함수 결과로 저장 |
| `clear_state(context, name=None, sender_scope=True)` | state 삭제 |

## TTL 기준

- 사용자 입력 대기 세션: 짧게. 예: 10분에서 30분.
- 방별 최근 목록: 업무 요구에 맞게. 예: 1일에서 7일.
- 운영 설정성 상태: 옵션이나 DB 설정을 우선 사용하고 state 저장은 신중히 사용.

TTL이 없으면 상태가 오래 남을 수 있다. stateful 봇은 명시 TTL을 권장한다.

TTL은 만료 시각을 SQLite row의 `expires_at`에 저장한다. 만료된 state는 조회 시 비어 있는 dict처럼 보이고, 주기 prune 또는 조회 경로에서 삭제된다. 장기 보관이 목적이면 TTL을 생략할 수 있지만, 개인정보나 원문 메시지를 장기 저장하지 않는다.

## 세션 helper

다단계 대화는 `StatefulBot` 세션 helper를 사용한다.

```python
class IntakeBot(StatefulBot):
    key = "intake_bot"
    command = "/intake"
    session_name = "intake"
    session_scope = "sender"
    session_ttl_millis = 30 * 60 * 1000

    def can_handle(self, context):
        return context.command == "/intake" or self.has_session(context)

    def run(self, context):
        if context.command == "/intake":
            self.start_session(context, "detail")
            return self.reply("요청 내용을 입력해주세요.")

        session = self.get_session(context)
        if session.get("step") == "detail":
            self.advance_session(context, "confirm", {"detail": context.normalizedText})
            return self.reply("접수할까요? 네/아니오")

        if session.get("step") == "confirm" and context.normalizedText == "네":
            self.end_session(context)
            return self.reply("접수했습니다.")

        self.end_session(context)
        return self.reply("접수를 취소했습니다.")
```

| helper | 설명 |
| --- | --- |
| `session_state_key(context, name=None, scope=None)` | 세션 key 생성 |
| `get_session(context, name=None, scope=None)` | 세션 조회 |
| `has_session(context, name=None, scope=None)` | 세션 존재 여부 |
| `start_session(context, step, payload=None, name=None, scope=None, ttl_millis=None)` | 세션 시작 |
| `advance_session(context, step, patch=None, name=None, scope=None, ttl_millis=None)` | step 이동 |
| `update_session(context, updater, name=None, scope=None, ttl_millis=None)` | 세션 mutate |
| `end_session(context, name=None, scope=None)` | 세션 삭제 |

## 세션 설계 기준

- 시작 명령, 진행 중 입력, 취소 입력, 완료 입력을 모두 설계한다.
- 진행 중 세션에서 다른 `/` 명령이 들어오면 가능하면 `pass_()`로 넘긴다.
- sender별 입력 대기면 `session_scope="sender"`를 사용한다.
- 방 전체가 같은 흐름을 공유해야 할 때만 `session_scope="room"`을 사용한다.
- TTL 만료 후 입력이 들어오면 재시작 안내를 답장한다.
- 개인정보나 원문 대화 전체를 상태에 저장하지 않는다.
