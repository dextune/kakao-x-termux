# 운영과 Hot Reload

봇 운영 API는 인증 token이 필요한 쓰기 API와 읽기 API로 나뉜다. 공개 문서 예시는 `shared-secret`을 사용하지만 실제 운영 비밀값을 문서나 fixture에 남기지 않는다.

## 모듈 목록

```bash
curl -s http://127.0.0.1:8787/chatbot/modules
```

인증 token을 주면 file details가 포함된다.

```bash
curl -s 'http://127.0.0.1:8787/chatbot/modules?token=shared-secret'
```

응답의 주요 필드:

| field | 설명 |
| --- | --- |
| `key` | 봇 key |
| `name` | 봇 이름 |
| `version` | 봇 버전 |
| `enabled` | 전역 활성 상태 |
| `commands` | 명령 목록 |
| `matchMode` | match mode |
| `optionSchema` | 저장 가능한 옵션 schema |
| `priority` | 실행 우선순위 |
| `loaded` | 현재 registry 로딩 여부 |
| `lastError` | 인증 조회 시 최근 오류 |
| `files` | 인증 조회 시 파일별 상태 목록 |

## 전역 설정 변경

```bash
curl -s -X POST http://127.0.0.1:8787/chatbot/modules/help_bot \
  -H 'content-type: application/json' \
  -d '{"enabled":true,"priority":50,"options":{"replyRateLimitMillis":50},"token":"shared-secret"}'
```

## 방별 설정 변경

```bash
curl -s -X POST http://127.0.0.1:8787/chatbot/rooms/room_a/modules/help_bot \
  -H 'content-type: application/json' \
  -d '{"enabled":false,"options":{},"token":"shared-secret"}'
```

## 수동 reload

```bash
curl -s -X POST http://127.0.0.1:8787/chatbot/reload \
  -H 'content-type: application/json' \
  -d '{"token":"shared-secret"}'
```

## Health

```bash
curl -s 'http://127.0.0.1:8787/chatbot/health?token=shared-secret'
```

주요 항목:

- `loadedBots`
- `failedBots`
- `failedFiles`
- `matchers`
- `lastReloadAt`
- `lastScanAt`
- `lastScanDurationMs`
- `lastScanError`
- `watcherEnabled`
- `stateCache`
- `configCache`

`stateCache`는 봇 state/session memory cache의 현재 상태다. `dirty`가 0이면 memory cache 안에 flush 대기 중인 변경분이 없다는 뜻이다. 실제 SQLite writer 처리 실패나 지연 여부는 bridge log와 `/health?includeDetails=true`의 `memoryPipeline.sqliteWriter`에서 `stateSnapshotWritten`, `stateSnapshotFailed`, writer queue 상태를 함께 확인한다.

## State 조회

```bash
curl -s 'http://127.0.0.1:8787/chatbot/states?token=shared-secret&limit=100'
```

기본 응답은 state 원문을 숨기고 `stateBytes`만 노출한다. 원문 확인은 운영 민감 작업이므로 `includeRaw=true`와 별도 `rawToken`을 함께 전달해야 한다.

```bash
curl -s 'http://127.0.0.1:8787/chatbot/states?token=shared-secret&includeRaw=true&rawToken=shared-secret'
```

state row는 SQLite `chatbot_states`에 저장된 봇별 비휘발성 자료다. DB 파일이 유지되고 `expiresAt`이 지나지 않았으면 백엔드 재시작이나 휴대폰 재부팅 후에도 남는다. 다만 강제 종료 직전 아직 checkpoint되지 않은 dirty state나 writer queue에만 들어간 snapshot은 유실될 수 있으므로, 운영 점검 전에는 `stateCache.dirty`와 SQLite writer 처리 수/실패 수를 확인한다.

## File status

`chatbot_module_files`에는 파일 단위 상태가 저장된다.

| status | 의미 |
| --- | --- |
| `loaded` | 정상 로딩됨 |
| `failed` | import, schema, 중복 key, 누락 파일 등으로 실패 |
| `removed` | 이전에 로드되었으나 현재 스캔 대상에서 사라짐 |

## Hot reload 실패 격리

수정본이 실패해도 기존 정상 handler는 유지된다. 예를 들어 기존 `help_bot`이 로딩된 상태에서 `help-bot/bot.py`에 syntax error가 생기면:

- registry에는 기존 handler가 남는다.
- 파일 상태는 `failed`가 된다.
- 오류는 bridge log와 module file 상태에 기록된다.

## Reload 대상

`bot.py`와 `bot.md` 둘 다 snapshot에 포함된다. 문서만 수정해도 reload 대상이다.

## 보안 기준

- 쓰기 API는 shared secret 또는 동등한 인증 경로로 보호한다.
- token, 개인 메시지, 전화번호, 계정 정보는 로그와 문서 예시에 남기지 않는다.
- 외부 HTTP endpoint를 공개 네트워크에 노출할 때는 별도 보안 검토가 필요하다.
- Termux 운영은 기본적으로 `127.0.0.1` 바인딩을 우선한다.
