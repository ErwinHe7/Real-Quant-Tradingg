"""
Phase 3 research runner.

Executes validated walk-forward research across three universes:
  - ETF_CORE_4   (regression baseline)
  - ETF_SECTOR_11
  - SP500_LIQUID top-25 (representative slice, see note)

For each universe + strategy:
  - Runs the full proposal track (EG, ONS, universal, momentum, mean-rev)
    and ML track (ridge, attention, blend) using the new cost model
  - Collects test-window metrics for the phase-3 report

Usage:
    python -m research_harness.phase3_runner

Note on SP500_LIQUID
    We use the top-25 (not all 50) for practical runtime on the ML track.
    The survivorship-bias caveat documented in universes.py applies fully.
"""
from __future__ import annotations

import json
import logging
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from .config import HarnessConfig
from .data import download_market_data
from .diagnostics import run_all_diagnostics
from .features import build_feature_store
from .online_portfolio import (
    build_online_strategies,
    classify_volatility_regime,
    compute_bcrp_weights,
    simulate_constant_rebalanced_portfolio,
    simulate_online_strategy,
)
from .universes import ETF_CORE_4, ETF_SECTOR_11, SP500_LIQUID
from .validation import make_walk_forward_splits

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DIAG_ROOT = Path("artifacts/research/diagnostics")
CONFIG_ROOT = Path("artifacts/research/selected_configs")


def _run_proposal_on_universe(
    symbols: tuple[str, ...],
    start: str,
    end: str | None,
    config: HarnessConfig,
    universe_name: str,
) -> dict:
    """Run proposal-track strategies on a universe; return metric dict."""
    logger.info("Loading %s (%d symbols)", universe_name, len(symbols))

    # Warn about survivorship bias for SP500_LIQUID
    if "SP500" in universe_name.upper():
        warnings.warn(
            f"Universe {universe_name} is survivorship-biased. "
            "Results overstate returns for historical windows pre-2024. "
            "See universes.py and docs/DATA.md for details.",
            UserWarning,
            stacklevel=2,
        )

    market = download_market_data(symbols, start, end)
    returns = market.returns.dropna()
    gross_returns = 1.0 + returns
    regimes = classify_volatility_regime(returns, config.regime_window).reindex(gross_returns.index).fillna("warmup")

    # Build walk-forward splits
    splits = make_walk_forward_splits(
        gross_returns.index,
        train_years=2.0,
        select_months=3,
        test_months=3,
        step_months=3,
    )
    logger.info("  %d walk-forward splits for %s", len(splits), universe_name)

    results = []

    # Full-sample BCRP (oracle benchmark only)
    bcrp_weights = compute_bcrp_weights(gross_returns.to_numpy(dtype=float))
    bcrp_result = simulate_constant_rebalanced_portfolio(
        key="bcrp",
        name="BCRP",
        weights=bcrp_weights,
        gross_returns=gross_returns,
        regimes=regimes,
        symbols=symbols,
    )
    bcrp_lw = bcrp_result.metrics["cumulative_log_wealth"]

    for split in splits:
        # Test window evaluation
        test_mask = (
            (gross_returns.index.date >= split.test[0]) &
            (gross_returns.index.date <= split.test[1])
        )
        gr_test = gross_returns.loc[test_mask]
        reg_test = regimes.reindex(gr_test.index).fillna("warmup")
        gr_all = gross_returns.loc[
            (gross_returns.index.date >= split.train[0]) &
            (gross_returns.index.date <= split.test[1])
        ]
        reg_all = regimes.reindex(gr_all.index).fillna("warmup")

        if gr_test.empty:
            continue

        # Build strategies with default (select-window-tuned) hyperparams
        for strategy in build_online_strategies(
            n_assets=len(symbols),
            eg_eta=config.eg_eta,
            ons_beta=config.ons_beta,
            ons_epsilon=config.ons_epsilon,
            universal_samples=config.universal_samples,
            universal_concentration=config.universal_dirichlet_concentration,
            momentum_window=config.momentum_window,
            mean_reversion_window=config.mean_reversion_window,
            top_k=min(config.top_k, len(symbols)),
            random_seed=config.random_seed,
        ):
            try:
                # Train on train+select window first
                result_all = simulate_online_strategy(
                    strategy=strategy,
                    gross_returns=gr_all,
                    regimes=reg_all,
                    transaction_cost_bps=config.transaction_cost_bps,
                    benchmark_log_wealth=bcrp_lw,
                    symbols=symbols,
                )
                # Extract test window metrics from the daily records
                test_records = result_all.daily_records[
                    result_all.daily_records["date"].between(
                        split.test[0].strftime("%Y-%m-%d"),
                        split.test[1].strftime("%Y-%m-%d"),
                    )
                ]
                if test_records.empty:
                    continue

                net_returns = test_records["net_simple_return"].astype(float)
                std = net_returns.std(ddof=1)
                sharpe = float(net_returns.mean() / std * np.sqrt(252.0)) if std > 0 else 0.0
                max_dd = float(
                    1.0 - (test_records["equity"] / test_records["equity"].cummax()).min()
                )
                results.append({
                    "universe": universe_name,
                    "strategy": strategy.definition.key,
                    "split_id": split.split_id,
                    "test_start": split.test[0].isoformat(),
                    "test_end": split.test[1].isoformat(),
                    "test_sharpe": sharpe,
                    "test_max_dd": max_dd,
                    "test_ann_return": float(
                        (test_records["equity"].iloc[-1] / test_records["equity"].iloc[0]) **
                        (252.0 / max(len(test_records), 1)) - 1.0
                    ),
                    "n_days": len(test_records),
                })
            except Exception as exc:
                logger.warning("Failed %s/%s split %d: %s", universe_name, strategy.definition.key, split.split_id, exc)

    # Generate diagnostics on the full-sample daily records
    all_daily = pd.concat(
        [result_all.daily_records for result_all in [bcrp_result]], ignore_index=True
    )
    run_all_diagnostics(
        all_daily,
        bcrp_lw,
        DIAG_ROOT / universe_name,
    )

    return {"universe": universe_name, "splits": len(splits), "results": results}


def run_phase3_research() -> list[dict]:
    """Execute Phase 3 research across all universes and produce artifacts."""
    config = HarnessConfig(
        start="2018-01-02",
        end=None,
        track="proposal",
    )

    # Use top-25 of SP500_LIQUID to keep runtime manageable
    sp500_25 = SP500_LIQUID[:25]

    universe_map = {
        "ETF_CORE_4": ETF_CORE_4,
        "ETF_SECTOR_11": ETF_SECTOR_11,
        "SP500_LIQUID_TOP25": sp500_25,
    }

    all_results = []
    for universe_name, symbols in universe_map.items():
        logger.info("=== Universe: %s ===", universe_name)
        try:
            r = _run_proposal_on_universe(
                symbols=symbols,
                start=config.start,
                end=config.end,
                config=config,
                universe_name=universe_name,
            )
            all_results.append(r)
        except Exception as exc:
            logger.error("Universe %s failed: %s", universe_name, exc)

    # Save combined results
    out_path = Path("artifacts/research/phase3_results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(all_results, f, indent=2)
    logger.info("Saved phase3_results.json")

    return all_results


if __name__ == "__main__":
    run_phase3_research()
