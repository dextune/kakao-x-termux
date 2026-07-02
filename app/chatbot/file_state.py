from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class BotFileSnapshot:
    """봇 파일 변경 감지를 위한 최소 메타데이터다."""

    path: str
    file_name: str
    size_bytes: int
    mtime_ns: int
    sha256: str | None = None


@dataclass
class BotLoadState:
    """파일 하나의 마지막 로딩 상태를 표현한다."""

    snapshot: BotFileSnapshot
    bot_key: str | None
    status: Literal["loaded", "failed", "removed"]
    last_error: str | None = None
    loaded_at: int | None = None


def snapshot_file(path: Path, include_hash: bool = False) -> BotFileSnapshot:
    """파일 크기와 수정 시각, 선택적 hash를 읽어 snapshot을 만든다."""

    stat = path.stat()
    sha256 = _sha256(path) if include_hash else None
    return BotFileSnapshot(
        path=str(path.resolve()),
        file_name=path.name,
        size_bytes=int(stat.st_size),
        mtime_ns=int(stat.st_mtime_ns),
        sha256=sha256,
    )


def snapshot_bot_package(bot_py: Path, include_hash: bool = False) -> BotFileSnapshot:
    """폴더형 봇의 `bot.py`와 `bot.md`를 하나의 reload snapshot으로 묶는다.

    Args:
        bot_py: 봇 폴더 아래의 `bot.py` 경로. 파일이 없을 수도 있다.
        include_hash: True이면 `bot.py`와 `bot.md` 내용을 함께 hash에 반영한다.

    Returns:
        `chatbot_module_files`에 기록할 패키지 단위 snapshot.
    """

    bot_dir = bot_py.parent
    files = [bot_py, bot_dir / "bot.md"]
    existing = [path for path in files if path.exists()]
    stats = [path.stat() for path in existing]
    if bot_dir.exists():
        stats.append(bot_dir.stat())
    size_bytes = sum(int(stat.st_size) for stat in stats[: len(existing)])
    mtime_ns = max((int(stat.st_mtime_ns) for stat in stats), default=0)
    sha256 = _package_sha256(files) if include_hash else None
    return BotFileSnapshot(
        path=str(bot_py.resolve()),
        file_name=f"{bot_dir.name}/bot.py",
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        sha256=sha256,
    )


def snapshot_changed(previous: BotFileSnapshot | None, current: BotFileSnapshot) -> bool:
    """이전 snapshot과 현재 snapshot이 의미 있게 다른지 판단한다."""

    if previous is None:
        return True
    return (
        previous.size_bytes != current.size_bytes
        or previous.mtime_ns != current.mtime_ns
        or previous.sha256 != current.sha256
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_sha256(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        if not path.exists():
            digest.update(b"\0missing")
            continue
        digest.update(b"\0present")
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(64 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()
