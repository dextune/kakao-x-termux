from __future__ import annotations
import sqlite3


CURRENT_SCHEMA_VERSION = 10


def migrate(conn: sqlite3.Connection) -> None:
    """SQLite DB를 현재 스키마 버전으로 보존 migration한다.

    빈 DB는 호출자가 최신 스키마를 생성한 뒤 `user_version`만 기록한다. 기존 v1 또는
    `user_version=0` DB는 현재 코드가 요구하는 누락 컬럼과 로그 테이블을 idempotent하게 추가한다.
    """

    current = user_version(conn)
    if current > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(f"unsupported database schema version: {current}")
    if current == 0 and _has_user_tables(conn):
        current = 1
    if current < 2:
        _migrate_to_2(conn)
    if current < 3:
        _migrate_to_3(conn)
    if current < 4:
        _migrate_to_4(conn)
    if current < 5:
        _migrate_to_5(conn)
    if current < 6:
        _migrate_to_6(conn)
    if current < 7:
        _migrate_to_7(conn)
    if current < 8:
        _migrate_to_8(conn)
    if current < 9:
        _migrate_to_9(conn)
    if current < 10:
        _migrate_to_10(conn)
    conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")


def user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _has_user_tables(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        """
    ).fetchone()
    return int(row[0]) > 0


def _migrate_to_2(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "messages", "source", "TEXT NOT NULL DEFAULT 'notification'")
    _add_column_if_missing(conn, "messages", "notification_key", "TEXT")
    _add_column_if_missing(conn, "reply_jobs", "reply_token", "TEXT")
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_messages_reply_token ON messages(reply_token);

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
        """
    )


def _migrate_to_3(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
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
        """
    )


def _migrate_to_4(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_chatbot_runs_created_at ON chatbot_runs(created_at);
        """
    )


def _migrate_to_5(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
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
        """
    )


def _migrate_to_6(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "reply_jobs", "updated_at", "INTEGER")
    conn.execute("UPDATE reply_jobs SET updated_at = COALESCE(updated_at, created_at)")


def _migrate_to_7(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "reply_jobs", "dispatch_owner", "TEXT")
    _add_column_if_missing(conn, "reply_jobs", "dispatch_lease_expires_at", "INTEGER")
    _add_column_if_missing(conn, "reply_jobs", "dispatch_started_at", "INTEGER")


def _migrate_to_8(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
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
        """
    )


def _migrate_to_9(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "messages", "updated_at", "INTEGER")
    _add_column_if_missing(conn, "messages", "deleted_at", "INTEGER")
    if _table_exists(conn, "messages"):
        conn.execute("UPDATE messages SET updated_at = COALESCE(updated_at, created_at)")


def _migrate_to_10(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
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
    )
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_messages_deleted_received_at
          ON messages(deleted_at, received_at, id);

        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(text, room, sender);
        """
    )
    if _table_exists(conn, "messages_fts") and _table_exists(conn, "messages"):
        conn.execute("DELETE FROM messages_fts")
        conn.execute(
            """
            INSERT INTO messages_fts(rowid, text, room, sender)
            SELECT id, text, room, COALESCE(sender, '')
            FROM messages
            WHERE deleted_at IS NULL
            """
        )


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if not _table_exists(conn, table):
        return
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None
