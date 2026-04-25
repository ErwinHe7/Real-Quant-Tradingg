"""
MoomooBroker — wraps the moomoo OpenAPI SDK for the paper (simulated) environment.

IMPORTANT:
  - env MUST be "paper" at construction time.  Passing env="live" raises
    LiveTradingNotAuthorizedError immediately.
  - `unlock_trade` is never called.  The moomoo skill explicitly forbids it.
    If any code path attempts to call it, this module raises.
  - All order submissions / fills are appended to ~/.futu_trade_audit.jsonl
    as required by the moomoo skill.

Moomoo API order-type mapping
------------------------------
  OrderType.MARKET → moomoo OrderType.MARKET
  OrderType.LIMIT  → moomoo OrderType.NORMAL (limit order)

Fill polling
------------
  fills_since(ts) polls moomoo's order_list_query(refresh_cache=True) for
  orders that transitioned to FILLED since ts.  Pushes are not used in this
  phase to keep the adapter simple.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Literal

from .types import Account, Fill, Order, OrderAck, OrderSide, OrderStatus, OrderType, Position, Quote

_AUDIT_PATH = Path.home() / ".futu_trade_audit.jsonl"


class LiveTradingNotAuthorizedError(RuntimeError):
    """Raised when live trading is requested without authorisation."""


def _append_audit(event: str, detail: dict) -> None:
    entry = json.dumps({
        "ts": datetime.utcnow().isoformat(),
        "event": event,
        **detail,
    })
    with _AUDIT_PATH.open("a") as f:
        f.write(entry + "\n")


class MoomooBroker:
    """
    Moomoo paper-trading broker adapter.

    Parameters
    ----------
    env         : must be "paper"; raises LiveTradingNotAuthorizedError if "live"
    host, port  : OpenD connection parameters
    """

    def __init__(
        self,
        env: Literal["paper", "live"] = "paper",
        host: str = "127.0.0.1",
        port: int = 11111,
    ) -> None:
        if env == "live":
            raise LiveTradingNotAuthorizedError(
                "Live trading is not authorized in Phase 5. "
                "Set env='paper' to use the simulated environment. "
                "Live gating is implemented in Phase 6."
            )
        self._env = "paper"
        self._host = host
        self._port = port
        self._ctx = None
        self._acc_id: int | None = None
        self._connect()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        try:
            import moomoo as mm
        except ImportError:
            raise ImportError(
                "moomoo-api is not installed. "
                "Install with: pip install 'moomoo-api>=10.4.6408'"
            )
        from research_harness.feed.moomoo_feed import OpenDUnavailable
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        try:
            sock.connect((self._host, self._port))
        except (ConnectionRefusedError, OSError) as exc:
            raise OpenDUnavailable(
                f"OpenD not reachable at {self._host}:{self._port}. "
                "Start OpenD first."
            ) from exc
        finally:
            sock.close()

        self._ctx = mm.OpenSecTradeContext(
            host=self._host,
            port=self._port,
            filter_trdmarket=mm.TrdMarket.US,
        )
        # Get the paper account ID
        ret, data = self._ctx.get_acc_list(trd_env=mm.TrdEnv.SIMULATE)
        if ret == mm.RET_OK and not data.empty:
            self._acc_id = int(data.iloc[0]["acc_id"])

    def close(self) -> None:
        if self._ctx is not None:
            try:
                self._ctx.close()
            except Exception:
                pass
            self._ctx = None

    def __enter__(self) -> "MoomooBroker":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Broker interface
    # ------------------------------------------------------------------

    def env(self) -> Literal["paper", "live"]:
        return "paper"

    def account(self) -> Account:
        import moomoo as mm
        ret, data = self._ctx.accinfo_query(
            trd_env=mm.TrdEnv.SIMULATE,
            acc_id=self._acc_id or 0,
            refresh_cache=True,
        )
        if ret != mm.RET_OK or data.empty:
            raise RuntimeError(f"accinfo_query failed: {data}")
        row = data.iloc[0]
        equity = float(row.get("total_assets", 0.0))
        cash = float(row.get("cash", 0.0))
        return Account(
            equity_usd=equity,
            cash_usd=cash,
            positions={},
            env="paper",
            timestamp=datetime.utcnow(),
        )

    def positions(self) -> dict[str, Position]:
        import moomoo as mm
        ret, data = self._ctx.position_list_query(
            trd_env=mm.TrdEnv.SIMULATE,
            acc_id=self._acc_id or 0,
            refresh_cache=True,
        )
        if ret != mm.RET_OK:
            return {}
        result = {}
        for _, row in data.iterrows():
            code = str(row.get("code", ""))
            sym = code.split(".")[-1] if "." in code else code
            result[sym] = Position(
                symbol=sym,
                quantity=float(row.get("qty", 0.0)),
                avg_cost_usd=float(row.get("cost_price", 0.0)),
            )
        return result

    def quote(self, symbol: str) -> Quote:
        import moomoo as mm
        code = f"US.{symbol}" if "." not in symbol else symbol
        ret, data = self._ctx.get_market_snapshot([code])
        if ret != mm.RET_OK or data.empty:
            raise KeyError(f"No snapshot for {symbol}")
        row = data.iloc[0]
        price = float(row.get("last_price", 0.0))
        return Quote(
            symbol=symbol,
            bid=float(row.get("bid_price", price)),
            ask=float(row.get("ask_price", price)),
            last=price,
            timestamp=datetime.utcnow(),
        )

    def submit(self, order: Order) -> OrderAck:
        """
        Submit order to moomoo paper environment.

        Never calls unlock_trade — paper trading does not require it.
        """
        import moomoo as mm

        # Map to moomoo types
        trd_side = mm.TrdSide.BUY if order.side == OrderSide.BUY else mm.TrdSide.SELL
        if order.order_type == OrderType.MARKET:
            mm_order_type = mm.OrderType.MARKET
            price = 0.0
        else:
            mm_order_type = mm.OrderType.NORMAL
            price = order.limit_price or 0.0

        code = f"US.{order.symbol}" if "." not in order.symbol else order.symbol

        ret, data = self._ctx.place_order(
            price=price,
            qty=order.quantity,
            code=code,
            trd_side=trd_side,
            order_type=mm_order_type,
            trd_env=mm.TrdEnv.SIMULATE,
            acc_id=self._acc_id or 0,
        )

        _append_audit("submit", {
            "order_id": order.order_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "order_type": order.order_type.value,
            "quantity": order.quantity,
            "limit_price": order.limit_price,
            "ret": ret,
        })

        if ret != mm.RET_OK:
            return OrderAck(order_id=order.order_id, status=OrderStatus.REJECTED, reason=str(data))

        broker_id = str(data.iloc[0].get("order_id", "")) if not data.empty else order.order_id
        return OrderAck(order_id=broker_id, status=OrderStatus.OPEN)

    def cancel(self, order_id: str) -> None:
        import moomoo as mm
        ret, data = self._ctx.modify_order(
            modify_order_op=mm.ModifyOrderOp.CANCEL,
            order_id=int(order_id),
            qty=0,
            price=0,
            trd_env=mm.TrdEnv.SIMULATE,
            acc_id=self._acc_id or 0,
        )
        _append_audit("cancel", {"order_id": order_id, "ret": ret})

    def open_orders(self) -> list[Order]:
        import moomoo as mm
        ret, data = self._ctx.order_list_query(
            trd_env=mm.TrdEnv.SIMULATE,
            acc_id=self._acc_id or 0,
            refresh_cache=True,
        )
        if ret != mm.RET_OK or data.empty:
            return []
        orders = []
        for _, row in data.iterrows():
            status_str = str(row.get("order_status", ""))
            if "FILLED" in status_str or "CANCEL" in status_str:
                continue
            code = str(row.get("code", ""))
            sym = code.split(".")[-1] if "." in code else code
            side = OrderSide.BUY if "BUY" in str(row.get("trd_side", "")) else OrderSide.SELL
            orders.append(Order(
                symbol=sym,
                side=side,
                order_type=OrderType.LIMIT,
                quantity=float(row.get("qty", 0.0)),
                limit_price=float(row.get("price", 0.0)),
                order_id=str(row.get("order_id", "")),
            ))
        return orders

    def fills_since(self, ts: datetime) -> list[Fill]:
        import moomoo as mm
        ret, data = self._ctx.order_list_query(
            trd_env=mm.TrdEnv.SIMULATE,
            acc_id=self._acc_id or 0,
            refresh_cache=True,
        )
        if ret != mm.RET_OK or data.empty:
            return []
        fills = []
        for _, row in data.iterrows():
            status_str = str(row.get("order_status", ""))
            if "FILLED" not in status_str:
                continue
            update_time_str = str(row.get("update_time", ""))
            try:
                fill_time = datetime.fromisoformat(update_time_str)
            except ValueError:
                fill_time = datetime.utcnow()
            if fill_time < ts:
                continue
            code = str(row.get("code", ""))
            sym = code.split(".")[-1] if "." in code else code
            side = OrderSide.BUY if "BUY" in str(row.get("trd_side", "")) else OrderSide.SELL
            fills.append(Fill(
                order_id=str(row.get("order_id", "")),
                symbol=sym,
                side=side,
                filled_quantity=float(row.get("dealt_qty", 0.0)),
                fill_price=float(row.get("dealt_avg_price", 0.0)),
                fill_time=fill_time,
            ))
        return fills
