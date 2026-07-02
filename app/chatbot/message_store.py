from __future__ import annotations

from dataclasses import dataclass

from app import repository


@dataclass(frozen=True)
class MessageRecord:
    """봇에 노출하는 안정된 읽기 전용 메시지 모델이다."""

    eventId: str
    roomKey: str
    room: str
    sender: str | None
    text: str
    messageType: str
    sourceType: str
    receivedAt: int
    processed: bool
    createdAt: int
    updatedAt: int


def _row_to_record(row) -> MessageRecord:
    updated_at = row["updated_at"] if row["updated_at"] is not None else row["created_at"]
    return MessageRecord(
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
    )


class ReadOnlyMessageStore:
    """챗봇 runtime이 사용하는 읽기 전용 메시지 조회 helper다."""

    def recent(self, room_key: str, limit: int = 20, before: int | None = None) -> list[MessageRecord]:
        rows = repository.recent_message_records(room_key, limit=limit, before=before)
        return [_row_to_record(row) for row in rows]

    def search(self, query: str, room_key: str | None = None, limit: int = 20) -> list[MessageRecord]:
        rows = repository.search_messages(
            query_text=query,
            room_key=room_key,
            include_deleted=False,
            limit=max(min(limit, 100), 1),
        )
        return [_row_to_record(row) for row in rows]

    def get(self, event_id: str) -> MessageRecord | None:
        row = repository.get_message(event_id, include_deleted=False)
        if row is None:
            return None
        return _row_to_record(row)
