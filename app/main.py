from __future__ import annotations
from contextlib import asynccontextmanager
from typing import List

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.chatbot.service import ChatbotService
from app.chatbot.options import validate_options as validate_bot_options
from app.db import init_db
from app.infra.runtime_resources import get_runtime_resources, shutdown_runtime_resources
from app.repository import upsert_room_rule
from app.schemas import (
    BridgeEvent,
    EventResponse,
    MessageDeleteRequest,
    MessageItem,
    MessageListResponse,
    MessagePatchRequest,
    RoomType,
    RoomRuleResponse,
    RoomRuleUpsertRequest,
    ChatbotModuleUpdateRequest,
    ChatbotPackageInstallResponse,
    ChatbotReloadRequest,
    SendBatchItemListResponse,
    SendBatchPreviewRequest,
    SendBatchPreviewResponse,
    SendBatchRequest,
    SendGroupBatchRequest,
    SendBatchResponse,
    SendBatchRetryRequest,
    SendBatchSummaryResponse,
    SendTargetFilter,
    SendTargetGroupResponse,
    SendTargetGroupUpsertRequest,
    SendTargetListResponse,
    TargetSourceFilter,
    TargetStatus,
    RoomBotOptionUpsertRequest,
    SendJobResponse,
    SendRequest,
    SendResponse,
)
from app.security import verify_token
from app.services.event_service import EventService
from app.services.message_service import MessageService
from app.services.config_service import update_chatbot_module_config as update_chatbot_module_config_cached
from app.services.config_service import upsert_room_bot_options as upsert_room_bot_options_cached
from app.services.operations_service import OperationsService
from app.services.package_service import PackageService
from app.services.recovery_service import RecoveryService
from app.services.send_batch_service import SendBatchService
from app.services.send_group_service import SendGroupService
from app.services.send_target_service import SendTargetService
from app.services.send_service import SendService

chatbot_service = ChatbotService()
event_service = EventService(chatbot_service)
send_service = SendService()
send_target_service = SendTargetService()
send_group_service = SendGroupService()
send_batch_service = SendBatchService(send_service, send_target_service, send_group_service)
operations_service = OperationsService(chatbot_service)
package_service = PackageService()
recovery_service = RecoveryService(event_service)
message_service = MessageService()


def reset_services_for_test() -> None:
    """테스트 간 전역 서비스 인스턴스와 봇 runtime 상태를 초기화한다."""

    global chatbot_service, event_service, send_service, send_target_service, send_group_service, send_batch_service, operations_service, package_service, recovery_service, message_service
    try:
        recovery_service.stop_scheduler()
    except Exception:
        pass
    try:
        chatbot_service.shutdown()
    except Exception:
        pass
    chatbot_service = ChatbotService()
    event_service = EventService(chatbot_service)
    send_service = SendService()
    send_target_service = SendTargetService()
    send_group_service = SendGroupService()
    send_batch_service = SendBatchService(send_service, send_target_service, send_group_service)
    operations_service = OperationsService(chatbot_service)
    package_service = PackageService()
    recovery_service = RecoveryService(event_service)
    message_service = MessageService()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """FastAPI process lifecycle에서 DB, chatbot, runtime resource를 관리한다."""

    init_db()
    get_runtime_resources()
    chatbot_service.startup()
    recovery_service.recover()
    recovery_service.start_scheduler()
    try:
        yield
    finally:
        recovery_service.stop_scheduler()
        chatbot_service.shutdown()
        shutdown_runtime_resources(wait=True)


app = FastAPI(title="kakao-termux-back", lifespan=lifespan)


def load_chatbots() -> int:
    """설정된 bot directory를 스캔해 중앙 registry를 갱신한다."""

    return chatbot_service.reload()


@app.get("/health")
def health(includeDetails: bool = False) -> dict:
    if not includeDetails:
        return {"ok": True}
    return {
        "ok": True,
        "runtime": get_runtime_resources().stats(),
        "recovery": recovery_service.stats(),
        "sendTargets": send_target_service.stats(),
        "sendBatches": send_batch_service.stats(),
    }


@app.post("/events", response_model=EventResponse)
def events(event: BridgeEvent) -> EventResponse:
    """메시지 이벤트를 저장하고 챗봇 프로세서 결과를 반환한다."""

    return event_service.handle_event(event)


@app.get("/messages", response_model=MessageListResponse)
def messages_list(
    token: str = Query(...),
    roomKey: str | None = None,
    sender: str | None = None,
    sourceType: str | None = None,
    messageType: str | None = None,
    receivedAfter: int | None = None,
    receivedBefore: int | None = None,
    includeDeleted: bool = False,
    limit: int = 50,
    cursor: str | None = None,
) -> MessageListResponse:
    """저장된 메시지를 최신순 cursor pagination으로 조회한다."""

    return message_service.list(
        token=token,
        room_key=roomKey,
        sender=sender,
        source_type=sourceType,
        message_type=messageType,
        received_after=receivedAfter,
        received_before=receivedBefore,
        include_deleted=includeDeleted,
        limit=limit,
        cursor=cursor,
    )


