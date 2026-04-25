"""
Static risk limits configuration.

These are the conservative defaults for the retail $5K account.
Override per-strategy in config or via environment variables.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    """All limits in fraction of equity unless noted."""

    # Position limits
    max_per_name_pct: float = 0.10           # 10% max single name
    max_per_sector_pct: float = 0.40         # 40% max single sector
    max_gross_leverage: float = 0.95         # 95% gross (effectively no leverage)
    max_net_leverage: float = 1.00           # 100% net (fully invested OK)
    max_positions: int = 25                  # max active names

    # Order minimums
    min_position_notional_usd: float = 5.0  # below this, skip the order

    # PDT protection
    max_day_trades_per_5d: int = 3

    # Short selling
    allow_short: bool = False               # long-only by default

    # Volatility targeting
    target_annual_vol: float = 0.12         # 12% annualised portfolio vol

    # Drawdown circuit breaker
    max_drawdown_from_hwm: float = 0.15     # 15% drawdown from HWM → halt
    drawdown_cool_off_days: int = 5         # trading days before re-arming

    # Daily loss circuit breaker
    max_daily_loss_pct: float = 0.03        # 3% of equity in a single day → halt


DEFAULT_LIMITS = RiskLimits()
