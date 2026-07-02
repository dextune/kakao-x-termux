# kakao-termux-back-public 작업 안내

이 폴더는 `kakao-termux-back`의 공개 배포용 사본이다. 공개 배포에서는 Termux에서 바로 실행되는 백엔드와, 봇 작성에 필요한 공개 문서만 남긴다.

## 폴더 구성

- `app/`: FastAPI 백엔드와 챗봇 런타임
- `app/chatbot/`: loader, registry, processor, state store 같은 공통 프레임워크
- `app/bots/`: 실제 봇 구현체
- `docs/bot/`: 공개 봇 작성, 운영, 테스트 문서
- `scripts/`: Termux bootstrap과 서버 실행 스크립트
- `app-apk/`: 브릿지앱, Termux, Termux:API APK

## 봇 작성 방법

- 전체 문서 목차: [docs/bot/index.md](docs/bot/index.md)
- 가장 빠른 시작: [docs/bot/quickstart.md](docs/bot/quickstart.md)
- 봇 패키지 구조: [docs/bot/package-structure.md](docs/bot/package-structure.md)
- 런타임과 생명주기: [docs/bot/runtime-lifecycle.md](docs/bot/runtime-lifecycle.md)
- 운영과 Hot Reload: [docs/bot/operations.md](docs/bot/operations.md)
- 테스트 기준: [docs/bot/testing.md](docs/bot/testing.md)

## 작업 원칙

- import 시점에 네트워크, DB write, subprocess 실행 같은 부작용을 만들지 않는다.
- 원문 메시지, 전화번호, 계정, token 같은 민감 정보는 문서와 로그에 남기지 않는다.
- 봇은 판단 로직만 담당하고, Android 브릿지앱은 실제 카카오톡 제어만 담당한다.
- public 배포본은 운영 보조 봇과 내부 호스트값이 들어간 봇을 제외한 상태를 유지한다.

## 실행 순서

1. `./scripts/install_termux_requirements.sh`
2. `./scripts/run_termux_server.sh`
3. 필요하면 `./scripts/install_termux_boot.sh`

## 최신화

public 최신화가 필요하면 원본 저장소에서 `./scripts/update_public_deploy.sh`를 실행한다.
