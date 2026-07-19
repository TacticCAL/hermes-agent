# INBOUND FROM deploy-lanes (Phase 0)

**Task:** t_d83d3e97 — PHASE 0 - Deploy Lanes: deploy_lane field + routing table + dispatch guard
**Branch:** `feature/deploy-lanes` (in `C:\Users\mikey\AppData\Local\hermes\hermes-agent`)
**Board-status branch:** commit `87c0d76` on `feature/security-xss` in `C:\Users\mikey\Desktop\HERMES BUILDERS\board-status`
**Builder:** builder-1 (GLM 5.2)
**Date:** 2026-07-18

## What this fixes

The "wrong-deployer" problem: a deploy task could be run by any deployer
profile whose name was written on the task's `assignee` field, even if
that deployer does not own the board the task lives on. With five
deployer profiles on disk (`deployer`, `deployer-appraisal-firearm`,
`deployer-probate-firearm`, `deployer-sitrepcore`,
`deployer-sitrep-ready`) this was a real misrouting risk.

## What changed

### `hermes_cli/kanban_db.py` (on `feature/deploy-lanes`)

1. **New `deploy_lane` column** on the `tasks` table (TEXT, nullable).
   Additive migration in `_migrate_add_optional_columns` — existing
   boards pick up the column on next open, existing rows get NULL
   (derive-from-board semantics). No data loss.

2. **`Task` dataclass + `from_row`** carry `deploy_lane`.

3. **`create_task`** accepts a `deploy_lane` kwarg.

4. **Routing table** (`DEPLOY_LANE_ROUTES` + `DEFAULT_DEPLOYER`):
   - Explicit overrides for boards whose deployer profile name does not
     follow the plain slug convention:
     `sitrep-core`/`sitrepcore` → `deployer-sitrepcore`,
     `appraisal-firearm` → `deployer-appraisal-firearm`,
     `probate-firearm` → `deployer-probate-firearm`,
     `sitrep-ready` → `deployer-sitrep-ready`.
   - Derive-from-slug rule: any other board `X` → `deployer-X`.
   - `DEFAULT_DEPLOYER` = `deployer` (the main profile) is the catch-all
     when the board slug is empty/None.

5. **`resolve_deployer_for_board`** / **`resolve_deployer_for_task`** —
   pure-string resolvers (no profile-store access) so they stay unit-
   testable. `resolve_deployer_for_task` honours an explicit
   `deploy_lane` tag on the task row when set, otherwise derives from
   the board.

6. **`_enforce_deploy_lane` dispatch guard** — the core fix. Runs in
   `_dispatch_once_locked` after the `default_assignee` resolution and
   before the `profile_exists` check. If the task is a deploy task
   (assignee role == deployer) and its assignee does not match the
   lane-resolved deployer, the guard rewrites the assignee and emits a
   `deploy_lane_rerouted` event.
   - **Profile-existence safety:** when the lane-resolved deployer does
     not exist on disk (e.g. `tacticcal` has no `deployer-tacticcal`
     profile), the guard falls back to `DEFAULT_DEPLOYER` rather than
     rerouting to a phantom profile. This keeps boards without a
     dedicated deployer working on the main `deployer` exactly as they
     did before Phase 0.
   - Non-deploy tasks (builder/verifier/reviewer) are never touched.

7. **`DispatchResult.deploy_lane_rerouted`** field —
   `list[tuple[task_id, from_assignee, to_assignee]]` so the CLI /
   dashboard / gateway can surface the reroute.

### `tests/hermes_cli/test_kanban_deploy_lanes.py` (new, 15 cases)

Covers: routing table explicit routes, derive-from-slug, fallback to
DEFAULT_DEPLOYER, case-insensitivity, `deploy_lane` field round-trip,
whitespace strip, empty-→-null, dispatch guard reroute / noop /
builder-skip / dry-run / derive-from-board-when-no-tag /
no-profile-fallback, and legacy-DB migration safety.

### `serve.py` + `index.html` (board-status app)

`_cost_summary` now returns a `deploy_lanes` array (one entry per board:
routed deployer, profile-exists flag, queued deploy-task count) plus
`deploy_lane_routes` and `deploy_lane_default`. `refreshCostSummary`
appends a DEPLOY LANES bar: green when all boards have their deployer
profile present, red with the missing board names when any are absent.

## Evidence

- `python -c "import ast; ast.parse(open('hermes_cli/kanban_db.py')...)"` → OK syntax
- `python -m pytest tests/hermes_cli/test_kanban_deploy_lanes.py -x -q` → **15 passed**
- `python -m pytest tests/hermes_cli/test_kanban_deploy_lanes.py tests/hermes_cli/test_kanban_default_assignee.py tests/hermes_cli/test_kanban_per_profile_cap.py tests/hermes_cli/test_kanban_block_kinds.py tests/hermes_cli/test_kanban_promote.py tests/hermes_cli/test_kanban_dispatch_lock.py -q` → **62 passed**
- Live smoke test against a copy of the module-2 board DB (dry-run):
  - `deploy_lane` column present after migration
  - guard detected and rerouted 1 misrouted `deployer-sitrep-ready` task
    on the module-2 board (fell back to main `deployer` because
    `deployer-module-2` does not exist as a profile)
  - no crash, no mutation (dry-run)
- `_cost_summary()` against live boards returns 9 boards routed; 4
  boards (`module-1`, `module-2`, `tacticcal`, and a duplicate
  `sitrepcore`) route to a deployer profile that does not exist on disk
  → they correctly fall back to the main `deployer`.

## Pre-existing test failures (NOT caused by this change)

`tests/hermes_cli/test_kanban_db.py` has ~35 failures on the baseline
(commit `20fa668f2`, before any deploy-lanes work) because the test
suite uses assignee names like `bob`/`alice` that are not registered
profiles, so the `profile_exists` check skips them. These failures are
environmental and pre-date this change. Verified by stashing the
deploy-lanes commit and re-running the same test on the baseline —
identical failure.

## How to verify

```bash
cd C:\Users\mikey\AppData\Local\hermes\hermes-agent
git checkout feature/deploy-lanes
python -m pytest tests/hermes_cli/test_kanban_deploy_lanes.py -v
```

## Routing table (current)

| Board slug        | Routed deployer                | Profile exists? |
|-------------------|--------------------------------|-----------------|
| sitrep-ready      | deployer-sitrep-ready          | YES             |
| sitrep-core       | deployer-sitrepcore            | YES             |
| sitrepcore        | deployer-sitrepcore            | YES             |
| appraisal-firearm | deployer-appraisal-firearm     | YES             |
| probate-firearm   | deployer-probate-firearm       | YES             |
| tacticcal         | deployer-tacticcal → fallback  | NO (uses main deployer) |
| module-1          | deployer-module-1 → fallback   | NO (uses main deployer) |
| module-2          | deployer-module-2 → fallback   | NO (uses main deployer) |
| (any other)       | deployer-<slug> → fallback     | depends         |

If Mike wants `tacticcal` or the module boards to have their own
dedicated deployer, create the `deployer-<slug>` profile and the guard
will start routing to it automatically (no code change needed).

## What this does NOT do

- Does not restart the board (per task constraint).
- Does not touch any other module.
- Does not change builder/verifier/reviewer routing — only deploy-role
  assignees are guarded.
- Does not backfill `deploy_lane` on existing task rows — they stay NULL
  and derive from the board at dispatch time, which is the correct
  behaviour.
