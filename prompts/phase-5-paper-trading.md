# Phase 5 — Paper Trading & OMS

Prerequisite: read `prompts/00-agent-charter.md`. Phases 2-4 complete (data,
validated strategies, risk layer). The moomoo skill at
`~/.claude/skills/moomooapi/` is installed and OpenD is available locally.

## Goal

Build a broker-agnostic Order Management System (OMS), a `PaperBroker` that
fills against cached + realtime data with realistic slippage, and a
`MoomooBroker` adapter that **trades only the moomoo simulated environment**
in this phase. No live trading. No `unlock_trade` calls. No real money.

## Why This Matters

The single most common reason retail quant systems blow up is execution
sloppiness: missed fills, double orders, stale state, races between
strategy loop and reconciliation, silent rejection of orders. A clean OMS
that has been hammered against a paper broker for weeks is the only way
to find these bugs before money is at stake.

## Required Reading

- charter
- moomoo skill: `~/.claude/skills/moomooapi/SKILL.md` and the underlying
  scripts; the skill enforces simulated default and forbids `unlock_trade`
- `live/risk/` from Phase 4
- `research_harness/feed/moomoo_feed.py` from Phase 2

## Deliverables

### D1. Broker interface

```text
live/broker/__init__.py
live/broker/base.py
live/broker/types.py        # Order, Fill, Position, Account, Quote
live/broker/paper.py        # PaperBroker
live/broker/moomoo.py       # MoomooBroker (paper env only in this phase)
```

`live/broker/base.py`:

```python
class Broker(Protocol):
    def account(self) -> Account: ...
    def positions(self) -> dict[str, Position]: ...
    def quote(self, symbol: str) -> Quote: ...
    def submit(self, order: Order) -> OrderAck: ...
    def cancel(self, order_id: str) -> None: ...
    def open_orders(self) -> list[Order]: ...
    def fills_since(self, ts: datetime) -> list[Fill]: ...
    def env(self) -> Literal["paper", "live"]: ...
```

`Order` is immutable. `submit` returns synchronously with an ack; fills
are pulled via `fills_since`. No callbacks in this layer; if moomoo's SDK
exposes them, the adapter buffers them into a queue that `fills_since`
reads.

### D2. PaperBroker

`live/broker/paper.py`:
- account state lives in `live/state/paper/account.json` and per-symbol
  position files; updated atomically (write to temp, rename)
- fills:
  - market orders fill at next-bar VWAP if next bar is available, else
    at last trade ± modeled spread/2
  - limit orders fill if the bar's range crosses the limit, partial fills
    based on (bar_volume * participation_rate, default 1%)
  - slippage model: per-symbol bps, configurable, default
    `5 + 8 * sqrt(notional / ADV20)` bps, capped at 30 bps
- borrow / locate: refuse short orders unless config explicitly enables;
  default off
- rejects orders that would exceed cash on hand; never silently reduces
  size without surfacing the change in the `OrderAck`

### D3. MoomooBroker (simulated env only)

`live/broker/moomoo.py`:
- wraps the moomoo skill scripts via the same Python SDK pattern shown
  in `~/.claude/skills/moomooapi/`
- on init, asserts `env="paper"`; if any code path attempts to set live,
  raise `LiveTradingNotAuthorizedError`
- never calls `unlock_trade` (the skill explicitly forbids this; preserve
  the prohibition)
- maps Moomoo order types and time-in-force into the broker `Order` model;
  document every mapping in code comments
- exposes audit hooks so that every submit / cancel / fill is appended to
  `~/.futu_trade_audit.jsonl` in addition to the broker's own audit

### D4. OMS

`live/oms/`:
- `oms/engine.py` — single-threaded event loop:
  1. tick: get market state from feed
  2. compute target weights from strategy
  3. `RiskManager.evaluate(...)` → approved weights
  4. translate (current positions, approved weights, account) → diff orders
  5. submit to broker
  6. wait for fills, reconcile, persist
- `oms/translator.py` — pure function turning weight diffs into Orders.
  Never produces a fractional share order. Never submits an order smaller
  than `min_notional`. Never produces same-day round-trips that would
  trip PDT.
- `oms/state.py` — persisted between runs; idempotent recovery: if the
  process dies between submit and ack-persist, the next start
  reconciles from broker truth, not local belief.

### D5. Reconciliation

`live/oms/reconcile.py` runs:
- on startup
- after every fill batch
- as a heartbeat every N minutes

It compares broker positions / cash to local belief and:
- on small drift (within tolerance): logs and updates local
- on large drift: engages the kill switch and writes
  `live/state/incidents/<ts>-reconcile-mismatch.json`

### D6. Scheduler / runner

`live/runner.py`:
- CLI: `python -m live.runner --strategy <name> --broker paper [--moomoo-paper]`
- daily schedule: pre-open warmup, in-session ticks (every N minutes,
  N >= 15 for the swing strategies in scope), end-of-day close-out / report
- writes `live/state/sessions/<date>.jsonl` with a row per tick

### D7. Monitoring

`live/monitor/`:
- `monitor/health.py`: emits a heartbeat file the runner touches every
  loop; an external watchdog (cron) can detect stalled runners
- `monitor/notify.py`: optional Slack / Telegram / email notifier;
  default no-op stub so missing creds do not crash the run

### D8. Tests and replay

`tests/oms/`:
- deterministic replay: feed the OMS a recorded session of synthetic
  market events and assert the resulting fills, positions, and equity
- chaos tests: drop the runner mid-loop, restart, verify reconciliation
- adversarial tests: inject a fill the OMS did not request (broker bug
  scenario) — the OMS must engage the kill switch

## Acceptance Criteria

1. `pytest tests/oms/ tests/risk/ tests/data_store.py` all pass.
2. `python -m live.runner --strategy <best-from-phase-3> --broker paper`
   runs unattended for 5 simulated trading days and produces:
   - a session log per day,
   - reconciled state at end of each day,
   - a summary report with realised P&L vs. backtest expectation.
3. `python -m live.runner --strategy <same> --broker moomoo-paper`
   connects to OpenD, submits orders into the simulated environment, and
   exits cleanly. Manual smoke test only — no automated network test.
4. Audit trail is append-only and matches the moomoo skill's audit log.
5. The kill switch from Phase 4 is honoured: while engaged, the runner
   places no orders.
6. `docs/EXECUTION.md` documents the runner lifecycle, recovery model,
   and operator runbook (how to engage the kill switch, how to inspect
   incidents, how to roll over the session log).
7. `artifacts/phase-5-report.md` documents what was built and any
   discrepancy between paper P&L and backtest expectation.

## Out Of Scope

- live (real-money) trading (Phase 6)
- options orders (deferred)
- multi-account / sub-portfolio support (deferred)
- co-located low-latency execution (out of scope forever for this project;
  see charter)

## Stop Conditions

Stop and ask if:
- the moomoo SDK requires `unlock_trade` for an operation you believe is
  necessary — the skill forbids this; the design must change instead,
- you find that the moomoo simulated environment does not provide
  realistic fills for the universes chosen — in that case, prefer
  PaperBroker and document moomoo-paper as a smoke-test environment only,
- reconciliation discovers an unexplained drift during smoke testing —
  do not "fix" it by widening tolerances; debug.
