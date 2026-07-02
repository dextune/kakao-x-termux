from __future__ import annotations

from typing import Any

from app import repository


class BotOptionStore:
    """전역/방별 봇 옵션을 병합해 프로세서에 제공한다."""

    def global_options(self, bot_key: str) -> dict[str, Any]:
        row = repository.get_chatbot_module(bot_key)
        if row is None:
            return {}
        return _json_dict(row["options_json"])

    def room_options(self, room_key: str, bot_key: str) -> tuple[bool, dict[str, Any]]:
        row = repository.get_room_bot_options(room_key, bot_key)
        if row is None:
            return True, {}
        return bool(row["enabled"]), _json_dict(row["options_json"])

    def merged_options(self, room_key: str, bot_key: str, defaults: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        options = dict(defaults)
        options.update(self.global_options(bot_key))
        enabled, room_options = self.room_options(room_key, bot_key)
        options.update(room_options)
        return enabled, options

    def merged_options_from_rows(
        self,
        bot_key: str,
        defaults: dict[str, Any],
        module_row: Any | None,
        room_row: Any | None,
    ) -> tuple[bool, dict[str, Any]]:
        """batch 조회된 row에서 전역/방별 옵션을 병합한다."""

        options = dict(defaults)
        if module_row is not None:
            options.update(_json_dict(module_row["options_json"]))
        if room_row is None:
            return True, options
        options.update(_json_dict(room_row["options_json"]))
        return bool(room_row["enabled"]), options


def _json_dict(raw: str | None) -> dict[str, Any]:
    import json

    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


ALLOWED_OPTION_TYPES = {"string", "integer", "number", "boolean", "array", "object"}


def validate_option_schema(schema: dict[str, Any]) -> None:
    """봇이 선언한 옵션 schema의 구조만 검증한다."""

    if not isinstance(schema, dict):
        raise ValueError("optionSchema must be object")
    for name, spec in schema.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("optionSchema key must be non-empty string")
        if not isinstance(spec, dict):
            raise ValueError(f"option schema for {name} must be object")
        option_type = spec.get("type")
        if option_type not in ALLOWED_OPTION_TYPES:
            raise ValueError(f"option schema for {name} has invalid type: {option_type}")
        if "description" in spec and not isinstance(spec["description"], str):
            raise ValueError(f"option schema for {name} description must be string")
        if "nullable" in spec and not isinstance(spec["nullable"], bool):
            raise ValueError(f"option schema for {name} nullable must be boolean")
        if "choices" in spec:
            choices = spec["choices"]
            if not isinstance(choices, list):
                raise ValueError(f"option schema for {name} choices must be array")
            for choice in choices:
                _validate_option_value(name, choice, spec)
        if "min" in spec and not isinstance(spec["min"], (int, float)):
            raise ValueError(f"option schema for {name} min must be number")
        if "max" in spec and not isinstance(spec["max"], (int, float)):
            raise ValueError(f"option schema for {name} max must be number")
        if "min" in spec and "max" in spec and float(spec["min"]) > float(spec["max"]):
            raise ValueError(f"option schema for {name} min cannot exceed max")
        if "default" in spec:
            _validate_option_value(name, spec["default"], spec)


def validate_default_options(defaults: dict[str, Any], schema: dict[str, Any]) -> None:
    """`default_options`와 schema의 default 값이 충돌하지 않는지 확인한다."""

    for name, spec in schema.items():
        if not isinstance(spec, dict) or "default" not in spec or name not in defaults:
            continue
        if defaults[name] != spec["default"]:
            raise ValueError(f"default option conflict for {name}: {defaults[name]!r} != {spec['default']!r}")


def validate_options(options: dict[str, Any], schema: dict[str, Any]) -> None:
    """API로 저장하려는 옵션 값이 봇 schema를 만족하는지 검증한다."""

    if not isinstance(options, dict):
        raise ValueError("options must be object")
    if not schema:
        if options:
            raise ValueError("bot has no option schema")
        return
    unknown = sorted(set(options) - set(schema))
    if unknown:
        raise ValueError(f"unknown option: {unknown[0]}")
    for name, value in options.items():
        _validate_option_value(name, value, schema[name])


def _validate_option_value(name: str, value: Any, spec: dict[str, Any]) -> None:
    if value is None:
        if spec.get("nullable", False):
            return
        raise ValueError(f"option {name} cannot be null")

    option_type = spec.get("type")
    if option_type == "string":
        if not isinstance(value, str):
            raise ValueError(f"option {name} must be string")
    elif option_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"option {name} must be integer")
    elif option_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"option {name} must be number")
    elif option_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"option {name} must be boolean")
    elif option_type == "array":
        if not isinstance(value, list):
            raise ValueError(f"option {name} must be array")
    elif option_type == "object":
        if not isinstance(value, dict):
            raise ValueError(f"option {name} must be object")
    else:
        raise ValueError(f"option {name} has invalid schema type")

    if "choices" in spec and value not in spec["choices"]:
        raise ValueError(f"option {name} must be one of {spec['choices']}")
    if option_type in {"integer", "number"}:
        numeric = float(value)
        if "min" in spec and numeric < float(spec["min"]):
            raise ValueError(f"option {name} must be >= {spec['min']}")
        if "max" in spec and numeric > float(spec["max"]):
            raise ValueError(f"option {name} must be <= {spec['max']}")
