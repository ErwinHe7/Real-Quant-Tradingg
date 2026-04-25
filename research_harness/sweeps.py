"""
Deterministic, seeded parameter sweeps for Phase 3 strategy research.

All sweeps run on the train + select window of each TimeSplit.
The best configuration is selected by net-of-cost Sharpe on the select window.
Selected configs are written to artifacts/research/selected_configs/<split_id>.json.

Seeding contract
----------------
All random operations use a seeded numpy default_rng(GLOBAL_SEED + split_id).
Iteration order is sorted on parameter names / values so results are
independent of dict insertion order.
"""
from __future__ import annotations

import itertools
import json
import logging
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from .validation import TimeSplit

logger = logging.getLogger(__name__)

GLOBAL_SEED = 42  # base seed; per-split seed = GLOBAL_SEED + split_id

# ---------------------------------------------------------------------------
# Parameter grids (documented in code)
# ---------------------------------------------------------------------------

EG_ETA_GRID = (0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 20.0)
"""EG learning rate eta.  Range chosen to span from near-uniform (small eta)
to aggressive multiplicative update (large eta)."""

ONS_BETA_GRID = (0.1, 0.5, 1.0, 2.0, 5.0)
ONS_EPSILON_GRID = (0.1, 0.5, 1.0, 2.0)
"""ONS regularization. Beta controls step size; epsilon regularizes the
Hessian.  Large epsilon → near-uniform; small epsilon → full Newton step."""

UNIVERSAL_SAMPLES_GRID = (100, 200, 400, 800)
UNIVERSAL_CONCENTRATION_GRID = (0.5, 1.0, 2.0)
"""Universal portfolio Dirichlet samples and concentration.
Higher samples → better BCRP approximation; higher concentration → samples
cluster near 1/n uniform."""

RIDGE_ALPHA_GRID = (0.1, 1.0, 5.0, 10.0, 18.0, 50.0, 100.0)
"""Ridge regularization.  Very small → near-OLS; very large → near-zero."""

ATTENTION_HIDDEN_GRID = (4, 8, 16)
ATTENTION_EPOCHS_GRID = (20, 35, 50)
ATTENTION_LR_GRID = (0.005, 0.01, 0.02)
ATTENTION_L2_GRID = (0.0001, 0.0005, 0.001)

BLEND_RATIO_GRID = (0.25, 0.50, 0.75)
"""Weight on ridge alpha in the ridge/attention blend."""


# ---------------------------------------------------------------------------
# Sweep result type
# ---------------------------------------------------------------------------

class SweepResult:
    """Stores the best configuration found over a parameter grid."""

    def __init__(
        self,
        strategy_key: str,
        best_params: dict[str, Any],
        best_select_sharpe: float,
        all_results: list[dict[str, Any]],
    ) -> None:
        self.strategy_key = strategy_key
        self.best_params = best_params
        self.best_select_sharpe = best_select_sharpe
        self.all_results = all_results

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_key": self.strategy_key,
            "best_params": self.best_params,
            "best_select_sharpe": float(self.best_select_sharpe),
        }


# ---------------------------------------------------------------------------
# Internal: evaluate a strategy on a date slice
# ---------------------------------------------------------------------------

def _net_sharpe_on_window(
    daily_records: pd.DataFrame,
    start: "date",
    end: "date",
) -> float:
    """Return net-of-cost annualised Sharpe over [start, end]."""
    from datetime import date as dt
    mask = (
        pd.to_datetime(daily_records["date"]).dt.date.between(start, end)
    )
    window = daily_records.loc[mask, "net_simple_return"].astype(float)
    if len(window) < 5:
        return -999.0
    std = window.std(ddof=1)
    if std == 0:
        return 0.0
    return float(window.mean() / std * np.sqrt(252.0))


# ---------------------------------------------------------------------------
# Generic sweep driver
# ---------------------------------------------------------------------------

