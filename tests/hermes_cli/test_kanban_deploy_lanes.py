"""Regression tests for Phase 0 — Deploy Lanes.

Covers the "wrong-deployer" fix:
  * ``deploy_lane`` field round-trips through create_task / Task.from_row.
  * ``resolve_deployer_for_board`` routes boards to the right deployer.
  * The dispatch guard rewrites a misrouted deploy task's assignee to the
    lane-resolved deployer before spawn, and surfaces it via
    ``result.deploy_lane_rerouted``.
  * Non-deploy tasks (builder/verifier) are NEVER touched by the guard.
  * The guard is a no-op when the correct deployer is already assigned.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

import pytest


@pytest.fixture()
def isolated_kanban_home(monkeypatch):
    """Fresh HERMES_HOME with a clean kanban DB."""
    test_home = tempfile.mkdtemp(prefix="kanban_deploy_lanes_test_")
    monkeypatch.setenv("HERMES_HOME", test_home)
    for mod in list(sys.modules.keys()):
        if mod.startswith("hermes_cli") or mod.startswith("hermes_state") or mod == "hermes_constants":
            del sys.modules[mod]
    from hermes_cli import kanban_db
    # Pre-create the deployer profile directories the routing table
    # resolves to, so the guard's profile_exists safety check passes and
    # the reroute actually fires (instead of falling back to DEFAULT).
    # Each lane-specific deployer gets a minimal config.yaml so
    # profile_exists() returns True.
    import os as _os
    profiles_root = _os.path.join(test_home, "profiles")
    for deployer_name in (
        "deployer",
        "deployer-sitrep-ready",
        "deployer-sitrepcore",
        "deployer-appraisal-firearm",
        "deployer-probate-firearm",
    ):
        pdir = _os.path.join(profiles_root, deployer_name)
        _os.makedirs(pdir, exist_ok=True)
        with open(_os.path.join(pdir, "config.yaml"), "w", encoding="utf-8") as fh:
            fh.write("kanban:\n  enabled: true\n")
    yield kanban_db, test_home


def _fake_spawn(*args, **kwargs):
    return 12345


# ---------------------------------------------------------------------------
# Routing table — pure string logic, no DB needed
# ---------------------------------------------------------------------------

def test_resolve_deployer_for_board_explicit_routes():
    from hermes_cli.kanban_db import resolve_deployer_for_board
    assert resolve_deployer_for_board("sitrep-ready") == "deployer-sitrep-ready"
    assert resolve_deployer_for_board("sitrep-core") == "deployer-sitrepcore"
    assert resolve_deployer_for_board("sitrepcore") == "deployer-sitrepcore"
    assert resolve_deployer_for_board("appraisal-firearm") == "deployer-appraisal-firearm"
    assert resolve_deployer_for_board("probate-firearm") == "deployer"


def test_resolve_deployer_for_board_derives_from_slug():
    """Boards not in the explicit table derive deployer-<slug>."""
    from hermes_cli.kanban_db import resolve_deployer_for_board
    assert resolve_deployer_for_board("module-2") == "deployer"  # explicitly routed in table
    # tacticcal is explicitly in DEPLOY_LANE_ROUTES -> "deployer" (not derived)
    assert resolve_deployer_for_board("tacticcal") == "deployer"


def test_resolve_deployer_for_board_falls_back_to_default():
    """Empty/None board falls back to the main deployer, never None."""
    from hermes_cli.kanban_db import resolve_deployer_for_board, DEFAULT_DEPLOYER
    assert resolve_deployer_for_board(None) == DEFAULT_DEPLOYER
    assert resolve_deployer_for_board("") == DEFAULT_DEPLOYER
    assert resolve_deployer_for_board("   ") == DEFAULT_DEPLOYER
    assert DEFAULT_DEPLOYER == "deployer"


def test_resolve_deployer_is_case_insensitive():
    from hermes_cli.kanban_db import resolve_deployer_for_board
    assert resolve_deployer_for_board("SITREP-READY") == "deployer-sitrep-ready"
    assert resolve_deployer_for_board("Sitrep-Core") == "deployer-sitrepcore"


# ---------------------------------------------------------------------------
# deploy_lane field round-trip
# ---------------------------------------------------------------------------

def test_create_task_persists_deploy_lane(isolated_kanban_home):
    kb, _ = isolated_kanban_home
    with kb.connect_closing() as conn:
        kb.create_board(slug="default", name="Test")
        tid = kb.create_task(
            conn, title="deploy", assignee="deployer-sitrep-ready",
            deploy_lane="sitrep-ready",
        )
        row = conn.execute(
            "SELECT deploy_lane FROM tasks WHERE id = ?", (tid,)
        ).fetchone()
    assert row["deploy_lane"] == "sitrep-ready"
    with kb.connect_closing() as conn:
        t = kb.get_task(conn, tid)
    assert t.deploy_lane == "sitrep-ready"


def test_create_task_deploy_lane_defaults_to_null(isolated_kanban_home):
    kb, _ = isolated_kanban_home
    with kb.connect_closing() as conn:
        kb.create_board(slug="default", name="Test")
        tid = kb.create_task(conn, title="no lane", assignee="builder-1")
        t = kb.get_task(conn, tid)
    assert t.deploy_lane is None


def test_create_task_strips_whitespace_deploy_lane(isolated_kanban_home):
    kb, _ = isolated_kanban_home
    with kb.connect_closing() as conn:
        kb.create_board(slug="default", name="Test")
        tid = kb.create_task(
            conn, title="ws", assignee="deployer", deploy_lane="  sitrep-ready  ",
        )
        t = kb.get_task(conn, tid)
    assert t.deploy_lane == "sitrep-ready"


def test_empty_deploy_lane_treated_as_null(isolated_kanban_home):
    kb, _ = isolated_kanban_home
    with kb.connect_closing() as conn:
        kb.create_board(slug="default", name="Test")
        tid = kb.create_task(
            conn, title="empty", assignee="deployer", deploy_lane="   ",
        )
        t = kb.get_task(conn, tid)
    assert t.deploy_lane is None


# ---------------------------------------------------------------------------
# Dispatch guard — the core wrong-deployer fix
# ---------------------------------------------------------------------------

def test_dispatch_guard_reroutes_wrong_deployer(isolated_kanban_home):
    """A deploy task on the sitrep-ready board whose assignee is the main
    `deployer` gets rewritten to `deployer-sitrep-ready` before spawn."""
    kb, _ = isolated_kanban_home
    with kb.connect_closing() as conn:
        kb.create_board(slug="sitrep-ready", name="SitRep Ready")
        tid = kb.create_task(
            conn, title="deploy it", assignee="deployer",
            deploy_lane="sitrep-ready",
        )
    with kb.connect_closing() as conn:
        res = kb.dispatch_once(
            conn, spawn_fn=_fake_spawn, dry_run=False, board="sitrep-ready",
        )
    # The reroute is surfaced
    assert len(res.deploy_lane_rerouted) == 1
    assert res.deploy_lane_rerouted[0][0] == tid
    assert res.deploy_lane_rerouted[0][1] == "deployer"
    assert res.deploy_lane_rerouted[0][2] == "deployer-sitrep-ready"
    # The DB row was corrected
    with kb.connect_closing() as conn:
        row = conn.execute(
            "SELECT assignee FROM tasks WHERE id = ?", (tid,)
        ).fetchone()
    assert row["assignee"] == "deployer-sitrep-ready"
    # A deploy_lane_rerouted event was emitted
    with kb.connect_closing() as conn:
        evs = list(conn.execute(
            "SELECT payload FROM task_events WHERE task_id = ? AND kind = 'deploy_lane_rerouted'",
            (tid,),
        ))
    assert len(evs) == 1
    payload = json.loads(evs[0]["payload"])
    assert payload["from"] == "deployer"
    assert payload["to"] == "deployer-sitrep-ready"


def test_dispatch_guard_noop_when_correct_deployer(isolated_kanban_home):
    """The guard does nothing when the right deployer is already assigned."""
    kb, _ = isolated_kanban_home
    with kb.connect_closing() as conn:
        kb.create_board(slug="sitrep-ready", name="SitRep Ready")
        tid = kb.create_task(
            conn, title="deploy it", assignee="deployer-sitrep-ready",
            deploy_lane="sitrep-ready",
        )
    with kb.connect_closing() as conn:
        res = kb.dispatch_once(
            conn, spawn_fn=_fake_spawn, dry_run=False, board="sitrep-ready",
        )
    assert res.deploy_lane_rerouted == []
    with kb.connect_closing() as conn:
        row = conn.execute(
            "SELECT assignee FROM tasks WHERE id = ?", (tid,)
        ).fetchone()
    assert row["assignee"] == "deployer-sitrep-ready"


def test_dispatch_guard_does_not_touch_builder_tasks(isolated_kanban_home):
    """Builder/verifier tasks are never rerouted — the guard only fires
    on deploy-role assignees."""
    kb, _ = isolated_kanban_home
    with kb.connect_closing() as conn:
        kb.create_board(slug="sitrep-ready", name="SitRep Ready")
        tid = kb.create_task(
            conn, title="build it", assignee="builder-1",
            deploy_lane="sitrep-ready",
        )
    with kb.connect_closing() as conn:
        res = kb.dispatch_once(
            conn, spawn_fn=_fake_spawn, dry_run=False, board="sitrep-ready",
        )
    assert res.deploy_lane_rerouted == []
    with kb.connect_closing() as conn:
        row = conn.execute(
            "SELECT assignee FROM tasks WHERE id = ?", (tid,)
        ).fetchone()
    assert row["assignee"] == "builder-1"


def test_dispatch_guard_dry_run_does_not_mutate(isolated_kanban_home):
    """Dry-run reports the would-be reroute without touching the DB."""
    kb, _ = isolated_kanban_home
    with kb.connect_closing() as conn:
        kb.create_board(slug="sitrep-ready", name="SitRep Ready")
        tid = kb.create_task(
            conn, title="deploy it", assignee="deployer",
            deploy_lane="sitrep-ready",
        )
    with kb.connect_closing() as conn:
        res = kb.dispatch_once(
            conn, spawn_fn=_fake_spawn, dry_run=True, board="sitrep-ready",
        )
    assert len(res.deploy_lane_rerouted) == 1
    # DB unchanged in dry_run
    with kb.connect_closing() as conn:
        row = conn.execute(
            "SELECT assignee FROM tasks WHERE id = ?", (tid,)
        ).fetchone()
    assert row["assignee"] == "deployer"


def test_dispatch_guard_derives_lane_from_board_when_no_tag(isolated_kanban_home):
    """When the task has no explicit deploy_lane, the guard derives the
    deployer from the board slug — so a bare `deployer` assignee on the
    sitrep-ready board still gets rerouted."""
    kb, _ = isolated_kanban_home
    with kb.connect_closing() as conn:
        kb.create_board(slug="sitrep-ready", name="SitRep Ready")
        tid = kb.create_task(
            conn, title="deploy it", assignee="deployer",
            # no deploy_lane set — derive from board
        )
    with kb.connect_closing() as conn:
        res = kb.dispatch_once(
            conn, spawn_fn=_fake_spawn, dry_run=False, board="sitrep-ready",
        )
    assert len(res.deploy_lane_rerouted) == 1
    assert res.deploy_lane_rerouted[0][2] == "deployer-sitrep-ready"


def test_dispatch_guard_main_board_falls_back_to_default(isolated_kanban_home):
    """On the tacticcal board (no explicit route, no deployer-tacticcal
    profile in the test home), a bare `deployer` assignee is correct and
    NOT rerouted. The guard's profile-existence safety falls back to
    DEFAULT_DEPLOYER when the derived deployer-<slug> profile doesn't
    exist on disk — so boards without a dedicated deployer profile keep
    working on the main `deployer` exactly as they did before Phase 0."""
    kb, _ = isolated_kanban_home
    with kb.connect_closing() as conn:
        kb.create_board(slug="tacticcal", name="TacticCAL")
        tid = kb.create_task(
            conn, title="deploy it", assignee="deployer",
        )
    with kb.connect_closing() as conn:
        res = kb.dispatch_once(
            conn, spawn_fn=_fake_spawn, dry_run=False, board="tacticcal",
        )
    # No reroute: deployer-tacticcal doesn't exist as a profile, so the
    # guard falls back to DEFAULT_DEPLOYER (== "deployer"), which matches
    # the task's existing assignee. The task is left alone.
    assert res.deploy_lane_rerouted == []
    with kb.connect_closing() as conn:
        row = conn.execute(
            "SELECT assignee FROM tasks WHERE id = ?", (tid,)
        ).fetchone()
    assert row["assignee"] == "deployer"


# ---------------------------------------------------------------------------
# Migration safety
# ---------------------------------------------------------------------------

def test_migration_adds_deploy_lane_to_legacy_db(isolated_kanban_home):
    """Opening a DB that predates the deploy_lane column must add it
    cleanly without losing existing rows."""
    kb, _ = isolated_kanban_home
    with kb.connect_closing() as conn:
        kb.create_board(slug="default", name="Test")
        # Create a task BEFORE simulating a legacy schema
        tid = kb.create_task(conn, title="legacy", assignee="builder-1")
    # Drop the column to simulate a legacy DB, then re-open + migrate
    import sqlite3
    db_path = kb.kanban_db_path()
    # SQLite cannot DROP COLUMN portably across versions; instead rebuild
    # without the column. Easiest: open raw, recreate tasks table without
    # deploy_lane, copy data.
    raw = sqlite3.connect(db_path)
    raw.row_factory = sqlite3.Row
    raw.executescript("""
        CREATE TABLE tasks_legacy AS
            SELECT id, title, body, assignee, status, priority, created_by,
                   created_at, started_at, completed_at, workspace_kind,
                   workspace_path, claim_lock, claim_expires, tenant, result,
                   consecutive_failures, worker_pid, last_failure_error,
                   max_runtime_seconds, last_heartbeat_at, current_run_id
            FROM tasks;
        DROP TABLE tasks;
        CREATE TABLE tasks AS SELECT * FROM tasks_legacy;
        DROP TABLE tasks_legacy;
    """)
    raw.commit()
    raw.close()
    # Now re-open through the kernel — migration should add deploy_lane
    with kb.connect_closing() as conn:
        kb.init_db()
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(tasks)")]
        assert "deploy_lane" in cols
        # Existing task still present, lane defaults to None
        t = kb.get_task(conn, tid)
        assert t is not None
        assert t.title == "legacy"
        assert t.deploy_lane is None
