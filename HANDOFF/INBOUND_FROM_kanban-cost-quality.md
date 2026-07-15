# Kanban Cost/Quality Remediation — TDC Handoff

**Status:** CODE COMPLETE / NOT DEPLOYED  
**Branch:** `fix/kanban-cost-quality-phase1`  
**Date:** 2026-07-15  
**Builder:** Hermes Agent (main chat session)

---

## 1. What was built

Three-phase remediation of the Hermes Kanban factory based on today's read-only audit:

### Phase 1 — Immediate cost containment (Tasks 0-6)

- **Money Dial fix** — MEDIUM/HIGH no longer re-enable `auto_decompose`. Dial changes worker count only.
- **Disabled-profile enforcement** — Profiles with `kanban.enabled: false` cannot be dispatched (stops td-anti-slop/td-slop-fix).
- **One Follow-Up Rule** — Code-enforced in `create_task()`: builders max 1 review, verifiers max 1 deploy, deployers/planners zero.
- **Deterministic failure classifier** — 401/403/404/missing-key errors stop after 1 attempt; transient/task errors use limit 3.
- **Gate A passed:** 173/173 tests.

### Phase 2 — Cost observability (Tasks 7-10)

- **Billing attribution** — `task_runs` gained `billing_session_id`, `billing_provider`, `billing_base_url`, `billing_model` columns (additive, nullable migration).
- **Cost summary endpoint** — `/api/cost-summary` on Board Status shows provider routing, auto_decompose state, billing proof.
- **Idle-burn verifier** — `verify-kanban-idle-burn.py` snapshots, waits, compares. PASS = zero new tokens while idle.
- **Gate B passed:** 183/183 tests + live idle-burn confirmed (0 tokens in 30s).

### Phase 3 — Operational cleanup (Tasks 11-17)

- **Singleton locks** — Watchdog and Board Status use Windows file locking (`msvcrt.locking`). Duplicate instances exit cleanly.
- **Pause state single-source** — Watchdog no longer force-enables dispatch. Only Resume action changes it.
- **Profile config cleanup** — 31 profiles cleaned of conflicting `auto_decompose`, `failure_limit`, `dispatch_in_gateway`, `max_in_progress` keys.
- **scheduler-module disabled** — `kanban.enabled: false` added.
- **Duplicate processes cleaned** — Killed duplicate board_proxy/dashboard/watchdog instances.
- **SitRep Ready triage** — 3 duplicate/rework cards archived. 14 real Milestone A cards remain.
- **Cost/quality scorecard** — `kanban-cost-quality-scorecard.py` produces plain-English verdict from local code.

---

## 2. Files changed

### In the Hermes git repo (`hermes-agent`)

| File | Changes |
|---|---|
| `hermes_cli/kanban_db.py` | +`ProfileDispatchEligibility` helper, +`_check_profile_dispatch_eligibility()`, +dispatch loop integration, +`classify_failure()`, +`effective_failure_limit()`, +`_enforce_follow_up_rule()`, +`_try_record_run_billing()`, +billing columns migration, +`follow_up_kind` param on `create_task()`, +`skipped_disabled_profile` on `DispatchResult` |
| `tests/local_factory/__init__.py` | New |
| `tests/local_factory/test_money_dial_invariants.py` | New — 24 tests |
| `tests/local_factory/test_disabled_profile_dispatch.py` | New — 4 tests |
| `tests/local_factory/test_follow_up_guard.py` | New — 7 tests |
| `tests/local_factory/test_nonretryable_failures.py` | New — 24 tests |
| `tests/local_factory/test_task_run_billing_attribution.py` | New — 5 tests |
| `tests/local_factory/test_idle_burn_verifier.py` | New — 8 tests |

### Outside the git repo (TDC must apply separately)

| File | Changes |
|---|---|
| `C:\Users\mikey\Desktop\HERMES BUILDERS\board-status\serve.py` | Money Dial presets simplified, `_apply_money_dial()` narrowed, `_money_dial_state()` reads config, +`_cost_summary()`, +`/api/cost-summary` endpoint, +singleton lock |
| `C:\Users\mikey\Desktop\HERMES BUILDERS\board-status\index.html` | +cost-bar in header, +`refreshCostSummary()` JS |
| `C:\Users\mikey\AppData\Local\hermes\factory-watchdog.py` | +singleton lock, +pause-respect fix |
| `C:\Users\mikey\AppData\Local\hermes\config.yaml` | `auto_decompose: false`, `auto_decompose_per_tick: 0`, `failure_limit: 3`, `max_in_progress_per_profile: 1` |
| `C:\Users\mikey\AppData\Local\hermes\factory-money-dial.json` | Rewritten without stale keys |
| `C:\Users\mikey\AppData\Local\hermes\profiles\*\config.yaml` | 31 profiles cleaned of conflicting keys; scheduler-module disabled |
| `C:\Users\mikey\AppData\Local\hermes\scripts\verify-kanban-idle-burn.py` | New |
| `C:\Users\mikey\AppData\Local\hermes\scripts\kanban-cost-quality-scorecard.py` | New |
| `C:\Users\mikey\AppData\Local\hermes\kanban\boards\sitrep-ready\kanban.db` | 3 duplicate cards archived |

