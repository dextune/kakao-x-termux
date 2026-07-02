from __future__ import annotations
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator, Optional

from app.config import get_settings
from app.migrations import migrate


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  schema_version INTEGER NOT NULL DEFAULT 1,
  source TEXT NOT NULL,
  source_package TEXT NOT NULL,
  source_type TEXT NOT NULL,
  room_key TEXT NOT NULL,
  room TEXT NOT NULL,
  sender TEXT,
  text TEXT NOT NULL,
  message_type TEXT NOT NULL DEFAULT 'text',
  notification_key TEXT,
  reply_token TEXT,
  reply_token_expires_at INTEGER,
  received_at INTEGER NOT NULL,
  processed INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER,
  deleted_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_messages_room_key_received_at ON messages(room_key, received_at);
CREATE INDEX IF NOT EXISTS idx_messages_source_type ON messages(source_type);
CREATE INDEX IF NOT EXISTS idx_messages_reply_token ON messages(reply_token);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(text, room, sender);

CREATE TABLE IF NOT EXISTS reply_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL UNIQUE,
  room_key TEXT NOT NULL,
  room TEXT NOT NULL,
  text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING',
  dedupe_key TEXT,
  reply_token TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  bridge_mode TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  dispatch_owner TEXT,
  dispatch_lease_expires_at INTEGER,
  dispatch_started_at INTEGER,
  sent_at INTEGER
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_reply_jobs_dedupe_key
  ON reply_jobs(dedupe_key)
  WHERE dedupe_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_reply_jobs_status_created_at ON reply_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_reply_jobs_room_key ON reply_jobs(room_key);

CREATE TABLE IF NOT EXISTS room_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_key TEXT NOT NULL UNIQUE,
  room TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  mode TEXT NOT NULL DEFAULT 'manual',
  rule_json TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_room_rules_enabled ON room_rules(enabled);
CREATE INDEX IF NOT EXISTS idx_room_rules_mode ON room_rules(mode);

CREATE TABLE IF NOT EXISTS bridge_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  level TEXT NOT NULL,
  category TEXT NOT NULL,
  message TEXT NOT NULL,
  ref_id TEXT,
  created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_backend_logs_created_at ON bridge_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_backend_logs_category ON bridge_logs(category);

CREATE TABLE IF NOT EXISTS chatbot_modules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bot_key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  version TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  priority INTEGER NOT NULL DEFAULT 100,
  options_json TEXT,
  loaded_at INTEGER,
  last_error TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chatbot_modules_enabled ON chatbot_modules(enabled);
CREATE INDEX IF NOT EXISTS idx_chatbot_modules_priority ON chatbot_modules(priority);

CREATE TABLE IF NOT EXISTS room_bot_options (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_key TEXT NOT NULL,
  bot_key TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  options_json TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  UNIQUE(room_key, bot_key)
);

CREATE INDEX IF NOT EXISTS idx_room_bot_options_room_key ON room_bot_options(room_key);
CREATE INDEX IF NOT EXISTS idx_room_bot_options_bot_key ON room_bot_options(bot_key);

CREATE TABLE IF NOT EXISTS chatbot_states (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  state_key TEXT NOT NULL UNIQUE,
  room_key TEXT NOT NULL,
  sender TEXT,
  bot_key TEXT NOT NULL,
  state_json TEXT NOT NULL,
  expires_at INTEGER,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chatbot_states_bot_key ON chatbot_states(bot_key);
CREATE INDEX IF NOT EXISTS idx_chatbot_states_expires_at ON chatbot_states(expires_at);

CREATE TABLE IF NOT EXISTS chatbot_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL,
  bot_key TEXT NOT NULL,
  action TEXT NOT NULL,
  reason TEXT,
  duration_ms INTEGER,
  error TEXT,
  created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chatbot_runs_event_id ON chatbot_runs(event_id);
CREATE INDEX IF NOT EXISTS idx_chatbot_runs_bot_key ON chatbot_runs(bot_key);
CREATE INDEX IF NOT EXISTS idx_chatbot_runs_created_at ON chatbot_runs(created_at);

CREATE TABLE IF NOT EXISTS chatbot_module_files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT NOT NULL UNIQUE,
  file_name TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL,
  sha256 TEXT,
  bot_key TEXT,
  status TEXT NOT NULL,
  last_error TEXT,
  loaded_at INTEGER,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chatbot_module_files_status
  ON chatbot_module_files(status);
CREATE INDEX IF NOT EXISTS idx_chatbot_module_files_bot_key
  ON chatbot_module_files(bot_key);

CREATE TABLE IF NOT EXISTS send_target_groups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  group_key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  filter_json TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_send_target_groups_enabled ON send_target_groups(enabled);
CREATE INDEX IF NOT EXISTS idx_send_target_groups_type ON send_target_groups(type);

CREATE TABLE IF NOT EXISTS send_target_group_rooms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  group_key TEXT NOT NULL,
  room_key TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  UNIQUE(group_key, room_key)
);

