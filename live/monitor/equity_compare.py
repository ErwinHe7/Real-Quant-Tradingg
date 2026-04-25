"""
Daily equity comparison: live vs paper vs backtest expectation.

If live equity is more than 2σ away from paper for 3 consecutive days,
engage the kill switch with reason 'live_paper_divergence'.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class EquityComparison:
    """
    Tracks live vs paper vs backtest equity daily.

    Parameters
    ----------
    backtest_mean_daily : expected daily return from backtest (e.g. 0.0004)
    backtest_std_daily  : std of daily return from backtest
    divergence_days     : consecutive days outside 2σ before triggering halt
    state_path          : path to persist comparison state
    """

    def __init__(
        self,
        backtest_mean_daily: float,
        backtest_std_daily: float,
        divergence_days: int = 3,
        state_path: Path = Path("live/state/equity_compare.json"),
    ) -> None:
        self._mean = backtest_mean_daily
        self._std = backtest_std_daily
        self._divergence_days = divergence_days
        self._state_path = state_path
        self._live_returns: list[float] = []
        self._paper_returns: list[float] = []
        self._prev_live_equity: float | None = None
        self._prev_paper_equity: float | None = None
        self._consecutive_diverge = 0
        self._load()

    def update(
        self,
        live_equity: float,
        paper_equity: float,
        kill_switch: "KillSwitch",
    ) -> dict:
        """
        Record today's equity for live and paper.  Check divergence.

        Call once per trading day after market close.
        """
        from live.risk.breakers import KillSwitch  # avoid circular import

        # Compute daily returns from equity deltas
        if self._prev_live_equity is not None and self._prev_live_equity > 0:
            live_ret = (live_equity / self._prev_live_equity) - 1.0
        else:
            live_ret = 0.0

        if self._prev_paper_equity is not None and self._prev_paper_equity > 0:
            paper_ret = (paper_equity / self._prev_paper_equity) - 1.0
        else:
            paper_ret = 0.0

        self._prev_live_equity = live_equity
        self._prev_paper_equity = paper_equity

        self._live_returns.append(live_ret)
        self._paper_returns.append(paper_ret)

        # Check if live is > 2σ from paper for consecutive days
        if self._std > 0:
            diff = abs(live_ret - paper_ret)
            sigma_2 = 2.0 * self._std
            if diff > sigma_2:
                self._consecutive_diverge += 1
            else:
                self._consecutive_diverge = 0

        report = {
            "live_equity": live_equity,
            "paper_equity": paper_equity,
            "live_daily_return": live_ret,
            "paper_daily_return": paper_ret,
            "consecutive_diverge_days": self._consecutive_diverge,
            "action": "ok",
        }

        if self._consecutive_diverge >= self._divergence_days:
            reason = (
                f"Live equity has diverged from paper by >2-sigma for "
                f"{self._consecutive_diverge} consecutive days. "
                "live_paper_divergence."
            )
            kill_switch.engage(reason)
            logger.error(reason)
            report["action"] = "kill_switch_engaged"
            report["reason"] = reason

        self._save()
        return report

    def _compute_equity_from_returns(self, returns: list[float], start: float) -> float:
        equity = start
        for r in returns:
            equity *= (1.0 + r)
        return equity

    def _compute_equity_from_returns(self, returns: list[float], start: float) -> float:
        equity = start
        for r in returns:
            equity *= (1.0 + r)
        return equity

    def _load(self) -> None:
        if not self._state_path.exists():
            return
        with self._state_path.open() as f:
            d = json.load(f)
        self._live_returns = d.get("live_returns", [])
        self._paper_returns = d.get("paper_returns", [])
        self._consecutive_diverge = int(d.get("consecutive_diverge", 0))
        self._prev_live_equity = d.get("prev_live_equity")
        self._prev_paper_equity = d.get("prev_paper_equity")

    def _save(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        with self._state_path.open("w") as f:
            json.dump({
                "live_returns": self._live_returns[-90:],
                "paper_returns": self._paper_returns[-90:],
                "consecutive_diverge": self._consecutive_diverge,
                "prev_live_equity": self._prev_live_equity,
                "prev_paper_equity": self._prev_paper_equity,
            }, f, indent=2)
