from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from queue import Full, Queue
import sqlite3
from threading import Condition, Event, Lock, Thread
import time
from uuid import uuid4

from app import repository
from app.config import Settings
from app.schemas import BridgeEvent, EventResponse
from app.time_utils import now_millis


@dataclass
class InMemoryEventEnvelope:
    """메모리 파이프라인에서 room worker로 전달하는 수신 이벤트 단위다.

    원본 `BridgeEvent` 계약은 유지하고, 처리 순서와 운영 통계를 위한 메타데이터만 덧붙인다.
    """

    event: BridgeEvent
    received_monotonic_ns: int
    accepted_at: int
    trace_id: str
    dedupe_key: str
    priority: int = 0
    checkpoint_processed: bool = True


@dataclass
class PipelineStats:
    """health API에 노출할 memory pipeline 누적/현재 상태다."""

    queued: int = 0
    active: int = 0
    accepted: int = 0
    processed: int = 0
    duplicate: int = 0
    rejected: int = 0
    dropped: int = 0
    errors: int = 0
    activeRooms: int = 0
    readyRooms: int = 0
    oldestAgeMs: int = 0


@dataclass
class SqliteWriterStats:
    """비동기 SQLite writer의 queue와 처리 결과 통계다."""

    queued: int = 0
    submitted: int = 0
    written: int = 0
    dropped: int = 0
    failed: int = 0
    stateSnapshotSubmitted: int = 0
    stateSnapshotWritten: int = 0
    stateSnapshotFailed: int = 0


@dataclass
class SqliteWriteTask:
    """SQLite writer가 순차 실행할 쓰기 작업이다."""

    kind: str
    payload: tuple
    priority: int = 0


@dataclass
class EnqueueResult:
    """`/events` ingress 단계의 memory queue 수락 결과다."""

    accepted: bool
    duplicate: bool = False
    error: str | None = None


