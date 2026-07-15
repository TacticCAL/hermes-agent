"""RED regression tests for One Follow-Up Rule enforcement.

Tests that kanban_create rejects excessive follow-up chains.

Expected to FAIL before the fix — kanban_create currently has no
per-origin count or chain-type validation.
"""
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

    # Import and use the real schema creation
    from hermes_cli.kanban_db import init_db

    init_db(db_path)

    return db_path


def _create_task(db_path, title, assignee, created_by="mike", status="running"):
    """Helper to create a task directly via the kanban DB API."""
    from hermes_cli.kanban_db import create_task

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    tid = create_task(
        conn,
        title=title,
        assignee=assignee,
        created_by=created_by,
        initial_status=status,
    )
    conn.commit()
    conn.close()
    return tid


def _attempt_create_child(db_path, parent_tid, title, assignee, profile, follow_up_kind="review"):
    """Simulate a worker calling kanban_create to create a follow-up child.

    Returns (success: bool, error_msg: str | None).
    """
    from hermes_cli.kanban_db import create_task

    env = {
        "HERMES_KANBAN_TASK": parent_tid,
        "HERMES_PROFILE": profile,
        "HERMES_KANBAN_RUN_ID": "1",
    }

    with mock.patch.dict(os.environ, env, clear=False):
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            create_task(
                conn,
                title=title,
                assignee=assignee,
                created_by=profile,
                initial_status="running",
                follow_up_kind=follow_up_kind,
                parents=(parent_tid,),
            )
            conn.commit()
            return True, None
        except ValueError as e:
            return False, str(e)
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()


class TestOneFollowUpGuard:
    """Test the code-enforced One Follow-Up Rule."""

    def test_builder_creates_one_review(self, tmp_board_db):
        """Builder may create one review child."""
        parent = _create_task(tmp_board_db, "Fix bug", "builder-1", "mike")
        ok, err = _attempt_create_child(
            tmp_board_db, parent, "REVIEW: Fix bug", "verifier", "builder-1",
            follow_up_kind="review",
        )
        assert ok, f"First review child should be allowed, got: {err}"

    def test_builder_cannot_create_second_review(self, tmp_board_db):
        """Second review from same origin must be rejected."""
        parent = _create_task(tmp_board_db, "Fix bug", "builder-1", "mike")
        _attempt_create_child(
            tmp_board_db, parent, "REVIEW: Fix bug", "verifier", "builder-1",
            follow_up_kind="review",
        )
        ok, err = _attempt_create_child(
            tmp_board_db, parent, "REVIEW v2: Fix bug", "verifier", "builder-1",
            follow_up_kind="review",
        )
        assert not ok, "Second review child should be rejected"
        assert "follow-up" in (err or "").lower() or "comment" in (err or "").lower()

    def test_builder_cannot_create_deploy(self, tmp_board_db):
        """Builder cannot create a deploy child directly."""
        parent = _create_task(tmp_board_db, "Fix bug", "builder-1", "mike")
        ok, err = _attempt_create_child(
            tmp_board_db, parent, "DEPLOY: Fix bug", "deployer", "builder-1",
            follow_up_kind="deploy",
        )
        assert not ok, "Builder should not create deploy children"

    def test_verifier_creates_one_deploy(self, tmp_board_db):
        """Verifier may create one deploy child after review.

        The review child is the origin for the deploy — not the original
        builder task. This is the correct Fix → Review → Deploy chain.
        """
        parent = _create_task(tmp_board_db, "Fix bug", "builder-1", "mike")
        # Builder creates review child linked to parent
        review_ok, _ = _attempt_create_child(
            tmp_board_db, parent, "REVIEW: Fix bug", "verifier", "builder-1",
            follow_up_kind="review",
        )
        assert review_ok, "Builder should be able to create review"

        # Find the review child task id
        conn = sqlite3.connect(str(tmp_board_db))
        conn.row_factory = sqlite3.Row
        review_child = conn.execute(
            "SELECT child_id FROM task_links WHERE parent_id = ?", (parent,)
        ).fetchone()
        conn.close()
        assert review_child is not None, "Review child should exist"
        review_tid = review_child["child_id"]

        # Now the verifier (as origin of the review task) creates a deploy
        ok, err = _attempt_create_child(
            tmp_board_db, review_tid, "DEPLOY: Fix bug", "deployer", "verifier",
            follow_up_kind="deploy",
        )
        assert ok, f"Verifier should be able to create one deploy, got: {err}"

    def test_verifier_cannot_create_second_deploy(self, tmp_board_db):
        """Second deploy from same origin must be rejected."""
        parent = _create_task(tmp_board_db, "Fix bug", "builder-1", "mike")
        _attempt_create_child(
            tmp_board_db, parent, "REVIEW: Fix bug", "verifier", "builder-1",
            follow_up_kind="review",
        )
        _attempt_create_child(
            tmp_board_db, parent, "DEPLOY: Fix bug", "deployer", "verifier",
            follow_up_kind="deploy",
        )
        ok, err = _attempt_create_child(
            tmp_board_db, parent, "DEPLOY v2: Fix bug", "deployer", "verifier",
            follow_up_kind="deploy",
        )
        assert not ok, "Second deploy child should be rejected"

    def test_deployer_creates_nothing(self, tmp_board_db):
        """Deployer cannot create any follow-up children."""
        parent = _create_task(tmp_board_db, "Fix bug", "builder-1", "mike")
        ok, err = _attempt_create_child(
            tmp_board_db, parent, "REVIEW: whatever", "verifier", "deployer",
            follow_up_kind="review",
        )
        assert not ok, "Deployer should not create children"

    def test_planner_creates_zero_by_default(self, tmp_board_db):
        """Planner cannot create children without explicit Mike approval."""
        parent = _create_task(tmp_board_db, "Plan feature", "planner", "mike")
        ok, err = _attempt_create_child(
            tmp_board_db, parent, "Child 1", "builder-1", "planner",
            follow_up_kind="other",
        )
        assert not ok, "Planner should not create children without Mike approval"
