from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
import json
import time
from threading import Event, RLock, Thread
from typing import Any, Protocol

from app import repository
from app.config import get_settings
from app.infra.async_writes import enqueue_bridge_log
from app.repositories.common import decode_json_dict
from app.time_utils import now_millis


@dataclass
class MemoryStateEntry:
    """메모리 상태 cache에 보관하는 checkpoint 후보다."""

    state_key: str
    bot_key: str
    room_key: str
    sender: str | None
    value: dict[str, Any]
    expires_at: int | None
    updated_at: int


@dataclass
class MemoryStateCacheStats:
    """운영 health에서 확인할 state cache 통계다."""

    entries: int = 0
    dirty: int = 0
    hits: int = 0
    misses: int = 0
    writes: int = 0
    flushes: int = 0
    evicted: int = 0
    rejected: int = 0
    failed: int = 0


class StateSnapshotWriter(Protocol):
    """dirty state snapshot을 비동기 SQLite writer에 위임하기 위한 최소 인터페이스다."""

    def enqueue_state_snapshot(
        self,
        state_key: str,
        bot_key: str,
        room_key: str,
        sender: str | None,
        value: dict,
        expires_at: int | None = None,
    ) -> bool:
        """state snapshot write task를 queue에 적재한다."""

    def wait_until_idle(self, timeout_seconds: float = 5.0) -> bool:
        """명시 flush에서 writer queue drain을 기다린다."""

    def enqueue_state_delete(self, state_key: str) -> bool:
        """state delete task를 queue에 적재한다."""

    def enqueue_state_prune(self, now: int | None = None) -> bool:
        """만료 state prune task를 queue에 적재한다."""