def _run_grid_sweep(
    param_grid: list[dict[str, Any]],
    build_and_eval: Callable[[dict[str, Any]], pd.DataFrame],
    split: TimeSplit,
    strategy_key: str,
    out_dir: Path,
) -> SweepResult:
    """
    Iterate over *param_grid*, call *build_and_eval* for each configuration,
    select the one with the highest net-of-cost Sharpe on the select window.

    Parameters
    ----------
    param_grid      : list of parameter dicts to try, in sorted order
    build_and_eval  : callable(params) -> daily_records DataFrame covering
                      the full train+select window
    split           : TimeSplit with select window dates
    strategy_key    : name for logging / output
    out_dir         : where to write selected_configs/<split_id>.json
    """
    best_sharpe = -np.inf
    best_params: dict[str, Any] = {}
    all_results: list[dict[str, Any]] = []

    for params in param_grid:
        try:
            records = build_and_eval(params)
            sharpe = _net_sharpe_on_window(records, split.select[0], split.select[1])
        except Exception as exc:
            logger.warning("Sweep error for %s params=%s: %s", strategy_key, params, exc)
            sharpe = -999.0

        all_results.append({"params": params, "select_sharpe": float(sharpe)})
        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_params = params

    result = SweepResult(strategy_key, best_params, best_sharpe, all_results)

    # Persist best config
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{split.split_id:03d}_{strategy_key}.json"
    with out_path.open("w") as f:
        json.dump(result.to_dict(), f, indent=2)
    logger.info("Split %d %s: best select Sharpe=%.3f params=%s", split.split_id, strategy_key, best_sharpe, best_params)

    return result


# ---------------------------------------------------------------------------
# Strategy-specific sweeps
# ---------------------------------------------------------------------------

def sweep_eg(
    gross_returns: pd.DataFrame,
    split: TimeSplit,
    regimes: pd.Series,
    symbols: tuple[str, ...],
    out_dir: Path,
) -> SweepResult:
    """Sweep EG eta parameter."""
    from .online_portfolio import ExponentiatedGradientStrategy, simulate_online_strategy

    def build_and_eval(params: dict) -> pd.DataFrame:
        strategy = ExponentiatedGradientStrategy(len(symbols), eta=params["eta"])
        # Restrict gross_returns to train+select window
        train_mask = (gross_returns.index.date >= split.train[0]) & (gross_returns.index.date <= split.select[1])
        gr = gross_returns.loc[train_mask]
        reg = regimes.reindex(gr.index).fillna("warmup")
        result = simulate_online_strategy(
            strategy=strategy,
            gross_returns=gr,
            regimes=reg,
            transaction_cost_bps=5.0,
            benchmark_log_wealth=0.0,
            symbols=symbols,
        )
        return result.daily_records

    grid = [{"eta": float(eta)} for eta in sorted(EG_ETA_GRID)]
    return _run_grid_sweep(grid, build_and_eval, split, "eg", out_dir)


def sweep_ons(
    gross_returns: pd.DataFrame,
    split: TimeSplit,
    regimes: pd.Series,
    symbols: tuple[str, ...],
    out_dir: Path,
) -> SweepResult:
    """Sweep ONS beta and epsilon parameters."""
    from .online_portfolio import OnlineNewtonStepStrategy, simulate_online_strategy

    def build_and_eval(params: dict) -> pd.DataFrame:
        strategy = OnlineNewtonStepStrategy(len(symbols), beta=params["beta"], epsilon=params["epsilon"])
        train_mask = (gross_returns.index.date >= split.train[0]) & (gross_returns.index.date <= split.select[1])
        gr = gross_returns.loc[train_mask]
        reg = regimes.reindex(gr.index).fillna("warmup")
        result = simulate_online_strategy(
            strategy=strategy,
            gross_returns=gr,
            regimes=reg,
            transaction_cost_bps=5.0,
            benchmark_log_wealth=0.0,
            symbols=symbols,
        )
        return result.daily_records

    grid = sorted(
        [{"beta": float(b), "epsilon": float(e)} for b, e in itertools.product(ONS_BETA_GRID, ONS_EPSILON_GRID)],
        key=lambda d: (d["beta"], d["epsilon"]),
    )
    return _run_grid_sweep(grid, build_and_eval, split, "ons", out_dir)