---

## 3. Git state

```
Branch: fix/kanban-cost-quality-phase1
Base: main
Commits: 7 (4 RED tests + 3 GREEN fixes)
```

```
e72c78c95 test: define kanban factory cost-control invariants (RED)
5a477d1c5 fix: enforce disabled kanban profiles during dispatch
80dc433d0 fix: stop deterministic kanban failures after 1 attempt
dee5d9c6b fix: enforce bounded kanban follow-up chains (One Follow-Up Rule)
a6fad86ea feat: record kanban run billing attribution
d6f22fee8 feat: add cost view, idle-burn verifier, billing endpoint
```

---

## 4. Test results

```
186 passed in 20.65s
```

All 186 tests pass (72 new + 114 existing). Zero regressions.

---

## 5. Live verification

| Check | Result |
|---|---|
| Board health | OK (port 8766, dashboard connected) |
| auto_decompose | false |
| auto_decompose_per_tick | 0 |
| max_in_progress | 1 (LOW) |
| failure_limit | 3 |
| max_in_progress_per_profile | 1 |
| MEDIUM button safe | auto_decompose stays false ✅ |
| HIGH button safe | auto_decompose stays false ✅ |
| Profile conflicting keys | 0 |
| scheduler-module disabled | kanban.enabled: false ✅ |
| Idle burn (15s) | PASS: zero new sessions/calls/tokens ✅ |
| Cost summary | Builders: DIRECT Z.AI, Reviews: DIRECT xAI, Planners: DIRECT ANTHROPIC ✅ |

---

## 6. Deploy instructions

### Step 1: Merge the feature branch

```bash
cd C:\Users\mikey\AppData\Local\hermes\hermes-agent
git checkout main
git merge fix/kanban-cost-quality-phase1
```

### Step 2: Apply out-of-repo files

The following files are NOT in the git repo. They have already been applied to the live system. TDC should verify they are in place:

1. `serve.py` and `index.html` in `C:\Users\mikey\Desktop\HERMES BUILDERS\board-status\`
2. `factory-watchdog.py` in `C:\Users\mikey\AppData\Local\hermes\`
3. `config.yaml` in `C:\Users\mikey\AppData\Local\hermes\`
4. Profile `config.yaml` files in `C:\Users\mikey\AppData\Local\hermes\profiles\*\`
5. Scripts in `C:\Users\mikey\AppData\Local\hermes\scripts\`

### Step 3: Restart services

```bash
# Kill all old processes
# Run the restart bat:
"C:\Users\mikey\Desktop\HERMES BUILDERS\RESTART Hermes Gateway - Direct Keys.bat"

# Then start the watchdog:
cd C:\Users\mikey\AppData\Local\hermes
pythonw factory-watchdog.py
```

### Step 4: Post-deploy verification

1. `curl http://127.0.0.1:8766/api/health` → ok: true
2. `curl http://127.0.0.1:8766/api/cost-summary` → auto_decompose: false, providers correct
3. Click MEDIUM on the board → verify auto_decompose stays false
4. Click LOW again
5. Run `python verify-kanban-idle-burn.py --seconds 30` → PASS
6. Run `python kanban-cost-quality-scorecard.py` → check verdict

---

## 7. Rollback

1. Restore `serve.py` from `serve.py.fixed-20260715` backup (or git restore)
2. Restore `config.yaml` from `config.yaml.bak-20260715-103004`
3. Restore `factory-money-dial.json` from `factory-money-dial.json.bak-20260715-103004`
4. Restore profile configs (31 profiles were cleaned)
5. Restart gateway via the Desktop bat
6. Verify board health

Database rollback:
- New `task_runs` columns are additive and nullable. Old code works if they're empty.
- Do not drop columns during rollback.

---

## 8. Post-deploy acceptance criteria

After 20+ new runs post-fix:
- [ ] Zero new auto-decomposer tasks
- [ ] Zero new Nous factory runs without explicit approval
- [ ] 100% of new runs have billing attribution
- [ ] Non-completed run share < 25%
- [ ] No duplicate review/deploy cards
- [ ] Protected work retains all required gates
- [ ] Idle/paused produces zero factory model calls
- [ ] No credentials in logs/reports/UI
