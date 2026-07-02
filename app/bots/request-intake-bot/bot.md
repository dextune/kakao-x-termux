# Request Intake Bot

## 목적
사용자의 요청을 유형, 내용, 긴급도 순서로 접수하고 최근 접수 목록을 관리한다.

## 명령어/트리거
- 명령어: `/접수`, `/접수목록`
- 자동 트리거: 진행 중인 sender session
- matcher: command, state_exists

## 입력
`/접수`로 세션을 시작하고 유형, 내용, 긴급도, 확인 메시지를 순서대로 보낸다.

## 출력
각 단계별 안내를 reply하고, 접수 완료 시 ticket id와 요약을 답장한다.

## 옵션
| 이름 | 타입 | 기본값 | 설명 |
| --- | --- | --- | --- |
| categories | array | ["상담", "예약", "주문", "기타"] | 접수 유형 목록 |
| maxDetailChars | integer | 300 | 요청 내용 최대 길이 |
| recentLimit | integer | 20 | 저장할 최근 접수 수 |
| recentTtlMillis | integer | 604800000 | 최근 접수 보관 TTL |

## 상태
sender scope `request_session`과 room scope `submitted_requests`를 저장한다.

## 외부 의존성
없음.

## 실패 조건
알 수 없는 단계는 세션을 종료하고 재시작 안내를 답장한다.

## 테스트
`tests/test_request_intake_bot.py`에서 세션 진행, 목록, 비활성화 경로를 검증한다.
