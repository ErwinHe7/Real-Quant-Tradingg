from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .data_store import load_prices as _load_prices_long, load_prices_wide


@dataclass
class MarketData:
  close: pd.DataFrame
  volume: pd.DataFrame
  returns: pd.DataFrame


def download_market_data(
  symbols: tuple[str, ...],
  start: str,
  end: str | None,
  *,
  cache_root: Path = Path("data/cache"),
  refresh: bool = False,
) -> MarketData:
  """
  Load market data for *symbols* over [start, end], backed by a local
  parquet cache.  On cache miss the data is downloaded from yfinance and
  stored for future runs; on cache hit the download is skipped.

  The returned MarketData uses **split-adjusted** close prices (adj_close)
  with point-in-time adjustments.  See data_store.py for the adjustment
  methodology.

  Parameters
  ----------
  symbols    : tuple of uppercase ticker strings
  start      : inclusive start date, 'YYYY-MM-DD'
  end        : inclusive end date, or None for today
  cache_root : root directory for parquet cache files
  refresh    : if True, force re-download and overwrite cache
  """
  long = _load_prices_long(
    symbols,
    start,
    end,
    source="yfinance",
    cache_root=cache_root,
    refresh=refresh,
  )

  if long.empty:
    raise RuntimeError(
      "No market data returned for any of the requested symbols. "
      "Check the symbols or date range."
    )

  close = load_prices_wide(
    symbols, start, end,
    field="adj_close",
    cache_root=cache_root,
    refresh=refresh,
  ).ffill().dropna()

  volume = (
    load_prices_wide(
      symbols, start, end,
      field="volume",
      cache_root=cache_root,
      refresh=refresh,
    )
    .reindex(close.index)
    .ffill()
    .fillna(0.0)
  )

  returns = close.pct_change()

  return MarketData(close=close, volume=volume, returns=returns)
