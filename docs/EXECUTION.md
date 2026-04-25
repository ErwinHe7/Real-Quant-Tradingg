# Execution Layer — Runner Lifecycle, Recovery Model, Operator Runbook

## Overview

The execution layer lives in `live/`.  It is the only path between strategy
signals and actual orders (paper or live).  All components are broker-agnostic
except for `live/broker/moomoo.py`.

## Directory Structure

```
live/
├── broker/
│   ├── base.py          # Broker Protocol
│   ├── types.py         # Order, Fill, Position, Account, Quote, OrderAck
│   ├── paper.py         # PaperBroker (fills against cached OHLCV)
│   └── moomoo.py        # MoomooBroker (paper env only in Phase 5)
├── oms/
│   ├── engine.py        # OMS event loop
│   ├── translator.py    # weights → orders (pure function)
│   ├── state.py         # persisted state (survives restarts)
│   └── reconcile.py     # position reconciliation
├── monitor/
│   ├── health.py        # heartbeat file
│   └── notify.py        # alert stub (no-op by default)
├── risk/                # Phase 4 risk layer
└── runner.py            # CLI entry point
```

## Runner Lifecycle

```
python -m live.runner --strategy ons --broker paper --ticks 10
```

1. Load cached price data for the strategy universe
2. Warm up the strategy on all available historical data
3. Instantiate broker (paper or moomoo-paper)
4. Check kill switch — abort if engaged
5. For each tick:
   a. Get account + market state from broker
   b. Call strategy → raw target weights
   c. RiskManager.evaluate() → approved weights
   d. weights_to_orders() → order list
   e. Submit orders to broker
   f. Every 4 ticks: reconcile with broker truth
   g. Record heartbeat and session log
6. Write end-of-day summary to `live/state/sessions/YYYY-MM-DD-summary.json`

## Recovery Model

**Crash between submit and ack-persist**: the broker (paper or moomoo) holds
the true state.  On restart, the OMS loads its persisted state, reconciles
against the broker, and continues.  No double-orders because the broker is the
source of truth.

**Process crash detected by watchdog**: the heartbeat file at
`live/state/heartbeat.json` is touched on each tick.  If it goes stale for
>30 minutes, an external watchdog (cron / Task Scheduler) can alert.

## Kill Switch — Operator Runbook

### Engage (any operator)
```bash
python -c "
from live.risk.breakers import KillSwitch
KillSwitch().engage('reason: manual halt by operator Alice')
"
```

### Check status
```bash
python -c "
from live.risk.breakers import KillSwitch
ks = KillSwitch()
print('Engaged:', ks.is_engaged(), '|', ks.read_reason())
"
```

### Disengage (human token required; agent cannot do this)
```bash
python -c "
from live.risk.breakers import KillSwitch
KillSwitch().disengage('Alice-2026-05-01-authorised')
"
```

The disengage call requires a non-empty, non-automated token.  Forbidden
tokens: AGENT, SYSTEM, AUTO, AUTOMATED, BOT.

### Audit log
```bash
cat live/state/kill_switch_audit.jsonl
```

## Inspect Incidents
```bash
ls live/state/incidents/
cat live/state/incidents/20260501T143000-reconcile-mismatch.json
```

## Inspect Session Logs
```bash
cat live/state/sessions/2026-05-01.jsonl          # per-tick equity log
cat live/state/sessions/2026-05-01-summary.json   # end-of-day summary
```

## Roll Over Session Log

Session logs are per-day files.  They roll automatically at midnight local
time.  To archive old sessions:
```bash
zip -r sessions_archive.zip live/state/sessions/2026-*.jsonl
```

## MoomooBroker Smoke Test (Paper Env)

Prerequisites: OpenD running at 127.0.0.1:11111

```bash
python -m live.runner --strategy ons --broker moomoo-paper --ticks 1
```

This submits one tick of orders to the moomoo simulated account.  Verify
the order appears in the moomoo app.  The audit trail is at
`~/.futu_trade_audit.jsonl`.

## Flatten All Positions

```bash
python -m live.tools.flatten --broker paper
```

This is a one-shot script (Phase 6) that liquidates all positions respecting
PDT and risk limits.

## What to Do When Something Goes Wrong

1. **Default action**: engage the kill switch
2. Investigate the incident file at `live/state/incidents/`
3. Fix the root cause
4. Re-run reconciliation manually
5. Disengage the kill switch with a human token
6. Restart the runner with `--ticks 1` to verify before resuming
