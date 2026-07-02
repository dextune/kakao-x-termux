from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Event, Lock, Thread

from app import repository
from app.config import get_settings
from app.infra.errors import safe_bridge_log
from app.infra.runtime_resources import RuntimeResources, get_runtime_resources
from app.schemas import BridgeEvent, BridgeMode, ReplyCommand, ReplyJobStatus
from app.services.event_service import EventService
from app.time_utils import now_millis


@dataclass
class RecoveryStats:
    """프로세스 시작 시 memory queue로 복원한 작업 수다."""

    messagesRequeued: int = 0
    replyJobsRequeued: int = 0
    failed: int = 0
    batchLimit: int = 100
    strandedQueuedReplyJobs: int = 0
    oldestStrandedQueuedAgeMs: int = 0
    scheduledRecoveries: int = 0
    schedulerRunning: int = 0


class RecoveryService:
    """SQLite checkpoint에서 미처리 event와 reply job을 memory worker로 복원한다."""

    def __init__(
        self,
        event_service: EventService,
        resources_provider=get_runtime_resources,
    ) -> None:
        self.event_service = event_service
        self._resources_provider = resources_provider
        self._stats = RecoveryStats()
        self._recover_lock = Lock()
        self._scheduler_stop = Event()
        self._scheduler_thread: Thread | None = None

    def recover(self, limit: int | None = None) -> dict[str, int]:
        """startup lifecycle에서 호출되는 best-effort recovery 경로다."""

        if not self._recover_lock.acquire(blocking=False):
            return self.stats()
        try:
            return self._recover_locked(limit)
        finally:
            self._recover_lock.release()

    def _recover_locked(self, limit: int | None = None) -> dict[str, int]:
        settings = get_settings()
        batch_limit = max(min(limit if limit is not None else settings.recovery_batch_limit, 1_000), 1)
        self._stats.batchLimit = batch_limit
        resources = self._resources_provider()
        self._recover_messages(resources, batch_limit)
        self._recover_reply_jobs(resources, batch_limit)
        return self.stats()

    def stats(self) -> dict[str, int]:
        self._refresh_stranded_reply_job_stats()
        self._stats.schedulerRunning = 1 if self._scheduler_thread is not None and self._scheduler_thread.is_alive() else 0
        return asdict(self._stats)

    def start_scheduler(self) -> None:
        """설정된 주기마다 stranded 작업 recovery를 best-effort로 재실행한다."""

        settings = get_settings()
        if not settings.recovery_scheduler_enabled:
            return
        if self._scheduler_thread is not None and self._scheduler_thread.is_alive():
            return
        self._scheduler_stop.clear()
        self._scheduler_thread = Thread(target=self._scheduler_loop, name="recovery-scheduler", daemon=True)
        self._scheduler_thread.start()

    def stop_scheduler(self) -> None:
        """FastAPI shutdown에서 recovery scheduler를 정리한다."""

        self._scheduler_stop.set()
        thread = self._scheduler_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
        self._scheduler_thread = None

    def _scheduler_loop(self) -> None:
        while True:
            interval = max(get_settings().recovery_scheduler_interval_ms, 100) / 1000
            if self._scheduler_stop.wait(interval):
                return
            try:
                self.recover()
                self._stats.scheduledRecoveries += 1
            except Exception as exc:
                self._stats.failed += 1
                safe_bridge_log("ERROR", "recovery", f"scheduled recovery failed: {exc}")

    def _refresh_stranded_reply_job_stats(self) -> None:
        metrics = repository.queued_reply_job_metrics()
        self._stats.strandedQueuedReplyJobs = metrics["count"]
        self._stats.oldestStrandedQueuedAgeMs = metrics["oldestAgeMs"]

    def _recover_messages(self, resources: RuntimeResources, limit: int) -> None:
        settings = get_settings()
        for row in repository.list_unprocessed_messages(limit=limit):
            try:
                event = BridgeEvent(
                    schemaVersion=row["schema_version"],
                    eventId=row["event_id"],
                    source=row["source"],
                    sourcePackage=row["source_package"],
                    sourceType=row["source_type"],
                    roomKey=row["room_key"],
                    room=row["room"],
                    sender=row["sender"],
                    text=row["text"],
                    messageType=row["message_type"],
                    receivedAt=row["received_at"],
                    notificationKey=row["notification_key"],
                    replyToken=row["reply_token"],
                    replyTokenExpiresAt=row["reply_token_expires_at"],
                    token=settings.shared_secret,
                )
                resources.reply_token_cache.update_from_event(event)
                result = resources.memory_pipeline.enqueue_event(
                    event,
                    self.event_service.recover_inserted_event,
                    backup=False,
                    checkpoint_processed=False,
                )
                if result.accepted:
                    self._stats.messagesRequeued += 1
                else:
                    self._stats.failed += 1
                    safe_bridge_log("WARN", "recovery", f"message recovery rejected: {result.error}", event.eventId)
            except Exception as exc:
                self._stats.failed += 1
                safe_bridge_log("ERROR", "recovery", f"message recovery failed: {exc}", row["event_id"])

    def _recover_reply_jobs(self, resources: RuntimeResources, limit: int) -> None:
        settings = get_settings()
        stale_before = now_millis() - max(settings.recovery_dispatching_stale_ms, 0)
        for row in repository.list_recoverable_reply_jobs(limit=limit, stale_dispatching_before=stale_before):
            try:
                current_status = ReplyJobStatus(row["status"])
                bridge_mode = BridgeMode(row["bridge_mode"] or settings.bridge_mode)
                command = ReplyCommand(
                    jobId=row["job_id"],
                    roomKey=row["room_key"],
                    room=row["room"],
                    text=row["text"],
                    dedupeKey=row["dedupe_key"] or row["job_id"],
                    replyToken=row["reply_token"],
                    token=settings.shared_secret,
                )
                claimed = repository.update_reply_job_if_status(
                    row["job_id"],
                    (current_status,),
                    ReplyJobStatus.queued,
                )
                if not claimed:
                    continue
                if resources.dispatch_queue.enqueue(command, bridge_mode):
                    self._stats.replyJobsRequeued += 1
                else:
                    self._stats.failed += 1
                    repository.update_reply_job_if_status(
                        row["job_id"],
                        (ReplyJobStatus.queued,),
                        ReplyJobStatus.failed,
                        "dispatch queue full",
                    )
                    safe_bridge_log("WARN", "recovery", "reply job recovery rejected: dispatch queue full", row["job_id"])
            except Exception as exc:
                self._stats.failed += 1
                safe_bridge_log("ERROR", "recovery", f"reply job recovery failed: {exc}", row["job_id"])
