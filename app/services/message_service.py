from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import HTTPException

from app import repository
from app.schemas import BridgeEvent, MessageItem, MessageListResponse, MessagePatchRequest
from app.security import verify_token


def _cursor_for_row(row: sqlite3.Row) -> str:
    return f"{int(row['received_at'])}\t{int(row['id'])}"


def _row_to_item(row: sqlite3.Row) -> MessageItem:
    updated_at = row["updated_at"] if row["updated_at"] is not None else row["created_at"]
    return MessageItem(
        eventId=row["event_id"],
        roomKey=row["room_key"],
        room=row["room"],
        sender=row["sender"],
        text=row["text"],
        messageType=row["message_type"],
        sourceType=row["source_type"],
        receivedAt=int(row["received_at"]),
        processed=bool(row["processed"]),
        createdAt=int(row["created_at"]),
        updatedAt=int(updated_at),
        deletedAt=row["deleted_at"],
    )


class MessageService:
    """메시지 관리 API의 인증, 응답 조립, repository 호출을 담당한다."""

    def create(self, event: BridgeEvent) -> MessageItem:
        verify_token(event.token)
        inserted = repository.insert_message(event)
        if not inserted:
            raise HTTPException(status_code=409, detail="duplicate eventId")
        row = repository.get_message(event.eventId)
        if row is None:
            raise HTTPException(status_code=500, detail="message insert failed")
        return _row_to_item(row)

    def get(self, event_id: str, *, token: str, include_deleted: bool = False) -> MessageItem:
        verify_token(token)
        row = repository.get_message(event_id, include_deleted=include_deleted)
        if row is None:
            raise HTTPException(status_code=404, detail="message not found")
        return _row_to_item(row)

    def list(
        self,
        *,
        token: str,
        room_key: str | None = None,
        sender: str | None = None,
        source_type: str | None = None,
        message_type: str | None = None,
        received_after: int | None = None,
        received_before: int | None = None,
        include_deleted: bool = False,
        limit: int = 50,
        cursor: str | None = None,
    ) -> MessageListResponse:
        verify_token(token)
        effective_limit = max(min(limit, 200), 1)
        rows = repository.list_messages(
            room_key=room_key,
            sender=sender,
            source_type=source_type,
            message_type=message_type,
            received_after=received_after,
            received_before=received_before,
            include_deleted=include_deleted,
            limit=effective_limit + 1,
            cursor=cursor,
        )
        return self._page(rows, effective_limit)

    def search(
        self,
        *,
        token: str,
        q: str,
        room_key: str | None = None,
        sender: str | None = None,
        source_type: str | None = None,
        message_type: str | None = None,
        received_after: int | None = None,
        received_before: int | None = None,
        include_deleted: bool = False,
        limit: int = 50,
        cursor: str | None = None,
    ) -> MessageListResponse:
        verify_token(token)
        effective_limit = max(min(limit, 200), 1)
        rows = repository.search_messages(
            query_text=q,
            room_key=room_key,
            sender=sender,
            source_type=source_type,
            message_type=message_type,
            received_after=received_after,
            received_before=received_before,
            include_deleted=include_deleted,
            limit=effective_limit + 1,
            cursor=cursor,
        )
        return self._page(rows, effective_limit)

    def update(self, event_id: str, request: MessagePatchRequest) -> MessageItem:
        verify_token(request.token)
        payload: dict[str, Any] = request.model_dump(exclude_unset=True)
        payload.pop("token", None)
        row = repository.update_message(event_id, payload)
        if row is None:
            raise HTTPException(status_code=404, detail="message not found")
        return _row_to_item(row)

    def delete(self, event_id: str, *, token: str) -> MessageItem:
        verify_token(token)
        row = repository.soft_delete_message(event_id)
        if row is None:
            raise HTTPException(status_code=404, detail="message not found")
        return _row_to_item(row)

    def _page(self, rows: list[sqlite3.Row], effective_limit: int) -> MessageListResponse:
        page_rows = rows[:effective_limit]
        next_cursor = _cursor_for_row(page_rows[-1]) if len(rows) > effective_limit and page_rows else None
        return MessageListResponse(items=[_row_to_item(row) for row in page_rows], nextCursor=next_cursor)
