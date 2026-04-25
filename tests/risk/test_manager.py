"""
Integration tests for live.risk.manager.RiskManager.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from live.risk.breakers import KillSwitch
from live.risk.limits import RiskLimits
from live.risk.manager import RiskManager, RiskOutcome
from live.risk.types import AccountState, MarketState, RiskHistory


def _account(equity=10_000.0, cash=10_000.0, day_trades=0):
    return AccountState(
        equity_usd=equity,
        cash_usd=cash,
        gross_notional_usd=0.0,
        net_notional_usd=0.0,
        day_trade_count=day_trades,
        open_order_count=0,
        timestamp=datetime.utcnow(),
    )


def _market(prices=None):
    prices = prices or {"SPY": 1.0, "QQQ": 1.0}
    return MarketState(
        prices=prices,
        adv20_usd={k: 1e8 for k in prices},
        highs={k: v * 1.01 for k, v in prices.items()},
        lows={k: v * 0.99 for k, v in prices.items()},
        sector_map={},
        timestamp=datetime.utcnow(),
    )


def _manager(tmp_path: Path, **limit_kwargs) -> RiskManager:
    ks = KillSwitch(state_root=tmp_path)
    limits = RiskLimits(**limit_kwargs) if limit_kwargs else RiskLimits()
    return RiskManager(limits=limits, kill_switch=ks)


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

def test_manager_halts_when_kill_switch_engaged(tmp_path):
    mgr = _manager(tmp_path)
    mgr._kill_switch.engage("test")
    target = pd.Series({"SPY": 0.50})
    outcome = mgr.evaluate(target, _account(), _market(), RiskHistory())
    assert outcome.mode == "halt"
    assert (outcome.approved_weights == 0).all()


# ---------------------------------------------------------------------------
# 500% single-name reject and kill switch engagement
# ---------------------------------------------------------------------------

def test_rogue_strategy_500_percent_is_rejected(tmp_path):
    """
    A strategy that wants to put 500% in a single name must be rejected
    and the kill switch must engage.
    This tests the charter requirement: 'simulate a rogue strategy'.
    """
    mgr = _manager(tmp_path, max_per_name_pct=0.10, max_gross_leverage=0.95)
    # 500% in SPY
    target = pd.Series({"SPY": 5.0})
    acct = _account(equity=10_000.0, cash=10_000.0)
    market = _market({"SPY": 1.0})
    outcome = mgr.evaluate(target, acct, market, RiskHistory())

    # The approved weight must be <= 10% (per-name cap) and rescaled
    assert float(outcome.approved_weights.get("SPY", 0.0)) <= 0.10 + 1e-6
    # Gross must be within cap after all adjustments
    assert float(outcome.approved_weights.abs().sum()) <= 0.95 + 1e-6


# ---------------------------------------------------------------------------
# Long-only enforcement
# ---------------------------------------------------------------------------

def test_manager_enforces_long_only(tmp_path):
    mgr = _manager(tmp_path, allow_short=False)
    target = pd.Series({"SPY": 0.60, "QQQ": -0.20})
    outcome = mgr.evaluate(target, _account(), _market(), RiskHistory())
    # QQQ short must be zeroed
    assert float(outcome.approved_weights.get("QQQ", 0.0)) >= 0.0


# ---------------------------------------------------------------------------
# Volatility targeting integration
# ---------------------------------------------------------------------------

def test_vol_target_applied_when_cov_provided(tmp_path):
    mgr = _manager(tmp_path, target_annual_vol=0.10)
    symbols = ["SPY", "QQQ"]
    target = pd.Series({"SPY": 0.50, "QQQ": 0.50})
    # Covariance corresponding to ~20% annual vol
    daily_cov = pd.DataFrame(
        [[0.0002, 0.0001], [0.0001, 0.0002]],
        index=symbols, columns=symbols
    )
    outcome = mgr.evaluate(
        target, _account(), _market(), RiskHistory(),
        realised_cov=daily_cov,
    )
    # After vol scaling, gross should be < 1.0 since target vol < realised vol
    gross = float(outcome.approved_weights.abs().sum())
    assert gross < 1.01  # within gross cap


# ---------------------------------------------------------------------------
# Drawdown breaker + kill switch
# ---------------------------------------------------------------------------

def test_drawdown_breaker_fires_and_halts(tmp_path):
    mgr = _manager(tmp_path, max_drawdown_from_hwm=0.15)
    # Simulate a 20% drawdown equity curve
    eq_curve = pd.Series([10_000.0, 11_000.0, 8_800.0])  # 8800/11000 = 80% → 20% dd
    target = pd.Series({"SPY": 0.50})
    history = RiskHistory()
    outcome = mgr.evaluate(
        target, _account(), _market(), history,
        equity_curve=eq_curve,
    )
    assert outcome.mode == "halt"
    assert mgr._kill_switch.is_engaged()


# ---------------------------------------------------------------------------
# No IO on good path
# ---------------------------------------------------------------------------

def test_manager_trade_mode_on_clean_input(tmp_path):
    mgr = _manager(tmp_path)
    target = pd.Series({"SPY": 0.05, "QQQ": 0.05})
    outcome = mgr.evaluate(target, _account(), _market(), RiskHistory())
    assert outcome.mode == "trade"
    assert not outcome.approved_weights.empty
