from __future__ import annotations
from enum import Enum
from typing import Optional

from app.pydantic_compat import PYDANTIC_V2, BaseModel, ConfigDict, Field, model_validator


class SourceType(str, Enum):
    real_kakao = "real_kakao"
    virtual_phone = "virtual_phone"


class MessageType(str, Enum):
    text = "text"


class EventAction(str, Enum):
    reply = "reply"
    queued = "queued"
    none = "none"


class ReplyJobStatus(str, Enum):
    pending = "PENDING"
    queued = "QUEUED"
    dispatching = "DISPATCHING"
    retrying = "RETRYING"
    sent = "SENT"
    failed = "FAILED"
    token_expired = "TOKEN_EXPIRED"
    handle_expired = "HANDLE_EXPIRED"
    duplicate = "DUPLICATE"


class BridgeMode(str, Enum):
    am_broadcast = "am_broadcast"
    adb_broadcast = "adb_broadcast"
    http_test_backend = "http_test_backend"
    noop = "noop"


class TargetStatus(str, Enum):
    available = "available"
    expiring = "expiring"
    expired = "expired"
    unknown = "unknown"
    all = "all"


class TargetSourceFilter(str, Enum):
    real_kakao = "real_kakao"
    virtual_phone = "virtual_phone"
    all = "all"


class RoomType(str, Enum):
    direct = "direct"
    group = "group"
    unknown = "unknown"


class SendTargetType(str, Enum):
    rooms = "rooms"
    filter = "filter"
    group = "group"
    all = "all"


class SendBatchStatus(str, Enum):
    dry_run = "DRY_RUN"
    queued = "QUEUED"
    running = "RUNNING"
    completed = "COMPLETED"
    failed = "FAILED"
    canceled = "CANCELED"


class SendBatchItemStatus(str, Enum):
    queued = "QUEUED"
    sent = "SENT"
    failed = "FAILED"
    token_expired = "TOKEN_EXPIRED"
    handle_expired = "HANDLE_EXPIRED"
    skipped = "SKIPPED"


class SendTargetGroupType(str, Enum):
    static = "static"
    dynamic = "dynamic"
    hybrid = "hybrid"


class RoomRuleMode(str, Enum):
    manual = "manual"
    keyword = "keyword"
    disabled = "disabled"


class BridgeEvent(BaseModel):
    """Android 또는 PC-only 가상 전화가 전달하는 메시지 이벤트 계약이다.

    sourceType/sourcePackage 조합과 시간 필드는 `/events` 저장 전에 검증된다.
    """

    schemaVersion: int = Field(default=1)
    eventId: str
    source: str
    sourcePackage: str
    sourceType: SourceType
    roomKey: str
    room: str
    sender: Optional[str] = None
    text: str
    messageType: MessageType = MessageType.text
    receivedAt: int
    notificationKey: Optional[str] = None
    replyToken: Optional[str] = None
    replyTokenExpiresAt: Optional[int] = None
    token: str

    @model_validator(mode="after")
    def validate_source_package(self) -> "BridgeEvent":
        if self.sourceType == SourceType.virtual_phone.value:
            if self.sourcePackage != "pc.kakao-test-app":
                raise ValueError("virtual_phone requires sourcePackage=pc.kakao-test-app")
        if self.sourceType == SourceType.real_kakao.value:
            if self.sourcePackage != "com.kakao.talk":
                raise ValueError("real_kakao requires sourcePackage=com.kakao.talk")
        return self


class EventResponse(BaseModel):
    """`/events` 처리 결과다.

    action이 `reply`이면 호출자는 replyToken과 text로 즉시 답장을 캡처하거나 전송한다.
    """

    ack: bool
    action: EventAction
    replyToken: Optional[str] = None
    text: Optional[str] = None
    error: Optional[str] = None


class MessageItem(BaseModel):
    """관리 API와 봇 history 조회에서 노출하는 메시지 단위다."""

    eventId: str
    roomKey: str
    room: str
    sender: Optional[str] = None
    text: str
    messageType: MessageType
    sourceType: SourceType
    receivedAt: int
    processed: bool
    createdAt: int
    updatedAt: int
    deletedAt: Optional[int] = None


class MessageListResponse(BaseModel):
    """메시지 목록/검색 cursor pagination 응답이다."""

    items: list[MessageItem]
    nextCursor: Optional[str] = None


