from __future__ import annotations
import os
from dataclasses import dataclass
from threading import RLock

DEFAULT_CHATBOT_REQUEST_TIMEOUT_MS = 30_000
DEFAULT_CHATBOT_LOAD_TIMEOUT_MS = 3_000
INTERNAL_SHARED_SECRET = "shared-secret"


@dataclass(frozen=True)
class Settings:
    """Termux 백엔드 실행 환경을 담는다.

    쓰기 API 인증값, SQLite 경로, 답장 전달 adapter 선택값을 환경 변수에서 읽는다.
    """

    shared_secret: str = INTERNAL_SHARED_SECRET
    bridge_mode: str = "am_broadcast"
    test_backend_url: str = "http://127.0.0.1:9797"
    adb_serial: str = "127.0.0.1:5555"
    db_path: str = "data/backend.sqlite3"
    log_pii: bool = False
    bridge_log_max_rows: int = 10_000
    bridge_log_retention_millis: int = 7 * 24 * 60 * 60 * 1000
    bridge_log_prune_interval_millis: int = 60_000
    adapter_max_attempts: int = 3
    chatbot_enabled: bool = True
    chatbot_bot_dir: str = "app/bots"
    chatbot_default_timeout_ms: int = DEFAULT_CHATBOT_REQUEST_TIMEOUT_MS
    chatbot_max_reply_chars: int = 800
    chatbot_state_prune_interval_millis: int = 60_000
    chatbot_run_max_rows: int = 10_000
    chatbot_run_retention_millis: int = 7 * 24 * 60 * 60 * 1000
    chatbot_run_prune_interval_millis: int = 60_000
    chatbot_max_state_bytes: int = 8_192
    chatbot_hot_reload_enabled: bool = True
    chatbot_hot_reload_interval_ms: int = 2_000
    chatbot_file_hash_enabled: bool = True
    chatbot_reload_max_files_per_tick: int = 20
    chatbot_bot_load_timeout_ms: int = DEFAULT_CHATBOT_LOAD_TIMEOUT_MS
    chatbot_bot_handle_timeout_ms: int = DEFAULT_CHATBOT_REQUEST_TIMEOUT_MS
    chatbot_max_loaded_bots: int = 100
    chatbot_max_bot_file_bytes: int = 262_144
    chatbot_max_pattern_count_per_bot: int = 100
    chatbot_max_option_bytes: int = 16_384
    chatbot_observer_workers: int = 1
    chatbot_observer_queue_size: int = 128
    chatbot_external_workers: int = 2
    chatbot_external_queue_size: int = 64
    chatbot_external_wait_timeout_ms: int = DEFAULT_CHATBOT_REQUEST_TIMEOUT_MS
    adapter_external_workers: int = 2
    adapter_external_queue_size: int = 128
    adapter_external_wait_timeout_ms: int = 15_000
    http_client_max_connections: int = 20
    http_client_max_keepalive: int = 10
    sqlite_busy_timeout_ms: int = 5_000
    event_process_mode: str = "inline_wait"
    event_inline_wait_timeout_ms: int = 100
    event_result_log_enabled: bool = True
    event_queue_size: int = 1_000
    event_durability_mode: str = "enqueue_backup"
    event_dedupe_ttl_ms: int = 300_000
    room_workers: int = 4
    room_max_pending_per_room: int = 500
    room_max_active_partitions: int = 10_000
    room_overflow_policy: str = "drop_newest"
    sqlite_writer_batch_size: int = 100
    sqlite_writer_flush_interval_ms: int = 100
    sqlite_writer_queue_size: int = 10_000
    sqlite_writer_drop_low_priority: bool = True
    send_dispatch_mode: str = "sync_wait"
    dispatch_queue_size: int = 2_000
    dispatch_workers: int = 2
    dispatch_max_attempts: int = 3
    dispatch_retry_backoff_ms: int = 1_000
    dispatch_lease_ms: int = 60_000
    recovery_batch_limit: int = 100
    recovery_dispatching_stale_ms: int = 300_000
    memory_state_enabled: bool = True
    memory_state_max_entries: int = 50_000
    memory_state_flush_interval_ms: int = 1_000
    memory_state_background_flush_enabled: bool = True
    memory_state_warmup_enabled: bool = True
    memory_config_warmup_enabled: bool = True
    memory_config_room_option_warmup_enabled: bool = True
    memory_config_room_option_max_rooms: int = 10_000
    memory_config_room_option_max_rows: int = 50_000
    memory_config_reconcile_enabled: bool = True
    memory_config_reconcile_interval_ms: int = 5_000
    recovery_scheduler_enabled: bool = True
    recovery_scheduler_interval_ms: int = 30_000
    bulk_send_enabled: bool = False
    bulk_send_max_targets: int = 100
    bulk_send_rate_per_second: int = 5
    bulk_send_require_dry_run: bool = True
    bulk_send_token_safety_window_ms: int = 5_000
    bulk_send_target_page_size: int = 50
    bulk_send_target_max_page_size: int = 500
    bulk_send_exclude_expired: bool = True
    bulk_send_allowed_source_types: str = "real_kakao,virtual_phone"
    send_target_cache_max_rooms: int = 10_000
    send_target_cache_expire_sweep_interval_ms: int = 30_000


