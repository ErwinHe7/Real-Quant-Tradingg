"""
OMS Engine — single-threaded event loop.

Loop:
  1. tick: get market state from feed / broker
  2. compute target weights from strategy
  3. RiskManager.evaluate(...) → approved weights
  4. translate (current positions, approved weights, account) → diff orders
  5. submit to broker
  6. wait for fills, reconcile, persist
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from live.broker.base import Broker
from live.broker.types import OrderStatus
from live.oms.reconcile import reconcile
from live.oms.state import OMSState
from live.oms.translator import weights_to_orders
from live.risk.breakers import KillSwitch
from live.risk.manager import RiskManager
from live.risk.types import AccountState, MarketState, RiskHistory

logger = logging.getLogger(__name__)


StrategyFn = Callable[[], pd.Series]
"""A callable that returns a weight Series when called (no arguments)."""


class OMSEngine:
    """
    Single-threaded OMS engine.

    Parameters
    ----------
    strategy        : callable returning target weights pd.Series (symbol->weight)
    broker          : Broker implementation (paper or moomoo-paper)
    risk_manager    : RiskManager instance
    state_path      : path for persisting OMS state
    kill_switch     : shared KillSwitch instance
    tick_interval_s : seconds between ticks
    reconcile_every : number of ticks between reconciliation checks
    """

    def __init__(
        self,
        strategy: StrategyFn,
        broker: Broker,
        risk_manager: RiskManager,
        state_path: Path = Path("live/state/oms_state.json"),
        kill_switch: KillSwitch | None = None,
        tick_interval_s: int = 60 * 15,   # 15-minute default for swing strategies
        reconcile_every: int = 4,
    ) -> None:
        self._strategy = strategy
        self._broker = broker
        self._risk_manager = risk_manager
        self._state = OMSState(state_path)
        self._kill_switch = kill_switch or KillSwitch()
        self._tick_interval = tick_interval_s
        self._reconcile_every = reconcile_every
        self._tick_count = 0
        self._risk_history = RiskHistory()

    def run_session(self, max_ticks: int | None = None) -> None:
        """
        Run the OMS event loop.

        Stops when:
        - kill switch is engaged
        - max_ticks is reached (for testing)
        - KeyboardInterrupt
        """
        logger.info("OMS session started (broker env=%s)", self._broker.env())

        try:
            tick = 0
            while max_ticks is None or tick < max_ticks:
                if self._kill_switch.is_engaged():
                    logger.warning("Kill switch engaged — OMS halting")
                    break
                self._tick()
                tick += 1
                if max_ticks is None:
                    time.sleep(self._tick_interval)
        except KeyboardInterrupt:
            logger.info("OMS session interrupted by user")
        finally:
            logger.info("OMS session ended after %d ticks", self._tick_count)

    def _tick(self) -> None:
        self._tick_count += 1
        ts = datetime.utcnow()
        logger.info("Tick %d at %s", self._tick_count, ts.isoformat())

        # 1. Get account + market state
        account = self._broker.account()
        positions = self._broker.positions()

        # Build current weight vector from positions
        total_equity = account.equity_usd
        current_shares = {sym: pos.quantity for sym, pos in positions.items()}

        # 2. Get target weights from strategy
        try:
            target_weights = self._strategy()
        except Exception as exc:
            logger.error("Strategy error: %s", exc)
            return

        # Ensure target_weights is a pd.Series
        if not isinstance(target_weights, pd.Series):
            target_weights = pd.Series(target_weights)

        # 3. Risk evaluation
        prices = {sym: self._broker.quote(sym).last for sym in target_weights.index}
        market_state = MarketState(
            prices=prices,
            adv20_usd={sym: 1e7 for sym in target_weights.index},
            highs={sym: prices[sym] * 1.01 for sym in prices},
            lows={sym: prices[sym] * 0.99 for sym in prices},
            sector_map={},
            timestamp=ts,
        )
        account_state = AccountState(
            equity_usd=account.equity_usd,
            cash_usd=account.cash_usd,
            gross_notional_usd=0.0,
            net_notional_usd=0.0,
            day_trade_count=0,
            open_order_count=0,
            timestamp=ts,
        )

        outcome = self._risk_manager.evaluate(
            target_weights,
            account_state,
            market_state,
            self._risk_history,
        )

        if outcome.mode != "trade":
            logger.warning("Risk manager mode=%s — skipping orders", outcome.mode)
            self._state.record_tick(total_equity)
            return

        # 4. Translate weights to orders
        orders = weights_to_orders(
            current_positions=current_shares,
            target_weights=outcome.approved_weights,
            account_equity=total_equity,
            prices=prices,
        )

        if not orders:
            logger.info("No orders to place this tick")
            self._state.record_tick(total_equity)
            return

        # 5. Submit orders
        acks = []
        for order in orders:
            ack = self._broker.submit(order)
            acks.append(ack)
            logger.info("Submitted %s %s %s qty=%d → %s",
                        order.symbol, order.side.value, order.order_type.value,
                        order.quantity, ack.status.value)

        # 6. Reconcile (every N ticks)
        if self._tick_count % self._reconcile_every == 0:
            local_pos = {sym: pos.quantity for sym, pos in self._broker.positions().items()}
            reconcile(
                broker=self._broker,
                local_positions=local_pos,
                local_equity=total_equity,
                kill_switch=self._kill_switch,
            )

        # 7. Persist state
        self._state.last_weights = {str(k): float(v) for k, v in outcome.approved_weights.items()}
        self._state.record_tick(total_equity)
