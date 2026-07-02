# 테스트

봇 변경 후에는 compile, 단위 테스트, 회귀 테스트를 실행한다.

## 기본 명령

```bash
cd kakao-termux-back
. ../.venv/bin/activate
python -m compileall -q app/chatbot app/bots
python -m pytest
```

실제 채팅에 가까운 다중 사용자/다중 방/다중 턴 검증은 [Python 채팅 백테스트](backtesting.md)의 `ChatBacktest` helper를 우선 사용한다. 신규 상태형 봇이나 사용자별 CRUD 봇은 단순 handler 테스트보다 `/events` 경유 백테스트를 먼저 작성한다.

챗봇 관련 빠른 검증:

```bash
python -m pytest \
  tests/test_chatbot_hot_reload.py \
  tests/test_chatbot_module.py \
  tests/test_ai_chatbot.py \
  tests/test_photo_analysis_bot.py \
  tests/test_voice_tts_bot.py \
  -q
```

## 이벤트 fixture

```python
from itertools import count

_ids = count(1)


def event_payload(text: str, room_key: str = "room_test", sender: str = "tester") -> dict:
    index = next(_ids)
    return {
        "schemaVersion": 1,
        "eventId": f"test_evt_{index}",
        "source": "notification",
        "sourcePackage": "pc.kakao-test-app",
        "sourceType": "virtual_phone",
        "roomKey": room_key,
        "room": "테스트방",
        "sender": sender,
        "text": text,
        "messageType": "text",
        "receivedAt": 1_700_000_000_000 + index,
        "notificationKey": f"test_noti_{index}",
        "replyToken": f"reply_test_{index}",
        "replyTokenExpiresAt": 1_900_000_000_000,
        "token": "shared-secret",
    }
```

## 명령형 봇 테스트

```python
def test_sample_bot_replies(client):
    response = client.post("/events", json=event_payload("/sample hello"))

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "reply"
    assert body["text"] == "처리했습니다: hello"
```

## 비대상 입력 테스트

```python
def test_sample_bot_ignores_other_command(client):
    response = client.post("/events", json=event_payload("/other"))

    assert response.status_code == 200
    assert response.json()["action"] in {"reply", "none"}
```

fallback이 켜져 있으면 다른 봇이 reply할 수 있으므로, 특정 봇의 run log를 함께 확인하는 방식도 사용한다.

## 옵션 schema 테스트

```python
def test_option_schema_rejects_invalid_value(client):
    response = client.post(
        "/chatbot/modules/sample_bot",
        json={"enabled": True, "options": {"timeoutSeconds": "fast"}, "token": "shared-secret"},
    )

    assert response.status_code == 400
```

## Hot reload 테스트

임시 bot directory를 만들고 `CHATBOT_BOT_DIR`를 해당 경로로 바꾼 뒤 `ChatbotService`를 직접 시작한다.

검증해야 할 항목:

- 폴더형 봇이 로드되는가.
- `bot.md` 누락이 failed로 기록되는가.
- `bot.py` syntax/import 실패가 격리되는가.
- flat `app/bots/*.py` 파일이 무시되는가.
- `bot.md` 변경만으로 reload되는가.
- duplicate key 후보가 failed가 되고 기존 봇이 유지되는가.

## 외부 I/O 테스트

HTTP helper는 `bot.runtime.httpClient.post`를 monkeypatch한다.

```python
def fake_post(url, json, timeout):
    request = httpx.Request("POST", url)
    return httpx.Response(200, request=request, json={"text": "ok"})

monkeypatch.setattr(bot.runtime.httpClient, "post", fake_post)
```

Termux command helper는 handler method를 monkeypatch하면 command 조립을 쉽게 검증할 수 있다.

```python
commands = []

def fake_command(command, timeout_seconds, ref_id=None, error_prefix="termux command failed"):
    commands.append(command)

monkeypatch.setattr(bot.handler, "termux_command", fake_command)
```

## 테스트 기준

- 성공 입력.
- 입력 누락.
- 비대상 입력.
- 옵션 override.
- 옵션 schema 실패.
- stateful reload 후 상태 유지.
- 외부 I/O 성공.
- 외부 I/O timeout 또는 실패.
- 개인정보가 응답과 로그에 과도하게 노출되지 않는지.
