"""
PaperBroker — fills orders against cached OHLCV data with realistic slippage.

State is persisted under live/state/paper/ as JSON files, updated atomically.

Slippage model
--------------
  slippage_bps = min(5 + 8 * sqrt(notional / ADV20), 30)  bps

Fills
-----
  Market orders: fill at next-bar VWAP proxy (H+L+C)/3, or last ± half-spread
  Limit orders:  fill if bar range crosses the limit; partial at 1% of bar volume

PDT: Does not model PDT (that is the risk layer's job).  This broker
executes all submitted orders unless it lacks cash or the quantity is zero.
"""
from __future__ import annotations

import json
import math
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from .types import Account, Fill, Order, OrderAck, OrderSide, OrderStatus, OrderType, Position, Quote

_LOCK = threading.Lock()


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.json")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2, default=str)
    tmp.replace(path)


def _slippage_bps(notional_usd: float, adv20_usd: float) -> float:
    if adv20_usd <= 0:
        return 30.0
    participation = notional_usd / adv20_usd
    return min(5.0 + 8.0 * math.sqrt(participation), 30.0)


class PaperBroker:
    """
    Paper trading broker.  All state lives in <state_root>/paper/.

    Parameters
    ----------
    initial_cash    : starting cash (default $10,000)
    state_root      : directory for persistent state
    price_feed      : callable(symbol, date) -> {'open', 'high', 'low', 'close', 'volume'}
                      If None, fills at last known price (tests use this).
    adv_feed        : callable(symbol) -> 20-day ADV in USD
    """

    def __init__(
        self,
        initial_cash: float = 10_000.0,
        state_root: Path = Path("live/state"),
        price_feed=None,
        adv_feed=None,
    ) -> None:
        self._state_root = state_root
        self._account_path = state_root / "paper" / "account.json"
        self._fills_path = state_root / "paper" / "fills.jsonl"
        self._orders_path = state_root / "paper" / "orders.json"
        self._price_feed = price_feed
        self._adv_feed = adv_feed

        # Load or initialise state
        self._cash: float = initial_cash
        self._positions: dict[str, Position] = {}
        self._open_orders: dict[str, Order] = {}
        self._fills: list[Fill] = []
        self._load_state()

    # ------------------------------------------------------------------
    # Broker interface
    # ------------------------------------------------------------------

    def env(self) -> Literal["paper", "live"]:
        return "paper"

    def account(self) -> Account:
        equity = self._cash + sum(
            abs(p.quantity) * p.avg_cost_usd for p in self._positions.values()
        )
        return Account(
            equity_usd=equity,
            cash_usd=self._cash,
            positions=dict(self._positions),
            env="paper",
            timestamp=datetime.utcnow(),
        )

    def positions(self) -> dict[str, Position]:
        return dict(self._positions)

    def quote(self, symbol: str) -> Quote:
        """Return last known quote from the price feed, or a flat $100 stub."""
        if self._price_feed is not None:
            bar = self._price_feed(symbol)
            price = bar.get("close", 100.0)
            high = bar.get("high", price * 1.001)
            low = bar.get("low", price * 0.999)
        else:
            price = self._positions[symbol].avg_cost_usd if symbol in self._positions else 100.0
            high, low = price * 1.001, price * 0.999
        spread_half = (high - low) / 2.0
        return Quote(
            symbol=symbol,
            bid=price - spread_half,
            ask=price + spread_half,
            last=price,
            timestamp=datetime.utcnow(),
        )

    def submit(self, order: Order) -> OrderAck:
        """
        Submit an order for paper execution.

        Market orders fill immediately at current price + slippage.
        Limit orders are queued and filled on the next price update.
        """
        with _LOCK:
            if order.quantity <= 0:
                return OrderAck(order_id=order.order_id, status=OrderStatus.REJECTED, reason="quantity must be > 0")

            if order.order_type == OrderType.MARKET:
                fill = self._fill_market_order(order)
                if fill is None:
                    return OrderAck(order_id=order.order_id, status=OrderStatus.REJECTED, reason="insufficient cash")
                self._record_fill(fill)
                self._save_state()
                return OrderAck(order_id=order.order_id, status=OrderStatus.FILLED)
            else:
                # Limit order — queue it
                self._open_orders[order.order_id] = order
                self._save_state()
                return OrderAck(order_id=order.order_id, status=OrderStatus.OPEN)

    def cancel(self, order_id: str) -> None:
        with _LOCK:
            self._open_orders.pop(order_id, None)
            self._save_state()

    def open_orders(self) -> list[Order]:
        return list(self._open_orders.values())

    def fills_since(self, ts: datetime) -> list[Fill]:
        return [f for f in self._fills if f.fill_time >= ts]

    # ------------------------------------------------------------------
    # Price-tick processing (called by OMS on each bar)
    # ------------------------------------------------------------------

    def process_bar(self, symbol: str, bar: dict) -> list[Fill]:
        """
        Process pending limit orders against a new OHLCV bar.

        Returns a list of new fills.
        """
        new_fills = []
        with _LOCK:
            to_fill = []
            for order in list(self._open_orders.values()):
                if order.symbol != symbol:
                    continue
                if order.order_type == OrderType.LIMIT and order.limit_price is not None:
                    # Buy limit: fills if bar low <= limit_price
                    # Sell limit: fills if bar high >= limit_price
                    if order.side == OrderSide.BUY and bar["low"] <= order.limit_price:
                        to_fill.append((order, order.limit_price))
                    elif order.side == OrderSide.SELL and bar["high"] >= order.limit_price:
                        to_fill.append((order, order.limit_price))

            for order, fill_price in to_fill:
                fill = self._execute_at(order, fill_price, bar)
                if fill:
                    self._record_fill(fill)
                    del self._open_orders[order.order_id]
                    new_fills.append(fill)

            if new_fills:
                self._save_state()
        return new_fills

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fill_market_order(self, order: Order) -> Fill | None:
        """Fill a market order at VWAP proxy with slippage."""
        if self._price_feed is not None:
            bar = self._price_feed(order.symbol)
            vwap = (bar.get("high", 100.0) + bar.get("low", 100.0) + bar.get("close", 100.0)) / 3.0
            adv20 = self._adv_feed(order.symbol) if self._adv_feed else 1e7
        else:
            pos = self._positions.get(order.symbol)
            vwap = pos.avg_cost_usd if pos else 100.0
            adv20 = 1e7

        notional = order.quantity * vwap
        slip_bps = _slippage_bps(notional, adv20)
        slip = notional * (slip_bps / 10_000.0)

        if order.side == OrderSide.BUY:
            fill_price = vwap + slip / order.quantity
            cost = order.quantity * fill_price
            if cost > self._cash:
                return None
            self._cash -= cost
        else:
            fill_price = vwap - slip / order.quantity
            proceeds = order.quantity * fill_price
            self._cash += proceeds

        self._update_position(order.symbol, order.side, order.quantity, fill_price)

        from research_harness.costs import commission
        comm = commission(order.quantity, fill_price)
        self._cash -= comm

        return Fill(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            filled_quantity=order.quantity,
            fill_price=fill_price,
            fill_time=datetime.utcnow(),
            commission_usd=comm,
        )

    def _execute_at(self, order: Order, price: float, bar: dict) -> Fill | None:
        """Execute a queued limit order at *price*."""
        adv20 = self._adv_feed(order.symbol) if self._adv_feed else 1e7
        participation = 0.01  # fill at max 1% of bar volume
        bar_vol = bar.get("volume", 1e6)
        max_shares = bar_vol * participation
        qty = min(order.quantity, max_shares)
        if qty <= 0:
            return None

        notional = qty * price
        if order.side == OrderSide.BUY:
            if notional > self._cash:
                return None
            self._cash -= notional
        else:
            self._cash += notional

        self._update_position(order.symbol, order.side, qty, price)

        from research_harness.costs import commission
        comm = commission(qty, price)
        self._cash -= comm

        return Fill(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            filled_quantity=qty,
            fill_price=price,
            fill_time=datetime.utcnow(),
            commission_usd=comm,
        )

    def _update_position(self, symbol: str, side: OrderSide, qty: float, price: float) -> None:
        existing = self._positions.get(symbol)
        if side == OrderSide.BUY:
            if existing is None:
                self._positions[symbol] = Position(symbol=symbol, quantity=qty, avg_cost_usd=price)
            else:
                total_qty = existing.quantity + qty
                avg = (existing.quantity * existing.avg_cost_usd + qty * price) / total_qty
                self._positions[symbol] = Position(symbol=symbol, quantity=total_qty, avg_cost_usd=avg)
        else:  # SELL
            if existing is not None:
                remaining = existing.quantity - qty
                if abs(remaining) < 1e-4:
                    del self._positions[symbol]
                else:
                    self._positions[symbol] = Position(
                        symbol=symbol, quantity=remaining, avg_cost_usd=existing.avg_cost_usd
                    )

    def _record_fill(self, fill: Fill) -> None:
        self._fills.append(fill)
        self._fills_path.parent.mkdir(parents=True, exist_ok=True)
        with self._fills_path.open("a") as f:
            f.write(json.dumps({
                "order_id": fill.order_id,
                "symbol": fill.symbol,
                "side": fill.side.value,
                "filled_quantity": fill.filled_quantity,
                "fill_price": fill.fill_price,
                "fill_time": fill.fill_time.isoformat(),
                "commission_usd": fill.commission_usd,
            }) + "\n")

    def _save_state(self) -> None:
        _atomic_write(self._account_path, {
            "cash": self._cash,
            "positions": {
                sym: {"quantity": p.quantity, "avg_cost": p.avg_cost_usd}
                for sym, p in self._positions.items()
            },
        })

    def _load_state(self) -> None:
        if not self._account_path.exists():
            return
        with self._account_path.open() as f:
            data = json.load(f)
        self._cash = float(data.get("cash", self._cash))
        for sym, pd_data in data.get("positions", {}).items():
            self._positions[sym] = Position(
                symbol=sym,
                quantity=float(pd_data["quantity"]),
                avg_cost_usd=float(pd_data["avg_cost"]),
            )
