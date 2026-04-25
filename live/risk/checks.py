"""
Pure pre-trade check functions.

Every function returns a RiskDecision.  No IO, no state mutation.
All functions follow the signature:
    check_*(target_weights, ...) -> RiskDecision
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .types import AccountState, CheckStatus, MarketState, RiskDecision


def check_per_name_weight(
    target: pd.Series,
    max_pct: float = 0.10,
) -> RiskDecision:
    """No single name may exceed max_pct of the portfolio."""
    max_weight = float(target.max()) if len(target) > 0 else 0.0
    if max_weight > max_pct:
        worst = target.idxmax()
        return RiskDecision(
            check_name="per_name_weight",
            status=CheckStatus.REJECT,
            reason=f"'{worst}' weight {max_weight:.2%} exceeds cap {max_pct:.2%}",
            detail={"worst_symbol": str(worst), "weight": max_weight, "cap": max_pct},
        )
    return RiskDecision(check_name="per_name_weight", status=CheckStatus.OK, reason="ok")


def check_per_sector_weight(
    target: pd.Series,
    sector_map: dict[str, str],
    max_pct: float = 0.40,
) -> RiskDecision:
    """No single sector may exceed max_pct of gross notional."""
    if not sector_map:
        return RiskDecision(check_name="per_sector_weight", status=CheckStatus.OK, reason="no sector map provided")

    sector_weights: dict[str, float] = {}
    for symbol, weight in target.items():
        sector = sector_map.get(str(symbol), "Unknown")
        sector_weights[sector] = sector_weights.get(sector, 0.0) + abs(float(weight))

    for sector, weight in sector_weights.items():
        if weight > max_pct:
            return RiskDecision(
                check_name="per_sector_weight",
                status=CheckStatus.REJECT,
                reason=f"Sector '{sector}' weight {weight:.2%} exceeds cap {max_pct:.2%}",
                detail={"sector": sector, "weight": weight, "cap": max_pct},
            )
    return RiskDecision(check_name="per_sector_weight", status=CheckStatus.OK, reason="ok")


def check_gross_leverage(
    target: pd.Series,
    max_gross: float = 1.0,
) -> RiskDecision:
    """Gross leverage (sum of absolute weights) must not exceed max_gross."""
    gross = float(target.abs().sum())
    if gross > max_gross:
        return RiskDecision(
            check_name="gross_leverage",
            status=CheckStatus.REJECT,
            reason=f"Gross leverage {gross:.2f} exceeds cap {max_gross:.2f}",
            detail={"gross": gross, "cap": max_gross},
        )
    return RiskDecision(check_name="gross_leverage", status=CheckStatus.OK, reason="ok")


def check_net_leverage(
    target: pd.Series,
    max_net: float = 1.0,
) -> RiskDecision:
    """Net leverage (long - short) must not exceed max_net."""
    net = float(target.sum())
    if abs(net) > max_net:
        return RiskDecision(
            check_name="net_leverage",
            status=CheckStatus.REJECT,
            reason=f"Net leverage {net:.2f} (abs) exceeds cap {max_net:.2f}",
            detail={"net": net, "cap": max_net},
        )
    return RiskDecision(check_name="net_leverage", status=CheckStatus.OK, reason="ok")


def check_position_count(
    target: pd.Series,
    max_positions: int = 50,
) -> RiskDecision:
    """Active position count must not exceed max_positions."""
    n_active = int((target.abs() > 1e-4).sum())
    if n_active > max_positions:
        return RiskDecision(
            check_name="position_count",
            status=CheckStatus.REJECT,
            reason=f"Active positions {n_active} exceeds cap {max_positions}",
            detail={"n_active": n_active, "cap": max_positions},
        )
    return RiskDecision(check_name="position_count", status=CheckStatus.OK, reason="ok")


def check_min_position_notional(
    target: pd.Series,
    equity: float,
    min_notional: float = 5.0,
) -> RiskDecision:
    """
    Remove positions too small to be worth a $0.99 minimum commission.

    Returns OK but logs a detail list of symbols that would be zeroed.
    This is a WARN, not a REJECT — callers may zero out the tiny positions.
    """
    too_small = [
        str(sym) for sym, w in target.items()
        if 0 < abs(float(w)) * equity < min_notional
    ]
    if too_small:
        return RiskDecision(
            check_name="min_position_notional",
            status=CheckStatus.WARN,
            reason=f"{len(too_small)} positions below min notional ${min_notional:.2f}",
            detail={"symbols": too_small, "min_notional": min_notional},
        )
    return RiskDecision(check_name="min_position_notional", status=CheckStatus.OK, reason="ok")


def check_pdt_day_trade_counter(
    account_state: AccountState,
    target: pd.Series,
    current_positions: pd.Series,
    max_day_trades: int = 3,
) -> RiskDecision:
    """
    Refuse any trade that would constitute a same-day round-trip if the
    PDT day-trade counter is at its 3-in-5-day limit.

    Rule: a day trade occurs when a security is opened and closed on the
    same day.  We conservatively refuse any new opening order if the
    counter is at the limit.
    """
    if account_state.day_trade_count < max_day_trades:
        return RiskDecision(check_name="pdt_counter", status=CheckStatus.OK, reason="ok")

    # Check if any of the target changes constitute new openings
    opens = [
        str(sym) for sym in target.index
        if float(target.get(sym, 0.0)) > 0 and float(current_positions.get(sym, 0.0)) == 0.0
    ]
    if opens:
        return RiskDecision(
            check_name="pdt_counter",
            status=CheckStatus.REJECT,
            reason=(
                f"PDT counter at {account_state.day_trade_count}/{max_day_trades}; "
                f"refusing new position opens: {opens}"
            ),
            detail={"day_trade_count": account_state.day_trade_count, "would_open": opens},
        )
    return RiskDecision(check_name="pdt_counter", status=CheckStatus.OK, reason="ok")


def check_buying_power(
    target: pd.Series,
    account: AccountState,
    market: MarketState,
) -> RiskDecision:
    """
    Verify that the target portfolio is affordable given available cash.

    Only checks buy-side; assumes the system sells existing positions first.
    """
    if account.equity_usd <= 0:
        return RiskDecision(
            check_name="buying_power",
            status=CheckStatus.REJECT,
            reason="Account equity is zero or negative",
        )

    required_cash = sum(
        float(w) * market.prices.get(str(sym), 0.0) * account.equity_usd
        for sym, w in target.items()
        if float(w) > 0
    )
    if required_cash > account.cash_usd * 1.05:  # 5% buffer for rounding
        return RiskDecision(
            check_name="buying_power",
            status=CheckStatus.REJECT,
            reason=(
                f"Required cash ${required_cash:.2f} exceeds available ${account.cash_usd:.2f}"
            ),
            detail={"required": required_cash, "available": account.cash_usd},
        )
    return RiskDecision(check_name="buying_power", status=CheckStatus.OK, reason="ok")


def check_short_locate(
    target: pd.Series,
    allow_short: bool = False,
) -> RiskDecision:
    """
    Refuse short positions unless explicitly enabled in config.

    Default is long-only; this is appropriate for the retail $5K account.
    """
    shorts = [str(sym) for sym, w in target.items() if float(w) < 0]
    if shorts and not allow_short:
        return RiskDecision(
            check_name="short_locate",
            status=CheckStatus.REJECT,
            reason=f"Short positions not allowed (long-only config): {shorts}",
            detail={"short_symbols": shorts},
        )
    return RiskDecision(check_name="short_locate", status=CheckStatus.OK, reason="ok")
