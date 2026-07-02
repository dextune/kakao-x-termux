# Bot Authoring Docs

이 폴더는 `kakao-termux-back` 챗봇을 작성, 운영, 테스트하기 위한 공개용 문서다. 봇은 `app/bots/{kebab-case}/bot.py`와 `bot.md`로 구성되며, Python 내부 봇 key는 snake_case를 사용한다.

## 문서 인덱스

| 문서 | 내용 |
| --- | --- |
| [빠른 시작](quickstart.md) | 최소 명령형 봇 작성, 로딩, 테스트까지의 전체 흐름 |
| [패키지 구조](package-structure.md) | `app/bots/{bot}/bot.py`, `bot.md`, 폴더명, import 부작용 규칙 |
| [런타임과 생명주기](runtime-lifecycle.md) | loader, registry, processor, hot reload, shutdown 호출 순서 |
| [봇 API 레퍼런스](api-reference.md) | `BaseBot`, `CommandBot`, `StatefulBot`, `ObserverBot`, `ChatContext`, `ChatDecision`, `BotRuntime` |
| [Matcher와 라우팅](matchers.md) | `MatchPattern`, match policy, command/keyword/regex/state/rate/fallback matcher |
| [옵션 스키마](options.md) | `default_options`, `option_schema`, 공통 옵션, 운영 API 검증 규칙 |
| [상태와 세션](state-and-sessions.md) | SQLite-backed 영속 state, TTL, sender/room scope, 다단계 대화 세션 helper |
| [응답과 발송](replies-and-send.md) | 즉시 답장, none/pass/queued, `/send` 기반 다중/지연 답장 helper |
| [외부 I/O](external-io.md) | HTTP API, Termux command, timeout, runner, 사용자 친화 오류 처리 |
| [운영과 Hot Reload](operations.md) | module API, file status, 실패 격리, reload 기준, 보안 주의사항 |
| [테스트](testing.md) | pytest, fixture, hot reload, option schema, 외부 I/O 테스트 작성 기준 |
| [Python 채팅 백테스트](backtesting.md) | `/events` 경유 다중 사용자/다중 방/다중 턴 봇 백테스트 작성 기준 |

## 유형별 예시

| 예시 | 내용 |
| --- | --- |
| [명령형 봇](bot-example-command.md) | `CommandBot`으로 단일 명령을 처리하는 기본 골격 |
| [상태형 봇](bot-example-stateful.md) | `StatefulBot`으로 여러 턴의 접수 흐름을 처리하는 골격 |
| [관찰형 봇](bot-example-observer.md) | `ObserverBot`으로 일반 메시지를 조건부 처리하는 골격 |
| [외부 HTTP 봇](bot-example-http.md) | `http_post_json` helper로 외부 API를 호출하는 골격 |
| [Termux Command 봇](bot-example-termux-command.md) | `termux_command` helper로 Termux:API 명령을 실행하는 골격 |

## 최소 구조

```text
kakao-termux-back/
  app/
    bots/
      sample-bot/
        bot.py
        bot.md
```

`bot.py`는 `create_bot()`을 제공해야 하며, 객체형 봇 인스턴스를 반환해야 한다. `bot.md`는 필수 설명 파일이며 누락되면 로더가 해당 봇을 failed로 기록한다.

## 주요 원칙

- Android bridge 계약과 `/events` 응답 계약은 봇 추가로 변경하지 않는다.
- 판단 로직은 `kakao-termux-back` 봇 안에 두고, Android 앱은 실제 카카오톡 제어만 담당한다.
- 공통 로직은 base class helper, matcher, state store, option schema, I/O helper를 우선 사용한다.
- import 시점에는 네트워크, DB write, subprocess 실행 같은 부작용을 만들지 않는다.
- 원문 메시지, 전화번호, 계정, token 등 민감 정보는 로그와 fixture에 남기지 않는다.
- 모든 외부 호출은 timeout을 둔다.

## 전체 검증 명령

```bash
cd kakao-termux-back
. ../.venv/bin/activate
python -m compileall -q app/chatbot app/bots
python -m pytest
```