class MemoryStateCache:
    """챗봇 상태를 메모리에서 원자적으로 처리하고 dirty checkpoint를 SQLite에 flush한다."""

    def __init__(self, snapshot_writer_provider: Callable[[], StateSnapshotWriter | None] | None = None) -> None:
        self._lock = RLock()
        self._entries: dict[str, MemoryStateEntry] = {}
        self._dirty: set[str] = set()
        self._deleted: set[str] = set()
        self._last_flush_at = now_millis()
        self._stats = MemoryStateCacheStats()
        self._snapshot_writer_provider = snapshot_writer_provider

    def warmup(self) -> int:
        settings = get_settings()
        if not settings.memory_state_enabled or not settings.memory_state_warmup_enabled:
            return 0
        rows = repository.list_bot_state_snapshots(limit=max(settings.memory_state_max_entries, 1))
        loaded = 0
        with self._lock:
            self._entries.clear()
            self._dirty.clear()
            self._deleted.clear()
            for row in rows:
                self._entries[row["state_key"]] = MemoryStateEntry(
                    state_key=row["state_key"],
                    bot_key=row["bot_key"],
                    room_key=row["room_key"],
                    sender=row["sender"],
                    value=decode_json_dict(row["state_json"]),
                    expires_at=row["expires_at"],
                    updated_at=row["updated_at"],
                )
                loaded += 1
            self._stats.entries = len(self._entries)
        return loaded

    def clear(self) -> None:
        """테스트 DB 전환 또는 startup warmup 전에 memory cache를 비운다."""

        with self._lock:
            self._entries.clear()
            self._dirty.clear()
            self._deleted.clear()
            self._stats.entries = 0
            self._stats.dirty = 0

    def get(self, key: str) -> dict[str, Any] | None:
        if not get_settings().memory_state_enabled:
            return None
        current = now_millis()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._stats.misses += 1
                return None
            if entry.expires_at is not None and entry.expires_at <= current:
                self._entries.pop(key, None)
                self._dirty.discard(key)
                self._deleted.add(key)
                self._stats.evicted += 1
                self._stats.misses += 1
                self._delete_persisted_state(key)
                return None
            self._stats.hits += 1
            return dict(entry.value)

    def put(
        self,
        key: str,
        value: dict[str, Any],
        *,
        bot_key: str,
        room_key: str,
        sender: str | None,
        expires_at: int | None,
    ) -> bool:
        settings = get_settings()
        if not settings.memory_state_enabled:
            return False
        if not self._fits_size(bot_key, key, value):
            with self._lock:
                self._stats.rejected += 1
            return False
        current = now_millis()
        with self._lock:
            self._entries[key] = MemoryStateEntry(
                state_key=key,
                bot_key=bot_key,
                room_key=room_key,
                sender=sender,
                value=dict(value),
                expires_at=expires_at,
                updated_at=current,
            )
            self._dirty.add(key)
            self._deleted.discard(key)
            self._stats.writes += 1
            self._evict_if_needed_locked(settings.memory_state_max_entries)
        self.flush_if_due()
        return True

    def remember_clean(
        self,
        key: str,
        value: dict[str, Any],
        *,
        bot_key: str,
        room_key: str,
        sender: str | None,
        expires_at: int | None = None,
    ) -> None:
        """DB fallback으로 읽은 상태를 dirty 표시 없이 memory cache에 올린다."""

        if not get_settings().memory_state_enabled:
            return
        with self._lock:
            self._entries[key] = MemoryStateEntry(
                state_key=key,
                bot_key=bot_key,
                room_key=room_key,
                sender=sender,
                value=dict(value),
                expires_at=expires_at,
                updated_at=now_millis(),
            )
            self._deleted.discard(key)
            self._evict_if_needed_locked(get_settings().memory_state_max_entries)

    def mutate(
        self,
        key: str,
        updater: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        bot_key: str,
        room_key: str,
        sender: str | None,
        expires_at: int | None,
    ) -> tuple[dict[str, Any], bool]:
        settings = get_settings()
        if not settings.memory_state_enabled:
            return {}, False
        current = now_millis()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.expires_at is not None and entry.expires_at <= current:
                self._entries.pop(key, None)
                self._dirty.discard(key)
                self._deleted.add(key)
                self._stats.evicted += 1
                self._stats.misses += 1
                self._delete_persisted_state(key)
                base = {}
            elif entry is None:
                base = self._load_from_repository(key, current)
                self._stats.misses += 1
            else:
                base = dict(entry.value)
                self._stats.hits += 1
            updated = updater(dict(base))
            if not self._fits_size(bot_key, key, updated):
                self._stats.rejected += 1
                return base, False
            self._entries[key] = MemoryStateEntry(
                state_key=key,
                bot_key=bot_key,
                room_key=room_key,
                sender=sender,
                value=dict(updated),
                expires_at=expires_at,
                updated_at=current,
            )
            self._dirty.add(key)
            self._deleted.discard(key)
            self._stats.writes += 1
            self._evict_if_needed_locked(settings.memory_state_max_entries)
        self.flush_if_due()
        return dict(updated), True

    def delete(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)
            self._dirty.discard(key)
            self._deleted.add(key)

    def flush_if_due(self) -> int:
        settings = get_settings()
        current = now_millis()
        if current - self._last_flush_at < max(settings.memory_state_flush_interval_ms, 0):
            return 0
        return self.flush_dirty(wait=False)

    def flush_dirty(self, wait: bool = True) -> int:
        with self._lock:
            keys = list(self._dirty)
            entries = [self._entries[key] for key in keys if key in self._entries]
        writer = self._snapshot_writer()
        flushed = 0
        failed = 0
        for entry in entries:
            saved = False
            if writer is not None:
                saved = writer.enqueue_state_snapshot(
                    entry.state_key,
                    entry.bot_key,
                    entry.room_key,
                    entry.sender,
                    entry.value,
                    entry.expires_at,
                )
            else:
                saved = repository.set_bot_state(
                    entry.state_key,
                    entry.bot_key,
                    entry.room_key,
                    entry.sender,
                    entry.value,
                    entry.expires_at,
                )
            if saved:
                flushed += 1
                with self._lock:
                    self._dirty.discard(entry.state_key)
            else:
                failed += 1
        if wait and writer is not None and flushed:
            if not writer.wait_until_idle(timeout_seconds=5):
                failed += 1
        with self._lock:
            self._last_flush_at = now_millis()
            self._stats.flushes += flushed
            self._stats.failed += failed
            self._evict_if_needed_locked(get_settings().memory_state_max_entries)
            self._stats.entries = len(self._entries)
            self._stats.dirty = len(self._dirty)
        return flushed

    def stats(self) -> dict[str, int]:
        with self._lock:
            self._stats.entries = len(self._entries)
            self._stats.dirty = len(self._dirty)
            return asdict(self._stats)

    def _load_from_repository(self, key: str, current: int) -> dict[str, Any]:
        snapshot = repository.get_bot_state_snapshot(key)
        if snapshot is None:
            self._entries.pop(key, None)
            self._dirty.discard(key)
            return {}
        value = dict(snapshot["value"])
        self._entries[key] = MemoryStateEntry(
            state_key=key,
            bot_key=str(snapshot["bot_key"]),
            room_key=str(snapshot["room_key"]),
            sender=snapshot["sender"],
            value=value,
            expires_at=snapshot["expires_at"],
            updated_at=int(snapshot["updated_at"] or current),
        )
        return value

    def recently_deleted(self, key: str) -> bool:
        with self._lock:
            return key in self._deleted

    def _evict_if_needed_locked(self, max_entries: int) -> None:
        limit = max(max_entries, 1)
        while len(self._entries) > limit:
            clean_candidates = [key for key in self._entries if key not in self._dirty]
            if not clean_candidates:
                break
            key = clean_candidates[0]
            self._entries.pop(key, None)
            self._dirty.discard(key)
            self._stats.evicted += 1

    def _fits_size(self, bot_key: str, key: str, value: dict[str, Any]) -> bool:
        state_json = json.dumps(value, ensure_ascii=False, sort_keys=True)
        max_bytes = max(get_settings().chatbot_max_state_bytes, 0)
        if not max_bytes or len(state_json.encode("utf-8")) <= max_bytes:
            return True
        enqueue_bridge_log(
            "ERROR",
            "chatbot_state",
            f"state too large botKey={bot_key} stateKey={key} bytes={len(state_json.encode('utf-8'))} maxBytes={max_bytes}",
            key,
        )
        return False

    def _snapshot_writer(self) -> StateSnapshotWriter | None:
        if self._snapshot_writer_provider is None:
            return None
        try:
            return self._snapshot_writer_provider()
        except Exception:
            return None

    def _delete_persisted_state(self, key: str) -> None:
        writer = self._snapshot_writer()
        if writer is not None:
            writer.enqueue_state_delete(key)
            return
        repository.delete_bot_state(key)