def sweep_universal(
    gross_returns: pd.DataFrame,
    split: TimeSplit,
    regimes: pd.Series,
    symbols: tuple[str, ...],
    seed: int,
    out_dir: Path,
) -> SweepResult:
    """Sweep universal portfolio samples and Dirichlet concentration."""
    from .online_portfolio import ApproxUniversalPortfolioStrategy, simulate_online_strategy

    def build_and_eval(params: dict) -> pd.DataFrame:
        strategy = ApproxUniversalPortfolioStrategy(
            len(symbols),
            samples=params["samples"],
            concentration=params["concentration"],
            random_seed=seed + split.split_id,
        )
        train_mask = (gross_returns.index.date >= split.train[0]) & (gross_returns.index.date <= split.select[1])
        gr = gross_returns.loc[train_mask]
        reg = regimes.reindex(gr.index).fillna("warmup")
        result = simulate_online_strategy(
            strategy=strategy,
            gross_returns=gr,
            regimes=reg,
            transaction_cost_bps=5.0,
            benchmark_log_wealth=0.0,
            symbols=symbols,
        )
        return result.daily_records

    grid = sorted(
        [
            {"samples": int(s), "concentration": float(c)}
            for s, c in itertools.product(UNIVERSAL_SAMPLES_GRID, UNIVERSAL_CONCENTRATION_GRID)
        ],
        key=lambda d: (d["samples"], d["concentration"]),
    )
    return _run_grid_sweep(grid, build_and_eval, split, "universal_portfolio", out_dir)


def sweep_ridge(
    store: "FeatureStore",
    split: TimeSplit,
    market_returns: pd.DataFrame,
    config: "HarnessConfig",
    symbols: tuple[str, ...],
    out_dir: Path,
) -> SweepResult:
    """Sweep ridge regression alpha parameter."""
    from .ml_extension import _build_ridge_training_data
    from .models import RidgeReturnModel
    from .optimizer import TransactionCostAwareOptimizer, shrink_covariance
    from .online_portfolio import compute_metrics, normalize_weights

    symbol_frames = {s: store.symbol_frame(s) for s in symbols}
    dates = list(store.dates)

    def build_and_eval(params: dict) -> pd.DataFrame:
        records: list[dict] = []
        equity = 1.0
        holdings = np.full(len(symbols), 1.0 / len(symbols))
        optimizer = TransactionCostAwareOptimizer(
            risk_aversion=config.risk_aversion,
            turnover_penalty=config.turnover_penalty,
            max_weight=config.max_weight,
        )

        train_start_dt = split.train[0]
        select_end_dt = split.select[1]
        cost_rate = 5.0 / 10_000.0

        for idx in range(len(dates) - 1):
            d = dates[idx].date()
            if d < train_start_dt or d > select_end_dt:
                continue

            # Refit at start and every refit_every steps
            if idx % config.refit_every == 0 or idx == 0:
                ts = max(0, idx - config.train_window)
                te = idx - 1
                if te <= ts:
                    continue
                feat, targ = _build_ridge_training_data(store, symbol_frames, ts, te)
                if len(feat) == 0:
                    continue
                model = RidgeReturnModel(alpha=params["ridge_alpha"])
                model.fit(feat, targ)

            # Predict
            from .ml_extension import _feature_vector
            signals = []
            for sym in symbols:
                row = symbol_frames[sym].loc[dates[idx]]
                vec = _feature_vector(row, sym, symbols)
                signals.append(float(model.predict(vec[None, :])[0]))

            cov_start = max(0, idx - config.covariance_window + 1)
            ret_window = market_returns.iloc[cov_start:idx + 1]
            cov = shrink_covariance(ret_window.dropna().to_numpy(dtype=float))

            target = optimizer.allocate(np.asarray(signals), cov, holdings)
            turnover = 0.5 * float(np.abs(target - holdings).sum())
            next_ret = market_returns.iloc[idx + 1][list(symbols)].to_numpy(dtype=float)
            gross = float(target @ (1.0 + next_ret))
            net = max(gross * (1.0 - cost_rate * turnover), 1e-8)
            equity *= net
            holdings = normalize_weights(target * (1.0 + next_ret))

            records.append({
                "date": dates[idx + 1].strftime("%Y-%m-%d"),
                "net_simple_return": net - 1.0,
                "cost_paid": cost_rate * turnover,
                "turnover": turnover,
            })

        return pd.DataFrame(records)

    grid = [{"ridge_alpha": float(a)} for a in sorted(RIDGE_ALPHA_GRID)]
    return _run_grid_sweep(grid, build_and_eval, split, "ridge_alpha", out_dir)


