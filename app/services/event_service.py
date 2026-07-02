from __future__ import annotations

from app.chatbot.service import ChatbotService
from app.config import get_settings
from app.infra.errors import safe_bridge_log
from app.infra.runtime_resources import RuntimeResources, get_runtime_resources
from app.log_policy import log_event_result
from app.repository import insert_message, mark_message_processed
from app.schemas import BridgeEvent, EventAction, EventResponse
from app.security import verify_token


class EventService:
    """`/events` 요청의 저장, 처리, 로깅 흐름을 담당한다."""

    def __init__(self, chatbot_service: ChatbotService, resources_provider=get_runtime_resources) -> None:
        self.chatbot_service = chatbot_service
        self._resources_provider = resources_provider

    def handle_event(self, event: BridgeEvent) -> EventResponse:
        """메시지 이벤트를 처리하고 계약 응답을 반환한다.

        프로세서 내부 예외는 HTTP 500으로 노출하지 않고 `none` 응답과 운영 로그로 격리한다.
        """

        verify_token(event.token)
        resources: RuntimeResources = self._resources_provider()
        resources.reply_token_cache.update_from_event(event)
        settings = get_settings()
        if settings.event_process_mode == "memory_queue":
            return self._handle_memory_queue_event(event)
        if settings.event_process_mode != "inline_wait":
            safe_bridge_log("WARN", "event", f"unknown event process mode: {settings.event_process_mode}", event.eventId)
        try:
            inserted = insert_message(event)
        except Exception as exc:
            safe_bridge_log("ERROR", "event", f"event insert failed: {exc}", event.eventId)
            return EventResponse(ack=True, action=EventAction.none, error="internal processing error")

        if not inserted:
            response = EventResponse(ack=True, action=EventAction.none, error="duplicate eventId")
            try:
                log_event_result(event, response, duplicate=True)
            except Exception as exc:
                safe_bridge_log("ERROR", "event", f"duplicate event result log failed: {exc}", event.eventId)
            return response

        return self._process_inserted_event(event, mark_processed=True, log_result=True)

    def _handle_memory_queue_event(self, event: BridgeEvent) -> EventResponse:
        settings = get_settings()
        resources: RuntimeResources = self._resources_provider()
        backup = settings.event_durability_mode in ("enqueue_backup", "memory_only")
        if settings.event_durability_mode == "sync_backup":
            try:
                inserted = insert_message(event)
            except Exception as exc:
                safe_bridge_log("ERROR", "event", f"sync event backup failed: {exc}", event.eventId)
                return EventResponse(ack=True, action=EventAction.none, error="internal processing error")
            if not inserted:
                response = EventResponse(ack=True, action=EventAction.none, error="duplicate eventId")
                try:
                    log_event_result(event, response, duplicate=True)
                except Exception as exc:
                    safe_bridge_log("ERROR", "event", f"duplicate event result log failed: {exc}", event.eventId)
                return response
            backup = False
        elif settings.event_durability_mode == "memory_only":
            backup = False

        result = resources.memory_pipeline.enqueue_event(
            event,
            lambda queued_event: self._process_inserted_event(queued_event, mark_processed=False, log_result=True),
            backup=backup,
            checkpoint_processed=settings.event_durability_mode != "memory_only",
        )
        if result.duplicate:
            response = EventResponse(ack=True, action=EventAction.none, error="duplicate eventId")
            try:
                log_event_result(event, response, duplicate=True)
            except Exception as exc:
                safe_bridge_log("ERROR", "event", f"duplicate event result log failed: {exc}", event.eventId)
            return response
        if not result.accepted:
            safe_bridge_log("WARN", "event", f"memory queue rejected: {result.error}", event.eventId)
            return EventResponse(ack=False, action=EventAction.none, error=result.error or "event queue rejected")
        return EventResponse(ack=True, action=EventAction.queued)

    def _process_inserted_event(
        self,
        event: BridgeEvent,
        *,
        mark_processed: bool,
        log_result: bool,
    ) -> EventResponse:
        response: EventResponse
        try:
            room_rule = self._resources_provider().config_cache.get_room_rule(event.roomKey)
            response = self.chatbot_service.process(event, room_rule)
            if get_settings().event_process_mode == "inline_wait":
                self.chatbot_service.state_store.flush_dirty()
        except Exception as exc:
            safe_bridge_log("ERROR", "event", f"event processing failed: {exc}", event.eventId)
            response = EventResponse(ack=True, action=EventAction.none, error="internal processing error")

        if mark_processed:
            try:
                mark_message_processed(event.eventId)
            except Exception as exc:
                safe_bridge_log("ERROR", "event", f"mark processed failed: {exc}", event.eventId)

        if log_result and get_settings().event_result_log_enabled:
            try:
                log_event_result(event, response)
            except Exception as exc:
                safe_bridge_log("ERROR", "event", f"event result log failed: {exc}", event.eventId)
        return response

    def recover_inserted_event(self, event: BridgeEvent) -> EventResponse:
        """DB backup에 있지만 processed 되지 않은 이벤트를 재시작 후 처리한다."""

        return self._process_inserted_event(event, mark_processed=True, log_result=True)
