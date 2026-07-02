# 런타임과 생명주기

챗봇 런타임은 loader, registry, processor, state store, option store로 구성된다.

## State store 생명주기

봇 state store는 메모리 캐시와 SQLite `chatbot_states` checkpoint로 구성된다.

1. 서버 startup에서 `MEMORY_STATE_WARMUP_ENABLED=true`이면 만료되지 않은 최신 state snapshot을 SQLite에서 memory cache로 올린다.
2. 봇이 `StatefulBot.set_state()`, `update_state()`, session helper 또는 `runtime.stateStore`를 호출하면 memory cache가 먼저 갱신된다.
3. dirty state는 `MEMORY_STATE_FLUSH_INTERVAL_MS` 주기나 명시 flush에서 SQLite writer로 checkpoint된다.
4. 서버 shutdown에서는 남은 dirty state를 flush한 뒤 종료한다.

따라서 checkpoint된 state는 백엔드 재시작, Termux 재시작, 휴대폰 재부팅 후에도 유지된다. 단, TTL 만료, DB 파일 삭제, Termux 앱 데이터 삭제, 강제 종료 직전 아직 flush되지 않은 dirty state는 복구 대상이 아니다.

## 로딩 순서

로더는 각 `app/bots/{bot}/bot.py`에 대해 다음 순서로 처리한다.

1. `bot.py`와 `bot.md` 존재 여부 확인.
2. 폴더명이 kebab-case인지 확인.
3. 파일 크기 제한 확인.
4. `bot.py`를 동적 import.
5. `create_bot()` 호출.
6. 반환 객체가 `BotHandler` 계약을 만족하는지 확인.
7. `handler.get_definition()` 호출.
8. `BotDefinition` 검증.
9. option schema 구조와 default 충돌 검증.
10. `BotRuntime` 생성.
11. `handler.initialize(runtime)` 호출.
12. registry에 등록.
13. `chatbot_modules`, `chatbot_module_files`에 로딩 상태 기록.

## 실행 순서

`/events`로 메시지가 들어오면 processor는 등록된 봇을 priority 순서로 평가한다.

1. room rule과 chatbot enabled 상태 확인.
2. 전역/방별 옵션 row 조회 또는 config cache 조회.
3. 봇별 활성 상태와 priority 계산.
4. fallback이 아닌 봇 먼저 실행.
5. 각 봇의 `patterns`를 matcher registry로 평가.
6. `bot.can_handle(context)` 호출.
7. `bot.handle(context)` 또는 subclass 실행 메서드 호출.
8. 반환값을 `ChatDecision`으로 검증.
9. reply text 길이 제한과 `replyRateLimitMillis` opt-in 적용.
10. run log 저장.
11. terminal 정책에 따라 후속 봇 실행 여부 결정.
12. 처리된 봇이 없으면 fallback 봇 평가.

## 오류 처리

봇 실행 중 예외가 발생하면 processor는 다음을 수행한다.

- chatbot run log에 `error` 기록.
- bridge log에 ERROR 기록.
- 봇에 `on_error(context, exc)`가 있으면 호출.
- `on_error()`가 non-pass decision을 반환하면 해당 decision을 사용.
- `on_error()`도 실패하면 다음 후보로 넘어간다.

기본 `BaseBot.on_error()`는 ERROR 로그를 남기고 `pass_("error")`를 반환한다.

## Hot Reload

hot reload snapshot은 `bot.py`와 `bot.md`를 함께 포함한다. 둘 중 하나라도 변경되면 reload 대상이 된다.

| 변경 | 동작 |
| --- | --- |
| 새 폴더 추가 | `bot.py`와 `bot.md`가 모두 있으면 로드 |
| `bot.py` 수정 | 새 handler가 정상 로드되면 registry 교체 |
| `bot.md` 수정 | 코드가 같아도 reload 대상 |
| 수정본 import 실패 | 기존 정상 handler 유지, 파일 상태 failed |
| key 변경 | 이전 key unregister, 새 key 등록 |
| duplicate key | 후보 봇 failed, 기존 봇 유지 |
| 폴더 삭제 | registry에서 제거, 파일 상태 removed |
| `bot.py` 또는 `bot.md` 누락 | failed 기록 |

## 종료 순서

서버 종료 또는 reload로 봇이 교체될 때 기존 handler의 `shutdown()`이 호출된다. 리소스를 직접 열었다면 `on_shutdown()`에서 닫아야 한다.

```python
class ResourceBot(CommandBot):
    key = "resource_bot"
    command = "/resource"

    def on_initialize(self, runtime) -> None:
        self._ready = True

    def on_shutdown(self) -> None:
        self._ready = False
```
