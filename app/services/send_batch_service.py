from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import uuid4

from fastapi import HTTPException

from app.config import get_settings
from app.repository import get_reply_job
from app.repositories.send_batches import (
    count_send_batches_by_status,
    get_send_batch,
    get_send_batch_items_summary,
    insert_send_batch,
    insert_send_batch_item,
    list_send_batch_items,
    update_send_batch_counts,
    update_send_batch_item_status,
)
from app.schemas import (
    ReplyJobStatus,
    SendBatchItemResponse,
    SendBatchItemListResponse,
    SendBatchItemStatus,
    SendBatchPreviewRequest,
    SendBatchPreviewResponse,
    SendBatchRequest,
    SendBatchResponse,
    SendBatchSummaryResponse,
    SendBatchStatus,
    SendTargetSpec,
    SendTargetType,
    SendRequest,
)
from app.security import verify_token
from app.services.send_target_service import ResolvedTarget, SendTargetService
from app.services.send_group_service import SendGroupService
from app.services.send_service import SendService
from app.time_utils import now_millis


@dataclass
class _BatchResult:
    target_count: int
    queued_count: int
    sent_count: int
    failed_count: int
    expired_count: int
    skipped_count: int


def _mask_preview(text: str) -> str:
    normalized = " ".join(text.split())
    return normalized[:80]


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _item_status_from_reply(status: ReplyJobStatus) -> SendBatchItemStatus:
    if status == ReplyJobStatus.sent:
        return SendBatchItemStatus.sent
    if status == ReplyJobStatus.queued:
        return SendBatchItemStatus.queued
    if status == ReplyJobStatus.token_expired:
        return SendBatchItemStatus.token_expired
    if status == ReplyJobStatus.handle_expired:
        return SendBatchItemStatus.handle_expired
    if status == ReplyJobStatus.failed:
        return SendBatchItemStatus.failed
    return SendBatchItemStatus.skipped