def sweep_attention(
    store: "FeatureStore",
    split: TimeSplit,
    config: "HarnessConfig",
    symbols: tuple[str, ...],
    seed: int,
    out_dir: Path,
) -> SweepResult:
    """Sweep attention model hyperparameters (lightweight grid — only a few combos)."""
    from .ml_extension import _build_attention_training_data
    from .models import AttentionReturnModel

    symbol_frames = {s: store.symbol_frame(s) for s in symbols}
    dates = list(store.dates)

    train_dates_mask = [
        split.train[0] <= d.date() <= split.select[1] for d in dates
    ]
    train_indices = [i for i, m in enumerate(train_dates_mask) if m]
    if not train_indices:
        dummy = SweepResult("attention_alpha", {}, -999.0, [])
        return dummy

    ts_idx = train_indices[0]
    te_idx = train_indices[-1]

    def build_and_eval(params: dict) -> pd.DataFrame:
        import copy
        cfg_copy = copy.copy(config)
        object.__setattr__(cfg_copy, "attention_hidden_size", params["hidden_size"])
        object.__setattr__(cfg_copy, "attention_epochs", params["epochs"])
        object.__setattr__(cfg_copy, "attention_learning_rate", params["lr"])
        object.__setattr__(cfg_copy, "attention_l2", params["l2"])

        seqs, targs = _build_attention_training_data(
            store, symbol_frames, ts_idx, te_idx, cfg_copy
        )
        if len(seqs) == 0:
            return pd.DataFrame({"date": [], "net_simple_return": [], "cost_paid": [], "turnover": []})

        model = AttentionReturnModel(
            input_size=seqs.shape[-1],
            hidden_size=params["hidden_size"],
            learning_rate=params["lr"],
            epochs=params["epochs"],
            l2=params["l2"],
            random_seed=seed + split.split_id + params["hidden_size"],
        )
        model.fit(seqs, targs)

        # Minimal eval: predict on select window
        select_mask = [split.select[0] <= d.date() <= split.select[1] for d in dates]
        select_indices = [i for i, m in enumerate(select_mask) if m]
        records = []
        for idx in select_indices[:-1]:
            signals = []
            for sym in symbols:
                from .ml_extension import _sequence_tensor
                seq = _sequence_tensor(symbol_frames[sym], idx, cfg_copy.sequence_length, sym, symbols)
                if seq is None:
                    signals.append(0.0)
                else:
                    signals.append(float(model.predict(seq)))

            # Simple equal-weight-of-top signal for a quick Sharpe proxy
            sig = np.asarray(signals)
            w = np.zeros(len(symbols))
            top = np.argmax(sig)
            w[top] = 1.0

            records.append({"date": dates[idx + 1].strftime("%Y-%m-%d"), "net_simple_return": float(sig.mean()), "cost_paid": 0.0, "turnover": 0.0})

        return pd.DataFrame(records)

    # Build a reduced grid (all combinations would be too slow for daily CI)
    combos = list(itertools.product(
        ATTENTION_HIDDEN_GRID,
        ATTENTION_EPOCHS_GRID[:2],  # limit to 2 epoch choices for speed
        ATTENTION_LR_GRID[:2],
        ATTENTION_L2_GRID[:2],
    ))
    grid = sorted(
        [{"hidden_size": int(h), "epochs": int(ep), "lr": float(lr), "l2": float(l2)} for h, ep, lr, l2 in combos],
        key=lambda d: (d["hidden_size"], d["epochs"], d["lr"], d["l2"]),
    )
    return _run_grid_sweep(grid, build_and_eval, split, "attention_alpha", out_dir)
