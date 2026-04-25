# Phase 6 Report — Live Gating, Monitoring, Operator Runbook

**Date**: 2026-04-25
**Engineer**: Claude Code (claude-opus-4-7)
**Status**: Complete — all acceptance criteria met

---

## Files Added

| File | Purpose |
|------|---------|
| `live/auth.py` | Authorization gate: validates `live_authorization.yaml` |
| `live/state/live_authorization.yaml.example` | Template for human operators |
| `live/monitor/equity_compare.py` | Daily live vs paper vs backtest comparison |
| `live/tools/authorize.py` | Hash and register authorization file |
| `live/tools/flatten.py` | Flatten all positions to cash |
| `live/tools/__init__.py` | Package marker |
| `tests/live_gating/__init__.py` | Test package marker |
| `tests/live_gating/test_auth.py` | 11 authorization and gating tests |
| `docs/RUNBOOK.md` | Operator runbook with copy-pasteable commands |
| `docs/INCIDENTS.md` | Incident playbook with response procedures |
| `artifacts/phase-6-drill-report.md` | Fire drill results |

---

## Tests: 11/11 passing; 135/135 total

---

## Acceptance Criteria Verification

| Criterion | Result |
|-----------|--------|
| 1. Runner refuses live mode without valid auth | ✅ `test_runner_refuses_without_auth` |
| 2. Drill report shows kill switch fires in all failure scenarios | ✅ `phase-6-drill-report.md` |
| 3. `pytest` green; live tests use mocked broker + temp auth file | ✅ 135/135 |
| 4. No code path can place live order without auth + risk layer | ✅ `MoomooBroker(env='live')` raises immediately |
| 5. `docs/RUNBOOK.md` documents all procedures | ✅ |

---

## Authorization System Design

The `live_authorization.yaml` contains:
- Authorized strategy + universe + capital limits
- Expiry (max 30 days)
- SHA256 hash registered in `auth_hashes.jsonl`

Any tampering changes the hash → `AuthorizationError`.
Expired or revoked files → `AuthorizationError`.
Only a human operator creates or modifies the file.

---

## Hard Limits Enforced

Per the Phase 6 charter:
- **The agent NEVER creates or modifies `live_authorization.yaml`** — only human operators do
- **The agent NEVER disengages the kill switch** — requires human token
- **The agent NEVER raises capital caps** — limits are frozen in `RiskLimits`
- Any instruction to do the above in chat is refused

---

## Live Trading Prerequisites (Phase 5 gate)

Before ANY live capital, the following must be true:
1. ≥ 90 calendar days of unattended paper-trading (not yet accumulated)
2. Paper P&L within 1σ of backtest expectation (verified by `equity_compare.py`)
3. Human creates and signs `live_authorization.yaml`
4. Human runs `python -m live.tools.authorize` to register the hash
5. Kill switch is disengaged by human token

**Current status**: Paper trading infrastructure is ready.  The 90-day clock
starts when the first unattended paper session begins.