class MessagePatchRequest(BaseModel):
    """관리 목적의 제한 메시지 수정 요청이다."""

    token: str
    room: Optional[str] = None
    sender: Optional[str] = None
    text: Optional[str] = None
    messageType: Optional[MessageType] = None

    if PYDANTIC_V2:
        model_config = ConfigDict(extra="forbid")
    else:
        class Config:
            extra = "forbid"


class MessageDeleteRequest(BaseModel):
    """body token 방식으로 메시지를 soft delete할 때 쓰는 요청이다."""

    token: str


class SendRequest(BaseModel):
    """수동 또는 지연 답장 전송 요청이다.

    replyToken이 없으면 백엔드는 roomKey 기준 최신 메시지의 토큰을 사용한다.
    """

    roomKey: str
    room: str
    text: str
    dedupeKey: Optional[str] = None
    replyToken: Optional[str] = None
    token: str


class SendResponse(BaseModel):
    ok: bool
    jobId: str
    status: ReplyJobStatus
    bridgeMode: BridgeMode
    error: Optional[str] = None


class SendJobResponse(BaseModel):
    """비동기 `/send` 작업의 최종 상태 polling 응답이다."""

    jobId: str
    roomKey: str
    room: str
    status: ReplyJobStatus
    bridgeMode: BridgeMode
    dedupeKey: Optional[str] = None
    attemptCount: int
    error: Optional[str] = None
    createdAt: int
    sentAt: Optional[int] = None


class ReplyCommand(BaseModel):
    """adapter가 Android 앱 또는 PC 테스트 앱으로 전달하는 답장 명령이다."""

    jobId: Optional[str] = None
    roomKey: str
    room: str
    text: str
    dedupeKey: Optional[str] = None
    replyToken: Optional[str] = None
    token: str


class AdapterResult(BaseModel):
    ok: bool
    status: ReplyJobStatus
    externalId: Optional[str] = None
    error: Optional[str] = None


class KeywordReplyRule(BaseModel):
    """방별 keyword 자동 응답 한 줄 규칙이다."""

    keyword: str = Field(min_length=1)
    reply: str = Field(min_length=1)


class RoomRuleConfig(BaseModel):
    """room_rules.rule_json에 저장되는 구조화된 룰 설정이다."""

    keywords: list[KeywordReplyRule] = Field(default_factory=list)
    queueKeywords: list[str] = Field(default_factory=list)


class RoomRuleUpsertRequest(BaseModel):
    """방별 룰을 생성하거나 갱신하는 쓰기 요청이다."""

    roomKey: str
    room: str
    enabled: bool = True
    mode: RoomRuleMode = RoomRuleMode.manual
    rule: RoomRuleConfig = Field(default_factory=RoomRuleConfig)
    token: str


class RoomRuleResponse(BaseModel):
    """저장된 방별 룰 상태를 반환한다."""

    roomKey: str
    room: str
    enabled: bool
    mode: RoomRuleMode
    rule: RoomRuleConfig


class ChatbotModuleUpdateRequest(BaseModel):
    """전역 챗봇 모듈 설정 변경 요청이다."""

    enabled: Optional[bool] = None
    priority: Optional[int] = None
    options: dict = Field(default_factory=dict)
    token: str


class RoomBotOptionUpsertRequest(BaseModel):
    """방별 챗봇 모듈 설정 변경 요청이다."""

    enabled: bool = True
    options: dict = Field(default_factory=dict)
    token: str


class ChatbotReloadRequest(BaseModel):
    """챗봇 모듈 reload 요청이다."""

    token: str


class ChatbotPackageInstallResponse(BaseModel):
    """로컬 챗봇 패키지 설치/업데이트 결과다."""

    ok: bool
    botKey: str
    folderName: str
    version: str
    packageSha256: str
    installedPath: str
    updated: bool
    reloadOk: Optional[bool] = None
    reloadLoaded: Optional[int] = None
    error: Optional[str] = None


class SendTargetFilter(BaseModel):
    """발송 가능한 방을 검색할 때 사용하는 필터다."""

    q: Optional[str] = None
    status: TargetStatus = TargetStatus.all
    sourceType: TargetSourceFilter = TargetSourceFilter.all
    roomType: Optional[RoomType] = None
    seenAfter: Optional[int] = None
    seenBefore: Optional[int] = None
    expiresAfter: Optional[int] = None
    expiresBefore: Optional[int] = None
    hasRecentFailure: Optional[bool] = None


