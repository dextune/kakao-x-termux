from __future__ import annotations
"""Compatibility facade for domain별 repository modules.

기존 코드와 테스트의 `app.repository` import를 유지하면서 실제 구현은
`app.repositories.*` 파일로 분리한다.
"""

from app.repositories.bridge_logs import (
    count_bridge_logs,
    insert_bridge_log,
    list_bridge_logs,
    prune_bridge_logs,
    prune_bridge_logs_throttled,
)
from app.repositories.chatbot_modules import (
    count_chatbot_module_files,
    count_chatbot_modules_with_errors,
    get_chatbot_module_file_by_key,
    get_chatbot_module,
    get_room_bot_options,
    list_chatbot_module_files,
    list_chatbot_modules,
    list_chatbot_modules_by_key,
    list_room_bot_options_by_key,
    list_room_bot_options_grouped,
    mark_chatbot_module_error,
    update_chatbot_module_config,
    upsert_chatbot_module,
    upsert_chatbot_module_file,
    upsert_room_bot_options,
)
from app.repositories.chatbot_marketplace_installs import (
    get_marketplace_install,
    upsert_marketplace_install,
)
from app.config import get_settings
from app.db import connect
from app.repositories.chatbot_runs import (
    insert_chatbot_run,
    list_chatbot_runs,
    prune_chatbot_runs as _prune_chatbot_runs,
)
from app.repositories.chatbot_states import (
    delete_bot_state,
    get_bot_state,
    get_bot_state_snapshot,
    list_bot_state_snapshots,
    list_bot_states,
    prune_bot_states as _prune_bot_states,
    set_bot_state,
    update_bot_state,
    update_bot_state_with_result,
)
from app.repositories.messages import (
    expires_at_for_token,
    get_message,
    insert_message,
    latest_reply_token,
    list_messages,
    list_unprocessed_messages,
    mark_message_processed,
    recent_message_records,
    search_messages,
    soft_delete_message,
    update_message,
)
from app.repositories.reply_jobs import (
    claim_reply_job_for_dispatch,
    complete_reply_job_if_owned,
    get_reply_job,
    insert_reply_job,
    list_recoverable_reply_jobs,
    mark_reply_job_retrying_if_owned,
    queued_reply_job_metrics,
    update_reply_job,
    update_reply_job_if_status,
)
from app.repositories.room_rules import get_room_rule, upsert_room_rule
from app.repositories.send_batches import (
    count_send_batches_by_status,
    get_send_batch,
    get_send_batch_items_summary,
    insert_send_batch,
    insert_send_batch_item,
    list_send_batch_items,
    list_send_batches,
    update_send_batch_counts,
    update_send_batch_item_status,
)
from app.repositories.send_groups import (
    delete_send_target_group,
    get_send_target_group,
    list_send_target_group_rooms,
    list_send_target_groups,
    replace_send_target_group_rooms,
    upsert_send_target_group,
)
from app.repositories.send_targets import (
    count_latest_send_targets,
    get_latest_send_target_for_room_key,
    get_latest_send_targets_for_room_keys,
    list_latest_send_targets,
)
from app.time_utils import now_millis

_last_state_prune_at: dict[str, int] = {}
_last_run_prune_at: dict[str, int] = {}


def prune_bot_states(now: int | None = None) -> int:
    """Compatibility wrapper for monkeypatch-friendly state pruning."""

    return _prune_bot_states(now=now)


def prune_bot_states_throttled(interval_millis: int, now: int | None = None) -> int:
    """DB path별 interval 안에서는 만료 상태 전체 삭제를 건너뛴다."""

    db_path = get_settings().db_path
    current = now if now is not None else now_millis()
    last = _last_state_prune_at.get(db_path)
    if last is not None and current - last < max(interval_millis, 0):
        return 0
    _last_state_prune_at[db_path] = current
    return prune_bot_states(now=current)


def prune_chatbot_runs(max_rows: int, retention_millis: int, now: int | None = None) -> None:
    """Compatibility wrapper for monkeypatch-friendly chatbot run pruning."""

    _prune_chatbot_runs(max_rows=max_rows, retention_millis=retention_millis, now=now)


def prune_chatbot_runs_throttled(
    max_rows: int,
    retention_millis: int,
    interval_millis: int,
    now: int | None = None,
) -> None:
    """실행 로그 pruning을 DB path별 interval 기준으로 제한한다."""

    db_path = get_settings().db_path
    current = now if now is not None else now_millis()
    last = _last_run_prune_at.get(db_path)
    if last is not None and current - last < max(interval_millis, 0):
        return
    _last_run_prune_at[db_path] = current
    prune_chatbot_runs(max_rows=max_rows, retention_millis=retention_millis, now=current)

__all__ = [
    "claim_reply_job_for_dispatch",
    "complete_reply_job_if_owned",
    "count_bridge_logs",
    "count_latest_send_targets",
    "count_send_batches_by_status",
    "count_chatbot_module_files",
    "count_chatbot_modules_with_errors",
    "get_chatbot_module_file_by_key",
    "connect",
    "delete_bot_state",
    "delete_send_target_group",
    "expires_at_for_token",
    "get_bot_state",
    "get_bot_state_snapshot",
    "get_chatbot_module",
    "get_room_bot_options",
    "get_room_rule",
    "get_latest_send_target_for_room_key",
    "get_latest_send_targets_for_room_keys",
    "get_message",
    "get_marketplace_install",
    "get_reply_job",
    "get_send_batch",
    "get_send_batch_items_summary",
    "get_send_target_group",
    "insert_bridge_log",
    "insert_chatbot_run",
    "insert_message",
    "insert_send_batch",
    "insert_send_batch_item",
    "insert_reply_job",
    "latest_reply_token",
    "list_recoverable_reply_jobs",
    "list_latest_send_targets",
    "list_messages",
    "list_unprocessed_messages",
    "list_bot_states",
    "list_bot_state_snapshots",
    "list_bridge_logs",
    "list_chatbot_module_files",
    "list_chatbot_modules",
    "list_chatbot_modules_by_key",
    "list_chatbot_runs",
    "list_send_batch_items",
    "list_send_batches",
    "list_send_target_group_rooms",
    "list_send_target_groups",
    "list_room_bot_options_by_key",
    "list_room_bot_options_grouped",
    "mark_chatbot_module_error",
    "mark_message_processed",
    "mark_reply_job_retrying_if_owned",
    "queued_reply_job_metrics",
    "prune_bot_states",
    "prune_bot_states_throttled",
    "prune_bridge_logs",
    "prune_bridge_logs_throttled",
    "prune_chatbot_runs",
    "prune_chatbot_runs_throttled",
    "set_bot_state",
    "replace_send_target_group_rooms",
    "recent_message_records",
    "search_messages",
    "update_bot_state",
    "update_bot_state_with_result",
    "update_chatbot_module_config",
    "update_message",
    "update_send_batch_counts",
    "update_send_batch_item_status",
    "update_reply_job",
    "update_reply_job_if_status",
    "upsert_chatbot_module",
    "upsert_chatbot_module_file",
    "upsert_marketplace_install",
    "upsert_send_target_group",
    "upsert_room_bot_options",
    "upsert_room_rule",
    "soft_delete_message",
]
