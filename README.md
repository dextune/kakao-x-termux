# KakaoTalk X Termux

<p align="center">
  <img src="./assets/kakao-talk-x-termux.svg" alt="KakaoTalk X Termux" width="100%" />
</p>

<p align="center">
  <img src="./assets/kakao-talk-x-termux-flow.svg" alt="KakaoTalk X Termux workflow" width="100%" />
</p>

KakaoTalk X Termux는 카카오톡 알림 기반 자동 응답 흐름을 검증하고 운영하기 위한 공개 배포본입니다.
이 저장소는 Android 브릿지앱, Termux 백엔드, 공개 봇 문서를 한 묶음으로 제공합니다.

## 빠른 설치

```bash
git clone https://github.com/dextune/kakao-x-termux.git
cd kakao-x-termux
./scripts/install_termux_requirements.sh
./scripts/run_termux_server.sh
./scripts/check_termux_runtime.sh
```

1. GitHub 저장소를 clone 한다.
2. Termux 안에서 `./scripts/install_termux_requirements.sh`를 실행한다.
3. `./scripts/run_termux_server.sh`로 백엔드를 띄운다.
4. `./scripts/check_termux_runtime.sh`로 상태를 확인한다.

## Android 설치

### 브릿지앱

1. `app-apk/kakao-bridge-app-debug.apk`를 설치한다.
2. Android 설정에서 브릿지앱 알림 권한을 켠다.
3. Android 설정에서 브릿지앱을 배터리 최적화 예외로 둔다.

### Termux

1. `app-apk/com.termux_1022.z01`과 `app-apk/com.termux_1022.zip`을 같은 폴더에 둔다.
2. 압축을 풀어 `com.termux_1022.apk`를 꺼낸다.
3. 꺼낸 `com.termux_1022.apk`를 설치한다.
4. 필요하면 `app-apk/com.termux.api_1002.apk`도 설치한다.
5. Android 설정에서 Termux 알림 권한을 켠다.
6. Android 설정에서 Termux를 배터리 최적화 예외로 둔다.

`install_termux_requirements.sh`는 브릿지앱 APK와 Termux 관련 배포 파일을 Download 폴더로 복사해서, 재설치할 때 다시 찾기 쉽게 만든다.

## 프로젝트 구성

| 구성 | 역할 |
| --- | --- |
| `kakao-bridge-app` | 알림 수신, reply token 확보, Termux 백엔드 연결을 담당하는 Android 브릿지앱 |
| `kakao-termux-back` | 메시지 판단, 룰 엔진, 상태 저장, 답장 작업을 처리하는 Termux 백엔드 |
| `app-apk/` | 브릿지앱 APK, Termux split ZIP, Termux:API APK |
| `scripts/` | Termux bootstrap, 서버 실행, 점검, 부팅 자동화 스크립트 |
| `docs/bot/` | 봇 작성, 운영, 테스트에 필요한 공개 문서 |

## 프로젝트 흐름

1. 카카오톡 알림이 들어오면 브릿지앱이 이벤트를 잡는다.
2. 브릿지앱이 reply token과 방 정보를 정리해 Termux 백엔드로 넘긴다.
3. Termux 백엔드가 봇 모듈, 룰, 상태를 읽고 응답을 결정한다.
4. 필요한 경우 reply job을 만들고 브릿지앱이 실제 답장을 전송한다.
5. 운영자는 `docs/bot/`와 `scripts/`를 기준으로 봇을 추가하거나 점검한다.

## 세부 정보

- 이 저장소는 Android와 Termux의 역할을 분리해서 운영한다.
- Android 앱은 판단 로직을 가지지 않는다.
- Python 백엔드는 카카오톡 UI를 직접 제어하지 않는다.
- 봇은 `app/bots/{kebab-case}/bot.py`와 `bot.md`로 작성한다.
- 공개 배포본은 운영 보조 봇과 내부 전용 설정을 제외한 상태를 유지한다.

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
- `app-apk/`: 브릿지앱 APK, Termux split ZIP, Termux:API APK

## 저장소

GitHub: http://github.com/dextune/kakao-x-termux

## 주의

- 이 배포본은 public snapshot입니다.
- 민감한 token, 개인 메시지, 전화번호, 내부 호스트 정보는 넣지 않습니다.
- 실기기 배포 전에는 `DEVICE.md`와 `TEST.md`를 확인합니다.
