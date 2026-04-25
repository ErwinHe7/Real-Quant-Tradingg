"""
Read-only moomoo realtime quote feed adapter.

This module wraps the moomoo OpenAPI Python SDK (package: moomoo-api) to
provide a typed, quote-only interface.  No order-placing methods are exposed
here.  Order placement is reserved for Phase 5.

Usage (requires OpenD running at host:port)::

    feed = MoomooQuoteFeed()
    feed.connect()
    feed.subscribe(["SPY", "QQQ"])
    quote = feed.latest_quote("SPY")
    feed.close()

If OpenD is not reachable, ``connect()`` raises ``OpenDUnavailable``; it does
not silently fall back or return None.
"""
from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field
from typing import Iterator, Sequence


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------

class OpenDUnavailable(RuntimeError):
    """Raised when the moomoo OpenD gateway cannot be reached."""


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Quote:
    symbol: str
    last_price: float
    bid: float
    ask: float
    volume: int       # shares traded today
    timestamp: float  # Unix epoch seconds (UTC)


@dataclass(frozen=True)
class Bar:
    symbol: str
    interval: str         # e.g. "1m", "5m", "1d"
    open: float
    high: float
    low: float
    close: float
    volume: int
    timestamp: float      # bar start time, Unix epoch seconds (UTC)


# ---------------------------------------------------------------------------
# Internal: lazy-import moomoo SDK
# ---------------------------------------------------------------------------

def _import_moomoo():
    """Import moomoo SDK, raising a clear ImportError if not installed."""
    try:
        import moomoo  # noqa: F401
        return moomoo
    except ImportError as exc:
        raise ImportError(
            "moomoo-api is not installed. "
            "Install it with: pip install 'moomoo-api>=10.4.6408'"
        ) from exc


def _moomoo_symbol(symbol: str) -> str:
    """Convert bare ticker 'SPY' to moomoo format 'US.SPY'."""
    if "." in symbol:
        return symbol          # already fully qualified
    return f"US.{symbol}"


def _strip_prefix(code: str) -> str:
    """'US.SPY' -> 'SPY'."""
    if "." in code:
        return code.split(".", 1)[1]
    return code


# ---------------------------------------------------------------------------
# Feed class
# ---------------------------------------------------------------------------