@app.get("/messages/search", response_model=MessageListResponse)
def messages_search(
    token: str = Query(...),
    q: str = Query(...),
    roomKey: str | None = None,
    sender: str | None = None,
    sourceType: str | None = None,
    messageType: str | None = None,
    receivedAfter: int | None = None,
    receivedBefore: int | None = None,
    includeDeleted: bool = False,
    limit: int = 50,
    cursor: str | None = None,
) -> MessageListResponse:
    """FTS5로 메시지 본문, 방 이름, 발신자를 검색한다."""

    return message_service.search(
        token=token,
        q=q,
        room_key=roomKey,
        sender=sender,
        source_type=sourceType,
        message_type=messageType,
        received_after=receivedAfter,
        received_before=receivedBefore,
        include_deleted=includeDeleted,
        limit=limit,
        cursor=cursor,
    )


@app.get("/messages/{event_id}", response_model=MessageItem)
def messages_get(
    event_id: str,
    token: str = Query(...),
    includeDeleted: bool = False,
) -> MessageItem:
    """event_id 기준 단일 메시지를 조회한다."""

    return message_service.get(event_id, token=token, include_deleted=includeDeleted)


@app.post("/messages", response_model=MessageItem)
def messages_create(event: BridgeEvent) -> MessageItem:
    """BridgeEvent 형태를 재사용해 관리 API에서 메시지를 수동 생성한다."""

    return message_service.create(event)


@app.patch("/messages/{event_id}", response_model=MessageItem)
def messages_update(event_id: str, request: MessagePatchRequest) -> MessageItem:
    """관리 목적의 제한 필드만 수정한다."""

    return message_service.update(event_id, request)


@app.delete("/messages/{event_id}", response_model=MessageItem)
def messages_delete(
    event_id: str,
    token: str | None = Query(default=None),
    request: MessageDeleteRequest | None = Body(default=None),
) -> MessageItem:
    """메시지를 soft delete하고 본문과 검색 색인을 제거한다."""

    return message_service.delete(event_id, token=token or (request.token if request is not None else ""))


@app.post("/room-rules", response_model=RoomRuleResponse)
def room_rules(request: RoomRuleUpsertRequest) -> RoomRuleResponse:
    """방별 자동 응답 룰을 생성하거나 갱신한다."""

    verify_token(request.token)
    row = upsert_room_rule(request)
    get_runtime_resources().config_cache.set_room_rule(row)
    return row


@app.get("/chatbot/modules")
def chatbot_modules(
    token: str | None = Query(default=None),
    status: str | None = None,
    limit: int = 100,
) -> dict:
    """로딩된 챗봇 모듈 목록과 DB 활성 상태를 반환한다."""

    include_file_details = token is not None
    if include_file_details:
        verify_token(token)
    return operations_service.list_modules(
        include_file_details=include_file_details,
        file_status=status,
        limit=limit,
    )


@app.get("/chatbot/modules/{bot_key}/document")
def chatbot_module_document(bot_key: str, token: str | None = Query(default=None)) -> dict:
    """봇 패키지의 bot.md 문서를 반환한다."""

    verify_token(token)
    try:
        document = operations_service.module_document(bot_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if document is None:
        raise HTTPException(status_code=404, detail="bot document not found")
    return document


@app.post("/chatbot/modules/{bot_key}")
def update_chatbot_module(bot_key: str, request: ChatbotModuleUpdateRequest) -> dict:
    """전역 챗봇 모듈 활성화, 우선순위, 옵션을 갱신한다."""

    verify_token(request.token)
    _validate_chatbot_options(bot_key, request.options)
    row = update_chatbot_module_config_cached(
        bot_key,
        enabled=request.enabled,
        priority=request.priority,
        options=request.options,
    )
    if row is None:
        return {"ok": False, "error": "bot not found"}
    return {"ok": True, "module": {"key": row["bot_key"], "enabled": bool(row["enabled"]), "priority": row["priority"]}}


@app.post("/chatbot/rooms/{room_key}/modules/{bot_key}")
def update_room_bot_options(room_key: str, bot_key: str, request: RoomBotOptionUpsertRequest) -> dict:
    """방별 챗봇 모듈 활성화와 옵션을 갱신한다."""

    verify_token(request.token)
    _validate_chatbot_options(bot_key, request.options)
    row = upsert_room_bot_options_cached(room_key, bot_key, request.enabled, request.options)
    return {"ok": True, "roomKey": row["room_key"], "botKey": row["bot_key"], "enabled": bool(row["enabled"])}


@app.post("/chatbot/reload")
def reload_chatbots(request: ChatbotReloadRequest) -> dict:
    """운영 중 수동으로 챗봇 모듈을 다시 로딩한다."""

    verify_token(request.token)
    count = load_chatbots()
    return {"ok": True, "loaded": count}


@app.get("/chatbot/packages/{bot_key}/export")
def export_chatbot_package(bot_key: str, token: str = Query(...)) -> Response:
    """로컬 봇 폴더를 marketplace 업로드 가능한 zip 패키지로 내보낸다."""

    verify_token(token)
    try:
        data, package_sha256, filename = package_service.export_package(bot_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Package-Sha256": package_sha256,
        },
    )


