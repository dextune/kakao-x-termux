from __future__ import annotations

from dataclasses import asdict, dataclass
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
import time
from uuid import uuid4

import httpx

from app.config import Settings
from app.infra.errors import safe_bridge_log
from app.repository import claim_reply_job_for_dispatch, complete_reply_job_if_owned, mark_reply_job_retrying_if_owned
from app.reply_dispatcher import dispatch_reply
from app.schemas import BridgeMode, ReplyCommand, ReplyJobStatus


@dataclass
class DispatchQueueStats:
    """비동기 답장 dispatch queue의 현재/누적 상태다."""

    queued: int = 0
    running: int = 0
    submitted: int = 0
    sent: int = 0
    failed: int = 0
    retrying: int = 0
    rejected: int = 0


@dataclass
class DispatchTask:
    """adapter worker가 처리할 답장 명령 단위다."""

    command: ReplyCommand
    bridge_mode: BridgeMode
    max_attempts: int


class DispatchQueue:
    """`/send` 요청과 adapter 호출을 분리하는 비동기 dispatch worker pool이다."""

    def __init__(self, settings: Settings, http_client: httpx.Client) -> None:
        self._queue: Queue[DispatchTask] = Queue(maxsize=max(settings.dispatch_queue_size, 1))
        self._http_client = http_client
        self._max_attempts = max(settings.dispatch_max_attempts, 1)
        self._retry_backoff_seconds = max(settings.dispatch_retry_backoff_ms, 0) / 1000
        self._lease_millis = max(settings.dispatch_lease_ms, 1)
        self._owner_prefix = uuid4().hex
        self._stop = Event()
        self._lock = Lock()
        self._stats = DispatchQueueStats()
        self._workers = [
            Thread(target=self._worker_loop, name=f"dispatch-worker-{idx}", daemon=True)
            for idx in range(max(settings.dispatch_workers, 1))
        ]
        for worker in self._workers:
            worker.start()

    def enqueue(self, command: ReplyCommand, bridge_mode: BridgeMode) -> bool:
        """답장 명령을 dispatch queue에 넣는다.

        Returns:
            queue에 수락되면 True, queue full이면 False.
        """

        try:
            self._queue.put_nowait(DispatchTask(command, bridge_mode, self._max_attempts))
        except Full:
            with self._lock:
                self._stats.rejected += 1
            return False
        with self._lock:
            self._stats.submitted += 1
        return True

    def stats(self) -> dict[str, int]:
        with self._lock:
            stats = asdict(self._stats)
        stats["queued"] = self._queue.qsize()
        return stats

    def shutdown(self, wait: bool = True) -> None:
        self._stop.set()
        if wait:
            for worker in self._workers:
                worker.join(timeout=5)

    def _worker_loop(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            try:
                task = self._queue.get(timeout=0.1)
            except Empty:
                continue
            with self._lock:
                self._stats.running += 1
            try:
                self._dispatch(task)
            finally:
                with self._lock:
                    self._stats.running -= 1
                self._queue.task_done()

    def _dispatch(self, task: DispatchTask) -> None:
        job_id = task.command.jobId or task.command.dedupeKey or ""
        terminal_no_retry = {
            ReplyJobStatus.token_expired,
            ReplyJobStatus.handle_expired,
            ReplyJobStatus.duplicate,
        }
        for attempt in range(1, task.max_attempts + 1):
            owner = f"{self._owner_prefix}:{job_id}:{attempt}:{time.monotonic_ns()}"
            try:
                claimed = claim_reply_job_for_dispatch(job_id, owner, self._lease_millis)
                if not claimed:
                    return
                result = dispatch_reply(
                    task.command,
                    task.bridge_mode.value,
                    http_client=self._http_client,
                )
            except Exception as exc:
                result_status = ReplyJobStatus.failed
                result_error = str(exc)
                result_ok = False
            else:
                result_status = result.status
                result_error = result.error
                result_ok = result.ok

            if result_ok and result_status == ReplyJobStatus.sent:
                if complete_reply_job_if_owned(job_id, owner, ReplyJobStatus.sent, result_error):
                    with self._lock:
                        self._stats.sent += 1
                return

            if result_status in terminal_no_retry:
                if complete_reply_job_if_owned(job_id, owner, result_status, result_error):
                    with self._lock:
                        self._stats.failed += 1
                return

            if attempt < task.max_attempts:
                if not mark_reply_job_retrying_if_owned(job_id, owner, result_error):
                    return
                with self._lock:
                    self._stats.retrying += 1
                if self._retry_backoff_seconds > 0:
                    time.sleep(self._retry_backoff_seconds)
                continue

            terminal = result_status if result_status != ReplyJobStatus.retrying else ReplyJobStatus.failed
            if terminal in (ReplyJobStatus.queued, ReplyJobStatus.dispatching, ReplyJobStatus.pending):
                terminal = ReplyJobStatus.failed
            if complete_reply_job_if_owned(job_id, owner, terminal, result_error):
                with self._lock:
                    self._stats.failed += 1
                safe_bridge_log("WARN", "dispatch", f"async dispatch failed: {result_error}", job_id)
