"""
Diagnostic plots and tables for Phase 3 strategy research.

Generates under artifacts/research/diagnostics/:
  - per-strategy cumulative regret vs BCRP (proposal track)
  - net-of-cost equity curves on test window only
  - turnover histograms
  - regime-conditioned Sharpe table (low/medium/high VIX proxy)
  - weight autocorrelation plots

All outputs use matplotlib with 'Agg' backend (no GUI required).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Use non-interactive backend so this works in headless environments
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _save(fig: "plt.Figure", path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved %s", path)


# ---------------------------------------------------------------------------
# D5a: Cumulative regret vs BCRP (proposal track)
# ---------------------------------------------------------------------------

def plot_regret_vs_bcrp(
    daily_records: pd.DataFrame,
    bcrp_log_wealth: float,
    out_dir: Path,
) -> None:
    """
    Plot cumulative log-wealth regret (BCRP - strategy) over time for all
    proposal-track strategies.
    """
    if daily_records.empty:
        return

    fig, ax = plt.subplots(figsize=(12, 5))
    strategies = daily_records["strategy"].unique()

    for strategy in sorted(strategies):
        if strategy == "bcrp":
            continue
        mask = daily_records["strategy"] == strategy
        subset = daily_records.loc[mask].copy()
        subset["date"] = pd.to_datetime(subset["date"])
        subset = subset.sort_values("date")

        log_wealth = np.log(subset["equity"].clip(lower=1e-8).to_numpy())
        strategy_final_lw = log_wealth[-1] if len(log_wealth) > 0 else 0.0
        regret = bcrp_log_wealth - strategy_final_lw

        cum_regret = bcrp_log_wealth - log_wealth
        ax.plot(subset["date"].to_numpy(), cum_regret, label=f"{strategy} (total regret={regret:.3f})")

    ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
    ax.set_title("Cumulative Regret vs BCRP (lower is better)")
    ax.set_xlabel("Date")
    ax.set_ylabel("Regret (BCRP log-wealth − strategy log-wealth)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    _save(fig, out_dir / "regret_vs_bcrp.png")


# ---------------------------------------------------------------------------
# D5b: Net-of-cost equity curves on test window
# ---------------------------------------------------------------------------

def plot_equity_curves(
    daily_records: pd.DataFrame,
    test_start: str | None,
    test_end: str | None,
    out_dir: Path,
    filename: str = "equity_curves_test_window.png",
) -> None:
    """
    Plot normalised equity curves (rebased to 1.0 at start of window) for
    all strategies in *daily_records*, optionally restricted to a test window.
    """
    if daily_records.empty:
        return

    df = daily_records.copy()
    df["date"] = pd.to_datetime(df["date"])
    if test_start:
        df = df[df["date"] >= test_start]
    if test_end:
        df = df[df["date"] <= test_end]
    if df.empty:
        return

    fig, ax = plt.subplots(figsize=(12, 5))
    strategies = df["strategy"].unique()

    for strategy in sorted(strategies):
        mask = df["strategy"] == strategy
        subset = df.loc[mask].sort_values("date")
        equity = subset["equity"].to_numpy(dtype=float)
        if len(equity) == 0:
            continue
        # Rebase to 1.0 at window start
        equity = equity / equity[0]
        ax.plot(subset["date"].to_numpy(), equity, label=strategy)

    ax.axhline(1.0, color="black", linewidth=0.8, linestyle="--")
    title = "Net-of-Cost Equity Curves"
    if test_start or test_end:
        title += f" (test window {test_start} – {test_end})"
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel("Normalised equity (rebased to 1.0 at start)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    _save(fig, out_dir / filename)


# ---------------------------------------------------------------------------
# D5c: Turnover histograms
# ---------------------------------------------------------------------------

def plot_turnover_histograms(
    daily_records: pd.DataFrame,
    out_dir: Path,
) -> None:
    """Plot per-strategy turnover distributions as overlapping histograms."""
    if daily_records.empty or "turnover" not in daily_records.columns:
        return

    strategies = sorted(daily_records["strategy"].unique())
    n = len(strategies)
    if n == 0:
        return

    fig, axes = plt.subplots(1, min(n, 4), figsize=(min(n, 4) * 4, 4), sharey=True)
    if n == 1:
        axes = [axes]

    for ax, strategy in zip(axes, strategies):
        mask = daily_records["strategy"] == strategy
        turnover = daily_records.loc[mask, "turnover"].astype(float)
        ax.hist(turnover, bins=30, edgecolor="white", alpha=0.8)
        ax.set_title(strategy, fontsize=9)
        ax.set_xlabel("Daily turnover")
        mean_to = turnover.mean()
        ax.axvline(mean_to, color="red", linewidth=1.0, linestyle="--", label=f"mean={mean_to:.3f}")
        ax.legend(fontsize=7)

    fig.suptitle("Turnover Histograms", fontsize=11)
    plt.tight_layout()
    _save(fig, out_dir / "turnover_histograms.png")


# ---------------------------------------------------------------------------
# D5d: Regime-conditioned Sharpe table
# ---------------------------------------------------------------------------

def regime_sharpe_table(
    daily_records: pd.DataFrame,
    out_dir: Path,
) -> pd.DataFrame:
    """
    Compute per-strategy Sharpe ratio split by volatility regime.

    Returns a DataFrame and saves it as a CSV and a matplotlib table image.
    """
    if daily_records.empty or "regime" not in daily_records.columns:
        return pd.DataFrame()

    rows = []
    for strategy in sorted(daily_records["strategy"].unique()):
        mask = daily_records["strategy"] == strategy
        subset = daily_records.loc[mask]
        row = {"strategy": strategy}
        for regime in ("low_vol", "high_vol", "warmup"):
            r = subset.loc[subset["regime"] == regime, "net_simple_return"].astype(float)
            if len(r) < 5:
                row[f"sharpe_{regime}"] = float("nan")
            else:
                std = r.std(ddof=1)
                row[f"sharpe_{regime}"] = float(r.mean() / std * np.sqrt(252.0)) if std > 0 else 0.0
        rows.append(row)

    table = pd.DataFrame(rows).set_index("strategy")
    out_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_dir / "regime_sharpe_table.csv")

    # Render as a simple image table
    fig, ax = plt.subplots(figsize=(8, max(2, len(rows) * 0.5 + 1)))
    ax.axis("off")
    col_labels = [c.replace("sharpe_", "") for c in table.columns]
    cell_text = [[f"{v:.2f}" if not np.isnan(v) else "N/A" for v in row] for _, row in table.iterrows()]
    tbl = ax.table(
        cellText=cell_text,
        rowLabels=list(table.index),
        colLabels=col_labels,
        cellLoc="center",
        loc="center",
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    ax.set_title("Regime-Conditioned Sharpe Ratios", fontsize=11, pad=20)
    _save(fig, out_dir / "regime_sharpe_table.png")
    return table


# ---------------------------------------------------------------------------
# D5e: Weight autocorrelation plots
# ---------------------------------------------------------------------------

def plot_weight_autocorrelation(
    weight_series: pd.Series,
    strategy_name: str,
    out_dir: Path,
    max_lag: int = 20,
) -> None:
    """
    Plot autocorrelation of weight changes for a single strategy.

    High autocorrelation at lag 1 with low at higher lags is healthy (trend
    following / mean reversion).  High autocorrelation everywhere suggests
    a drift or implementation bug.

    Parameters
    ----------
    weight_series : time series of a weight scalar (e.g. first asset weight)
    """
    if len(weight_series) < max_lag + 5:
        return

    changes = weight_series.diff().dropna()
    acf_vals = [1.0]
    for lag in range(1, max_lag + 1):
        shifted = changes.shift(lag).dropna()
        aligned = changes.loc[shifted.index]
        if len(aligned) < 5:
            acf_vals.append(float("nan"))
        else:
            corr = np.corrcoef(aligned.to_numpy(), shifted.to_numpy())[0, 1]
            acf_vals.append(float(corr))

    fig, ax = plt.subplots(figsize=(8, 4))
    lags = list(range(max_lag + 1))
    ax.bar(lags, acf_vals, color="steelblue", edgecolor="white")
    ax.axhline(0, color="black", linewidth=0.8)
    # Approximate 95% confidence band for white noise
    n = len(changes)
    band = 1.96 / np.sqrt(n)
    ax.axhline(band, color="red", linewidth=0.8, linestyle="--", label="95% CI")
    ax.axhline(-band, color="red", linewidth=0.8, linestyle="--")
    ax.set_title(f"Weight-Change Autocorrelation — {strategy_name}")
    ax.set_xlabel("Lag (days)")
    ax.set_ylabel("ACF")
    ax.legend(fontsize=8)
    ax.set_ylim(-1.1, 1.1)
    _save(fig, out_dir / f"acf_{strategy_name}.png")


# ---------------------------------------------------------------------------
# Convenience: run all diagnostics
# ---------------------------------------------------------------------------

def run_all_diagnostics(
    daily_records: pd.DataFrame,
    bcrp_log_wealth: float,
    out_dir: Path,
    test_start: str | None = None,
    test_end: str | None = None,
) -> None:
    """Generate all Phase 3 diagnostic outputs."""
    if daily_records.empty:
        logger.warning("No daily records provided; skipping diagnostics.")
        return

    plot_regret_vs_bcrp(daily_records, bcrp_log_wealth, out_dir)
    plot_equity_curves(daily_records, test_start, test_end, out_dir)
    plot_turnover_histograms(daily_records, out_dir)
    regime_sharpe_table(daily_records, out_dir)

    # Weight ACF: use the first asset's weight proxy (turnover as a scalar)
    for strategy in daily_records["strategy"].unique():
        mask = daily_records["strategy"] == strategy
        subset = daily_records.loc[mask].sort_values("date")
        if "turnover" in subset.columns:
            plot_weight_autocorrelation(
                subset["turnover"].astype(float).reset_index(drop=True),
                str(strategy),
                out_dir,
            )
