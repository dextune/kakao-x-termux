# 봇 API 레퍼런스

이 문서는 봇 작성자가 사용하는 주요 Python API를 정리한다.

## BaseBot

`BaseBot`은 모든 객체형 봇의 공통 base class다.

### Metadata class fields

| field | 타입 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `key` | `str` | `""` | 전역 유일 봇 key. snake_case 사용 |
| `name` | `str` | `""` | 운영 API와 도움말에 표시할 이름 |
| `version` | `str` | `"0.1.0"` | 봇 구현 버전 |
| `description` | `str` | `""` | 봇 목적 한 문장 |
| `match_mode` | `str` | `"command"` | `command`, `pattern`, `stateful`, `scheduled`, `event`, `observer`, `fallback` |
| `commands` | `list[str]` | `[]` | 지원 명령 목록 |
| `patterns` | `list[MatchPattern]` | `[]` | matcher 입력 |
| `priority` | `int` | `100` | 낮을수록 먼저 실행 |
| `enabled` | `bool` | `True` | 기본 활성 상태 |
| `terminal` | `bool` | `True` | non-pass decision 후 후속 봇 중단 여부 |
| `timeout_millis` | `int` | `3000` | 처리 시간 경고 기준 |
| `state_ttl_millis` | `int | None` | `None` | 기본 state TTL |
| `default_options` | `dict` | `{}` | 옵션 기본값 |
| `option_schema` | `dict` | `{}` | 저장 API 옵션 검증 schema |
| `match_policy` | `str` | `"any"` | `any`, `all`, `score`, `custom` |
| `match_threshold` | `float` | `1.0` | score 정책 threshold |

### Lifecycle hooks

```python
def on_initialize(self, runtime: BotRuntime) -> None:
    pass

def on_shutdown(self) -> None:
    pass

def on_error(self, context: ChatContext, exc: Exception) -> ChatDecision:
    return self.pass_("error")
```

### Decision helpers

| helper | 반환 | 설명 |
| --- | --- | --- |
| `self.reply(text, reason=None)` | `ChatDecision` | 즉시 답장 |
| `self.queued(reason=None)` | `ChatDecision` | 비동기 처리 예정 |
| `self.none(reason=None, terminal=True)` | `ChatDecision` | 응답 없음 |
| `self.pass_(reason=None)` | `ChatDecision` | 다음 후보 봇으로 넘김 |

### Option helpers

| helper | 설명 |
| --- | --- |
| `self.option(context, key, default=None)` | 원본 옵션 조회 |
| `self.str_option(context, key, default="")` | 문자열 변환 조회 |
| `self.int_option(context, key, default, min_value=None, max_value=None)` | 정수 변환과 clamp |
| `self.float_option(context, key, default, min_value=None, max_value=None)` | 실수 변환과 clamp |
| `self.bool_option(context, key, default=False)` | bool 변환 |
| `self.list_option(context, key, default=None)` | list 조회 |
| `self.dict_option(context, key, default=None)` | dict 조회 |
| `self.bounded_int(context, key, default, min_value, max_value)` | 범위 제한 정수 |
| `self.bounded_float(context, key, default, min_value, max_value)` | 범위 제한 실수 |

### Send and I/O helpers

| helper | 설명 |
| --- | --- |
| `self.send_reply(context, text, dedupe_key=None, reply_token=None)` | `/send` job 단건 생성 |
| `self.send_replies(context, texts, dedupe_key_prefix=None, reply_token=None)` | `/send` job 여러 건 생성 |
| `self.queue_reply(context, text, delay_millis=0, dedupe_key=None, reply_token=None)` | 외부 runner에 지연 발송 등록 |
| `self.reply_dedupe_key(context, text, suffix=None)` | 안정적인 dedupe key 생성 |
| `self.http_post_json(url, payload, timeout_seconds, ref_id=None, error_prefix=...)` | HTTP JSON POST |
| `self.termux_command(args, timeout_seconds, ref_id=None, error_prefix=...)` | Termux command 실행 |

## CommandBot

명령어 기반 봇에 사용한다.

```python
class HelpBot(CommandBot):
    key = "help_bot"
    command = "/help"
    aliases = ["/도움말"]

    def handle_command(self, context: ChatContext) -> ChatDecision:
        return self.reply("help")
```

