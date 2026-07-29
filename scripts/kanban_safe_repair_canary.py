#!/usr/bin/env python
"""Isolated no-model canary for the Kanban safe-repair invariants."""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from hermes_cli import kanban_db as kb


class FinishedProcess:
    def __init__(self, pid: int, returncode: int):
        self.pid = pid
        self.returncode = returncode

    def poll(self):
        return self.returncode


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="kanban-safe-canary-") as raw:
        home = Path(raw) / ".hermes"
        home.mkdir()
        old_home = os.environ.get("HERMES_HOME")
        old_grace = os.environ.get("HERMES_KANBAN_CRASH_GRACE_SECONDS")
        os.environ["HERMES_HOME"] = str(home)
        os.environ["HERMES_KANBAN_CRASH_GRACE_SECONDS"] = "0"
        kb._INITIALIZED_PATHS.clear()
        kb._worker_processes.clear()
        kb._recent_worker_returncodes.clear()
        kb.init_db()
        try:
            # Canary 1: retain and classify a real Windows-style return code.
            proc = FinishedProcess(51001, 0)
            kb._register_worker_process(proc)
            assert kb._poll_worker_processes() == [51001]
            assert kb._classify_worker_exit(51001) == ("clean_exit", 0)

            with kb.connect_closing() as conn:
                # Canary 2: dependency waits require a real unfinished parent.
                child = kb.create_task(conn, title="child", assignee="worker")
                kb.claim_task(conn, child, claimer="canary")
                try:
                    kb.block_task(conn, child, kind="dependency", reason="fake wait")
                except ValueError as exc:
                    assert "unfinished parent" in str(exc)
                else:
                    raise AssertionError("fake dependency wait was accepted")
                assert kb.get_task(conn, child).status == "running"

                parent = kb.create_task(conn, title="parent", assignee="worker")
                kb.link_tasks(conn, parent_id=parent, child_id=child)
                assert kb.block_task(conn, child, kind="dependency", reason="real wait")
                assert kb.get_task(conn, child).status == "todo"

                # Canary 3: an unknown dead worker stops once instead of respawning.
                unknown = kb.create_task(conn, title="unknown exit", assignee="worker")
                host = kb._claimer_id().split(":", 1)[0]
                conn.execute(
                    "UPDATE tasks SET status='running', worker_pid=?, claim_lock=?, "
                    "started_at=? WHERE id=?",
                    (51002, f"{host}:canary", int(time.time()) - 60, unknown),
                )
                conn.commit()
                original_alive = kb._pid_alive
                original_classify = kb._classify_worker_exit
                kb._pid_alive = lambda _pid: False
                kb._classify_worker_exit = lambda _pid: ("unknown", None)
                try:
                    assert unknown in kb.detect_crashed_workers(conn)
                finally:
                    kb._pid_alive = original_alive
                    kb._classify_worker_exit = original_classify
                task = kb.get_task(conn, unknown)
                assert task.status == "blocked"
                assert task.consecutive_failures == 1
                assert "exit result unavailable" in (task.last_failure_error or "")

            print("CANARY PASS: real exit retained; fake dependency rejected; unknown exit stopped once")
        finally:
            if old_home is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = old_home
            if old_grace is None:
                os.environ.pop("HERMES_KANBAN_CRASH_GRACE_SECONDS", None)
            else:
                os.environ["HERMES_KANBAN_CRASH_GRACE_SECONDS"] = old_grace


if __name__ == "__main__":
    main()
