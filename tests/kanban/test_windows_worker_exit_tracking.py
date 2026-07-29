"""Regression tests for paid restart loops caused by lost Windows exits."""

from __future__ import annotations

import sqlite3
import time

import pytest

from hermes_cli import kanban_db as kb


class _FinishedProcess:
    def __init__(self, pid: int, returncode: int):
        self.pid = pid
        self.returncode = returncode

    def poll(self):
        return self.returncode


def test_poll_worker_processes_records_clean_windows_exit(monkeypatch):
    pid = 42001
    proc = _FinishedProcess(pid, 0)
    kb._worker_processes.clear()
    kb._recent_worker_returncodes.clear()

    kb._register_worker_process(proc)
    assert kb._poll_worker_processes() == [pid]
    assert kb._classify_worker_exit(pid) == ("clean_exit", 0)
    assert pid not in kb._worker_processes


def test_poll_worker_processes_records_nonzero_windows_exit(monkeypatch):
    pid = 42002
    proc = _FinishedProcess(pid, 7)
    kb._worker_processes.clear()
    kb._recent_worker_returncodes.clear()

    kb._register_worker_process(proc)
    assert kb._poll_worker_processes() == [pid]
    assert kb._classify_worker_exit(pid) == ("nonzero_exit", 7)


def test_unknown_dead_worker_blocks_once_instead_of_restarting(
    tmp_path, monkeypatch,
):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_KANBAN_CRASH_GRACE_SECONDS", "0")
    monkeypatch.setattr(kb, "_pid_alive", lambda _pid: False)
    monkeypatch.setattr(kb, "_classify_worker_exit", lambda _pid: ("unknown", None))
    kb.init_db()

    with kb.connect_closing() as conn:
        tid = kb.create_task(conn, title="unknown Windows exit", assignee="worker")
        host = kb._claimer_id().split(":", 1)[0]
        conn.execute(
            "UPDATE tasks SET status='running', worker_pid=?, claim_lock=?, "
            "started_at=? WHERE id=?",
            (42003, f"{host}:worker", int(time.time()) - 60, tid),
        )
        conn.commit()

        assert tid in kb.detect_crashed_workers(conn)
        task = kb.get_task(conn, tid)
        assert task.status == "blocked"
        assert task.consecutive_failures == 1
        assert "exit result unavailable" in (task.last_failure_error or "")


def test_clean_exit_without_terminal_transition_blocks_as_protocol_violation(
    tmp_path, monkeypatch,
):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_KANBAN_CRASH_GRACE_SECONDS", "0")
    monkeypatch.setattr(kb, "_pid_alive", lambda _pid: False)
    kb._recent_worker_returncodes[42004] = (0, time.time())
    kb.init_db()

    with kb.connect_closing() as conn:
        tid = kb.create_task(conn, title="clean exit, open card", assignee="worker")
        host = kb._claimer_id().split(":", 1)[0]
        conn.execute(
            "UPDATE tasks SET status='running', worker_pid=?, claim_lock=?, "
            "started_at=? WHERE id=?",
            (42004, f"{host}:worker", int(time.time()) - 60, tid),
        )
        conn.commit()

        assert tid in kb.detect_crashed_workers(conn)
        task = kb.get_task(conn, tid)
        assert task.status == "blocked"
        assert "exited cleanly" in (task.last_failure_error or "")
        assert any(
            event.kind == "protocol_violation"
            for event in kb.list_events(conn, tid)
        )


def test_budget_exhaustion_note_reads_profile_session(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    profile = home / "profiles" / "worker"
    profile.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    kb.init_db()

    state = sqlite3.connect(profile / "state.db")
    state.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, api_call_count INTEGER)"
    )
    state.execute("INSERT INTO sessions VALUES (?, ?)", ("session-1", 60))
    state.commit()
    state.close()

    with kb.connect_closing() as conn:
        tid = kb.create_task(
            conn, title="budget", assignee="worker", goal_mode=True,
            goal_max_turns=60, session_id="session-1",
        )
        note = kb._budget_exhaustion_note(conn, tid)
        assert note is not None
        assert "60/60" in note
        assert "NOT a crash" in note
