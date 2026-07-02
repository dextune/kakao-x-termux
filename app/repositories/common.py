from __future__ import annotations

import json
from typing import Any, Optional


def decode_json_dict(raw: Optional[str]) -> dict[str, Any]:
    """DB에 저장된 JSON object 문자열을 안전하게 dict로 복원한다."""

    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}