_ENV_NAMES = (
    "BRIDGE_SHARED_SECRET",
    "ANDROID_BRIDGE_MODE",
    "TEST_BACKEND_URL",
    "ADB_SERIAL",
    "BACKEND_DB_PATH",
    "LOG_PII",
    "BRIDGE_LOG_MAX_ROWS",
    "BRIDGE_LOG_RETENTION_DAYS",
    "BRIDGE_LOG_PRUNE_INTERVAL_MS",
    "ADAPTER_MAX_ATTEMPTS",
    "CHATBOT_ENABLED",
    "CHATBOT_BOT_DIR",
    "CHATBOT_DEFAULT_TIMEOUT_MS",
    "CHATBOT_MAX_REPLY_CHARS",
    "CHATBOT_STATE_PRUNE_INTERVAL_MS",
    "CHATBOT_RUN_MAX_ROWS",
    "CHATBOT_RUN_RETENTION_DAYS",
    "CHATBOT_RUN_PRUNE_INTERVAL_MS",
    "CHATBOT_MAX_STATE_BYTES",
    "CHATBOT_HOT_RELOAD_ENABLED",
    "CHATBOT_HOT_RELOAD_INTERVAL_MS",
    "CHATBOT_FILE_HASH_ENABLED",
    "CHATBOT_RELOAD_MAX_FILES_PER_TICK",
    "CHATBOT_BOT_LOAD_TIMEOUT_MS",
    "CHATBOT_BOT_HANDLE_TIMEOUT_MS",
    "CHATBOT_MAX_LOADED_BOTS",
    "CHATBOT_MAX_BOT_FILE_BYTES",
    "CHATBOT_MAX_PATTERN_COUNT_PER_BOT",
    "CHATBOT_MAX_OPTION_BYTES",
    "CHATBOT_OBSERVER_WORKERS",
    "CHATBOT_OBSERVER_QUEUE_SIZE",
    "CHATBOT_EXTERNAL_WORKERS",
    "CHATBOT_EXTERNAL_QUEUE_SIZE",
    "CHATBOT_EXTERNAL_WAIT_TIMEOUT_MS",
    "ADAPTER_EXTERNAL_WORKERS",
    "ADAPTER_EXTERNAL_QUEUE_SIZE",
    "ADAPTER_EXTERNAL_WAIT_TIMEOUT_MS",
    "HTTP_CLIENT_MAX_CONNECTIONS",
    "HTTP_CLIENT_MAX_KEEPALIVE",
    "SQLITE_BUSY_TIMEOUT_MS",
    "EVENT_PROCESS_MODE",
    "EVENT_INLINE_WAIT_TIMEOUT_MS",
    "EVENT_RESULT_LOG_ENABLED",
    "EVENT_QUEUE_SIZE",
    "EVENT_DURABILITY_MODE",
    "EVENT_DEDUPE_TTL_MS",
    "ROOM_WORKERS",
    "ROOM_MAX_PENDING_PER_ROOM",
    "ROOM_IDLE_EVICT_MILLIS",
    "ROOM_MAX_ACTIVE_PARTITIONS",
    "ROOM_OVERFLOW_POLICY",
    "SQLITE_WRITER_BATCH_SIZE",
    "SQLITE_WRITER_FLUSH_INTERVAL_MS",
    "SQLITE_WRITER_QUEUE_SIZE",
    "SQLITE_WRITER_DROP_LOW_PRIORITY",
    "SEND_DISPATCH_MODE",
    "DISPATCH_QUEUE_SIZE",
    "DISPATCH_WORKERS",
    "DISPATCH_MAX_ATTEMPTS",
    "DISPATCH_RETRY_BACKOFF_MS",
    "DISPATCH_LEASE_MS",
    "RECOVERY_BATCH_LIMIT",
    "RECOVERY_DISPATCHING_STALE_MS",
    "MEMORY_STATE_ENABLED",
    "MEMORY_STATE_MAX_ENTRIES",
    "MEMORY_STATE_FLUSH_INTERVAL_MS",
    "MEMORY_STATE_BACKGROUND_FLUSH_ENABLED",
    "MEMORY_STATE_WARMUP_ENABLED",
    "MEMORY_CONFIG_WARMUP_ENABLED",
    "MEMORY_CONFIG_ROOM_OPTION_WARMUP_ENABLED",
    "MEMORY_CONFIG_ROOM_OPTION_MAX_ROOMS",
    "MEMORY_CONFIG_ROOM_OPTION_MAX_ROWS",
    "MEMORY_CONFIG_RECONCILE_ENABLED",
    "MEMORY_CONFIG_RECONCILE_INTERVAL_MS",
    "RECOVERY_SCHEDULER_ENABLED",
    "RECOVERY_SCHEDULER_INTERVAL_MS",
    "BULK_SEND_ENABLED",
    "BULK_SEND_MAX_TARGETS",
    "BULK_SEND_RATE_PER_SECOND",
    "BULK_SEND_REQUIRE_DRY_RUN",
    "BULK_SEND_TOKEN_SAFETY_WINDOW_MS",
    "BULK_SEND_TARGET_PAGE_SIZE",
    "BULK_SEND_TARGET_MAX_PAGE_SIZE",
    "BULK_SEND_EXCLUDE_EXPIRED",
    "BULK_SEND_ALLOWED_SOURCE_TYPES",
    "SEND_TARGET_CACHE_MAX_ROOMS",
    "SEND_TARGET_CACHE_EXPIRE_SWEEP_INTERVAL_MS",
)

