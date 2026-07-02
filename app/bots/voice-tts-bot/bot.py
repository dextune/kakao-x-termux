from __future__ import annotations

from typing import Any

from app.chatbot.base_bot import CommandBot
from app.chatbot.context import ChatContext
from app.chatbot.decision import ChatDecision
from app.chatbot.io_helpers import ExternalIOError
from app.chatbot.module import BotRuntime
from app.infra.async_writes import enqueue_bridge_log

_COMMAND = "/음성"
_DEFAULT_RATE = 1.2
_DEFAULT_PITCH = 1.0
_DEFAULT_LANGUAGE = "ko"
_DEFAULT_STREAM = "MUSIC"
_DEFAULT_TIMEOUT_SECONDS = 10
_DEFAULT_TIMEOUT_MILLIS = _DEFAULT_TIMEOUT_SECONDS * 1000
_MAX_TEXT_CHARS = 300


class VoiceTtsBot(CommandBot):
    """`/음성 문장` 명령으로 Termux:API TTS를 실행한다."""

    key = "voice_tts_bot"
    name = "Voice TTS Bot"
    version = "0.1.0"
    description = "`/음성 문장` 명령으로 Termux:API TTS를 실행한다."
    command = _COMMAND
    priority = 56
    timeout_millis = _DEFAULT_TIMEOUT_MILLIS
    default_options = {
        "rate": _DEFAULT_RATE,
        "pitch": _DEFAULT_PITCH,
        "language": _DEFAULT_LANGUAGE,
        "stream": _DEFAULT_STREAM,
        "timeoutSeconds": _DEFAULT_TIMEOUT_SECONDS,
        "maxTextChars": _MAX_TEXT_CHARS,
    }
    option_schema = {
        "rate": {"type": "number", "default": _DEFAULT_RATE, "min": 0.1, "max": 4.0, "description": "TTS 속도."},
        "pitch": {"type": "number", "default": _DEFAULT_PITCH, "min": 0.1, "max": 4.0, "description": "TTS pitch."},
        "language": {"type": "string", "default": _DEFAULT_LANGUAGE, "description": "언어 코드."},
        "stream": {"type": "string", "default": _DEFAULT_STREAM, "description": "Android audio stream."},
        "timeoutSeconds": {
            "type": "number",
            "default": _DEFAULT_TIMEOUT_SECONDS,
            "min": 1,
            "max": 120,
            "description": "TTS 명령 timeout.",
        },
        "maxTextChars": {"type": "integer", "default": _MAX_TEXT_CHARS, "min": 1, "max": 1000, "description": "읽을 최대 글자 수."},
        "engine": {"type": "string", "description": "선택 TTS engine."},
        "region": {"type": "string", "description": "선택 음성 region."},
        "variant": {"type": "string", "description": "선택 음성 variant."},
    }

    def handle_command(self, context: ChatContext) -> ChatDecision:
        """명령 인자를 Termux TTS로 출력하고 처리 결과를 답장한다."""

        text = _select_text(context)
        if not text:
            return self.reply("읽을 문장을 함께 보내주세요. 예: /음성 안녕하세요")

        options = context.botOptions or {}
        try:
            spoken_text = _limit_text(text, _int_option(options.get("maxTextChars"), _MAX_TEXT_CHARS))
            _speak_text(self, spoken_text, options, ref_id=context.eventId)
        except FileNotFoundError as exc:
            _log_failure(self.runtime, "voice_tts_bot command missing", exc, context.eventId)
            return self.reply("TTS 명령을 찾지 못했습니다. Termux:API 앱과 `pkg install termux-api` 설치를 확인해주세요.")
        except (VoiceTtsError, ExternalIOError) as exc:
            _log_failure(self.runtime, "voice_tts_bot failed", exc, context.eventId)
            return self.reply(str(exc))
        except Exception as exc:
            _log_failure(self.runtime, "voice_tts_bot unexpected failure", exc, context.eventId)
            return self.reply("음성 출력 중 오류가 발생했습니다.")

        return self.reply("음성으로 재생했습니다.")


class VoiceTtsError(RuntimeError):
    """Termux TTS 실행 실패를 사용자 응답 가능 오류로 표현한다."""


def create_bot() -> VoiceTtsBot:
    """로더가 사용할 객체형 봇 인스턴스를 생성한다."""

    return VoiceTtsBot()


def _select_text(context: ChatContext) -> str:
    return context.args.strip()


def _speak_text(bot: VoiceTtsBot, text: str, options: dict[str, Any], ref_id: str | None = None) -> None:
    """`termux-tts-speak` 명령으로 텍스트를 음성 출력한다."""

    rate = _bounded_float(options.get("rate"), _DEFAULT_RATE, minimum=0.1, maximum=4.0)
    pitch = _bounded_float(options.get("pitch"), _DEFAULT_PITCH, minimum=0.1, maximum=4.0)
    timeout_seconds = max(_float_option(options.get("timeoutSeconds"), float(_DEFAULT_TIMEOUT_SECONDS)), 1.0)
    command = ["termux-tts-speak", "-r", _format_float(rate), "-p", _format_float(pitch)]

    language = str(options.get("language", _DEFAULT_LANGUAGE) or "").strip()
    if language:
        command.extend(["-l", language])
    stream = str(options.get("stream", _DEFAULT_STREAM) or "").strip()
    if stream:
        command.extend(["-s", stream])
    engine = str(options.get("engine", "") or "").strip()
    if engine:
        command.extend(["-e", engine])
    region = str(options.get("region", "") or "").strip()
    if region:
        command.extend(["-n", region])
    variant = str(options.get("variant", "") or "").strip()
    if variant:
        command.extend(["-v", variant])
    command.append(text)

    bot.termux_command(
        command,
        timeout_seconds=timeout_seconds,
        ref_id=ref_id,
        error_prefix="음성 출력에 실패했습니다",
    )


def _limit_text(text: str, max_chars: int) -> str:
    limit = max(max_chars, 1)
    return text if len(text) <= limit else text[:limit]


def _bounded_float(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    parsed = _float_option(value, default)
    return min(max(parsed, minimum), maximum)


def _float_option(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_option(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _format_float(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _log_failure(runtime: BotRuntime, message: str, exc: Exception, ref_id: str | None) -> None:
    runtime.logger.warning("%s: %s", message, exc)
    enqueue_bridge_log("WARN", "chatbot", f"{message}: {exc}", ref_id)
