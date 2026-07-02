# KakaoTalk X Termux

<p align="center">
  <img src="./assets/kakao-talk-x-termux.svg" alt="KakaoTalk X Termux" width="100%" />
</p>

KakaoTalk X Termux는 카카오톡 알림 기반 자동 응답 흐름을 검증하고 운영하기 위한 공개 배포본입니다.
이 저장소는 Android 브릿지앱, Termux 백엔드, 공개 봇 문서를 한 묶음으로 제공합니다.

## 핵심 구성

| 구성 | 역할 |
| --- | --- |
| `kakao-bridge-app` | Android 브릿지앱. 알림 수신, 답장 핸들 확보, Termux 백엔드 연동 |
| `kakao-termux-back` | Termux FastAPI 백엔드. 메시지 판단, 룰 엔진, 답장 명령 생성 |
| `docs/bot/` | 공개 봇 작성, 운영, 테스트 문서 |
| `scripts/` | Termux 최초 설치, 서버 실행, 부팅 자동화 스크립트 |
| `app-apk/` | 브릿지앱, Termux, Termux:API APK |

## 빠른 설치

1. 저장소를 clone 합니다.
2. `./scripts/install_termux_requirements.sh`를 실행합니다.
3. `./scripts/check_termux_runtime.sh`로 헬스체크를 확인합니다.

## 봇 문서

봇을 만들거나 수정할 때는 아래 문서를 순서대로 보면 됩니다.

- [문서 인덱스](docs/bot/index.md)
- [패키지 구조](docs/bot/package-structure.md)
- [런타임과 생명주기](docs/bot/runtime-lifecycle.md)
- [운영과 Hot Reload](docs/bot/operations.md)
- [테스트](docs/bot/testing.md)

## 이 저장소가 하는 일

- 카카오톡 알림을 백엔드로 전달합니다.
- 백엔드는 봇 규칙과 상태를 처리합니다.
- 브릿지앱은 실제 카카오톡 답장을 전송합니다.
- public 배포본에서는 운영 보조 봇과 내부 전용 설정을 제외합니다.

## 배포 파일

- `AGENTS.md`: public 전용 작업 안내
- `README.md`: GitHub 메인 소개
- `docs/bot/`: 봇 작성용 공개 문서
- `app-apk/`: 설치 파일 3개

## 저장소

GitHub: http://github.com/dextune/kakao-x-termux

APK 파일은 Git LFS로 저장한다. 저장소를 처음 받을 때는 `git lfs install`을 준비하면 좋다.

## 주의

- 이 배포본은 public snapshot입니다.
- 민감한 token, 개인 메시지, 전화번호, 내부 호스트 정보는 넣지 않습니다.
- 실기기 배포 전에는 `DEVICE.md`와 `TEST.md`를 확인합니다.
