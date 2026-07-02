import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from app.db import init_db
from app.migrations import CURRENT_SCHEMA_VERSION


def main() -> None:
    """Termux 운영 DB를 현재 스키마로 초기화 또는 migration한다."""

    init_db()
    print(f"database schema ready: user_version={CURRENT_SCHEMA_VERSION}")


if __name__ == "__main__":
    main()
