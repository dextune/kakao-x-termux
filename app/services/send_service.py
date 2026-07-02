from __future__ import annotations

from uuid import uuid4

from app.config import get_settings
from app.infra.errors import safe_bridge_log
from app.infra.runtime_resources import RuntimeResources, get_runtime_resources
from app.log_policy import log_send_result
from app.repository import (
    expires_at_for_token,
    get_reply_job,
    insert_reply_job,
    latest_reply_token,
    update_reply_job,
    update_reply_job_if_status,
)
from app.reply_dispatcher import dispatch_reply
from app.schemas import BridgeMode, ReplyCommand, ReplyJobStatus, SendJobResponse, SendRequest, SendResponse
from app.security import verify_token
from app.time_utils import now_millis


class SendService:
    """`/send` 요청의 job 저장, token 검증, dispatch, 결과 기록을 담당한다."""

    def __init__(self, resources_provider=get_runtime_resources) -> None:
        self._resources_provider = resources_provider

    def handle_send(self, request: SendRequest) -> SendResponse:
        verify_token(request.token)
        settings = get_settings()
        bridge_mode = BridgeMode(settings.bridge_mode)
        job_id = request.dedupeKey or f"job_{uuid4().hex}"
        reply_token = request.replyToken
        resources: RuntimeResources = self._resources_provider()
        reply_token_cache = getattr(resources, "reply_token_cache", None)
        try:
            expires_at = (
                reply_token_cache.peek_expires_at_for_token(reply_token)
                if reply_token and reply_token_cache is not None
                else expires_at_for_token(reply_token)
                if reply_token
                else None
            )
            if reply_token and expires_at is None:
                expires_at = expires_at_for_token(reply_token)
            if reply_token is None:
                if reply_token_cache is not None:
                    cached = reply_token_cache.peek_latest_for_room(request.roomKey)
                    if cached is not None:
                        reply_token, expires_at = cached
                    else:
                        reply_token, expires_at = latest_reply_token(request.roomKey)
                else:
                    reply_token, expires_at = latest_reply_token(request.roomKey)
        except Exception as exc:
            safe_bridge_log("ERROR", "send", f"reply token lookup failed: {exc}", job_id)
            response = SendResponse(
                ok=False,
                jobId=job_id,
                status=ReplyJobStatus.failed,
                bridgeMode=bridge_mode,
                error="reply token lookup failed",
            )
            self._log_send(request, response, reply_token_found=False)
            return response

        try:
            inserted = insert_reply_job(
                job_id=job_id,
                room_key=request.roomKey,
                room=request.room,
                text=request.text,
                dedupe_key=request.dedupeKey,
                reply_token=reply_token,
                bridge_mode=bridge_mode.value,
            )
        except Exception as exc:
            safe_bridge_log("ERROR", "send", f"reply job insert failed: {exc}", job_id)
            response = SendResponse(
                ok=False,
                jobId=job_id,
                status=ReplyJobStatus.failed,
                bridgeMode=bridge_mode,
                error="reply job insert failed",
            )
            self._log_send(request, response, reply_token_found=reply_token is not None)
            return response

        if not inserted:
            response = SendResponse(
                ok=False,
                jobId=job_id,
                status=ReplyJobStatus.duplicate,
                bridgeMode=bridge_mode,
                error="duplicate dedupeKey",
            )
            self._log_send(request, response, reply_token_found=reply_token is not None)
            return response

        if reply_token is None:
            return self._terminal_response(
                request,
                job_id,
                bridge_mode,
                ReplyJobStatus.handle_expired,
                "reply token not found",
                reply_token_found=False,
            )
        if expires_at is not None and expires_at <= now_millis():
            return self._terminal_response(
                request,
                job_id,
                bridge_mode,
                ReplyJobStatus.token_expired,
                "reply token expired",
                reply_token_found=True,
            )

        command = ReplyCommand(
            jobId=job_id,
            roomKey=request.roomKey,
            room=request.room,
            text=request.text,
            dedupeKey=request.dedupeKey or job_id,
            replyToken=reply_token,
            token=request.token,
        )
        if settings.send_dispatch_mode == "async_enqueue":
            return self._enqueue_response(request, job_id, bridge_mode, command, resources)
        if settings.send_dispatch_mode != "sync_wait":
            safe_bridge_log("WARN", "send", f"unknown send dispatch mode: {settings.send_dispatch_mode}", job_id)
        wait_timeout = self._adapter_wait_timeout_seconds(bridge_mode, settings)
        external_result = resources.adapter_external_runner.run(
            lambda: dispatch_reply(
                command,
                bridge_mode.value,
                http_client=resources.http_client,
            ),
            timeout_seconds=wait_timeout,
        )
        if not external_result.ok:
            safe_bridge_log(
                "WARN",
                "adapter_external",
                f"adapter dispatch {external_result.status}: {external_result.error}",
                job_id,
            )
            result_status = ReplyJobStatus.failed
            result_error = external_result.error or f"adapter dispatch {external_result.status}"
            result_ok = False
        else:
            result = external_result.value
            result_status = result.status
            result_error = result.error
            result_ok = result.ok

        try:
            update_reply_job(job_id, result_status, result_error)
        except Exception as exc:
            safe_bridge_log("ERROR", "send", f"dispatch_success_update_failed: {exc}", job_id)

        response = SendResponse(
            ok=result_ok,
            jobId=job_id,
            status=result_status,
            bridgeMode=bridge_mode,
            error=result_error,
        )
        self._log_send(request, response, reply_token_found=True)
        return response

    def _enqueue_response(
        self,
        request: SendRequest,
        job_id: str,
        bridge_mode: BridgeMode,
        command: ReplyCommand,
        resources: RuntimeResources,
    ) -> SendResponse:
        try:
            update_reply_job(job_id, ReplyJobStatus.queued)
        except Exception as exc:
            safe_bridge_log("ERROR", "send", f"queued reply job update failed: {exc}", job_id)
        accepted = resources.dispatch_queue.enqueue(command, bridge_mode)
        error = None if accepted else "dispatch queue full"
        if not accepted:
            safe_bridge_log("WARN", "send", error, job_id)
            try:
                update_reply_job_if_status(job_id, (ReplyJobStatus.queued,), ReplyJobStatus.failed, error)
            except Exception as exc:
                safe_bridge_log("ERROR", "send", f"queue-full reply job update failed: {exc}", job_id)
        response = SendResponse(
            ok=accepted,
            jobId=job_id,
            status=ReplyJobStatus.queued if accepted else ReplyJobStatus.failed,
            bridgeMode=bridge_mode,
            error=error,
        )
        self._log_send(request, response, reply_token_found=True)
        return response

    def get_job(self, job_id: str) -> SendJobResponse | None:
        """비동기 `/send` job의 현재 저장 상태를 API 응답 모델로 변환한다."""

        row = get_reply_job(job_id)
        if row is None:
            return None
        return SendJobResponse(
            jobId=row["job_id"],
            roomKey=row["room_key"],
            room=row["room"],
            status=ReplyJobStatus(row["status"]),
            bridgeMode=BridgeMode(row["bridge_mode"]),
            dedupeKey=row["dedupe_key"],
            attemptCount=int(row["attempt_count"]),
            error=row["last_error"],
            createdAt=int(row["created_at"]),
            sentAt=row["sent_at"],
        )

    def _adapter_wait_timeout_seconds(self, bridge_mode: BridgeMode, settings) -> float:
        configured = max(settings.adapter_external_wait_timeout_ms, 1) / 1000
        if bridge_mode == BridgeMode.http_test_backend:
            adapter_timeout = max(settings.adapter_max_attempts, 1) * 5.0
        elif bridge_mode == BridgeMode.am_broadcast:
            adapter_timeout = 10.0
        elif bridge_mode == BridgeMode.adb_broadcast:
            adapter_timeout = 15.0
        else:
            adapter_timeout = 1.0
        return max(configured, adapter_timeout + 0.5)

    def _terminal_response(
        self,
        request: SendRequest,
        job_id: str,
        bridge_mode: BridgeMode,
        status: ReplyJobStatus,
        error: str,
        reply_token_found: bool,
    ) -> SendResponse:
        try:
            update_reply_job(job_id, status, error)
        except Exception as exc:
            safe_bridge_log("ERROR", "send", f"terminal reply job update failed: {exc}", job_id)
        response = SendResponse(ok=False, jobId=job_id, status=status, bridgeMode=bridge_mode, error=error)
        self._log_send(request, response, reply_token_found=reply_token_found)
        return response

    def _log_send(self, request: SendRequest, response: SendResponse, reply_token_found: bool) -> None:
        try:
            log_send_result(request, response, reply_token_found=reply_token_found)
        except Exception as exc:
            safe_bridge_log("ERROR", "send", f"send result log failed: {exc}", response.jobId)
