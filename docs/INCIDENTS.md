# Incident Playbook

## General Response Template

For any incident:
1. **Engage kill switch** immediately
2. **Assess** (what failed, when, what data is at risk)
3. **Preserve state** (don't delete logs)
4. **Recover** (fix root cause, reconcile, restart)
5. **Post-mortem** (update this doc)

---

## 1. Broker Connection Lost Mid-Session

**Detection**: OMS logs `ERROR` on `broker.account()` or `broker.submit()`. Heartbeat file goes stale.

**Immediate action**:
- Kill switch engages automatically if reconciliation sees large drift
- Or engage manually: `python -c "from live.risk.breakers import KillSwitch; KillSwitch().engage('connection lost')"`

**Recovery**:
1. Restart OpenD (if moomoo broker)
2. Re-run `python -m live.runner --ticks 1` — OMS will reconcile on startup
3. If reconciliation passes, continue normal operation

---

## 2. Reconciliation Mismatch

**Detection**: `live/state/incidents/<ts>-reconcile-mismatch.json` exists. Kill switch engaged.

**Immediate action**: Kill switch already engaged.

**Recovery**:
1. Read the incident file: `cat live/state/incidents/<ts>-reconcile-mismatch.json`
2. Identify source of mismatch: unexpected fill? Stale local state?
3. If small drift (within 1%): update local state to match broker
4. If large drift (>2%): investigate all fills since last reconciliation
5. Do NOT disengage kill switch until mismatch is explained
6. Disengage with human token, restart with `--ticks 1`

---

## 3. moomoo OpenD Process Dies

**Detection**: Connection error on any broker call. Task Manager shows OpenD not running.

**Immediate action**:
- Orders stop being placed (safe: kill switch is not required but recommended)
- All pending fills are lost (they won't be received)

**Recovery**:
1. Restart OpenD
2. Re-run runner; OMS reconciles from broker state
3. Check `fills_since(ts)` to verify no fills were missed

---

## 4. Strategy Produces NaN Weights

**Detection**: `WARNING` log: strategy returned NaN weights. OMS falls back to zero weights (no orders placed).

**Immediate action**: No trade is safer than a NaN trade. Monitor for one session.

**Recovery**:
1. Check the feature store for NaN values in recent data
2. Check if a new symbol was added with insufficient history
3. Fix the feature or exclude the symbol
4. If NaN persists for > 3 sessions, engage kill switch and investigate

---

## 5. Runner Cannot Read State Files

**Detection**: `FileNotFoundError` or `PermissionError` in logs.

**Immediate action**: Runner will crash; engage kill switch manually.

**Recovery**:
1. Check disk space: `df -h live/state/`
2. Check file permissions: `ls -la live/state/`
3. If disk is full: archive old session logs
4. If permissions: fix ownership
5. Restart runner

---

## Post-Mortem Template

```
Date: YYYY-MM-DD
Incident: [brief description]
Timeline:
  HH:MM - First alert / symptom
  HH:MM - Kill switch engaged
  HH:MM - Root cause identified
  HH:MM - Recovery complete
Root cause: [what failed and why]
Impact: [P&L impact, positions affected, duration]
Fix: [what changed to prevent recurrence]
```
