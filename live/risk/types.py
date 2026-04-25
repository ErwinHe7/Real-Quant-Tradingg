"""
Shared data types for the risk layer.

All types are immutable (frozen dataclasses or NamedTuples).
No broker, feed, or IO dependencies here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Any


class CheckStatus(Enum):
    OK = "ok"
    WARN = "warn"       # allowed but flagged
    REJECT = "reject"   # order not allowed
    HALT = "halt"       # all trading suspended


@dataclass(frozen=True)
class RiskDecision:
    check_name: str
    status: CheckStatus
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status in (CheckStatus.OK, CheckStatus.WARN)

    @property
    def is_halt(self) -> bool:
        return self.status == CheckStatus.HALT


@dataclass(frozen=True)
class AccountState:
    equity_usd: float          # total account value
    cash_usd: float            # available cash (buying power)
    gross_notional_usd: float  # sum of abs(position) values
    net_notional_usd: float    # long - short notional
    day_trade_count: int       # PDT counter: day trades in rolling 5-day window
    open_order_count: int
    timestamp: datetime


@dataclass(frozen=True)
class MarketState:
    prices: dict[str, float]       # symbol -> last price
    adv20_usd: dict[str, float]    # symbol -> 20-day avg daily volume in USD
    highs: dict[str, float]        # symbol -> bar high (for spread proxy)
    lows: dict[str, float]         # symbol -> bar low
    sector_map: dict[str, str]     # symbol -> sector
    timestamp: datetime


@dataclass
class RiskHistory:
    """
    Mutable state that persists between evaluate() calls.

    Load from disk at startup; save after each call.  The RiskManager
    itself is stateless; all state lives here.
    """
    peak_equity: float = 0.0
    day_pnl: float = 0.0
    drawdown_breaker_engaged: bool = False
    daily_loss_breaker_engaged: bool = False
    drawdown_cool_off_until: datetime | None = None
    last_rebalance_date: date | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "peak_equity": self.peak_equity,
            "day_pnl": self.day_pnl,
            "drawdown_breaker_engaged": self.drawdown_breaker_engaged,
            "daily_loss_breaker_engaged": self.daily_loss_breaker_engaged,
            "drawdown_cool_off_until": (
                self.drawdown_cool_off_until.isoformat()
                if self.drawdown_cool_off_until else None
            ),
            "last_rebalance_date": (
                self.last_rebalance_date.isoformat()
                if self.last_rebalance_date else None
            ),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RiskHistory":
        from datetime import datetime as dt, date as dt_date
        obj = cls()
        obj.peak_equity = float(d.get("peak_equity", 0.0))
        obj.day_pnl = float(d.get("day_pnl", 0.0))
        obj.drawdown_breaker_engaged = bool(d.get("drawdown_breaker_engaged", False))
        obj.daily_loss_breaker_engaged = bool(d.get("daily_loss_breaker_engaged", False))
        cool_off = d.get("drawdown_cool_off_until")
        obj.drawdown_cool_off_until = dt.fromisoformat(cool_off) if cool_off else None
        last_reb = d.get("last_rebalance_date")
        obj.last_rebalance_date = dt_date.fromisoformat(last_reb) if last_reb else None
        return obj
