from __future__ import annotations
from app.schemas import BridgeEvent, EventAction, EventResponse, RoomRuleMode, RoomRuleResponse


def decide_event_response(
    event: BridgeEvent,
    room_rule: RoomRuleResponse | None = None,
) -> EventResponse:
    """수신 메시지에 대한 MVP 자동 응답 정책을 결정한다.

    저장된 방별 룰이 있으면 `disabled`, `manual`, `keyword` 정책을 먼저 적용한다.
    `manual:`로 시작하면 무응답, `queue:`로 시작하면 큐 적재 응답을 반환한다.
    그 외 replyToken이 있는 텍스트 메시지는 PC-only 검증을 위해 즉시 답장을 반환한다.
    """

    lowered = event.text.strip().lower()
    if room_rule is not None:
        return _decide_from_room_rule(event, room_rule, lowered)
    if lowered.startswith("manual:"):
        return EventResponse(ack=True, action=EventAction.none)
    if lowered.startswith("queue:"):
        return EventResponse(ack=True, action=EventAction.queued)
    if event.replyToken:
        return EventResponse(
            ack=True,
            action=EventAction.reply,
            replyToken=event.replyToken,
            text="확인했습니다.",
        )
    return EventResponse(ack=True, action=EventAction.none)


def _decide_from_room_rule(
    event: BridgeEvent,
    room_rule: RoomRuleResponse,
    lowered_text: str,
) -> EventResponse:
    if not room_rule.enabled or room_rule.mode == RoomRuleMode.disabled:
        return EventResponse(ack=True, action=EventAction.none)
    if room_rule.mode == RoomRuleMode.manual:
        return EventResponse(ack=True, action=EventAction.none)
    if room_rule.mode == RoomRuleMode.keyword:
        if any(keyword.strip().lower() in lowered_text for keyword in room_rule.rule.queueKeywords if keyword.strip()):
            return EventResponse(ack=True, action=EventAction.queued)
        if event.replyToken is None:
            return EventResponse(ack=True, action=EventAction.none)
        for rule in room_rule.rule.keywords:
            if rule.keyword.strip().lower() in lowered_text:
                return EventResponse(
                    ack=True,
                    action=EventAction.reply,
                    replyToken=event.replyToken,
                    text=rule.reply,
                )
    return EventResponse(ack=True, action=EventAction.none)
