# KakaoTalk x Termux 설치방법

이 문서는 Android 기기에서 KakaoTalk X Termux를 처음 설치하는 순서를 정리합니다.

이 시스템은 Android에서만 동작합니다.

지원 범위는 Android 10부터 Android 15까지입니다.

루팅은 필요하지 않습니다.

## 전체 설치 흐름

1. Termux 설치
2. Termux:API 설치
3. Termux에서 필요한 기본 패키지 설치
4. 백엔드 저장소 clone
5. 백엔드 설치 스크립트 실행
6. Download 폴더에서 브릿지앱 APK 설치
7. 브릿지앱 권한 설정
8. 백엔드 실행 및 헬스체크

## 1. Termux 설치

백엔드는 Android 앱이 아니라 Termux 안에서 실행되는 Python/FastAPI 서버입니다.
따라서 백엔드 설치 명령을 입력하기 전에 Termux가 반드시 설치되어 있어야 합니다.

Termux가 아직 설치되어 있지 않다면 이 저장소의 `app-apk/` 폴더에 있는 Termux 설치 파일을 먼저 받습니다.

필요한 파일은 다음과 같습니다.

- `app-apk/com.termux_1022.z01`
- `app-apk/com.termux_1022.z02`
- `app-apk/com.termux_1022.zip`

세 파일을 같은 폴더에 둔 뒤 분할 ZIP을 압축 해제해서 `com.termux_1022.apk`를 꺼냅니다.
꺼낸 APK를 Android에서 설치하고, 설치가 끝나면 Termux를 한 번 실행해서 초기 파일 시스템 생성을 완료합니다.

설치가 막히면 Android 설정에서 APK를 여는 앱의 `알 수 없는 앱 설치` 권한을 허용합니다.
Play 스토어의 Play 프로텍트가 설치를 차단하면 Play 스토어 설정에서 Play 프로텍트 검사를 잠시 해제한 뒤 설치합니다.
설치가 끝난 뒤에는 Play 프로텍트 검사를 다시 켜는 것을 권장합니다.

## 2. Termux:API 설치

Termux:API는 Android 기능을 Termux 쪽에서 사용할 때 필요합니다.
이 저장소의 `app-apk/com.termux.api_1002.apk`를 Android에 설치합니다.

Termux:API도 설치가 막히면 Termux와 같은 방식으로 `알 수 없는 앱 설치` 권한을 허용한 뒤 설치합니다.

## 3. Termux 기본 패키지 설치

Termux 앱을 열고 아래 명령을 입력합니다.
fresh Termux 상태에서는 `git`이 없을 수 있으므로 clone 전에 먼저 설치합니다.

```bash
pkg update -y
pkg install -y git curl openssh
```

저장소 파일과 APK를 Download 폴더로 복사하려면 Termux 저장소 접근 권한도 열어둡니다.

```bash
termux-setup-storage
```

권한 확인 창이 뜨면 허용합니다.

## 4. 백엔드 저장소 clone

Termux 안에서 public 저장소를 clone 합니다.

```bash
cd ~
git clone https://github.com/dextune/kakao-x-termux.git
cd kakao-x-termux
```

## 5. 백엔드 설치 스크립트 실행

아래 스크립트는 Python, SQLite, curl, openssh, termux-api 등 필요한 패키지를 확인하고 부족한 항목을 설치합니다.
이후 Python 가상환경과 백엔드 의존성을 준비합니다.

```bash
./scripts/install_termux_requirements.sh
```

설치가 끝나면 스크립트가 브릿지앱 APK와 Termux 관련 설치 파일을 Android Download 폴더로 복사합니다.

## 6. Download 폴더에서 브릿지앱 APK 설치

Android 파일 앱에서 Download 폴더를 열고 `kakao-bridge-app-debug.apk`를 설치합니다.

설치가 막히는 경우 아래 항목을 확인합니다.

1. Android 설정에서 파일 앱 또는 브라우저의 `알 수 없는 앱 설치` 권한을 허용합니다.
2. Play 스토어의 Play 프로텍트가 차단하면 Play 스토어 설정에서 Play 프로텍트 검사를 잠시 해제합니다.
3. 설치가 끝난 뒤에는 Play 프로텍트 검사를 다시 켜는 것을 권장합니다.

## 7. 브릿지앱 권한 설정

브릿지앱은 카카오톡 알림을 읽고, 백엔드가 만든 응답을 실제 카카오톡 답장으로 보내는 역할을 합니다.
설치 후 Android 설정에서 아래 권한을 확인합니다.

1. 브릿지앱 알림 권한을 켭니다.
2. 브릿지앱 알림 접근 권한을 허용합니다.
3. 브릿지앱을 배터리 최적화 예외로 둡니다.
4. Termux도 알림 권한을 켭니다.
5. Termux도 배터리 최적화 예외로 둡니다.

브릿지앱 설정에서 백엔드 주소가 `http://127.0.0.1:8787`인지 확인합니다.

## 8. 백엔드 실행 및 헬스체크

Termux에서 백엔드를 실행합니다.

```bash
cd ~/kakao-x-termux
./scripts/run_termux_server.sh
```

다른 Termux 세션에서 상태를 확인합니다.

```bash
cd ~/kakao-x-termux
./scripts/check_termux_runtime.sh
```

정상이라면 `/health` 확인이 통과하고 백엔드가 `127.0.0.1:8787`에서 실행됩니다.

## 설치 후 확인

- 브릿지앱에서 백엔드 연결 상태가 정상인지 확인합니다.
- 브릿지앱에서 봇 목록이 표시되는지 확인합니다.
- 카카오톡 알림이 실제로 오는 방에서 테스트합니다.
- 문제가 있으면 Termux에서 `./scripts/check_termux_runtime.sh`를 먼저 실행합니다.
