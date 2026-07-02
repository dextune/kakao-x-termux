# kakao-termux-back-public 작업 안내

이 폴더는 `kakao-termux-back`의 공개 배포용 사본이다. 공개 배포에서는 Termux에서 바로 실행되는 백엔드와, 봇 작성에 필요한 공개 문서만 남긴다.

## 폴더 구성

- `app/`: FastAPI 백엔드와 챗봇 런타임
- `app/chatbot/`: loader, registry, processor, state store 같은 공통 프레임워크
- `app/bots/`: 실제 봇 구현체
- `docs/bot/`: 공개 봇 작성, 운영, 테스트 문서
- `scripts/`: Termux bootstrap과 서버 실행 스크립트
- `app-apk/`: 브릿지앱 APK, Termux split ZIP, Termux:API APK

## 봇 작성 방법

- 전체 문서 목차: [docs/bot/overview-index.md](docs/bot/overview-index.md)
- 프로젝트 소개와 빠른 설치: [README.md](README.md)
- Android 전체 설치 절차: [INSTALL.md](INSTALL.md)
- 가이드: [docs/bot/guide-quickstart.md](docs/bot/guide-quickstart.md), [docs/bot/guide-operations.md](docs/bot/guide-operations.md), [docs/bot/guide-testing.md](docs/bot/guide-testing.md)
- 아키텍처: [docs/bot/architecture-package-structure.md](docs/bot/architecture-package-structure.md), [docs/bot/architecture-runtime-lifecycle.md](docs/bot/architecture-runtime-lifecycle.md)
- 레퍼런스: [docs/bot/reference-api.md](docs/bot/reference-api.md), [docs/bot/reference-matchers.md](docs/bot/reference-matchers.md), [docs/bot/reference-options.md](docs/bot/reference-options.md)
- 예시: [docs/bot/example-command-bot.md](docs/bot/example-command-bot.md), [docs/bot/example-stateful-bot.md](docs/bot/example-stateful-bot.md)

## 루트 문서 관계

| 문서 | 성격 |
| --- | --- |
| [README.md](README.md) | GitHub 첫 화면용 소개, 지원 환경, 빠른 설치 명령, 프로젝트 구성 |
| [INSTALL.md](INSTALL.md) | Android 10~15 기준 전체 설치 순서와 권한 설정 |
| [AGENTS.md](AGENTS.md) | public 배포본에서 작업하는 에이전트와 개발자를 위한 구조 안내 |
| [docs/bot/overview-index.md](docs/bot/overview-index.md) | 봇 개발 문서 전체 목차 |

## 작업 원칙

- import 시점에 네트워크, DB write, subprocess 실행 같은 부작용을 만들지 않는다.
- 원문 메시지, 전화번호, 계정, token 같은 민감 정보는 문서와 로그에 남기지 않는다.
- 봇은 판단 로직만 담당하고, Android 브릿지앱은 실제 카카오톡 제어만 담당한다.
- public 배포본은 운영 보조 봇과 내부 호스트값이 들어간 봇을 제외한 상태를 유지한다.

## 실행 순서

처음 설치하는 사용자는 [INSTALL.md](INSTALL.md)를 먼저 따른다.

Termux 설치와 저장소 clone이 끝난 뒤에는 아래 순서로 실행한다.

1. `./scripts/install_termux_requirements.sh`
2. `./scripts/run_termux_server.sh`
3. `./scripts/check_termux_runtime.sh`
4. 필요하면 `./scripts/install_termux_boot.sh`

## 최신화

public 최신화가 필요하면 원본 저장소에서 `./scripts/update_public_deploy.sh`를 실행한다.
