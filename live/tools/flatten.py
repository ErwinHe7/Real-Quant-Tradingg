"""
Flatten — liquidate all positions to cash.

Respects PDT and risk limits.  Sells all positions as market orders.

Usage:
    python -m live.tools.flatten --broker paper
    python -m live.tools.flatten --broker moomoo-paper
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Flatten all positions to cash")
    parser.add_argument("--broker", default="paper", choices=["paper", "moomoo-paper"])
    parser.add_argument("--state-root", default="live/state")
    args = parser.parse_args(argv)

    state_root = Path(args.state_root)

    if args.broker == "paper":
        from live.broker.paper import PaperBroker
        broker = PaperBroker(state_root=state_root)
    elif args.broker == "moomoo-paper":
        from live.broker.moomoo import MoomooBroker
        broker = MoomooBroker(env="paper")
    else:
        print(f"Unknown broker: {args.broker}", file=sys.stderr)
        return 1

    positions = broker.positions()
    if not positions:
        logger.info("No positions to flatten.")
        return 0

    logger.info("Flattening %d positions...", len(positions))

    from live.broker.types import Order, OrderSide, OrderType
    errors = []
    for sym, pos in positions.items():
        if pos.quantity <= 0:
            continue
        order = Order(
            symbol=sym,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=pos.quantity,
        )
        ack = broker.submit(order)
        logger.info("SELL %s qty=%d → %s", sym, pos.quantity, ack.status.value)
        if ack.status.value not in ("FILLED", "OPEN"):
            errors.append(f"{sym}: {ack.reason}")

    if errors:
        logger.error("Some orders failed: %s", errors)
        return 1

    account = broker.account()
    logger.info("Flatten complete. Cash: $%.2f, Equity: $%.2f",
                account.cash_usd, account.equity_usd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
