# 외부 I/O

봇에서 외부 HTTP API나 Termux command를 사용할 수 있다. 모든 외부 I/O는 timeout, 짧은 오류 메시지, 운영 로그, 개인정보 비노출 기준을 지켜야 한다.

## HTTP JSON POST

`self.http_post_json()`을 사용한다.

```python
class AiBot(CommandBot):
    key = "ai_bot"
    command = "/ai"
    default_options = {"endpoint": "http://127.0.0.1:8080/v1/completions", "timeoutSeconds": 30}
    option_schema = {
        "endpoint": {"type": "string", "default": "http://127.0.0.1:8080/v1/completions", "description": "LLM endpoint."},
        "timeoutSeconds": {"type": "number", "default": 30, "min": 1, "max": 300, "description": "HTTP timeout."},
    }

    def handle_command(self, context):
        endpoint = self.str_option(context, "endpoint")
        timeout = self.float_option(context, "timeoutSeconds", 30.0, min_value=1.0, max_value=300.0)
        response = self.http_post_json(
            endpoint,
            {"prompt": context.args, "stream": False},
            timeout_seconds=timeout,
            ref_id=context.eventId,
            error_prefix="ai_bot backend unavailable",
        )
        return self.reply(response.json().get("text", ""))
```

helper는 `runtime.httpClient`와 `runtime.externalRunner`를 사용한다. runner queue full, timeout, HTTP 오류는 `ExternalIOError`로 변환된다.

## Termux command

`self.termux_command()`을 사용한다.

```python
class VibrateBot(CommandBot):
    key = "vibrate_bot"
    command = "/vibrate"

    def handle_command(self, context):
        try:
            self.termux_command(
                ["termux-vibrate", "-d", "300"],
                timeout_seconds=5,
                ref_id=context.eventId,
                error_prefix="진동 실행에 실패했습니다",
            )
        except FileNotFoundError:
            return self.reply("Termux:API 앱과 `pkg install termux-api` 설치를 확인해주세요.")
        except Exception:
            return self.reply("진동 실행 중 오류가 발생했습니다.")
        return self.reply("진동을 실행했습니다.")
```

command 인자는 list로 전달한다. 사용자 입력을 shell string으로 조립하지 않는다.

## 사용자 오류와 운영 로그 분리

사용자에게는 복구 가능한 짧은 메시지를 준다.

```python
try:
    response = self.http_post_json(...)
except Exception as exc:
    self.log_warn(f"ai backend failed: {exc.__class__.__name__}", context.eventId)
    return self.reply("AI 서버 응답이 지연되고 있습니다. 잠시 후 다시 시도해주세요.")
```

로그에는 원문 메시지, token, 개인정보, 외부 response 전문을 남기지 않는다.

## 옵션화해야 하는 값

- endpoint URL.
- model 이름.
- timeout.
- max token 또는 max text length.
- 파일 크기 제한.
- cleanup 여부.
- Termux command 부가 옵션.

## 긴 작업 기준

외부 호출이 `/events` 응답 시간을 길게 만들 수 있으면 `queue_reply()` 또는 별도 job 구조를 사용한다. 특히 모델 호출, 파일 압축, 네트워크 재시도는 무제한으로 대기하지 않는다.

## 파일 작업 기준

- 임시 파일은 `data/{bot-key}/` 같은 봇 전용 하위 폴더를 사용한다.
- cleanup 옵션을 둔다.
- binary 데이터는 state store에 저장하지 않는다.
- 생성 파일명에 사용자 입력을 그대로 쓰지 않는다.