_settings_lock = RLock()
_settings_cache: Settings | None = None
_settings_signature: tuple[tuple[str, str | None], ...] | None = None


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_int_with_fallback(name: str, fallback_name: str, default: int) -> int:
    if os.getenv(name) is not None:
        return _env_int(name, default)
    return _env_int(fallback_name, default)


def get_settings() -> Settings:
    """현재 프로세스 환경 기준 설정을 반환한다.

    운영 hot path 비용을 줄이기 위해 env signature가 바뀌지 않으면 캐시를 재사용한다.
    테스트는 `reset_settings_for_test()`로 명시 초기화할 수 있고, env 변경도 자동 감지한다.
    """

    global _settings_cache, _settings_signature
    if _settings_cache is not None and os.getenv("SETTINGS_AUTO_RELOAD", "true").lower() == "false":
        return _settings_cache
    signature = tuple((name, os.getenv(name)) for name in _ENV_NAMES)
    with _settings_lock:
        if _settings_cache is not None and _settings_signature == signature:
            return _settings_cache

    bridge_log_retention_days = _env_int("BRIDGE_LOG_RETENTION_DAYS", 7)
    chatbot_run_retention_days = _env_int("CHATBOT_RUN_RETENTION_DAYS", 7)
    settings = Settings(
        shared_secret=os.getenv("BRIDGE_SHARED_SECRET", INTERNAL_SHARED_SECRET),
        bridge_mode=os.getenv("ANDROID_BRIDGE_MODE", "am_broadcast"),
        test_backend_url=os.getenv("TEST_BACKEND_URL", "http://127.0.0.1:9797"),
        adb_serial=os.getenv("ADB_SERIAL", "127.0.0.1:5555"),
        db_path=os.getenv("BACKEND_DB_PATH", "data/backend.sqlite3"),
        log_pii=os.getenv("LOG_PII", "false").lower() == "true",
        bridge_log_max_rows=_env_int("BRIDGE_LOG_MAX_ROWS", 10_000),
        bridge_log_retention_millis=max(bridge_log_retention_days, 0) * 24 * 60 * 60 * 1000,
        bridge_log_prune_interval_millis=_env_int("BRIDGE_LOG_PRUNE_INTERVAL_MS", 60_000),
        adapter_max_attempts=_env_int("ADAPTER_MAX_ATTEMPTS", 3),
        chatbot_enabled=os.getenv("CHATBOT_ENABLED", "true").lower() == "true",
        chatbot_bot_dir=os.getenv("CHATBOT_BOT_DIR", "app/bots"),
        chatbot_default_timeout_ms=_env_int("CHATBOT_DEFAULT_TIMEOUT_MS", DEFAULT_CHATBOT_REQUEST_TIMEOUT_MS),
        chatbot_max_reply_chars=_env_int("CHATBOT_MAX_REPLY_CHARS", 800),
        chatbot_state_prune_interval_millis=_env_int("CHATBOT_STATE_PRUNE_INTERVAL_MS", 60_000),
        chatbot_run_max_rows=_env_int("CHATBOT_RUN_MAX_ROWS", 10_000),
        chatbot_run_retention_millis=max(chatbot_run_retention_days, 0) * 24 * 60 * 60 * 1000,
        chatbot_run_prune_interval_millis=_env_int("CHATBOT_RUN_PRUNE_INTERVAL_MS", 60_000),
        chatbot_max_state_bytes=_env_int("CHATBOT_MAX_STATE_BYTES", 8_192),
        chatbot_hot_reload_enabled=os.getenv("CHATBOT_HOT_RELOAD_ENABLED", "true").lower() == "true",
        chatbot_hot_reload_interval_ms=_env_int("CHATBOT_HOT_RELOAD_INTERVAL_MS", 2_000),
        chatbot_file_hash_enabled=os.getenv("CHATBOT_FILE_HASH_ENABLED", "true").lower() == "true",
        chatbot_reload_max_files_per_tick=_env_int("CHATBOT_RELOAD_MAX_FILES_PER_TICK", 20),
        chatbot_bot_load_timeout_ms=_env_int("CHATBOT_BOT_LOAD_TIMEOUT_MS", DEFAULT_CHATBOT_LOAD_TIMEOUT_MS),
        chatbot_bot_handle_timeout_ms=_env_int("CHATBOT_BOT_HANDLE_TIMEOUT_MS", DEFAULT_CHATBOT_REQUEST_TIMEOUT_MS),
        chatbot_max_loaded_bots=_env_int("CHATBOT_MAX_LOADED_BOTS", 100),
        chatbot_max_bot_file_bytes=_env_int("CHATBOT_MAX_BOT_FILE_BYTES", 262_144),
        chatbot_max_pattern_count_per_bot=_env_int("CHATBOT_MAX_PATTERN_COUNT_PER_BOT", 100),
        chatbot_max_option_bytes=_env_int("CHATBOT_MAX_OPTION_BYTES", 16_384),
        chatbot_observer_workers=_env_int("CHATBOT_OBSERVER_WORKERS", 1),
        chatbot_observer_queue_size=_env_int("CHATBOT_OBSERVER_QUEUE_SIZE", 128),
        chatbot_external_workers=_env_int("CHATBOT_EXTERNAL_WORKERS", 2),
        chatbot_external_queue_size=_env_int("CHATBOT_EXTERNAL_QUEUE_SIZE", 64),
        chatbot_external_wait_timeout_ms=_env_int("CHATBOT_EXTERNAL_WAIT_TIMEOUT_MS", DEFAULT_CHATBOT_REQUEST_TIMEOUT_MS),
        adapter_external_workers=_env_int("ADAPTER_EXTERNAL_WORKERS", 2),
        adapter_external_queue_size=_env_int("ADAPTER_EXTERNAL_QUEUE_SIZE", 128),
        adapter_external_wait_timeout_ms=_env_int("ADAPTER_EXTERNAL_WAIT_TIMEOUT_MS", 15_000),
        http_client_max_connections=_env_int("HTTP_CLIENT_MAX_CONNECTIONS", 20),
        http_client_max_keepalive=_env_int("HTTP_CLIENT_MAX_KEEPALIVE", 10),
        sqlite_busy_timeout_ms=_env_int("SQLITE_BUSY_TIMEOUT_MS", 5_000),
        event_process_mode=os.getenv("EVENT_PROCESS_MODE", "inline_wait"),
        event_inline_wait_timeout_ms=_env_int("EVENT_INLINE_WAIT_TIMEOUT_MS", 100),
        event_result_log_enabled=os.getenv("EVENT_RESULT_LOG_ENABLED", "true").lower() == "true",
        event_queue_size=_env_int("EVENT_QUEUE_SIZE", 1_000),
        event_durability_mode=os.getenv("EVENT_DURABILITY_MODE", "enqueue_backup"),
        event_dedupe_ttl_ms=_env_int_with_fallback("EVENT_DEDUPE_TTL_MS", "ROOM_IDLE_EVICT_MILLIS", 300_000),
        room_workers=_env_int("ROOM_WORKERS", 4),
        room_max_pending_per_room=_env_int("ROOM_MAX_PENDING_PER_ROOM", 500),
        room_max_active_partitions=_env_int("ROOM_MAX_ACTIVE_PARTITIONS", 10_000),
        room_overflow_policy=os.getenv("ROOM_OVERFLOW_POLICY", "drop_newest"),
        sqlite_writer_batch_size=_env_int("SQLITE_WRITER_BATCH_SIZE", 100),
        sqlite_writer_flush_interval_ms=_env_int("SQLITE_WRITER_FLUSH_INTERVAL_MS", 100),
        sqlite_writer_queue_size=_env_int("SQLITE_WRITER_QUEUE_SIZE", 10_000),
        sqlite_writer_drop_low_priority=os.getenv("SQLITE_WRITER_DROP_LOW_PRIORITY", "true").lower() == "true",
        send_dispatch_mode=os.getenv("SEND_DISPATCH_MODE", "sync_wait"),
        dispatch_queue_size=_env_int("DISPATCH_QUEUE_SIZE", 2_000),
        dispatch_workers=_env_int("DISPATCH_WORKERS", 2),
        dispatch_max_attempts=_env_int("DISPATCH_MAX_ATTEMPTS", 3),
        dispatch_retry_backoff_ms=_env_int("DISPATCH_RETRY_BACKOFF_MS", 1_000),
        dispatch_lease_ms=_env_int("DISPATCH_LEASE_MS", 60_000),
        recovery_batch_limit=_env_int("RECOVERY_BATCH_LIMIT", 100),
        recovery_dispatching_stale_ms=_env_int("RECOVERY_DISPATCHING_STALE_MS", 300_000),
        memory_state_enabled=os.getenv("MEMORY_STATE_ENABLED", "true").lower() == "true",
        memory_state_max_entries=_env_int("MEMORY_STATE_MAX_ENTRIES", 50_000),
        memory_state_flush_interval_ms=_env_int("MEMORY_STATE_FLUSH_INTERVAL_MS", 1_000),
        memory_state_background_flush_enabled=os.getenv("MEMORY_STATE_BACKGROUND_FLUSH_ENABLED", "true").lower()
        == "true",
        memory_state_warmup_enabled=os.getenv("MEMORY_STATE_WARMUP_ENABLED", "true").lower() == "true",
        memory_config_warmup_enabled=os.getenv("MEMORY_CONFIG_WARMUP_ENABLED", "true").lower() == "true",
        memory_config_room_option_warmup_enabled=os.getenv(
            "MEMORY_CONFIG_ROOM_OPTION_WARMUP_ENABLED", "true"
        ).lower()
        == "true",
        memory_config_room_option_max_rooms=_env_int("MEMORY_CONFIG_ROOM_OPTION_MAX_ROOMS", 10_000),
        memory_config_room_option_max_rows=_env_int("MEMORY_CONFIG_ROOM_OPTION_MAX_ROWS", 50_000),
        memory_config_reconcile_enabled=os.getenv("MEMORY_CONFIG_RECONCILE_ENABLED", "true").lower() == "true",
        memory_config_reconcile_interval_ms=_env_int("MEMORY_CONFIG_RECONCILE_INTERVAL_MS", 5_000),
        recovery_scheduler_enabled=os.getenv("RECOVERY_SCHEDULER_ENABLED", "true").lower() == "true",
        recovery_scheduler_interval_ms=_env_int("RECOVERY_SCHEDULER_INTERVAL_MS", 30_000),
        bulk_send_enabled=os.getenv("BULK_SEND_ENABLED", "false").lower() == "true",
        bulk_send_max_targets=_env_int("BULK_SEND_MAX_TARGETS", 100),
        bulk_send_rate_per_second=_env_int("BULK_SEND_RATE_PER_SECOND", 5),
        bulk_send_require_dry_run=os.getenv("BULK_SEND_REQUIRE_DRY_RUN", "true").lower() == "true",
        bulk_send_token_safety_window_ms=_env_int("BULK_SEND_TOKEN_SAFETY_WINDOW_MS", 5_000),
        bulk_send_target_page_size=_env_int("BULK_SEND_TARGET_PAGE_SIZE", 50),
        bulk_send_target_max_page_size=_env_int("BULK_SEND_TARGET_MAX_PAGE_SIZE", 500),
        bulk_send_exclude_expired=os.getenv("BULK_SEND_EXCLUDE_EXPIRED", "true").lower() == "true",
        bulk_send_allowed_source_types=os.getenv("BULK_SEND_ALLOWED_SOURCE_TYPES", "real_kakao,virtual_phone"),
        send_target_cache_max_rooms=_env_int("SEND_TARGET_CACHE_MAX_ROOMS", 10_000),
        send_target_cache_expire_sweep_interval_ms=_env_int("SEND_TARGET_CACHE_EXPIRE_SWEEP_INTERVAL_MS", 30_000),
    )
    with _settings_lock:
        _settings_cache = settings
        _settings_signature = signature
    return settings


def reset_settings_for_test() -> None:
    """테스트에서 환경 변수 변경 후 settings cache를 비운다."""

    global _settings_cache, _settings_signature
    with _settings_lock:
        _settings_cache = None
        _settings_signature = None