CREATE INDEX IF NOT EXISTS idx_send_target_group_rooms_group_key ON send_target_group_rooms(group_key);
CREATE INDEX IF NOT EXISTS idx_send_target_group_rooms_room_key ON send_target_group_rooms(room_key);

CREATE TABLE IF NOT EXISTS send_batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT NOT NULL UNIQUE,
  target_type TEXT NOT NULL,
  target_json TEXT NOT NULL,
  text_hash TEXT NOT NULL,
  text_preview TEXT NOT NULL,
  status TEXT NOT NULL,
  target_count INTEGER NOT NULL DEFAULT 0,
  queued_count INTEGER NOT NULL DEFAULT 0,
  sent_count INTEGER NOT NULL DEFAULT 0,
  failed_count INTEGER NOT NULL DEFAULT 0,
  expired_count INTEGER NOT NULL DEFAULT 0,
  skipped_count INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  completed_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_send_batches_created_at ON send_batches(created_at);
CREATE INDEX IF NOT EXISTS idx_send_batches_status ON send_batches(status);

CREATE TABLE IF NOT EXISTS send_batch_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT NOT NULL,
  room_key TEXT NOT NULL,
  room TEXT NOT NULL,
  job_id TEXT,
  status TEXT NOT NULL,
  skip_reason TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  UNIQUE(batch_id, room_key)
);

CREATE INDEX IF NOT EXISTS idx_send_batch_items_batch_id_status ON send_batch_items(batch_id, status);
CREATE INDEX IF NOT EXISTS idx_send_batch_items_job_id ON send_batch_items(job_id);

CREATE TABLE IF NOT EXISTS chatbot_marketplace_installs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bot_key TEXT NOT NULL UNIQUE,
  marketplace_bot_id TEXT,
  marketplace_base_url TEXT,
  package_sha256 TEXT NOT NULL,
  version TEXT NOT NULL,
  folder_name TEXT NOT NULL,
  installed_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chatbot_marketplace_installs_marketplace_bot_id
  ON chatbot_marketplace_installs(marketplace_bot_id);
"""

_initialized_paths: set[str] = set()
_init_lock = threading.Lock()


def _normalize_path(path: str) -> str:
    return os.path.abspath(path)


def init_db(path: Optional[str] = None) -> None:
    """SQLite DB를 열고 현재 MVP 스키마로 초기화 또는 migration한다."""

    db_path = _normalize_path(path or get_settings().db_path)
    directory = os.path.dirname(db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        migrate(conn)
        conn.commit()
    with _init_lock:
        _initialized_paths.add(db_path)


def ensure_initialized(path: Optional[str] = None) -> None:
    """요청 처리 경로에서 DB path별 1회만 schema 초기화를 수행한다."""

    db_path = _normalize_path(path or get_settings().db_path)
    with _init_lock:
        initialized = db_path in _initialized_paths
    if initialized and os.path.exists(db_path):
        return
    init_db(db_path)


@contextmanager
def connect(path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    """row dict 접근이 가능한 SQLite connection context를 연다."""

    db_path = _normalize_path(path or get_settings().db_path)
    ensure_initialized(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {max(get_settings().sqlite_busy_timeout_ms, 0)}")
        yield conn
        conn.commit()
    finally:
        conn.close()
