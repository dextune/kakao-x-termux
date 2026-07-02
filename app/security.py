from __future__ import annotations
from fastapi import HTTPException

from app.config import get_settings


def verify_token(token: str) -> None:
    """body token을 shared secret과 비교해 쓰기 API를 보호한다."""

    if token != get_settings().shared_secret:
        raise HTTPException(status_code=401, detail="invalid token")
