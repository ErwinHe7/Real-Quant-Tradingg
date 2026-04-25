"""
Broker-agnostic data types for the OMS layer.

All types are immutable.  No broker or feed dependencies.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal, Optional


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class Order:
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float          # shares
    limit_price: float | None = None   # None for market orders
    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)
    client_tag: str = ""    # optional tag for reconciliation


@dataclass(frozen=True)
class Fill:
    order_id: str
    symbol: str
    side: OrderSide
    filled_quantity: float
    fill_price: float
    fill_time: datetime
    commission_usd: float = 0.0


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: float          # positive = long, negative = short
    avg_cost_usd: float      # average cost basis per share


@dataclass(frozen=True)
class Account:
    equity_usd: float
    cash_usd: float
    positions: dict[str, Position]
    env: Literal["paper", "live"]
    timestamp: datetime


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: float
    ask: float
    last: float
    timestamp: datetime


@dataclass(frozen=True)
class OrderAck:
    order_id: str
    status: OrderStatus
    reason: str = ""    # rejection reason if status == REJECTED
