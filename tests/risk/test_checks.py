"""
Tests for live.risk.checks — all pure-function pre-trade checks.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from live.risk.checks import (
    check_buying_power,
    check_gross_leverage,
    check_min_position_notional,
    check_net_leverage,
    check_pdt_day_trade_counter,
    check_per_name_weight,
    check_per_sector_weight,
    check_position_count,
    check_short_locate,
)
from live.risk.types import AccountState, CheckStatus, MarketState


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


def _market(prices=None, adv=None, highs=None, lows=None, sectors=None):
    prices = prices or {"SPY": 400.0, "QQQ": 350.0, "GLD": 180.0}
    return MarketState(
        prices=prices,
        adv20_usd=adv or {k: 1e8 for k in prices},
        highs=highs or {k: v * 1.01 for k, v in prices.items()},
        lows=lows or {k: v * 0.99 for k, v in prices.items()},
        sector_map=sectors or {},
        timestamp=datetime.utcnow(),
    )


# ---------------------------------------------------------------------------
# Per-name weight
# ---------------------------------------------------------------------------

def test_per_name_ok():
    target = pd.Series({"SPY": 0.05, "QQQ": 0.05})
    d = check_per_name_weight(target, max_pct=0.10)
    assert d.status == CheckStatus.OK


def test_per_name_reject():
    target = pd.Series({"SPY": 0.60, "QQQ": 0.40})
    d = check_per_name_weight(target, max_pct=0.10)
    assert d.status == CheckStatus.REJECT
    assert "SPY" in d.reason


# ---------------------------------------------------------------------------
# Per-sector weight
# ---------------------------------------------------------------------------

def test_per_sector_ok():
    target = pd.Series({"SPY": 0.30, "QQQ": 0.30})
    sectors = {"SPY": "Equity", "QQQ": "Equity"}
    d = check_per_sector_weight(target, sectors, max_pct=0.40)
    assert d.status == CheckStatus.REJECT  # 0.60 in Equity > 0.40


def test_per_sector_within_cap():
    target = pd.Series({"SPY": 0.20, "QQQ": 0.15})
    sectors = {"SPY": "Equity", "QQQ": "Equity"}
    d = check_per_sector_weight(target, sectors, max_pct=0.40)
    assert d.status == CheckStatus.OK


# ---------------------------------------------------------------------------
# Gross / net leverage
# ---------------------------------------------------------------------------

def test_gross_leverage_ok():
    target = pd.Series({"A": 0.50, "B": 0.45})
    assert check_gross_leverage(target, max_gross=1.0).status == CheckStatus.OK


def test_gross_leverage_reject():
    target = pd.Series({"A": 0.60, "B": 0.60})  # gross = 1.2
    d = check_gross_leverage(target, max_gross=1.0)
    assert d.status == CheckStatus.REJECT


def test_net_leverage_ok():
    target = pd.Series({"A": 0.50, "B": 0.50})
    assert check_net_leverage(target, max_net=1.0).status == CheckStatus.OK


def test_net_leverage_reject():
    target = pd.Series({"A": 1.20})  # net = 1.2
    assert check_net_leverage(target, max_net=1.0).status == CheckStatus.REJECT


# ---------------------------------------------------------------------------
# Position count
# ---------------------------------------------------------------------------

def test_position_count_ok():
    target = pd.Series({f"S{i}": 0.05 for i in range(10)})
    d = check_position_count(target, max_positions=20)
    assert d.status == CheckStatus.OK


def test_position_count_reject():
    target = pd.Series({f"S{i}": 0.01 for i in range(30)})
    d = check_position_count(target, max_positions=25)
    assert d.status == CheckStatus.REJECT


# ---------------------------------------------------------------------------
# Min notional
# ---------------------------------------------------------------------------

def test_min_notional_warn_for_tiny_positions():
    target = pd.Series({"SPY": 0.0001, "QQQ": 0.50})
    d = check_min_position_notional(target, equity=10_000.0, min_notional=5.0)
    # SPY: 0.0001 * 10000 = $1 < $5 → warn
    assert d.status == CheckStatus.WARN
    assert "SPY" in d.detail["symbols"]


def test_min_notional_ok_for_normal_positions():
    target = pd.Series({"SPY": 0.10, "QQQ": 0.10})
    d = check_min_position_notional(target, equity=10_000.0, min_notional=5.0)
    assert d.status == CheckStatus.OK


# ---------------------------------------------------------------------------
# PDT counter
# ---------------------------------------------------------------------------

def test_pdt_ok_below_limit():
    acct = _account(day_trades=2)
    target = pd.Series({"SPY": 0.50})
    current = pd.Series({"SPY": 0.0})
    d = check_pdt_day_trade_counter(acct, target, current, max_day_trades=3)
    assert d.status == CheckStatus.OK


def test_pdt_reject_at_limit():
    acct = _account(day_trades=3)
    target = pd.Series({"NEW": 0.50})  # new position
    current = pd.Series({"NEW": 0.0})
    d = check_pdt_day_trade_counter(acct, target, current, max_day_trades=3)
    assert d.status == CheckStatus.REJECT


# ---------------------------------------------------------------------------
# Buying power
# ---------------------------------------------------------------------------

def test_buying_power_ok():
    acct = _account(equity=10_000.0, cash=10_000.0)
    target = pd.Series({"SPY": 0.50})  # 50% of $10K = $5K needed
    market = _market({"SPY": 1.0})
    d = check_buying_power(target, acct, market)
    assert d.status == CheckStatus.OK


def test_buying_power_reject():
    acct = _account(equity=10_000.0, cash=100.0)
    target = pd.Series({"SPY": 0.90})  # needs $9K
    market = _market({"SPY": 1.0})
    d = check_buying_power(target, acct, market)
    assert d.status == CheckStatus.REJECT


# ---------------------------------------------------------------------------
# Short locate (long-only config)
# ---------------------------------------------------------------------------

def test_short_refused_long_only():
    target = pd.Series({"SPY": 0.50, "QQQ": -0.10})
    d = check_short_locate(target, allow_short=False)
    assert d.status == CheckStatus.REJECT


def test_short_ok_when_enabled():
    target = pd.Series({"SPY": 0.50, "QQQ": -0.10})
    d = check_short_locate(target, allow_short=True)
    assert d.status == CheckStatus.OK