`CommandBot`은 `command`와 `aliases`를 `commands`와 command matcher로 자동 변환한다. `context.command`가 지원 명령에 포함될 때만 처리한다.

## StatefulBot

상태 저장 또는 다단계 세션이 필요한 봇에 사용한다. helper로 저장한 값은 JSON dict로 SQLite `chatbot_states`에 checkpoint되며, DB 파일이 유지되고 TTL이 만료되지 않았으면 백엔드 재시작이나 휴대폰 재부팅 후에도 조회된다. 임의 SQL CRUD가 필요한 대량/관계형 데이터는 별도 repository/table로 분리한다.

| helper | 설명 |
| --- | --- |
| `get_state(context, name=None, sender_scope=True)` | state dict 조회. 없거나 만료됐으면 빈 dict |
| `set_state(context, value, name=None, ttl_millis=None, sender_scope=True)` | state 저장 또는 덮어쓰기 |
| `update_state(context, updater, name=None, ttl_millis=None, sender_scope=True)` | 현재 state를 읽고 updater 결과를 저장 |
| `clear_state(context, name=None, sender_scope=True)` | state 삭제 |
| `state_key(context, name, sender_scope=True)` | state key 생성 |
| `start_session(context, step, payload=None, name=None, scope=None, ttl_millis=None)` | 세션 시작 |
| `advance_session(context, step, patch=None, name=None, scope=None, ttl_millis=None)` | 다음 step 이동 |
| `update_session(context, updater, name=None, scope=None, ttl_millis=None)` | 세션 갱신 |
| `end_session(context, name=None, scope=None)` | 세션 종료 |

## ObserverBot

관찰형 봇에 사용한다. 기본값은 `match_mode="observer"`, `terminal=False`다.

```python
class WatchBot(ObserverBot):
    key = "watch_bot"
    priority = 300

    def can_handle(self, context: ChatContext) -> bool:
        return not self.skip_command(context)

    def run(self, context: ChatContext) -> ChatDecision:
        return self.pass_("observed")
```

`skip_command(context)`는 `/` 명령 메시지를 건너뛸 때 사용한다.

## ChatContext

| field | 타입 | 설명 |
| --- | --- | --- |
| `eventId` | `str` | 수신 이벤트 고유 ID |
| `roomKey` | `str` | 안정적인 방 식별자 |
| `room` | `str` | 표시용 방 이름 |
| `sender` | `str | None` | 발신자명 |
| `text` | `str` | 원문 메시지 |
| `normalizedText` | `str` | trim/공백 정규화 메시지 |
| `messageType` | `str` | 메시지 타입 |
| `sourceType` | `str` | `real_kakao` 또는 `virtual_phone` |
| `replyToken` | `str | None` | 즉시 답장 token |
| `replyTokenExpiresAt` | `int | None` | token 만료 시각 ms |
| `receivedAt` | `int` | 수신 시각 ms |
| `command` | `str | None` | 첫 `/` 토큰 |
| `args` | `str` | command 뒤 인자 |
| `botOptions` | `dict` | 병합된 봇 옵션 |
| `roomRule` | `RoomRuleResponse | None` | 기존 room rule |
| `handled` | `bool` | 앞선 봇 처리 여부 |

## ChatDecision

| action | 생성 helper | 의미 |
| --- | --- | --- |
| `reply` | `self.reply(text)` | 즉시 답장 |
| `queued` | `self.queued(reason)` | 비동기 처리 예정 |
| `none` | `self.none(reason)` | 응답 없음 |
| `pass` | `self.pass_(reason)` | 후보 봇 처리 계속 |

`reply`는 processor가 `context.replyToken`을 채워 최종 `EventResponse`로 변환한다.

## BotRuntime

| field | 설명 |
| --- | --- |
| `botKey` | 현재 봇 key |
| `logger` | 봇 전용 logger |
| `stateStore` | SQLite-backed 봇 상태 저장소 |
| `optionStore` | 옵션 조회 store |
| `nowMillis` | 현재 시각 ms 함수 |
| `messageStore` | read-only 메시지 store |
| `botRegistry` | 로딩된 봇 registry |
| `externalRunner` | 봇 외부 I/O runner |
| `httpClient` | 공유 HTTP client |
