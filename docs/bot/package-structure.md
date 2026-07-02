# 패키지 구조

봇 로더는 `app/bots/*/bot.py`만 로딩 대상으로 인정한다. direct `app/bots/*.py` 파일은 로딩하지 않는다.

## 디렉터리 규칙

```text
app/bots/
  help-bot/
    bot.py
    bot.md
  request-intake-bot/
    bot.py
    bot.md
```

| 항목 | 규칙 |
| --- | --- |
| 봇 폴더명 | kebab-case. 예: `photo-analysis-bot` |
| 봇 key | snake_case. 예: `photo_analysis_bot` |
| 코드 파일 | `bot.py` 필수 |
| 설명 파일 | `bot.md` 필수 |
| 무시 폴더 | `__pycache__`, `_`로 시작하는 폴더, `.`로 시작하는 폴더 |
| 무시 파일 | `app/bots/*.py` direct 파일. 단 `__init__.py`는 패키지 파일로만 존재 |

`bot.py` 또는 `bot.md`가 없으면 로더는 해당 폴더의 `bot.py` 경로를 `chatbot_module_files`에 failed로 기록한다.

## Marketplace zip 패키지 계약

마켓플레이스와 Termux 설치 API에서 주고받는 패키지는 zip으로 고정한다.

필수 파일:

- `bot-package.json`
- `bot.py`
- `bot.md`

`bot-package.json` 예시:

```json
{
  "schemaVersion": 1,
  "botKey": "sample_bot",
  "folderName": "sample-bot",
  "name": "Sample Bot",
  "version": "1.0.0",
  "description": "샘플 봇",
  "minRuntimeApi": "1.0",
  "files": ["bot-package.json", "bot.py", "bot.md"]
}
```

검증 규칙:

| 항목 | 규칙 |
| --- | --- |
| 압축 형식 | zip |
| `folderName` | kebab-case |
| `botKey` | snake_case |
| `version` | semver |
| 경로 | 절대 경로, `..`, 역슬래시 경로 금지 |
| 인코딩 | JSON, Python, Markdown은 UTF-8 |
| 코드 검증 | `ast.parse` syntax 검증까지만 수행 |
| 무결성 | 업로드/다운로드 응답에서 package sha256 기록 |
| 압축 크기 | `MARKETPLACE_MAX_PACKAGE_BYTES` 초과 거부 |
| 파일 수 | `MARKETPLACE_MAX_PACKAGE_FILES` 초과 거부 |
| 압축 해제 총량 | `MARKETPLACE_MAX_PACKAGE_UNCOMPRESSED_BYTES` 초과 거부 |

마켓플레이스 서버는 사용자 봇 코드를 실행하지 않는다. 실제 실행 가능 여부는 Termux 백엔드 설치 후 `/chatbot/reload` 결과와 로더 상태로 판단한다.
마켓플레이스에 업로드한 신규 배포와 재배포는 저장 직후 `ACTIVE`가 되며, `public` 봇은 public catalog와 download에 즉시 노출된다.
직접 URL 접근은 `ACTIVE` 버전만 허용하고 그 외 버전은 404로 처리한다.

## `bot.py` 계약

객체형 봇은 `create_bot()` 함수를 제공해야 한다.

```python
def create_bot() -> MyBot:
    """로더가 사용할 봇 인스턴스를 생성한다."""

    return MyBot()
```

반환 객체는 `BotHandler` 계약을 만족해야 한다. 보통 `BaseBot`, `CommandBot`, `StatefulBot`, `ObserverBot` 중 하나를 상속하면 된다.

## `bot.md` 템플릿

```md
# {Bot Name}

## 목적
이 봇이 해결하는 문제와 사용 시점을 설명한다.

## 명령어/트리거
- 명령어:
- 자동 트리거:
- matcher:

## 입력
사용자가 보내야 하는 메시지 형식과 옵션을 설명한다.

## 출력
봇이 반환하는 답장, queued, none 조건을 설명한다.

## 옵션
| 이름 | 타입 | 기본값 | 설명 |
| --- | --- | --- | --- |

## 상태
저장하는 state/session key, sender/room scope, TTL, 재시작 후 유지가 필요한지 여부를 설명한다. `StatefulBot` helper로 저장한 값은 SQLite `chatbot_states`에 checkpoint되며, 임시 메모리 변수만 쓰는 값은 재시작 후 유지되지 않는다고 명시한다.

## 외부 의존성
HTTP, Termux command, 파일, 모델 서버 등 의존성을 설명한다.

## 실패 조건
사용자에게 노출되는 실패 응답과 운영 로그 기준을 설명한다.

## 테스트
대표 pytest 또는 시나리오를 적는다.
```

## Import 부작용 금지

`bot.py` import 시점에는 아래 작업을 하지 않는다.

- HTTP 요청
- DB write
- subprocess 실행
- 파일 생성/삭제
- 오래 걸리는 모델 초기화
- 운영 설정 변경

초기화가 필요하면 `on_initialize(runtime)`에서 가벼운 준비만 수행하고, 실패 가능성이 있는 작업은 `handle_command()` 또는 `run()` 내부에서 처리한다.
