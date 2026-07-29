"""Tests for the parked status — cards Mike explicitly holds."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb


@pytest.fixture
def kanban_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


def _running_task(conn, title="t"):
    tid = kb.create_task(conn, title=title, assignee="worker")
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
    claimed = kb.claim_task(conn, tid, claimer="worker")
    assert claimed is not None
    return tid


def test_park_task_moves_to_parked(kanban_home: Path) -> None:
    with kb.connect_closing() as conn:
        tid = _running_task(conn)
        assert kb.park_task(conn, tid, reason="Mike said hold")
        t = kb.get_task(conn, tid)
        assert t.status == "parked"
        assert t.block_kind == "parked"
        assert t.consecutive_failures == 0


def test_parked_task_invisible_to_recompute_ready(kanban_home: Path) -> None:
    with kb.connect_closing() as conn:
        tid = _running_task(conn)
        kb.park_task(conn, tid, reason="hold")
        # recompute_ready should not promote a parked task
        promoted = kb.recompute_ready(conn)
        assert promoted == 0
        assert kb.get_task(conn, tid).status == "parked"


def test_unblock_refuses_parked_task(kanban_home: Path) -> None:
    with kb.connect_closing() as conn:
        tid = _running_task(conn)
        kb.park_task(conn, tid, reason="hold")
        # unblock_task must refuse
        assert kb.unblock_task(conn, tid) is False
        assert kb.get_task(conn, tid).status == "parked"


def test_unpark_releases_to_ready(kanban_home: Path) -> None:
    with kb.connect_closing() as conn:
        tid = _running_task(conn)
        kb.park_task(conn, tid, reason="hold")
        assert kb.unpark_task(conn, tid)
        t = kb.get_task(conn, tid)
        assert t.status == "ready"
        assert t.block_kind is None


def test_unpark_routed_to_todo_if_parents_incomplete(kanban_home: Path) -> None:
    with kb.connect_closing() as conn:
        parent = kb.create_task(conn, title="parent", assignee="worker")
        child = kb.create_task(
            conn, title="child", assignee="worker", parents=[parent]
        )
        with kb.write_txn(conn):
            conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (child,))
        kb.park_task(conn, child, reason="hold")
        assert kb.unpark_task(conn, child)
        # Parent is not done — child should go to todo, not ready
        assert kb.get_task(conn, child).status == "todo"


def test_park_clears_failures(kanban_home: Path) -> None:
    with kb.connect_closing() as conn:
        tid = _running_task(conn)
        # Simulate accumulated failures
        with kb.write_txn(conn):
            conn.execute(
                "UPDATE tasks SET consecutive_failures=3, "
                "last_failure_error='something broke' WHERE id=?",
                (tid,),
            )
        kb.park_task(conn, tid, reason="hold")
        t = kb.get_task(conn, tid)
        assert t.consecutive_failures == 0
        assert t.last_failure_error is None


def test_park_from_blocked(kanban_home: Path) -> None:
    with kb.connect_closing() as conn:
        tid = _running_task(conn)
        kb.block_task(conn, tid, reason="needs input", kind="needs_input")
        assert kb.get_task(conn, tid).status == "blocked"
        kb.park_task(conn, tid, reason="Mike said hold")
        assert kb.get_task(conn, tid).status == "parked"
