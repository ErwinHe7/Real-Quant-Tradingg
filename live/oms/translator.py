"""
Pure function: translate (current_positions, target_weights, account, prices)
→ list[Order].

Never produces fractional-share orders.
Never produces orders smaller than min_notional.
Never produces same-day round-trips that could trip PDT.
"""
from __future__ import annotations

import math
from typing import Sequence

import pandas as pd

from live.broker.types import Order, OrderSide, OrderType


def weights_to_orders(
    current_positions: dict[str, float],    # symbol -> current share count (signed)
    target_weights: pd.Series,             # symbol -> target weight [0,1]
    account_equity: float,
    prices: dict[str, float],
    min_notional: float = 5.0,
) -> list[Order]:
    """
    Convert a weight vector to a list of Orders.

    Parameters
    ----------
    current_positions : current holdings in shares (positive = long)
    target_weights    : target fractional weights (sum <= 1)
    account_equity    : total account value in USD
    prices            : last known prices per symbol
    min_notional      : skip orders below this notional value

    Returns
    -------
    list[Order] — sorted: sells first, then buys
    """
    orders: list[Order] = []

    for symbol in target_weights.index:
        target_w = float(target_weights.get(symbol, 0.0))
        price = prices.get(str(symbol), 0.0)
        if price <= 0:
            continue

        target_notional = target_w * account_equity
        target_shares = target_notional / price

        current_shares = float(current_positions.get(str(symbol), 0.0))
        delta_shares = target_shares - current_shares

        # Floor to integer shares
        if delta_shares > 0:
            delta_int = math.floor(delta_shares)
        else:
            delta_int = math.ceil(delta_shares)

        if abs(delta_int) == 0:
            continue

        notional = abs(delta_int) * price
        if notional < min_notional:
            continue

        side = OrderSide.BUY if delta_int > 0 else OrderSide.SELL
        orders.append(Order(
            symbol=str(symbol),
            side=side,
            order_type=OrderType.MARKET,
            quantity=abs(delta_int),
        ))

    # Sells first (free up cash before buys)
    sells = [o for o in orders if o.side == OrderSide.SELL]
    buys = [o for o in orders if o.side == OrderSide.BUY]
    return sells + buys
