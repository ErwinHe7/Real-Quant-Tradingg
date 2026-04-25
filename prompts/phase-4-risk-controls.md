# Phase 4 — Risk Controls

Prerequisite: read `prompts/00-agent-charter.md`. Phase 3 complete (validated
strategies on a real universe with an honest cost model).

## Goal

Insert a deterministic risk layer between strategy weight output and order
generation. No order can be sent to a broker (paper or live) except through
this layer. The layer is a pure function of (current portfolio state, target
weights, market data, config) — no LLM, no randomness.

## Why This Matters

The existing harness has `max_weight=0.55` and that is the entire risk
"system". A retail account with PDT constraints, leverage limits, and
asymmetric tail risk needs at minimum:
- position size sanity (per-name and per-sector caps),
- volatility targeting (realised vol, not implied),
- drawdown circuit breaker,
- daily loss circuit breaker,
- a kill switch that survives process restart,
- pre-trade checks (cash, buying power, PDT counter, locate for shorts).

## Required Reading

- charter
- `research_harness/optimizer.py`
- `research_harness/backtest.py`
- `docs/ARCHITECTURE.md` (deterministic execution rule)

## Deliverables

### D1. Risk module

Create `live/risk/` (mirrors the future `live/` execution layer):

```text
live/risk/__init__.py
live/risk/limits.py          # static / per-strategy limits
live/risk/checks.py           # pure functions, no IO
live/risk/state.py            # persisted state (drawdown HWM, kill switch)
live/risk/manager.py          # orchestrates checks and transitions
```

Concrete checks (each a pure function returning `RiskDecision`):
- `check_per_name_weight(target, max_pct)`
- `check_per_sector_weight(target, sector_map, max_pct)`
- `check_gross_leverage(target, max_gross)`
- `check_net_leverage(target, max_net)`
- `check_position_count(target, max_positions)`
- `check_min_position_notional(target, equity, min_notional)` — avoids
  buying $4 of something with a $0.99 minimum commission
- `check_pdt_day_trade_counter(account_state)` — refuses to open a position
  that would be a same-day round-trip if the 3-in-5 counter is at limit
- `check_buying_power(target, account)`
- `check_short_locate(target, locate_provider)` — if shorting is allowed at
  all; default config is long-only

### D2. Volatility targeting

`live/risk/vol_target.py`:

```python
def scale_to_vol_target(
    weights: pd.Series,
    realised_cov: pd.DataFrame,
    target_annual_vol: float,
    max_gross: float,
) -> pd.Series:
    """
    Returns scaled weights so that ex-ante portfolio vol ≈ target,
    capped by max_gross.
    """
```

Use rolling realised covariance from cached daily returns (60-day window,
Ledoit-Wolf shrinkage, the same shrinkage path the existing optimizer
uses). Default target_annual_vol = 12% — explicitly conservative for $5K.

### D3. Circuit breakers

`live/risk/breakers.py`:

```python
class DrawdownBreaker:
    def update(self, equity_curve: pd.Series) -> BreakerState: ...
class DailyLossBreaker:
    def update(self, day_pnl: float, equity: float) -> BreakerState: ...
class KillSwitch:
    """File-backed, process-independent. Existence of
       <state_root>/KILL means: do nothing, do not place orders."""
    def is_engaged(self) -> bool: ...
    def engage(self, reason: str) -> None: ...
    def disengage(self, human_token: str) -> None: ...
```

Disengaging the kill switch requires a human-supplied token recorded in
`live/state/kill_switch_audit.jsonl`. The agent is not authorised to
disengage on its own; if it tries, the disengage call must reject the agent
identity.

### D4. Position sizing (Kelly fractional)

`live/risk/sizing.py`:

```python
def fractional_kelly(
    expected_returns: pd.Series,
    cov: pd.DataFrame,
    fraction: float = 0.25,
    cap_per_name: float = 0.10,
    cap_gross: float = 0.95,
) -> pd.Series: ...
```

Fractional, never full. Default fraction = 0.25. Cap per name 10% of equity
unless explicitly overridden in config. Document that Kelly assumes the
estimate of expected returns is unbiased — it is not, so the fraction must
be small.

### D5. Risk Manager orchestration

`live/risk/manager.py` exposes one method:

```python
def evaluate(
    target_weights: pd.Series,
    account_state: AccountState,
    market_state: MarketState,
    history: RiskHistory,
) -> RiskOutcome:
    """
    Returns:
      - approved_weights: pd.Series  (may be all-zero if a breaker fired)
      - decisions: list[RiskDecision] (per check, with reason)
      - mode: "trade" | "halt" | "liquidate"
    """
```

The manager is deterministic and pure given inputs. State changes (drawdown
HWM, breakers) live in `RiskHistory`, which is loaded and saved by callers.

### D6. Integration with backtest

Modify `research_harness/backtest.py` so each strategy's weights pass
through `RiskManager.evaluate` before P&L is computed. Add a config flag
to disable for legacy A/B comparison. The phase-3 baseline numbers should
still be reproducible by toggling that flag.

### D7. Tests

`tests/risk/` covering:
- every check function with green / yellow / red fixtures
- breaker hysteresis: after a drawdown breach, requires a documented
  cool-off window before re-arming
- kill switch survives process restart (write to disk, simulate fresh
  process by re-importing)
- fractional Kelly recovers correct sign and respects caps under various
  expected-return inputs
- integration test: a strategy that wants 200% gross is scaled down; a
  strategy that wants -100% net is rejected if config is long-only

## Acceptance Criteria

1. `pytest tests/risk/` passes.
2. With risk on, the phase-3 strategies have lower realised vol and
   smaller max DD than without; report the deltas in
   `artifacts/phase-4-report.md`.
3. The kill switch is provably effective: simulate a "rogue strategy"
   that wants to put 500% in a single name; the manager must reject it
   and engage the kill switch.
4. No broker code is added in this phase. The risk layer is broker-agnostic.
5. `docs/RISK.md` documents every check, every default, and explains why
   each default is conservative.

## Out Of Scope

- broker integration (Phase 5)
- live equity tracking against intraday prices (Phase 5)
- portfolio insurance / options-based hedging (later)

## Stop Conditions

Stop and ask if:
- a check would be too restrictive to allow any of the phase-3 strategies
  to trade — that is information, not a problem to engineer around,
- the kill switch design needs a feature that requires elevated process
  permissions — surface the design question, do not add a workaround.
