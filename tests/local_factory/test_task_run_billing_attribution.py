"""Tests for Kanban run billing attribution.

Verifies that task_runs can store billing session/provider/model info
and that the _try_record_run_billing helper writes env-based billing
data without blocking task completion on failure.
"""
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

import pytest


@pytest.fixture
def tmp_board_db(tmp_path):
    """Create a temporary board database with the kanban schema."""
    db_path = tmp_path / "test_board" / "kanban.db"
    db_path.parent.mkdir(parents=True)
    from hermes_cli.kanban_db import init_db
    init_db(db_path)
    return db_path


def _get_conn(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


class TestBillingColumnsExist:
    """Verify the billing columns were added by the migration."""

    def test_billing_columns_exist(self, tmp_board_db):
        conn = _get_conn(tmp_board_db)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(task_runs)")}
        conn.close()
        assert "billing_session_id" in cols
        assert "billing_provider" in cols
        assert "billing_base_url" in cols
        assert "billing_model" in cols


class TestTryRecordRunBilling:
    """Test the best-effort billing attribution helper."""

    def test_writes_billing_when_session_id_present(self, tmp_board_db):
        """When HERMES_SESSION_ID is set, billing info is written to the run."""
        from hermes_cli.kanban_db import _try_record_run_billing, create_task

        conn = _get_conn(tmp_board_db)
        # Create a task in ready status
        tid = create_task(
            conn, title="Test task", assignee="builder-1",
            created_by="mike", initial_status="blocked",
        )
        # Manually create a run row
        conn.execute(
            "INSERT INTO task_runs (task_id, profile, status, started_at) "
            "VALUES (?, ?, 'running', ?)",
            (tid, "builder-1", 12345),
        )
        conn.commit()
        run_id = conn.execute(
            "SELECT id FROM task_runs WHERE task_id = ?", (tid,)
        ).fetchone()["id"]

        env = {
            "HERMES_SESSION_ID": "20260715_120000_test123",
            "HERMES_BILLING_PROVIDER": "zai",
            "HERMES_BILLING_BASE_URL": "https://api.z.ai/api/paas/v4",
            "HERMES_MODEL": "glm-5.2",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            _try_record_run_billing(conn, run_id)

        row = conn.execute(
            "SELECT billing_session_id, billing_provider, billing_base_url, billing_model "
            "FROM task_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        conn.close()

        assert row["billing_session_id"] == "20260715_120000_test123"
        assert row["billing_provider"] == "zai"
        assert row["billing_base_url"] == "https://api.z.ai/api/paas/v4"
        assert row["billing_model"] == "glm-5.2"

    def test_does_nothing_without_session_id(self, tmp_board_db):
        """When HERMES_SESSION_ID is not set, nothing is written."""
        from hermes_cli.kanban_db import _try_record_run_billing, create_task

        conn = _get_conn(tmp_board_db)
        tid = create_task(
            conn, title="Test task", assignee="builder-1",
            created_by="mike", initial_status="blocked",
        )
        conn.execute(
            "INSERT INTO task_runs (task_id, profile, status, started_at) "
            "VALUES (?, ?, 'running', ?)",
            (tid, "builder-1", 12345),
        )
        conn.commit()
        run_id = conn.execute(
            "SELECT id FROM task_runs WHERE task_id = ?", (tid,)
        ).fetchone()["id"]

        # Clear session id
        with mock.patch.dict(os.environ, {}, clear=True):
            _try_record_run_billing(conn, run_id)

        row = conn.execute(
            "SELECT billing_session_id FROM task_runs WHERE id = ?", (run_id,)
        ).fetchone()
        conn.close()
        assert row["billing_session_id"] is None

    def test_never_raises_on_failure(self, tmp_board_db):
        """Telemetry failure must never block task completion."""
        from hermes_cli.kanban_db import _try_record_run_billing

        # Pass an invalid run_id — should not raise
        conn = _get_conn(tmp_board_db)
        _try_record_run_billing(conn, 999999)
        conn.close()
        # If we got here without exception, the test passes

    def test_no_credentials_stored(self, tmp_board_db):
        """No API keys or auth headers should be stored in billing fields."""
        from hermes_cli.kanban_db import _try_record_run_billing, create_task

        conn = _get_conn(tmp_board_db)
        tid = create_task(
            conn, title="Test task", assignee="builder-1",
            created_by="mike", initial_status="blocked",
        )
        conn.execute(
            "INSERT INTO task_runs (task_id, profile, status, started_at) "
            "VALUES (?, ?, 'running', ?)",
            (tid, "builder-1", 12345),
        )
        conn.commit()
        run_id = conn.execute(
            "SELECT id FROM task_runs WHERE task_id = ?", (tid,)
        ).fetchone()["id"]

        # Even if someone accidentally puts a key in the env, the helper
        # only reads the specific billing fields, not arbitrary env vars
        env = {
            "HERMES_SESSION_ID": "test_session",
            "HERMES_BILLING_PROVIDER": "zai",
            "HERMES_BILLING_BASE_URL": "https://api.z.ai/api/paas/v4",
            "HERMES_MODEL": "glm-5.2",
            "ZAI_API_KEY": "sk-secret-key-12345",  # Should NOT be stored
        }
        with mock.patch.dict(os.environ, env, clear=False):
            _try_record_run_billing(conn, run_id)

        row = conn.execute(
            "SELECT billing_session_id, billing_provider, billing_base_url, billing_model "
            "FROM task_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        conn.close()

        # Verify no credential leaked into any billing field
        for val in [row["billing_session_id"], row["billing_provider"],
                     row["billing_base_url"], row["billing_model"]]:
            assert "sk-secret" not in str(val)
            assert "key" not in str(val).lower() or "api.z.ai" in str(val)