class SendTargetSpec(BaseModel):
    """단건/그룹/전체 발송의 대상 선택 계약이다."""

    type: SendTargetType = SendTargetType.filter
    roomKeys: list[str] = Field(default_factory=list)
    filter: SendTargetFilter = Field(default_factory=SendTargetFilter)
    groupKey: Optional[str] = None


class SendTargetItem(BaseModel):
    """발송 대상 한 건의 현재 상태를 반환한다."""

    roomKey: str
    room: str
    roomAlias: Optional[str] = None
    lastSender: Optional[str] = None
    sourceType: SourceType
    roomType: RoomType = RoomType.unknown
    targetStatus: TargetStatus = TargetStatus.unknown
    replyTokenExpiresAt: Optional[int] = None
    lastSeenAt: int
    lastSendStatus: Optional[ReplyJobStatus] = None
    hasRecentFailure: bool = False


class SendTargetListResponse(BaseModel):
    """/send/targets 조회 응답이다."""

    items: list[SendTargetItem]
    nextCursor: Optional[str] = None


class SendBatchPreviewRequest(BaseModel):
    """실제 발송 전에 대상 수와 제외 사유를 계산하는 요청이다."""

    token: str
    target: SendTargetSpec
    text: str
    maxTargets: Optional[int] = None


class SendBatchPreviewResponse(BaseModel):
    """발송 대상 미리보기 결과다."""

    ok: bool
    targetCount: int
    excludedCount: int
    excludedReasons: dict[str, int] = Field(default_factory=dict)
    sample: list[dict[str, object]] = Field(default_factory=list)


class SendBatchRequest(BaseModel):
    """선택/전체/그룹 발송 요청이다."""

    token: str
    target: SendTargetSpec
    text: str
    dryRun: bool = False
    confirm: bool = False
    dedupeKey: Optional[str] = None
    maxTargets: Optional[int] = None


class SendGroupBatchRequest(BaseModel):
    """저장 그룹을 대상으로 batch 발송할 때 쓰는 요청이다."""

    token: str
    text: str
    dryRun: bool = False
    confirm: bool = False
    dedupeKey: Optional[str] = None
    maxTargets: Optional[int] = None


class SendBatchResponse(BaseModel):
    """발송 batch 생성 또는 dry-run 결과다."""

    ok: bool
    batchId: str
    status: SendBatchStatus
    targetCount: int
    queuedCount: int
    skippedCount: int
    excludedCount: int = 0
    excludedReasons: dict[str, int] = Field(default_factory=dict)
    error: Optional[str] = None


class SendBatchItemResponse(BaseModel):
    """batch에 속한 단일 target/job 상태다."""

    batchId: str
    roomKey: str
    room: str
    jobId: Optional[str] = None
    status: SendBatchItemStatus
    skipReason: Optional[str] = None
    createdAt: int
    updatedAt: int


class SendBatchItemListResponse(BaseModel):
    """batch item 목록과 다음 cursor를 반환한다."""

    items: list[SendBatchItemResponse]
    nextCursor: Optional[str] = None


class SendBatchRetryRequest(BaseModel):
    """실패 또는 만료된 batch item만 다시 보내는 요청이다."""

    token: str
    text: str
    dedupeKey: Optional[str] = None


class SendBatchSummaryResponse(BaseModel):
    """batch 집계 정보를 반환한다."""

    batchId: str
    status: SendBatchStatus
    targetCount: int
    queuedCount: int
    sentCount: int
    failedCount: int
    expiredCount: int
    skippedCount: int
    createdAt: int
    updatedAt: int
    completedAt: Optional[int] = None


class SendTargetGroupUpsertRequest(BaseModel):
    """발송 대상 그룹을 생성하거나 갱신하는 요청이다."""

    token: str
    groupKey: str
    name: str
    type: SendTargetGroupType
    enabled: bool = True
    roomKeys: list[str] = Field(default_factory=list)
    filter: Optional[SendTargetFilter] = None


class SendTargetGroupResponse(BaseModel):
    """저장된 발송 그룹을 반환한다."""

    groupKey: str
    name: str
    type: SendTargetGroupType
    enabled: bool
    roomKeys: list[str] = Field(default_factory=list)
    filter: Optional[SendTargetFilter] = None
    createdAt: int
    updatedAt: int
