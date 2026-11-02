"""Run migrations in isolated subprocesses, never against the user's database."""

import os
from pathlib import Path
import sqlite3
import subprocess
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def run_alembic(database, *args):
    environment = os.environ.copy()
    environment.update(
        DATABASE_URL=f"sqlite:///{database.as_posix()}",
        JWT_SECRET_KEY="migration-tests-only",
        LLM_API_KEY="unused",
        LLM_BASE_URL="http://localhost:11434/v1",
        LLM_MODEL="unused",
    )
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def test_upgrade_downgrade_and_schema_match(tmp_path):
    database = tmp_path / "migrations.db"
    run_alembic(database, "upgrade", "head")
    run_alembic(database, "check")
    run_alembic(database, "upgrade", "head")  # Already current: no changes.
    with sqlite3.connect(database) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert tables == {
            "alembic_version", "users", "labs", "equipments", "reservations",
            "chat_messages", "pending_actions", "agent_traces", "agent_trace_steps",
        }
    run_alembic(database, "downgrade", "base")
    with sqlite3.connect(database) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert tables == {"alembic_version"}
    run_alembic(database, "upgrade", "head")
    run_alembic(database, "check")


def test_existing_baseline_data_survives_stamp_and_index_upgrade(tmp_path):
    database = tmp_path / "legacy.db"
    run_alembic(database, "upgrade", "5ce161a3c16f")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users (username, password, name, role, status, create_time, update_time) "
            "VALUES ('existing', 'hash', 'Existing user', 'student', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.execute("DROP TABLE alembic_version")
    run_alembic(database, "stamp", "5ce161a3c16f")
    run_alembic(database, "upgrade", "head")
    run_alembic(database, "check")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT username FROM users").fetchone() == ("existing",)
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(reservations)")}
        assert "ix_reservations_conflict_lookup" in indexes
