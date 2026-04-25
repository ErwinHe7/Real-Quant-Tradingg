# Risk Controls

## Architecture

The risk layer lives in `live/risk/` and is the only path between strategy
weight output and order placement.  No code outside this layer may place an
order without first calling `RiskManager.evaluate()`.

The manager is a **pure function** given its inputs — no hidden mutable
state.  All persistent state lives in `RiskHistory` (loaded and saved by the
caller) and in the file-backed `KillSwitch`.

## Checks and Defaults

| Check | Default | Rationale |
|-------|---------|-----------|
| Per-name weight cap | 10% | Retail diversification; no single name dominates |
| Per-sector weight cap | 40% | Sector concentration risk |
| Gross leverage cap | 95% | Effectively no leverage; leaves 5% cash buffer |
| Net leverage cap | 100% | Fully invested OK; no net short by default |
| Max active positions | 25 | Bounded by PDT and commission minimums |
| Min position notional | $5.00 | Below this, the $0.99 minimum commission wipes returns |
| PDT day-trade counter | 3 per 5 days | Pattern Day Trader rule (Reg T) |
| Short selling | Disabled | Long-only default; no locate infrastructure |
| Target annual vol | 12% | Conservative for $5K retail account |
| Drawdown from HWM | 15% | Halt threshold; requires human disengagement |
| Drawdown cool-off | 5 trading days | Before automatic re-arm |
| Daily loss limit | 3% of equity | Hard stop for a single day |
| Rogue concentration | >5× per-name cap | Engages kill switch immediately |

## Kill Switch

The kill switch is file-backed: the presence of `live/state/KILL` means all
trading is suspended.  The state survives process restarts.

- **Engage**: any process may call `KillSwitch.engage(reason)`.  The reason
  is written to the file and logged to `live/state/kill_switch_audit.jsonl`.
- **Disengage**: requires a human-supplied token.  The following tokens are
  rejected: AGENT, SYSTEM, AUTO, AUTOMATED, BOT.  Any other non-empty string
  is accepted.  This prevents the agent from autonomously re-enabling trading.

## Circuit Breakers

### DrawdownBreaker
Tracks the all-time high-water mark across equity curve values.  Fires when
current equity drops ≥ 15% below the HWM.  After firing, the drawdown breaker
engages the kill switch.  Disengaging the kill switch is a manual operation;
the drawdown breaker then enters a 5-day cool-off window before re-arming.

### DailyLossBreaker
Fires when the day's P&L falls below -3% of the start-of-day equity.  Resets
at midnight UTC.  Does not engage the kill switch — just halts that day's
trading.

## Volatility Targeting

`vol_target.scale_to_vol_target()` scales weights so the ex-ante portfolio
volatility equals `target_annual_vol = 12%`, using Ledoit-Wolf shrinkage on
the 60-day rolling covariance.  The gross leverage cap is applied after
scaling.

A 12% annualised vol target means the portfolio expects to gain or lose up to
~0.75% on a typical day.  For a $5K account this is a ~$37.50 daily swing —
consistent with the drawdown budget.

## Position Sizing (Fractional Kelly)

`sizing.fractional_kelly()` computes the Kelly-optimal position sizes at
fraction=0.25 of full Kelly.  Full Kelly assumes the expected-return estimate
is unbiased; for a retail signal, this assumption is optimistic.  A 25%
fraction dramatically reduces bet sizes and tail risk.

Per-name cap: 10%.  Gross leverage cap: 95%.

## Integration with Backtest

`research_harness/backtest.py` has a `use_risk_layer=True` flag.  When True,
weights from each strategy pass through `RiskManager.evaluate()` before P&L
is computed.  The legacy path (flag=False) preserves Phase 3 baseline numbers
for A/B comparison.
