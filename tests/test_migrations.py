"""Alembic migration tests: fresh upgrade and safe downgrade on a clean DB."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, inspect

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECTED_TABLES = {
    "businesses", "admin_users", "services", "faqs", "customers",
    "bookings", "conversations", "conversation_states", "knowledge_documents",
}


def _alembic(db_url, *args):
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    env["APP_ENV"] = "testing"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_migration_upgrade_and_downgrade_on_fresh_db():
    fd, path = tempfile.mkstemp(suffix="_mig.db")
    os.close(fd)
    os.remove(path)  # start from a truly empty (non-existent) database
    db_url = f"sqlite:///{path}"
    try:
        up = _alembic(db_url, "upgrade", "head")
        assert up.returncode == 0, up.stderr

        engine = create_engine(db_url)
        tables = set(inspect(engine).get_table_names())
        engine.dispose()
        assert EXPECTED_TABLES.issubset(tables)
        assert "alembic_version" in tables

        down = _alembic(db_url, "downgrade", "base")
        assert down.returncode == 0, down.stderr

        engine = create_engine(db_url)
        tables_after = set(inspect(engine).get_table_names())
        engine.dispose()
        # All application tables removed; only Alembic's bookkeeping remains.
        assert not EXPECTED_TABLES.intersection(tables_after)
    finally:
        if os.path.exists(path):
            os.remove(path)