class MoomooQuoteFeed:
    """
    Read-only realtime quote feed backed by moomoo OpenD.

    Thread safety: not thread-safe; instantiate one per thread if needed.

    Parameters
    ----------
    host : OpenD host (default 127.0.0.1)
    port : OpenD port (default 11111)
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 11111) -> None:
        self._host = host
        self._port = port
        self._ctx = None          # OpenQuoteContext
        self._subscribed: set[str] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """
        Open a connection to OpenD.

        Raises
        ------
        OpenDUnavailable
            If the TCP port is not reachable within 2 seconds.
        ImportError
            If the moomoo-api package is not installed.
        """
        self._check_opend_reachable()
        mm = _import_moomoo()

        try:
            self._ctx = mm.OpenQuoteContext(host=self._host, port=self._port)
        except Exception as exc:
            raise OpenDUnavailable(
                f"Could not open moomoo quote context at "
                f"{self._host}:{self._port}: {exc}"
            ) from exc

    def close(self) -> None:
        """Close the quote context."""
        if self._ctx is not None:
            try:
                self._ctx.close()
            except Exception:
                pass
            self._ctx = None
        self._subscribed.clear()

    def __enter__(self) -> "MoomooQuoteFeed":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def subscribe(self, symbols: Sequence[str]) -> None:
        """
        Subscribe to realtime QUOTE updates for the given symbols.

        Parameters
        ----------
        symbols : bare tickers like ['SPY', 'QQQ'] or prefixed 'US.SPY'
        """
        self._require_connected()
        mm = _import_moomoo()

        codes = [_moomoo_symbol(s) for s in symbols]
        ret, msg = self._ctx.subscribe(codes, [mm.SubType.QUOTE], subscribe_push=False)
        if ret != mm.RET_OK:
            raise RuntimeError(f"moomoo subscribe failed: {msg}")
        self._subscribed.update(codes)

    # ------------------------------------------------------------------
    # Snapshot queries
    # ------------------------------------------------------------------

    def latest_quote(self, symbol: str) -> Quote:
        """
        Return the latest snapshot quote for *symbol*.

        Parameters
        ----------
        symbol : bare ticker 'SPY' or prefixed 'US.SPY'

        Returns
        -------
        Quote

        Raises
        ------
        OpenDUnavailable
            If not connected.
        KeyError
            If the snapshot is empty for this symbol.
        """
        self._require_connected()
        mm = _import_moomoo()

        code = _moomoo_symbol(symbol)
        ret, df = self._ctx.get_market_snapshot([code])
        if ret != mm.RET_OK or df.empty:
            raise KeyError(f"No snapshot available for {symbol}: {df}")

        row = df.iloc[0]
        return Quote(
            symbol=_strip_prefix(str(row.get("code", code))),
            last_price=float(row.get("last_price", 0.0)),
            bid=float(row.get("bid_price", 0.0)),
            ask=float(row.get("ask_price", 0.0)),
            volume=int(row.get("volume", 0)),
            timestamp=time.time(),
        )

    # ------------------------------------------------------------------
    # Streaming bar generator (blocking)
    # ------------------------------------------------------------------

    def stream_bars(self, symbols: Sequence[str], interval: str) -> Iterator[Bar]:
        """
        Yield Bar objects as they arrive from OpenD.

        This is a blocking generator; call it in a dedicated thread.  It
        subscribes to the appropriate K-line type and polls the API.

        Parameters
        ----------
        symbols  : list of tickers
        interval : '1m', '5m', '15m', '30m', '60m', '1d', etc.

        Yields
        ------
        Bar

        Notes
        -----
        This is a simplified polling implementation; a production version
        would use moomoo push handlers.  Suitable for research use only.
        """
        self._require_connected()
        mm = _import_moomoo()

        ktype_map = {
            "1m": mm.KLType.K_1M,
            "5m": mm.KLType.K_5M,
            "15m": mm.KLType.K_15M,
            "30m": mm.KLType.K_30M,
            "60m": mm.KLType.K_60M,
            "1d": mm.KLType.K_DAY,
            "1w": mm.KLType.K_WEEK,
        }
        ktype = ktype_map.get(interval)
        if ktype is None:
            raise ValueError(
                f"Unsupported interval '{interval}'. "
                f"Supported: {list(ktype_map)}"
            )

        codes = [_moomoo_symbol(s) for s in symbols]

        poll_seconds = {
            "1m": 30,
            "5m": 60,
            "15m": 120,
            "30m": 240,
            "60m": 480,
            "1d": 3600,
            "1w": 3600,
        }.get(interval, 60)

        seen_times: dict[str, float] = {}

        while True:
            for code in codes:
                ret, df = self._ctx.get_cur_kline(code, 1, ktype, mm.AuType.QFQ)
                if ret != mm.RET_OK or df.empty:
                    continue
                row = df.iloc[-1]
                ts = float(pd.Timestamp(row.get("time_key", "")).timestamp()) if hasattr(row, "get") else time.time()
                if seen_times.get(code) == ts:
                    continue
                seen_times[code] = ts
                yield Bar(
                    symbol=_strip_prefix(code),
                    interval=interval,
                    open=float(row.get("open", 0.0)),
                    high=float(row.get("high", 0.0)),
                    low=float(row.get("low", 0.0)),
                    close=float(row.get("close", 0.0)),
                    volume=int(row.get("volume", 0)),
                    timestamp=ts,
                )
            time.sleep(poll_seconds)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _require_connected(self) -> None:
        if self._ctx is None:
            raise OpenDUnavailable(
                "Not connected. Call connect() before using the feed."
            )

    def _check_opend_reachable(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        try:
            sock.connect((self._host, self._port))
        except (ConnectionRefusedError, OSError) as exc:
            raise OpenDUnavailable(
                f"OpenD is not reachable at {self._host}:{self._port}. "
                "Please start the moomoo OpenD application first."
            ) from exc
        finally:
            sock.close()


# Avoid top-level import of pandas — only needed in stream_bars
try:
    import pandas as pd
except ImportError:
    pass
