# Voice TTS Bot

## 목적
`/음성 문장` 명령으로 Termux:API TTS를 실행해 기기에서 음성을 재생한다.

## 명령어/트리거
- 명령어: `/음성`
- 자동 트리거: 없음
- matcher: command

## 입력
`/음성 읽을 문장` 형식의 텍스트 메시지를 받는다.

## 출력
TTS 실행 성공 시 `음성으로 재생했습니다.`를 답장하고, 입력 누락이나 실행 실패는 안내 문구를 답장한다.

## 옵션
| 이름 | 타입 | 기본값 | 설명 |
| --- | --- | --- | --- |
| rate | number | 1.2 | TTS 속도 |
| pitch | number | 1.0 | TTS pitch |
| language | string | ko | 언어 코드 |
| stream | string | MUSIC | Android audio stream |
| timeoutSeconds | number | 10 | 명령 실행 timeout |
| maxTextChars | integer | 300 | 읽을 최대 글자 수 |

## 상태
저장하는 state/session key가 없다.

## 외부 의존성
Termux:API `termux-tts-speak` 명령을 사용한다.

## 실패 조건
Termux 명령 없음, timeout, stderr 포함 실패를 사용자 친화 메시지로 변환하고 WARN 로그를 남긴다.

## 테스트
`tests/test_voice_tts_bot.py`에서 명령 조립, 입력 누락, 실패 응답을 검증한다.
