# Operator Runbook

## Start / Stop / Restart the Runner

### Start (paper broker)
```bash
python -m live.runner --strategy ons --broker paper
```

### Start (moomoo paper env, requires OpenD running)
```bash
python -m live.runner --strategy ons --broker moomoo-paper
```

### Stop (graceful)
Press `Ctrl+C`.  The runner completes the current tick and writes a session summary.

### Restart
Just re-run the start command.  The OMS loads its persisted state and continues.
If the kill switch is engaged, disengage it first (see below).

---

## Kill Switch

### Engage (manual)
```bash
python -c "
from live.risk.breakers import KillSwitch
KillSwitch().engage('Manual halt — reason: ...')
"
```

### Check Status
```bash
python -c "
from live.risk.breakers import KillSwitch
ks = KillSwitch()
print('Engaged:', ks.is_engaged())
print('Reason:', ks.read_reason())
"
```

### Inspect Audit Log
```bash
python -c "
import json
from pathlib import Path
for line in Path('live/state/kill_switch_audit.jsonl').read_text().splitlines():
    print(json.dumps(json.loads(line), indent=2))
"
```

### Disengage (human token required — agent cannot do this)
```bash
python -c "
from live.risk.breakers import KillSwitch
KillSwitch().disengage('YourName-YYYY-MM-DD-reason')
"
```
Forbidden tokens: AGENT, SYSTEM, AUTO, AUTOMATED, BOT.

---

## Rotate Authorization File (for live trading, Phase 6)

1. Edit `live/state/live_authorization.yaml` manually.
2. Run:
   ```bash
   python -m live.tools.authorize
   ```
3. The hash is appended to `live/state/auth_hashes.jsonl`.

---

## Inspect Incidents
```bash
ls live/state/incidents/
cat live/state/incidents/20260501T143000-reconcile-mismatch.json
```

## Inspect Session Logs
```bash
cat live/state/sessions/2026-05-01.jsonl
cat live/state/sessions/2026-05-01-summary.json
```

---

## Flatten All Positions to Cash
```bash
python -m live.tools.flatten --broker paper
```

---

## "Something is Wrong" Checklist

1. **Engage the kill switch first** (see above)
2. Check `live/state/incidents/` for incident files
3. Check `live/state/heartbeat.json` — is `unix` timestamp recent?
4. Check `live/state/kill_switch_audit.jsonl` — who engaged it and why?
5. Run reconciliation manually:
   ```python
   from live.broker.paper import PaperBroker
   from live.risk.breakers import KillSwitch
   from live.oms.reconcile import reconcile
   broker = PaperBroker()
   ks = KillSwitch()
   report = reconcile(broker, {}, broker.account().equity_usd, ks)
   print(report)
   ```
6. Fix root cause
7. Disengage kill switch with human token
8. Restart runner with `--ticks 1` to verify before full run
