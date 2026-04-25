"""
Tests for live.broker.paper.PaperBroker — deterministic replay without network.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from live.broker.paper import PaperBroker
from live.broker.types import Order, OrderSide, OrderType


def _make_broker(tmp_path: Path, initial_cash: float = 10_000.0) -> PaperBroker:
    return PaperBroker(initial_cash=initial_cash, state_root=tmp_path)


# ---------------------------------------------------------------------------
# Basic fill tests
# ---------------------------------------------------------------------------

def test_market_buy_fills_immediately(tmp_path):
    broker = _make_broker(tmp_path)
    order = Order(symbol="SPY", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10)
    ack = broker.submit(order)
    from live.broker.types import OrderStatus
    assert ack.status == OrderStatus.FILLED
    # Cash should decrease
    assert broker.account().cash_usd < 10_000.0


def test_market_buy_creates_position(tmp_path):
    broker = _make_broker(tmp_path)
    order = Order(symbol="SPY", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=5)
    broker.submit(order)
    positions = broker.positions()
    assert "SPY" in positions
    assert positions["SPY"].quantity == pytest.approx(5.0)


def test_market_sell_reduces_position(tmp_path):
    broker = _make_broker(tmp_path)
    # Buy first
    broker.submit(Order(symbol="SPY", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10))
    # Sell 5
    broker.submit(Order(symbol="SPY", side=OrderSide.SELL, order_type=OrderType.MARKET, quantity=5))
    assert broker.positions()["SPY"].quantity == pytest.approx(5.0)


def test_market_sell_full_removes_position(tmp_path):
    broker = _make_broker(tmp_path)
    broker.submit(Order(symbol="SPY", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10))
    broker.submit(Order(symbol="SPY", side=OrderSide.SELL, order_type=OrderType.MARKET, quantity=10))
    assert "SPY" not in broker.positions()


def test_insufficient_cash_rejects_order(tmp_path):
    broker = _make_broker(tmp_path, initial_cash=10.0)  # only $10
    order = Order(symbol="SPY", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=1000)
    ack = broker.submit(order)
    from live.broker.types import OrderStatus
    assert ack.status == OrderStatus.REJECTED


def test_zero_quantity_rejects_order(tmp_path):
    broker = _make_broker(tmp_path)
    order = Order(symbol="SPY", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=0)
    ack = broker.submit(order)
    from live.broker.types import OrderStatus
    assert ack.status == OrderStatus.REJECTED


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def test_state_survives_restart(tmp_path):
    """
    Buy shares with Broker A, then create Broker B from the same state root.
    Broker B must see the same positions.
    """
    b1 = _make_broker(tmp_path)
    b1.submit(Order(symbol="SPY", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=3))
    cash_after = b1.account().cash_usd

    b2 = PaperBroker(state_root=tmp_path)  # "new process"
    assert "SPY" in b2.positions()
    assert b2.positions()["SPY"].quantity == pytest.approx(3.0)
    assert b2.account().cash_usd == pytest.approx(cash_after, rel=0.01)


# ---------------------------------------------------------------------------
# Fills log
# ---------------------------------------------------------------------------

def test_fills_since_returns_recent_fills(tmp_path):
    broker = _make_broker(tmp_path)
    t0 = datetime.utcnow()
    broker.submit(Order(symbol="SPY", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=5))
    fills = broker.fills_since(t0)
    assert len(fills) == 1
    assert fills[0].symbol == "SPY"


def test_fills_since_filters_old_fills(tmp_path):
    """fills_since should return empty if timestamp is in the future."""
    broker = _make_broker(tmp_path)
    broker.submit(Order(symbol="SPY", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=5))
    from datetime import timedelta
    future = datetime.utcnow() + timedelta(hours=1)
    fills = broker.fills_since(future)
    assert len(fills) == 0


# ---------------------------------------------------------------------------
# Limit orders
# ---------------------------------------------------------------------------

def test_limit_order_queued_not_immediately_filled(tmp_path):
    broker = _make_broker(tmp_path)
    from live.broker.types import OrderStatus
    order = Order(symbol="SPY", side=OrderSide.BUY, order_type=OrderType.LIMIT,
                  quantity=5, limit_price=99.0)
    ack = broker.submit(order)
    assert ack.status == OrderStatus.OPEN
    assert len(broker.open_orders()) == 1


def test_limit_order_fills_when_price_crosses(tmp_path):
    broker = _make_broker(tmp_path)
    order = Order(symbol="SPY", side=OrderSide.BUY, order_type=OrderType.LIMIT,
                  quantity=5, limit_price=105.0)
    broker.submit(order)

    # Simulate a bar where low=99 < limit_price=105 → fills
    bar = {"open": 108.0, "high": 110.0, "low": 99.0, "close": 107.0, "volume": 1_000_000}
    new_fills = broker.process_bar("SPY", bar)
    assert len(new_fills) == 1
    assert len(broker.open_orders()) == 0


def test_limit_order_does_not_fill_if_price_not_crossed(tmp_path):
    broker = _make_broker(tmp_path)
    order = Order(symbol="SPY", side=OrderSide.BUY, order_type=OrderType.LIMIT,
                  quantity=5, limit_price=98.0)
    broker.submit(order)

    bar = {"open": 100.0, "high": 102.0, "low": 100.0, "close": 101.0, "volume": 500_000}
    new_fills = broker.process_bar("SPY", bar)
    assert len(new_fills) == 0
    assert len(broker.open_orders()) == 1


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

def test_cancel_removes_open_order(tmp_path):
    broker = _make_broker(tmp_path)
    order = Order(symbol="SPY", side=OrderSide.BUY, order_type=OrderType.LIMIT,
                  quantity=5, limit_price=95.0)
    ack = broker.submit(order)
    broker.cancel(ack.order_id)
    assert len(broker.open_orders()) == 0
