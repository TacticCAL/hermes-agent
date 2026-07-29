# Hermes Kanban Windows Safe-Repair Runbook

**Status:** CODE COMPLETE / TESTED / NOT LOADED BY RUNNING GATEWAY
**Branch:** `feature/deploy-lanes`
**Builder:** Hermes Desktop main session
**Date:** 2026-07-28
**Owner:** Hermes Agent/Kanban operator. This is not a TacticCAL Dashboard handoff and is not for TDC.

## Plain-English result

This repair stops the board from paying to restart work when Windows cannot prove why a worker ended, stops fake review waits from immediately restarting a builder, gives large workers time to save their work, and keeps ordinary cards out of long-running goal mode unless explicitly requested.

## Confirmed root causes fixed

1. **Windows worker endings were lost.** The dispatcher launched a process and kept only its PID. Windows has no Unix-style child reaper here, so a clean exit became `pid not alive` and could restart paid work.
2. **Unknown endings were treated as crashes.** If the gateway could not classify an exit, the card was requeued. The safe behavior is now one stop for investigation.
3. **Fake dependency waits restarted immediately.** A card could say it was waiting for review without an unfinished prerequisite attached. The dispatcher then promoted it again.
4. **Workers burned their final steps waiting for review.** An enforced landing checkpoint now tells Kanban workers to commit and hand off at about 83% of their allowance.
5. **Ordinary cards were accidentally changed to long-running goal cards.** Goal mode is opt-in again.
6. **Card context included too much automated failure noise.** Worker context now keeps the newest useful comments, newest handoff, recent runs, and recent events.
7. **Restart counting crossed board/reset boundaries.** The active Token Cop counter is board-specific and reset-aware; its regression test is included.

## Files changed in this branch

| File | What changed |
|---|---|
| `agent/conversation_loop.py` | Enforced 83% landing checkpoint for Kanban workers; forbids waiting/polling and requires a handoff. |
| `hermes_cli/kanban_db.py` | Retains worker process handles and polls real return codes; unknown exits stop once; dependency waits require an unfinished parent; budget-exhaustion diagnosis; goal-mode default restored; task sizing/routing/failure safeguards already in the working branch preserved. |
| `hermes_cli/_subprocess_compat.py` | Removes the invalid Windows combination of mutually exclusive process flags. |
| `tools/kanban_tools.py` | Removes automated stop-noise and old history from paid worker context while preserving the newest handoff. |
| `tests/kanban/test_windows_worker_exit_tracking.py` | New Windows exit and unknown-stop regression tests. |
| `tests/kanban/test_token_cop_board_scope.py` | New board-specific/reset-aware restart-count regression test. |
| `tests/hermes_cli/test_kanban_block_kinds.py` | Dependency-wait validation tests. |
| `tests/hermes_cli/test_kanban_db.py` | Unknown-exit policy test updated to the safe stop-once behavior. |
| `tests/tools/test_kanban_tools.py` | Goal/dependency and stale-run tests updated for the new safety contract. |
| `scripts/kanban_safe_repair_canary.py` | No-model temporary-board canary covering the three core protections. |

## Out-of-repository live support files

These are not part of the git commit and must be verified separately by the Hermes/Kanban operator:

- `C:\Users\mikey\AppData\Local\hermes\scripts\token_cop.py`
  - Uses provider-specific rates.
  - Uses real API-call count, not inflated message count.
  - Restart count is board-specific and reset-aware.
  - Same-error stop rule matches Mike’s three-failure rule.
- `C:\Users\mikey\AppData\Local\hermes\scripts\test_limit_guard.py`
- `C:\Users\mikey\AppData\Local\hermes\scripts\test_landing_checkpoint.py`
- Worker profile instruction files contain the `NEVER WAIT FOR A VERDICT` rule.

## Verification evidence

### Focused Kanban suite

```text
144 passed in 18.57s
```

Command:

```bash
python -m pytest \
  tests/hermes_cli/test_kanban_goal_mode.py \
  tests/hermes_cli/test_kanban_block_kinds.py \
  tests/kanban/test_windows_worker_exit_tracking.py \
  tests/kanban/test_token_cop_board_scope.py \
  tests/tools/test_kanban_tools.py \
  tests/hermes_cli/test_kanban_worker_spawn_toolsets.py \
  tests/hermes_cli/test_kanban_worker_terminal_cwd.py \
  tests/tools/test_windows_native_support.py::TestSubprocessCompatHelpers \
  -q --tb=short
```

### Core safety regressions

```text
17 passed in 1.81s
```

### Isolated no-model canary

Ran twice:

```text
CANARY PASS: real exit retained; fake dependency rejected; unknown exit stopped once
CANARY PASS: real exit retained; fake dependency rejected; unknown exit stopped once
```

