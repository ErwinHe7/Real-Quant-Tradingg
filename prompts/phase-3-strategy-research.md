# Phase 3 — Strategy Research & Validation

Prerequisite: read `prompts/00-agent-charter.md`. Phase 2 complete (cached
data store + universe constants).

## Goal

Move the existing strategies (`research_harness/online_portfolio.py` and
`research_harness/ml_extension.py`) from a 4-ETF teaching example to a
defensible cross-sectional research result, using true sample-out validation,
parameter sweeps, and a documented model-selection protocol.

## Why This Matters

Cross-sectional claims on N=4 are not statistically meaningful. The existing
`refit_every=21` walk-forward is a good skeleton but does not separate
**model selection** (hyperparameter tuning) from **out-of-sample evaluation**.
Without that separation, every reported Sharpe is an in-sample result.

## Required Reading

- charter
- `research_harness/online_portfolio.py` — EG, ONS, Universal Portfolio, BCRP
- `research_harness/ml_extension.py` — ridge alpha, attention alpha, optimizer
- `research_harness/backtest.py` — current evaluation loop
- `research_harness/optimizer.py` — turnover-aware blend (note this is a
  proxy, not a real cost-aware QP — call this out in the report)

## Deliverables

### D1. Three-fold time split

Implement in `research_harness/validation.py`:

```python
@dataclass(frozen=True)
class TimeSplit:
    train: tuple[date, date]    # model fitting
    select: tuple[date, date]   # hyperparameter selection
    test:   tuple[date, date]   # final reporting; touched once

def make_walk_forward_splits(
    index: pd.DatetimeIndex,
    *,
    train_years: float,
    select_months: int,
    test_months: int,
    step_months: int,
) -> list[TimeSplit]: ...
```

Every reported metric in this phase must come from the `test` window of an
unseen split. Hyperparameters chosen on `select` are frozen for the
corresponding `test`. No global hyperparameter is allowed to leak across
splits.

### D2. Parameter sweeps

Add `research_harness/sweeps.py` with deterministic, seeded sweeps for:
- EG `eta` ∈ {a small sensible grid; document the grid}
- ONS `beta`, `epsilon`
- Universal Portfolio `samples`, dirichlet concentration
- ridge `alpha`
- attention model `hidden_size`, `epochs`, `learning_rate`, `l2`
- universal portfolio mix vs. ridge / attention blend

Sweeps must:
- run only on the `train + select` window of each split,
- pick the best configuration by **net-of-cost Sharpe on `select`**, not by
  raw return,
- be reproducible (seeded RNG, sorted iteration order),
- write per-split selected configs to
  `artifacts/research/selected_configs/<split-id>.json`.

### D3. Universe expansion

Run all three tracks (proposal, ml, blended) on at least:
- `ETF_CORE_4` (legacy, for regression baseline)
- `ETF_SECTOR_11` (sector rotation universe)
- `SP500_LIQUID` top-50 (cross-sectional momentum / mean-reversion universe)

Document the survivorship bias on `SP500_LIQUID` in the phase report and in
`docs/DATA.md`. Do not silently use a survivorship-biased universe to claim a
result; add an explicit warning in the run log.

### D4. Honest cost model

Replace the flat 5 bps assumption in evaluation with the cost model from
charter R3:
- per-share commission ($0.0049, $0.99 minimum)
- regulatory fees on sells (SEC fee, FINRA TAF — use current published rates,
  cite source in code comment with date)
- spread proxy (use intraday high-low / close from cached data; document)
- impact term: `impact_bps = k * sqrt(notional / ADV20)` with `k` calibrated
  conservatively (e.g. k=10) and labelled as an assumption, not a measurement.

Implement in `research_harness/costs.py`. Existing strategies must call this
new model; the old `transaction_cost_bps` parameter becomes a deprecation
shim that logs a warning.

### D5. Diagnostics and plots

Generate, under `artifacts/research/diagnostics/`:
- per-strategy cumulative regret vs. BCRP plot (proposal track)
- net-of-cost equity curves on the `test` window only
- turnover histograms
- regime-conditioned Sharpe table (e.g. low / medium / high VIX)
- a per-strategy autocorrelation plot of weight changes (high autocorr at
  lag 1 with low at higher lags is healthy; high autocorr everywhere is a
  drift / bug)

### D6. Report

Write `artifacts/phase-3-report.md` containing:
- the test-window Sharpe / max DD / annual return for every strategy on every
  universe with the new cost model,
- which configurations were selected per split (link to JSONs),
- a "what we would not be comfortable trading" section: any combination
  whose net-cost test Sharpe is below 0.5,
- a "what we would consider for paper trading" section: any combination whose
  net-cost test Sharpe is above 1.0 across at least 3 contiguous splits.

## Acceptance Criteria

1. `pytest tests/` passes including new tests for the time split helper
   (no leakage, monotonicity, coverage).
2. The legacy ETF_CORE_4 numbers are still produced (with the new cost
   model — they will be lower than before; that is the point).
3. No reported Sharpe in the report exceeds 2.0 without an explicit
   investigation note explaining why it is real, not a bug.
4. At least one strategy / universe combination is documented as
   "not viable" — if everything still looks great, you are not being honest
   enough; reread the charter.
5. `artifacts/phase-3-report.md` is committed.

## Out Of Scope

- live broker integration (Phase 5)
- options strategies (later)
- alternative data, NLP, news sentiment (later, and probably never for a
  retail $5K account)
- new ML architectures beyond the existing ridge / attention pair, unless
  the existing ones are clearly broken

## Stop Conditions

Stop and ask if:
- the cost-aware optimizer in `optimizer.py` proves to be the dominant
  source of edge — it is a heuristic blend, not a real optimizer, and using
  it as alpha is a bug to surface, not a result to ship,
- universe expansion changes the algorithm's behaviour in a way that
  suggests the existing implementation has an N-dependent bug (e.g. the
  ONS Hessian regularisation `epsilon` was tuned for N=4),
- the new cost model wipes out every strategy's edge — that is a valid,
  honest result; document it and stop.