class SendBatchService:
    """배치 발송, 미리보기, 재시도, 집계 관리를 담당한다."""

    def __init__(
        self,
        send_service: SendService,
        target_service: SendTargetService | None = None,
        group_service: SendGroupService | None = None,
    ) -> None:
        self.send_service = send_service
        self.target_service = target_service or SendTargetService()
        self.group_service = group_service or SendGroupService()

    def preview_batch(self, request: SendBatchPreviewRequest) -> SendBatchPreviewResponse:
        """실제 발송 전 대상 수와 제외 사유를 계산한다."""

        verify_token(request.token)
        self._ensure_enabled()
        preview = self.target_service.preview_target_spec(request.target, max_targets=request.maxTargets)
        return SendBatchPreviewResponse(**preview)

    def create_batch(self, request: SendBatchRequest) -> SendBatchResponse:
        """선택된 대상에 대해 batch 발송을 생성하고 dispatch 한다."""

        verify_token(request.token)
        self._ensure_enabled()
        if not request.dryRun and not request.confirm:
            raise HTTPException(status_code=400, detail="confirm is required for bulk send")
        resolution = self.target_service.resolve_target_spec(request.target, max_targets=request.maxTargets, for_send=not request.dryRun)
        if not request.dryRun and resolution.excluded_reasons.get("maxTargets", 0) > 0:
            raise HTTPException(status_code=400, detail="bulk send target limit exceeded")
        batch_id = f"batch_{uuid4().hex[:12]}"
        batch_status = SendBatchStatus.dry_run if request.dryRun else SendBatchStatus.queued
        insert_send_batch(
            batch_id=batch_id,
            target_type=_enum_value(request.target.type),
            target_json=request.target.model_dump(mode="json"),
            text_hash=_hash_text(request.text),
            text_preview=_mask_preview(request.text),
            status=batch_status.value,
            target_count=len(resolution.targets) + sum(resolution.excluded_reasons.values()),
            queued_count=0,
            sent_count=0,
            failed_count=0,
            expired_count=0,
            skipped_count=sum(resolution.excluded_reasons.values()),
        )
        if request.dryRun:
            self._persist_preview_items(batch_id, resolution.targets, request.target)
            self._refresh_batch_counts(batch_id)
            return self.get_batch(batch_id)

        result = self._dispatch_targets(batch_id, resolution.targets, request)
        self._refresh_batch_counts(batch_id, result)
        return self.get_batch(batch_id)

    def get_batch(self, batch_id: str) -> SendBatchResponse:
        """저장된 batch 상태를 반환한다."""

        row = get_send_batch(batch_id)
        if row is None:
            raise HTTPException(status_code=404, detail="send batch not found")
        summary = self._summary_from_batch_row(row)
        return SendBatchResponse(
            ok=True,
            batchId=row["batch_id"],
            status=SendBatchStatus(row["status"]),
            targetCount=summary.target_count,
            queuedCount=summary.queued_count,
            skippedCount=summary.skipped_count,
            excludedCount=summary.failed_count + summary.expired_count + summary.skipped_count,
            excludedReasons={},
        )

    def get_batch_summary(self, batch_id: str) -> SendBatchSummaryResponse:
        """저장된 batch 상태와 세부 집계를 반환한다."""

        self._refresh_batch_counts(batch_id)
        row = get_send_batch(batch_id)
        if row is None:
            raise HTTPException(status_code=404, detail="send batch not found")
        return SendBatchSummaryResponse(
            batchId=row["batch_id"],
            status=SendBatchStatus(row["status"]),
            targetCount=int(row["target_count"]),
            queuedCount=int(row["queued_count"]),
            sentCount=int(row["sent_count"]),
            failedCount=int(row["failed_count"]),
            expiredCount=int(row["expired_count"]),
            skippedCount=int(row["skipped_count"]),
            createdAt=int(row["created_at"]),
            updatedAt=int(row["updated_at"]),
            completedAt=row["completed_at"],
        )

    def list_batch_items(
        self,
        batch_id: str,
        limit: int = 100,
        cursor: str | None = None,
    ) -> SendBatchItemListResponse:
        """batch item 목록을 페이지네이션으로 반환한다."""

        self._refresh_batch_counts(batch_id)
        rows = list_send_batch_items(batch_id=batch_id, limit=limit, cursor=cursor)
        next_cursor = str(rows[-1]["id"]) if len(rows) == limit and rows else None
        return SendBatchItemListResponse(
            items=[
                SendBatchItemResponse(
                    batchId=row["batch_id"],
                    roomKey=row["room_key"],
                    room=row["room"],
                    jobId=row["job_id"],
                    status=SendBatchItemStatus(row["status"]),
                    skipReason=row["skip_reason"],
                    createdAt=int(row["created_at"]),
                    updatedAt=int(row["updated_at"]),
                )
                for row in rows
            ],
            nextCursor=next_cursor,
        )

    def retry_failed(self, batch_id: str, text: str, token: str, dedupe_key: str | None = None) -> SendBatchSummaryResponse:
        """실패 또는 만료된 대상만 새 batch로 다시 보낸다."""

        verify_token(token)
        self._ensure_enabled()
        rows = list_send_batch_items(batch_id=batch_id, limit=10_000)
        failed_room_keys = [row["room_key"] for row in rows if row["status"] in {"FAILED", "TOKEN_EXPIRED", "HANDLE_EXPIRED"}]
        if not failed_room_keys:
            raise HTTPException(status_code=400, detail="no failed items to retry")
        request = SendBatchRequest(
            token=token,
            target=SendTargetSpec(type=SendTargetType.rooms, roomKeys=failed_room_keys),
            text=text,
            dryRun=False,
            confirm=True,
            dedupeKey=dedupe_key,
        )
        created = self.create_batch(request)
        return self.get_batch_summary(created.batchId)

    def cancel_batch(self, batch_id: str) -> SendBatchSummaryResponse:
        """아직 완료되지 않은 batch를 취소 상태로 전환한다."""

        row = get_send_batch(batch_id)
        if row is None:
            raise HTTPException(status_code=404, detail="send batch not found")
        if row["status"] in {SendBatchStatus.completed.value, SendBatchStatus.failed.value, SendBatchStatus.canceled.value}:
            return self.get_batch_summary(batch_id)
        update_send_batch_counts(
            batch_id=batch_id,
            status=SendBatchStatus.canceled.value,
            target_count=int(row["target_count"]),
            queued_count=int(row["queued_count"]),
            sent_count=int(row["sent_count"]),
            failed_count=int(row["failed_count"]),
            expired_count=int(row["expired_count"]),
            skipped_count=int(row["skipped_count"]),
            completed_at=now_millis(),
        )
        return self.get_batch_summary(batch_id)

    def stats(self) -> dict[str, int]:
        """health API에서 사용할 batch 집계를 반환한다."""

        return count_send_batches_by_status()

    def _ensure_enabled(self) -> None:
        if not get_settings().bulk_send_enabled:
            raise HTTPException(status_code=403, detail="bulk send is disabled")

    def _persist_preview_items(self, batch_id: str, targets: list[ResolvedTarget], spec: SendTargetSpec) -> None:
        for target in targets:
            insert_send_batch_item(
                batch_id=batch_id,
                room_key=target.room_key,
                room=target.room,
                job_id=None,
                status=SendBatchItemStatus.skipped.value,
                skip_reason="dryRun",
            )

    def _dispatch_targets(self, batch_id: str, targets: list[ResolvedTarget], request: SendBatchRequest) -> _BatchResult:
        settings = get_settings()
        queued_count = 0
        sent_count = 0
        failed_count = 0
        expired_count = 0
        skipped_count = 0
        for index, target in enumerate(targets):
            dedupe_seed = request.dedupeKey or batch_id
            dedupe_key = f"{dedupe_seed}:{target.room_key}"
            send_request = SendRequest(
                roomKey=target.room_key,
                room=target.room,
                text=request.text,
                dedupeKey=dedupe_key,
                replyToken=target.reply_token,
                token=request.token,
            )
            response = self.send_service.handle_send(send_request)
            item_status = _item_status_from_reply(response.status)
            if item_status == SendBatchItemStatus.queued:
                queued_count += 1
            elif item_status == SendBatchItemStatus.sent:
                sent_count += 1
            elif item_status in (SendBatchItemStatus.token_expired, SendBatchItemStatus.handle_expired):
                expired_count += 1
            elif item_status == SendBatchItemStatus.failed:
                failed_count += 1
            else:
                skipped_count += 1
            insert_send_batch_item(
                batch_id=batch_id,
                room_key=target.room_key,
                room=target.room,
                job_id=response.jobId,
                status=item_status.value,
                skip_reason=response.error,
            )
            if settings.bulk_send_rate_per_second > 0 and index + 1 < len(targets):
                sleep_seconds = 1 / settings.bulk_send_rate_per_second
                if sleep_seconds > 0:
                    import time

                    time.sleep(sleep_seconds)
        return _BatchResult(
            target_count=len(targets),
            queued_count=queued_count,
            sent_count=sent_count,
            failed_count=failed_count,
            expired_count=expired_count,
            skipped_count=skipped_count,
        )

    def _refresh_batch_counts(self, batch_id: str, result: _BatchResult | None = None) -> None:
        batch_row = get_send_batch(batch_id)
        rows = list_send_batch_items(batch_id=batch_id, limit=10_000)
        current_status = batch_row["status"] if batch_row is not None else None
        queued_count = 0
        sent_count = 0
        failed_count = 0
        expired_count = 0
        skipped_count = 0
        for item_row in rows:
            job_id = item_row["job_id"]
            status = item_row["status"]
            if job_id:
                job = get_reply_job(job_id)
                if job is not None:
                    status = job["status"]
                    mapped = _item_status_from_reply(ReplyJobStatus(status))
                    if mapped.value != item_row["status"]:
                        update_send_batch_item_status(batch_id, item_row["room_key"], mapped.value, skip_reason=job["last_error"], job_id=job_id)
                    status = mapped.value
            if status == SendBatchItemStatus.queued.value:
                queued_count += 1
            elif status == SendBatchItemStatus.sent.value:
                sent_count += 1
            elif status in (SendBatchItemStatus.token_expired.value, SendBatchItemStatus.handle_expired.value):
                expired_count += 1
            elif status == SendBatchItemStatus.failed.value:
                failed_count += 1
            else:
                skipped_count += 1
        if current_status == SendBatchStatus.canceled.value:
            status = SendBatchStatus.canceled.value
        elif current_status in {SendBatchStatus.completed.value, SendBatchStatus.failed.value}:
            status = current_status
        else:
            status = SendBatchStatus.running.value if queued_count > 0 else SendBatchStatus.completed.value
            if failed_count > 0 and sent_count == 0 and queued_count == 0:
                status = SendBatchStatus.failed.value
            if skipped_count == len(rows) and rows:
                status = SendBatchStatus.completed.value
        update_send_batch_counts(
            batch_id=batch_id,
            status=status,
            target_count=int(batch_row["target_count"]) if batch_row is not None else len(rows),
            queued_count=queued_count,
            sent_count=sent_count,
            failed_count=failed_count,
            expired_count=expired_count,
            skipped_count=skipped_count,
            completed_at=(batch_row["completed_at"] if batch_row is not None and current_status == SendBatchStatus.canceled.value else now_millis() if queued_count == 0 else None),
        )

    def _summary_from_batch_row(self, row) -> _BatchResult:
        return _BatchResult(
            target_count=int(row["target_count"]),
            queued_count=int(row["queued_count"]),
            sent_count=int(row["sent_count"]),
            failed_count=int(row["failed_count"]),
            expired_count=int(row["expired_count"]),
            skipped_count=int(row["skipped_count"]),
        )
