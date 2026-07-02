from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
import threading
import time
from typing import Callable, Generic, Literal, TypeVar

T = TypeVar("T")


ExternalTaskStatus = Literal["completed", "rejected", "timeout", "failed"]


@dataclass(frozen=True)
class ExternalRunnerStats:
    """외부 I/O runner 운영 지표다."""

    queued: int
    running: int
    submitted: int
    completed: int
    rejected: int
    timeout: int
    failed: int


@dataclass(frozen=True)
class ExternalTaskResult(Generic[T]):
    """외부 I/O 작업 실행 결과다."""

    ok: bool
    status: ExternalTaskStatus
    value: T | None = None
    error: str | None = None
    durationMs: int = 0


class ExternalTaskRunner:
    """외부 I/O 작업을 제한된 worker/queue로 실행하는 공통 runner다."""

    def __init__(self, max_workers: int, queue_size: int, name: str = "external") -> None:
        self.name = name
        self.max_workers = max(max_workers, 1)
        self.queue_size = max(queue_size, 0)
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix=name)
        # ThreadPoolExecutor의 내부 queue는 unbounded라, 별도 semaphore로 running + queued 총량을 제한한다.
        self._semaphore = threading.BoundedSemaphore(self.max_workers + self.queue_size)
        self._lock = threading.Lock()
        self._running = 0
        self._submitted = 0
        self._completed = 0
        self._rejected = 0
        self._timeout = 0
        self._failed = 0
        self._shutdown = False

    def submit(self, fn: Callable[[], T]) -> Future[T] | None:
        """queue가 가득 차면 None을 반환한다."""

        with self._lock:
            if self._shutdown:
                self._rejected += 1
                return None
        acquired = self._semaphore.acquire(blocking=False)
        if not acquired:
            with self._lock:
                self._rejected += 1
            return None
        with self._lock:
            self._submitted += 1
        try:
            future = self._executor.submit(self._run_tracked, fn)
        except Exception:
            with self._lock:
                self._failed += 1
                self._rejected += 1
            self._semaphore.release()
            return None
        future.add_done_callback(lambda _: self._finish())
        return future

    def run(self, fn: Callable[[], T], timeout_seconds: float | None = None) -> ExternalTaskResult[T]:
        """작업을 제출하고 제한 시간 동안 결과를 기다린다."""

        started = time.monotonic()
        future = self.submit(fn)
        if future is None:
            return ExternalTaskResult(
                ok=False,
                status="rejected",
                error=f"{self.name} queue full",
                durationMs=0,
            )
        try:
            value = future.result(timeout=timeout_seconds)
        except FutureTimeoutError as exc:
            if future.done():
                with self._lock:
                    self._failed += 1
                return ExternalTaskResult(
                    ok=False,
                    status="failed",
                    error=str(exc),
                    durationMs=int((time.monotonic() - started) * 1000),
                )
            future.cancel()
            with self._lock:
                self._timeout += 1
            return ExternalTaskResult(
                ok=False,
                status="timeout",
                error=f"{self.name} timeout",
                durationMs=int((time.monotonic() - started) * 1000),
            )
        except Exception as exc:
            with self._lock:
                self._failed += 1
            return ExternalTaskResult(
                ok=False,
                status="failed",
                error=str(exc),
                durationMs=int((time.monotonic() - started) * 1000),
            )
        return ExternalTaskResult(
            ok=True,
            status="completed",
            value=value,
            durationMs=int((time.monotonic() - started) * 1000),
        )

    def stats(self) -> ExternalRunnerStats:
        with self._lock:
            queued = max(self._submitted - self._completed - self._running, 0)
            return ExternalRunnerStats(
                queued=queued,
                running=self._running,
                submitted=self._submitted,
                completed=self._completed,
                rejected=self._rejected,
                timeout=self._timeout,
                failed=self._failed,
            )

    def shutdown(self, wait: bool = False) -> None:
        with self._lock:
            self._shutdown = True
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def _run_tracked(self, fn: Callable[[], T]) -> T:
        with self._lock:
            self._running += 1
        try:
            return fn()
        finally:
            with self._lock:
                self._running -= 1

    def _finish(self) -> None:
        with self._lock:
            self._completed += 1
        self._semaphore.release()