class AsyncSqliteWriter:
    """SQLite 쓰기를 hot path 밖에서 단일 worker로 순차 처리한다."""

    def __init__(self, settings: Settings) -> None:
        self._batch_size = max(settings.sqlite_writer_batch_size, 1)
        self._flush_interval = max(settings.sqlite_writer_flush_interval_ms, 1) / 1000
        self._drop_low_priority = settings.sqlite_writer_drop_low_priority
        self._queue: Queue[SqliteWriteTask] = Queue(maxsize=max(settings.sqlite_writer_queue_size, 1))
        self._stop = Event()
        self._thread = Thread(target=self._run, name="sqlite-writer", daemon=True)
        self._lock = Lock()
        self._stats = SqliteWriterStats()
        self._thread.start()

    def enqueue_message_backup(self, event: BridgeEvent) -> bool:
        return self._enqueue(SqliteWriteTask("message_backup", (event,), priority=10))

    def enqueue_message_processed(self, event_id: str) -> bool:
        return self._enqueue(SqliteWriteTask("message_processed", (event_id,), priority=10))

    def enqueue_bridge_log(
        self,
        level: str,
        category: str,
        message: str,
        ref_id: str | None = None,
        *,
        prune: bool = False,
    ) -> bool:
        return self._enqueue(SqliteWriteTask("bridge_log", (level, category, message, ref_id, prune), priority=1))

    def enqueue_chatbot_run(
        self,
        event_id: str,
        bot_key: str,
        action: str,
        reason: str | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> bool:
        return self._enqueue(
            SqliteWriteTask("chatbot_run", (event_id, bot_key, action, reason, duration_ms, error), priority=1)
        )

    def enqueue_state_snapshot(
        self,
        state_key: str,
        bot_key: str,
        room_key: str,
        sender: str | None,
        value: dict,
        expires_at: int | None = None,
    ) -> bool:
        """dirty bot state checkpoint를 writer queue에 적재한다."""

        return self._enqueue(
            SqliteWriteTask("state_snapshot", (state_key, bot_key, room_key, sender, dict(value), expires_at), priority=5)
        )

    def enqueue_state_delete(self, state_key: str) -> bool:
        """만료/명시 삭제된 state를 writer queue에서 제거한다."""

        return self._enqueue(SqliteWriteTask("state_delete", (state_key,), priority=5))

    def enqueue_state_prune(self, now: int | None = None) -> bool:
        """만료 state 일괄 삭제를 writer queue에 적재한다."""

        return self._enqueue(SqliteWriteTask("state_prune", (now,), priority=5))

    def stats(self) -> dict[str, int]:
        with self._lock:
            stats = asdict(self._stats)
        stats["queued"] = self._queue.qsize()
        return stats

    def wait_until_idle(self, timeout_seconds: float = 5.0) -> bool:
        """명시 flush/shutdown 검증에서 queue 처리 완료를 기다린다."""

        deadline = time.monotonic() + max(timeout_seconds, 0)
        while time.monotonic() <= deadline:
            with self._lock:
                finished = self._stats.written + self._stats.failed + self._stats.dropped
                submitted = self._stats.submitted
            if self._queue.empty() and finished >= submitted:
                return True
            time.sleep(0.005)
        return False

    def shutdown(self, wait: bool = True) -> None:
        self._stop.set()
        if wait:
            self._thread.join(timeout=5)

    def _enqueue(self, task: SqliteWriteTask) -> bool:
        try:
            self._queue.put_nowait(task)
        except Full:
            if self._drop_low_priority and task.priority <= 1:
                with self._lock:
                    self._stats.dropped += 1
                return False
            with self._lock:
                self._stats.failed += 1
            return False
        with self._lock:
            self._stats.submitted += 1
            if task.kind == "state_snapshot":
                self._stats.stateSnapshotSubmitted += 1
        return True

    def _run(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            batch = self._drain_batch()
            if not batch:
                continue
            for task in batch:
                try:
                    self._write_with_retry(task)
                    with self._lock:
                        self._stats.written += 1
                        if task.kind == "state_snapshot":
                            self._stats.stateSnapshotWritten += 1
                except Exception:
                    with self._lock:
                        self._stats.failed += 1
                        if task.kind == "state_snapshot":
                            self._stats.stateSnapshotFailed += 1

    def _write_with_retry(self, task: SqliteWriteTask) -> None:
        for attempt in range(3):
            try:
                self._write(task)
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 2:
                    raise
                time.sleep(0.02 * (attempt + 1))

    def _drain_batch(self) -> list[SqliteWriteTask]:
        batch: list[SqliteWriteTask] = []
        deadline = time.monotonic() + self._flush_interval
        while len(batch) < self._batch_size:
            timeout = max(deadline - time.monotonic(), 0.001)
            try:
                task = self._queue.get(timeout=timeout)
            except Exception:
                break
            batch.append(task)
            if time.monotonic() >= deadline:
                break
        return batch

    def _write(self, task: SqliteWriteTask) -> None:
        if task.kind == "message_backup":
            repository.insert_message(task.payload[0])
        elif task.kind == "message_processed":
            repository.mark_message_processed(task.payload[0])
        elif task.kind == "bridge_log":
            level, category, message, ref_id, prune = task.payload
            repository.insert_bridge_log(level, category, message, ref_id)
            if prune:
                settings = self._settings()
                repository.prune_bridge_logs_throttled(
                    max_rows=settings.bridge_log_max_rows,
                    retention_millis=settings.bridge_log_retention_millis,
                    interval_millis=settings.bridge_log_prune_interval_millis,
                )
        elif task.kind == "chatbot_run":
            repository.insert_chatbot_run(*task.payload)
        elif task.kind == "state_snapshot":
            if not repository.set_bot_state(*task.payload):
                raise RuntimeError("state snapshot write rejected")
        elif task.kind == "state_delete":
            repository.delete_bot_state(*task.payload)
        elif task.kind == "state_prune":
            repository.prune_bot_states(now=task.payload[0])
        else:
            raise ValueError(f"unknown sqlite write task: {task.kind}")

    def _settings(self) -> Settings:
        from app.config import get_settings

        return get_settings()


class MemoryPipeline:
    """room별 순서를 보장하는 memory-first event pipeline이다."""

    def __init__(self, settings: Settings) -> None:
        self.writer = AsyncSqliteWriter(settings)
        self._global_limit = max(settings.event_queue_size, 1)
        self._room_limit = max(settings.room_max_pending_per_room, 1)
        self._room_workers = max(settings.room_workers, 1)
        self._max_active_partitions = max(settings.room_max_active_partitions, 1)
        self._overflow_policy = settings.room_overflow_policy
        self._dedupe_ttl_ms = max(settings.event_dedupe_ttl_ms, 1)
        self._condition = Condition()
        self._room_queues: dict[str, deque[tuple[InMemoryEventEnvelope, Callable[[BridgeEvent], EventResponse]]]] = {}
        self._ready_rooms: deque[str] = deque()
        self._ready_room_set: set[str] = set()
        self._active_rooms: set[str] = set()
        self._dedupe: dict[str, int] = {}
        self._dedupe_order: deque[tuple[str, int]] = deque()
        self._queued_total = 0
        self._active_total = 0
        self._oldest_accepted_at: int | None = None
        self._stats = PipelineStats()
        self._stop = Event()
        self._workers = [
            Thread(target=self._worker_loop, name=f"memory-event-worker-{idx}", daemon=True)
            for idx in range(self._room_workers)
        ]
        for worker in self._workers:
            worker.start()

    def enqueue_event(
        self,
        event: BridgeEvent,
        processor: Callable[[BridgeEvent], EventResponse],
        *,
        backup: bool = True,
        checkpoint_processed: bool = True,
    ) -> EnqueueResult:
        """event를 room partition queue에 넣고 즉시 반환한다."""

        dedupe_key = event.eventId
        accepted_at = now_millis()
        with self._condition:
            self._evict_dedupe_locked(accepted_at)
            if dedupe_key in self._dedupe:
                self._stats.duplicate += 1
                return EnqueueResult(accepted=False, duplicate=True, error="duplicate eventId")
            known_room = event.roomKey in self._room_queues or event.roomKey in self._active_rooms
            active_partitions = len(set(self._room_queues) | self._active_rooms)
            if not known_room and active_partitions >= self._max_active_partitions:
                self._stats.rejected += 1
                return EnqueueResult(accepted=False, error="active room partition limit reached")
            room_queue = self._room_queues.setdefault(event.roomKey, deque())
            if self._queued_total >= self._global_limit:
                self._stats.rejected += 1
                return EnqueueResult(accepted=False, error="event queue full")
            if len(room_queue) >= self._room_limit:
                if self._overflow_policy == "drop_oldest" and room_queue:
                    room_queue.popleft()
                    self._queued_total -= 1
                    self._stats.dropped += 1
                else:
                    self._stats.rejected += 1
                    return EnqueueResult(accepted=False, error="room queue full")

        if backup and not self.writer.enqueue_message_backup(event):
            with self._condition:
                self._stats.rejected += 1
            return EnqueueResult(accepted=False, error="sqlite writer queue full")

        envelope = InMemoryEventEnvelope(
            event=event,
            received_monotonic_ns=time.monotonic_ns(),
            accepted_at=accepted_at,
            trace_id=uuid4().hex,
            dedupe_key=dedupe_key,
            checkpoint_processed=checkpoint_processed,
        )
        with self._condition:
            room_queue = self._room_queues.setdefault(event.roomKey, deque())
            room_queue.append((envelope, processor))
            self._dedupe[dedupe_key] = accepted_at
            self._dedupe_order.append((dedupe_key, accepted_at))
            self._queued_total += 1
            self._stats.accepted += 1
            if self._oldest_accepted_at is None or accepted_at < self._oldest_accepted_at:
                self._oldest_accepted_at = accepted_at
            self._mark_room_ready_locked(event.roomKey)
            self._condition.notify()
        return EnqueueResult(accepted=True)

    def stats(self) -> dict[str, dict[str, int] | int]:
        with self._condition:
            current = now_millis()
            self._stats.queued = self._queued_total
            self._stats.active = self._active_total
            self._stats.activeRooms = len(self._active_rooms)
            self._stats.readyRooms = len(self._ready_room_set)
            self._stats.oldestAgeMs = (
                max(current - self._oldest_accepted_at, 0) if self._oldest_accepted_at is not None else 0
            )
            pipeline = asdict(self._stats)
            room_depths = {room: len(queue) for room, queue in self._room_queues.items() if queue}
        return {
            "pipeline": pipeline,
            "sqliteWriter": self.writer.stats(),
            "rooms": room_depths,
        }

    def shutdown(self, wait: bool = True) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if wait:
            for worker in self._workers:
                worker.join(timeout=5)
        self.writer.shutdown(wait=wait)

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            item = self._next_item()
            if item is None:
                continue
            room_key, envelope, processor = item
            try:
                processor(envelope.event)
                if envelope.checkpoint_processed:
                    self.writer.enqueue_message_processed(envelope.event.eventId)
                with self._condition:
                    self._stats.processed += 1
            except Exception:
                with self._condition:
                    self._stats.errors += 1
            finally:
                with self._condition:
                    self._active_total -= 1
                    self._active_rooms.discard(room_key)
                    if self._room_queues.get(room_key):
                        self._mark_room_ready_locked(room_key)
                    self._recompute_oldest_locked()
                    self._condition.notify_all()

    def _next_item(
        self,
    ) -> tuple[str, InMemoryEventEnvelope, Callable[[BridgeEvent], EventResponse]] | None:
        with self._condition:
            while not self._stop.is_set() and not self._ready_rooms:
                self._condition.wait(timeout=0.1)
            if self._stop.is_set():
                return None
            room_key = self._ready_rooms.popleft()
            self._ready_room_set.discard(room_key)
            room_queue = self._room_queues.get(room_key)
            if not room_queue:
                return None
            envelope, processor = room_queue.popleft()
            self._queued_total -= 1
            self._active_total += 1
            self._active_rooms.add(room_key)
            if not room_queue:
                self._room_queues.pop(room_key, None)
            return room_key, envelope, processor

    def _mark_room_ready_locked(self, room_key: str) -> None:
        if room_key in self._active_rooms or room_key in self._ready_room_set:
            return
        self._ready_rooms.append(room_key)
        self._ready_room_set.add(room_key)

    def _evict_dedupe_locked(self, current: int) -> None:
        while self._dedupe_order:
            key, accepted_at = self._dedupe_order[0]
            if current - accepted_at <= self._dedupe_ttl_ms:
                break
            self._dedupe_order.popleft()
            if self._dedupe.get(key) == accepted_at:
                self._dedupe.pop(key, None)

    def _recompute_oldest_locked(self) -> None:
        oldest: int | None = None
        for queue in self._room_queues.values():
            if queue:
                accepted_at = queue[0][0].accepted_at
                oldest = accepted_at if oldest is None else min(oldest, accepted_at)
        self._oldest_accepted_at = oldest