class BotStateStore:
    """챗봇별 영속 상태를 SQLite에 저장하는 공통 API다."""

    def __init__(
        self,
        cache: MemoryStateCache | None = None,
        snapshot_writer_provider: Callable[[], StateSnapshotWriter | None] | None = None,
    ) -> None:
        self.cache = cache or MemoryStateCache(snapshot_writer_provider=snapshot_writer_provider)
        self._flush_stop = Event()
        self._flush_thread: Thread | None = None

    def startup(self) -> int:
        """SQLite checkpoint에서 memory state cache를 warmup한다."""

        self.cache.clear()
        loaded = self.cache.warmup()
        self._start_background_flush()
        return loaded

    def shutdown(self) -> None:
        """종료 전 dirty state를 SQLite checkpoint로 flush한다."""

        self._stop_background_flush()
        self.flush_dirty()

    def flush_dirty(self) -> int:
        return self.cache.flush_dirty()

    def stats(self) -> dict[str, int]:
        return self.cache.stats()

    def get(self, key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
        value = self.cache.get(key)
        if value is None and not self.cache.recently_deleted(key):
            snapshot = repository.get_bot_state_snapshot(key)
            if snapshot is not None:
                value = dict(snapshot["value"])
                self.cache.remember_clean(
                    key,
                    value,
                    bot_key=str(snapshot["bot_key"]),
                    room_key=str(snapshot["room_key"]),
                    sender=snapshot["sender"],
                    expires_at=snapshot["expires_at"],
                )
        if value is None:
            return dict(default or {})
        return value

    def set(
        self,
        key: str,
        value: dict[str, Any],
        ttlMillis: int | None = None,
        botKey: str | None = None,
        roomKey: str | None = None,
        sender: str | None = None,
    ) -> None:
        parsed = parse_state_key(key)
        expires_at = now_millis() + ttlMillis if ttlMillis is not None else None
        saved = self.cache.put(
            key,
            value,
            bot_key=botKey or str(parsed["botKey"]),
            room_key=roomKey or str(parsed["roomKey"]),
            sender=sender if sender is not None else parsed["sender"],
            expires_at=expires_at,
        )
        if not saved and not get_settings().memory_state_enabled:
            repository.set_bot_state(
                state_key=key,
                bot_key=botKey or parsed["botKey"],
                room_key=roomKey or parsed["roomKey"],
                sender=sender if sender is not None else parsed["sender"],
                value=value,
                expires_at=expires_at,
            )

    def update(
        self,
        key: str,
        patch: dict[str, Any],
        ttlMillis: int | None = None,
        botKey: str | None = None,
        roomKey: str | None = None,
        sender: str | None = None,
    ) -> dict[str, Any]:
        def apply_patch(value: dict[str, Any]) -> dict[str, Any]:
            value.update(patch)
            return value

        return self.mutate(
            key,
            apply_patch,
            ttlMillis=ttlMillis,
            botKey=botKey,
            roomKey=roomKey,
            sender=sender,
        )

    def mutate(
        self,
        key: str,
        updater: Callable[[dict[str, Any]], dict[str, Any]],
        ttlMillis: int | None = None,
        botKey: str | None = None,
        roomKey: str | None = None,
        sender: str | None = None,
    ) -> dict[str, Any]:
        """현재 상태 조회와 갱신을 하나의 SQLite transaction으로 처리한다."""

        parsed = parse_state_key(key)
        expires_at = now_millis() + ttlMillis if ttlMillis is not None else None
        updated, saved = self.cache.mutate(
            key,
            updater,
            bot_key=botKey or str(parsed["botKey"]),
            room_key=roomKey or str(parsed["roomKey"]),
            sender=sender if sender is not None else parsed["sender"],
            expires_at=expires_at,
        )
        if saved:
            return updated
        return repository.update_bot_state(
            state_key=key,
            bot_key=botKey or parsed["botKey"],
            room_key=roomKey or parsed["roomKey"],
            sender=sender if sender is not None else parsed["sender"],
            updater=updater,
            expires_at=expires_at,
        )

    def mutate_result(
        self,
        key: str,
        updater: Callable[[dict[str, Any]], dict[str, Any]],
        ttlMillis: int | None = None,
        botKey: str | None = None,
        roomKey: str | None = None,
        sender: str | None = None,
    ) -> "StateWriteResult":
        """현재 상태 조회와 갱신을 transaction으로 처리하고 저장 성공 여부를 반환한다."""

        parsed = parse_state_key(key)
        expires_at = now_millis() + ttlMillis if ttlMillis is not None else None
        value, saved = self.cache.mutate(
            key,
            updater,
            bot_key=botKey or str(parsed["botKey"]),
            room_key=roomKey or str(parsed["roomKey"]),
            sender=sender if sender is not None else parsed["sender"],
            expires_at=expires_at,
        )
        if not saved and not get_settings().memory_state_enabled:
            value, saved = repository.update_bot_state_with_result(
                state_key=key,
                bot_key=botKey or parsed["botKey"],
                room_key=roomKey or parsed["roomKey"],
                sender=sender if sender is not None else parsed["sender"],
                updater=updater,
                expires_at=expires_at,
            )
        return StateWriteResult(saved=saved, value=value, error=None if saved else "state write rejected")

    def delete(self, key: str) -> None:
        self.cache.delete(key)
        self.cache._delete_persisted_state(key)

    def prune_expired(self) -> int:
        writer = self.cache._snapshot_writer()
        if writer is not None:
            writer.enqueue_state_prune(now_millis())
            return 0
        return repository.prune_bot_states()

    def make_key(self, botKey: str, roomKey: str, sender: str | None, scope: str) -> str:
        clean_sender = sender or "_"
        return f"{botKey}|{roomKey}|{clean_sender}|{scope}"

    def _start_background_flush(self) -> None:
        settings = get_settings()
        if not settings.memory_state_enabled or not settings.memory_state_background_flush_enabled:
            return
        if settings.memory_state_flush_interval_ms <= 0:
            return
        if self._flush_thread is not None and self._flush_thread.is_alive():
            return
        self._flush_stop.clear()
        self._flush_thread = Thread(target=self._background_flush_loop, name="memory-state-flush", daemon=True)
        self._flush_thread.start()

    def _stop_background_flush(self) -> None:
        self._flush_stop.set()
        thread = self._flush_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
        self._flush_thread = None

    def _background_flush_loop(self) -> None:
        while True:
            interval = max(get_settings().memory_state_flush_interval_ms, 100) / 1000
            if self._flush_stop.wait(interval):
                return
            try:
                self.cache.flush_dirty(wait=False)
            except Exception:
                continue


def parse_state_key(key: str) -> dict[str, str | None]:
    parts = key.split("|", 3)
    if len(parts) != 4:
        return {"botKey": "unknown", "roomKey": "unknown", "sender": None, "scope": key}
    sender = None if parts[2] == "_" else parts[2]
    return {"botKey": parts[0], "roomKey": parts[1], "sender": sender, "scope": parts[3]}


@dataclass(frozen=True)
class StateWriteResult:
    """상태 저장 helper가 반환하는 저장 결과다."""

    saved: bool
    value: dict[str, Any]
    error: str | None = None