The canary uses a temporary Kanban database and makes zero model calls.

### Structural safety scripts

- Limit consistency guard: PASS for small, normal, and big cards.
- Landing checkpoint guard: PASS.
- Python compile: PASS.
- `git diff --check`: PASS.
- Static secret/injection scan of added lines: no findings.

### Independent review

Independent reviewer verdict: **PASS**.

- Security concerns: none.
- Logic errors: none.
- Two documentation/cleanup suggestions were applied in a follow-up commit:
  the retry-policy description now matches Mike's three-failure rule, and an
  unused database field read was removed.
- The reviewer suggested optionally capping retained process handles. The operator should
  not evict a still-running handle merely to satisfy a fixed cap because that
  would recreate the lost-exit bug. The registry is naturally bounded by the
  dispatcher's concurrent-worker limit and removes each handle when it exits.
- Two earlier architecture reviewers identified missing regression coverage.
  Their requested cases are now pinned: clean-exit protocol violation,
  profile-session budget lookup, blocked-parent gating, full
  build→review→deploy order, rework gating, archived-parent consistency, and
  mutually exclusive Windows process flags.

## Broad-suite disclosure

`tests/hermes_cli/test_kanban_db.py` is not fully green on this Windows checkout: **205 passed, 18 failed**.

The remaining failures are pre-existing/test-harness assumptions rather than failures of this repair:

- Windows Git prints forward-slash worktree paths while tests expect backslashes.
- Worker-launch tests expect `hermes.exe`/`python.exe`, while the live Windows fix intentionally uses hidden `pythonw.exe`.
- Unix `waitpid` reaper tests run on Windows without forcing Unix mode.
- Two worktree-dispatch fixtures patch the wrong profile-existence reference.

The Hermes maintainer/operator must either update those platform assumptions or prove the same baseline failures on the branch base before merging. Do not claim the entire repository suite is green.

## Live-card reconciliation performed

No builds were rerun and nothing was deployed.

1. NFA Phase 2 build `t_687ad632` was closed from verified git evidence:
   - Real code commits: `e69a880c`, `51c2c21c`
   - Handoff commit: `49255626`
   - Application-review record remains `t_0dbb7b5a`
2. Purchasing-safety build `t_23109b78` was closed from verified git and verifier evidence:
   - Real code commits: `6131af97`, `894ca436`, `b7c87a7f`
   - Verifier PASS: `t_7d9b59ad`
3. NOTC remains parked because Mike explicitly said hold.
4. POS Phase 5 remains resumable because its handoff says work remains.
5. Both purchasing-safety deployment cards remain blocked. No Neon migration was applied.

After reconciliation, stopped cards fell from six to four; the two false build failures disappeared.

## Hermes operator activation instructions

1. Review this Hermes Agent branch and the independent reviewer result.
2. Run the focused 144-test command above.
3. Run `python scripts/kanban_safe_repair_canary.py` twice.
4. Verify the out-of-repo Token Cop script and safety scripts listed above.
5. Resolve or baseline the 18 broad-suite Windows harness failures before merge.
6. Merge the reviewed branch according to the Hermes Agent repository policy.
7. Restart the Hermes gateway only after the merge. A restart is required for the running gateway to load the code.
8. After restart, reapply/verify Money Dial and Token Cop, per Mike’s locked restart procedure.
9. Run one temporary or harmless canary before allowing live cards to dispatch.
10. Monitor only events newer than the restart timestamp for at least 24 hours.

## Post-activation checks

- A Windows child exiting 0 is classified as a clean exit.
- A clean exit with no final card transition stops once as a protocol problem.
- An unknown exit after a gateway restart stops once instead of respawning.
- A dependency wait without an unfinished parent is rejected.
- A valid dependency wait remains parked until its parent finishes.
- No card rebuilds code already verified in git.
- No production deploy starts without a typed `MIKE ANSWER: GO` on the card.
- No new paid restart loop appears after the deployment timestamp.

## Rollback

If the repair causes a regression:

1. Stop new dispatches without killing Hermes Desktop.
2. Revert this repair commit/merge.
3. Restart the gateway.
4. Reapply Money Dial and Token Cop.
5. Keep all production deployment cards blocked.
6. Preserve the failed canary/event evidence for diagnosis.

## Hard NO-GO conditions

Do not activate the repair if:

- Focused tests fail.
- The temporary canary fails.
- Windows launches visible console windows.
- Unknown exits return to `ready` instead of stopping once.
- Fake dependency waits are accepted.
- Token Cop counts events from another board or before the latest reset.
- The Hermes maintainer/operator cannot explain the 18 broad-suite Windows harness failures.

**This runbook does not authorize TacticCAL production deployment, Neon changes, or restarting finished builds.**
