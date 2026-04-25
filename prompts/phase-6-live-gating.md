# Phase 6 — Live Gating, Monitoring, Operator Runbook

Prerequisite: read `prompts/00-agent-charter.md`. Phases 2-5 complete. The
runner has been paper-trading via PaperBroker and `MoomooBroker(env=paper)`
for at least 90 consecutive calendar days **before** this phase begins.
That gate is non-negotiable.

## Goal

Add the controls, monitoring, and human-in-the-loop gates that let the
owner flip a single switch to point the runner at a real-money moomoo
account with the smallest plausible capital. Real-money trading must be
preceded by an explicit, recorded human authorisation.

## Required Reading

- charter (R5 in particular)
- `live/broker/moomoo.py`
- `live/risk/`
- moomoo skill SKILL.md, especially the live-trading confirmation protocol
  — preserve it; do not weaken it

## Deliverables

### D1. Live authorisation file

`live/state/live_authorization.yaml` — committed, gitignored only after
first creation. Schema:

```yaml
authorized_at: 2026-MM-DDTHH:MM:SSZ   # ISO timestamp set by a human
authorized_by: "<name>"
strategy: "<exact strategy id>"
universe: "<exact universe id>"
max_gross_notional_usd: 1000          # hard cap, enforced pre-trade
max_per_name_usd: 200
trading_days: ["mon","tue","wed","thu","fri"]
expires_at: 2026-MM-DDTHH:MM:SSZ      # mandatory; max 30 days from authorized_at
revoked: false
```

`MoomooBroker` and the runner refuse to enter live mode unless this file:
- exists and parses,
- has not expired,
- is signed by a SHA256 hash recorded in `live/state/auth_hashes.jsonl`
  (append-only; any tampering changes the hash and trips the gate).

### D2. Live broker mode

Extend `live/broker/moomoo.py`:
- new constructor flag `env="live"`,
- on construct, validates the authorisation file,
- preserves the moomoo skill prohibition on `unlock_trade`,
- per-order pre-trade checks against `max_gross_notional_usd` and
  `max_per_name_usd`,
- if any pre-trade check fails, the order is rejected and the kill switch
  is engaged with reason `live_pre_trade_violation`.

### D3. Sanity equity comparison

`live/monitor/equity_compare.py`:
- once per day, computes:
  - paper-runner equity over the same window,
  - live equity from the broker,
  - backtest expectation (mean ± 1σ from phase-3 distribution).
- if live is more than 2σ away from paper for 3 consecutive days, it
  engages the kill switch with reason `live_paper_divergence`.

### D4. Operator runbook

`docs/RUNBOOK.md` covers, with copy-pasteable commands:
- start / stop / restart the runner,
- engage / inspect / disengage the kill switch (disengage requires
  human token; agent must not do it),
- rotate authorisation file,
- find the audit logs,
- the "something is wrong, what do I do" checklist (default action:
  engage kill switch, then investigate),
- how to wind down all positions to cash via a one-shot script
  `live.tools.flatten` (which itself respects PDT and risk limits).

### D5. Incident playbook

`docs/INCIDENTS.md` documents, in advance, how to respond to:
- broker connection lost mid-session,
- reconciliation mismatch,
- moomoo OpenD process dies,
- a strategy starts producing NaN weights,
- the runner cannot read its state files (disk full / permissions).

For each: detection signal, immediate action, post-mortem template.

### D6. Drill

Perform a paper-environment fire drill: while the paper runner is
mid-session, intentionally:
- kill OpenD,
- corrupt a state file,
- inject a fake reconciliation mismatch.
Confirm each triggers the documented response. Record the drill in
`artifacts/phase-6-drill-report.md`.

## Acceptance Criteria

1. The runner refuses to enter live mode without a valid authorisation
   file. Tests prove this.
2. The runbook drill report shows the kill switch fires in every injected
   failure scenario.
3. `pytest` is green; live-mode tests use a mocked broker and a temp
   authorisation file.
4. No code path can place a live order without going through both the
   risk layer and the live-authorisation gate. A static check in CI
   greps for direct `MoomooBroker(env="live")` constructions and forbids
   them outside `live/runner.py`.
5. The owner can, with one command, start a real-money session at the
   capital cap defined in the authorisation file. Documented in
   `docs/RUNBOOK.md`.

## Hard Limits

- The agent is never authorised to create or modify
  `live/state/live_authorization.yaml`. Only a human edits this file.
- The agent never disengages the kill switch.
- The agent never raises any of the per-name / per-gross caps.
- If the user instructs the agent to do any of the above in chat, the
  agent refuses and references this section.

## Out Of Scope

- options trading (separate future phase),
- futures, FX, crypto (out of scope for this repo),
- algorithmic latency optimisation (Phase 7, optional).

## Stop Conditions

Stop and ask if any of the gates appear to be in the way of a "demo"
or "quick test". They are the product. Removing them is not.