@app.post("/chatbot/packages/install", response_model=ChatbotPackageInstallResponse)
async def install_chatbot_package(
    token: str = Form(...),
    file: UploadFile = File(...),
    marketplaceBotId: str | None = Form(default=None),
    marketplaceBaseUrl: str | None = Form(default=None),
) -> ChatbotPackageInstallResponse:
    """marketplace에서 내려받은 봇 zip을 로컬 봇 폴더에 설치한다."""

    verify_token(token)
    try:
        result = package_service.install_package(
            await file.read(),
            marketplace_bot_id=marketplaceBotId,
            marketplace_base_url=marketplaceBaseUrl,
            allow_update=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ChatbotPackageInstallResponse(**result.__dict__)


@app.post("/chatbot/packages/{bot_key}/update", response_model=ChatbotPackageInstallResponse)
async def update_chatbot_package(
    bot_key: str,
    token: str = Form(...),
    file: UploadFile = File(...),
    marketplaceBotId: str | None = Form(default=None),
    marketplaceBaseUrl: str | None = Form(default=None),
) -> ChatbotPackageInstallResponse:
    """이미 marketplace에서 설치된 봇을 더 높은 버전 zip으로 업데이트한다."""

    verify_token(token)
    try:
        result = package_service.install_package(
            await file.read(),
            marketplace_bot_id=marketplaceBotId,
            marketplace_base_url=marketplaceBaseUrl,
            allow_update=True,
            expected_bot_key=bot_key,
            reload_callback=load_chatbots,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ChatbotPackageInstallResponse(**result.__dict__)


def _validate_chatbot_options(bot_key: str, options: dict) -> None:
    bot = chatbot_service.registry.get(bot_key)
    if bot is None:
        if options:
            raise HTTPException(status_code=400, detail="bot not loaded")
        return
    try:
        validate_bot_options(options, bot.definition.optionSchema)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/chatbot/health")
def chatbot_health(token: str = Query(...)) -> dict:
    """챗봇 운영 상태를 반환한다."""

    verify_token(token)
    return chatbot_service.health()


@app.get("/chatbot/runs")
def chatbot_runs(
    token: str = Query(...),
    eventId: str | None = None,
    botKey: str | None = None,
    limit: int = 100,
) -> dict:
    """최근 챗봇 실행 기록을 limit 기반으로 조회한다."""

    verify_token(token)
    return operations_service.list_runs(event_id=eventId, bot_key=botKey, limit=limit)


@app.get("/chatbot/states")
def chatbot_states(
    token: str = Query(...),
    botKey: str | None = None,
    roomKey: str | None = None,
    limit: int = 100,
    includeRaw: bool = False,
    rawToken: str | None = None,
) -> dict:
    """챗봇 상태 목록을 조회한다. 기본 응답은 state 원문을 노출하지 않는다."""

    verify_token(token)
    if includeRaw:
        verify_token(rawToken or "")
    return operations_service.list_states(bot_key=botKey, room_key=roomKey, limit=limit, include_raw=includeRaw)


@app.post("/send", response_model=SendResponse)
def send(request: SendRequest) -> SendResponse:
    """수동/지연 답장 job을 저장한 뒤 선택된 adapter로 dispatch한다."""

    return send_service.handle_send(request)


@app.get("/send/jobs/{job_id}", response_model=SendJobResponse)
def send_job(job_id: str, token: str = Query(...)) -> SendJobResponse:
    """비동기 답장 job의 현재 상태를 조회한다."""

    verify_token(token)
    job = send_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="reply job not found")
    return job


@app.get("/send/targets", response_model=SendTargetListResponse)
def send_targets(
    token: str = Query(...),
    q: str | None = None,
    status: TargetStatus = TargetStatus.all,
    sourceType: TargetSourceFilter = TargetSourceFilter.all,
    roomType: RoomType | None = None,
    seenAfter: int | None = None,
    seenBefore: int | None = None,
    expiresAfter: int | None = None,
    expiresBefore: int | None = None,
    hasRecentFailure: bool | None = None,
    limit: int = 50,
    cursor: str | None = None,
    includeRaw: bool = False,
    rawToken: str | None = None,
) -> SendTargetListResponse:
    """reply token 풀에서 발송 가능한 방 목록을 조회한다."""

    verify_token(token)
    if includeRaw:
        verify_token(rawToken or "")
    return send_target_service.list_targets(
        q=q,
        status=status,
        source_type=sourceType,
        room_type=roomType,
        seen_after=seenAfter,
        seen_before=seenBefore,
        expires_after=expiresAfter,
        expires_before=expiresBefore,
        has_recent_failure=hasRecentFailure,
        limit=limit,
        cursor=cursor,
        include_raw=includeRaw,
    )


@app.post("/send/batches/preview", response_model=SendBatchPreviewResponse)
def send_batches_preview(request: SendBatchPreviewRequest) -> SendBatchPreviewResponse:
    """실제 batch 발송 전에 대상 수와 제외 사유를 계산한다."""

    return send_batch_service.preview_batch(request)


@app.post("/send/batches", response_model=SendBatchResponse)
def send_batches(request: SendBatchRequest) -> SendBatchResponse:
    """선택/전체/그룹 대상에 대해 batch 발송을 생성한다."""

    return send_batch_service.create_batch(request)


@app.get("/send/batches/{batch_id}", response_model=SendBatchSummaryResponse)
def send_batch(batch_id: str, token: str = Query(...)) -> SendBatchSummaryResponse:
    """batch 집계와 현재 상태를 조회한다."""

    verify_token(token)
    return send_batch_service.get_batch_summary(batch_id)


@app.get("/send/batches/{batch_id}/jobs", response_model=SendBatchItemListResponse)
def send_batch_jobs(
    batch_id: str,
    token: str = Query(...),
    limit: int = 100,
    cursor: str | None = None,
) -> SendBatchItemListResponse:
    """batch에 속한 개별 reply job 상태를 조회한다."""

    verify_token(token)
    return send_batch_service.list_batch_items(batch_id=batch_id, limit=limit, cursor=cursor)


@app.post("/send/batches/{batch_id}/retry-failed", response_model=SendBatchSummaryResponse)
def send_batch_retry_failed(batch_id: str, request: SendBatchRetryRequest) -> SendBatchSummaryResponse:
    """실패 또는 만료된 대상만 새 batch로 다시 보낸다."""

    return send_batch_service.retry_failed(batch_id, text=request.text, token=request.token, dedupe_key=request.dedupeKey)


@app.post("/send/batches/{batch_id}/cancel", response_model=SendBatchSummaryResponse)
def send_batch_cancel(batch_id: str, token: str = Query(...)) -> SendBatchSummaryResponse:
    """batch를 취소 상태로 전환한다."""

    verify_token(token)
    return send_batch_service.cancel_batch(batch_id)


@app.post("/send/groups", response_model=SendTargetGroupResponse)
def send_groups_upsert(request: SendTargetGroupUpsertRequest) -> SendTargetGroupResponse:
    """저장 발송 그룹을 생성하거나 갱신한다."""

    verify_token(request.token)
    return send_group_service.upsert_group(request)


@app.get("/send/groups", response_model=List[SendTargetGroupResponse])
def send_groups_list(token: str = Query(...), limit: int = 100) -> list[SendTargetGroupResponse]:
    """저장된 발송 그룹 목록을 조회한다."""

    verify_token(token)
    return send_group_service.list_groups(limit=limit)


@app.get("/send/groups/{group_key}", response_model=SendTargetGroupResponse)
def send_groups_get(group_key: str, token: str = Query(...)) -> SendTargetGroupResponse:
    """저장된 단일 발송 그룹을 조회한다."""

    verify_token(token)
    group = send_group_service.get_group(group_key)
    if group is None:
        raise HTTPException(status_code=404, detail="send group not found")
    return group


@app.delete("/send/groups/{group_key}")
def send_groups_delete(group_key: str, token: str = Query(...)) -> dict:
    """발송 그룹을 삭제한다."""

    verify_token(token)
    send_group_service.delete_group(group_key)
    return {"ok": True}


@app.post("/send/groups/{group_key}/send", response_model=SendBatchResponse)
def send_groups_send(group_key: str, request: SendGroupBatchRequest) -> SendBatchResponse:
    """저장 그룹을 batch 발송 대상으로 변환해 전송한다."""

    group_spec = send_group_service.resolve_group_spec(group_key)
    if group_spec is None:
        raise HTTPException(status_code=404, detail="send group not found")
    batch_request = SendBatchRequest(
        token=request.token,
        target=group_spec,
        text=request.text,
        dryRun=request.dryRun,
        confirm=request.confirm,
        dedupeKey=request.dedupeKey,
        maxTargets=request.maxTargets,
    )
    return send_batch_service.create_batch(batch_request)
