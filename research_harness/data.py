from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import yfinance as yf


@dataclass
class MarketData:
  close: pd.DataFrame
  volume: pd.DataFrame
  returns: pd.DataFrame


def _extract_frame(raw: pd.DataFrame, field: str, symbols: tuple[str, ...]) -> pd.DataFrame:
  if isinstance(raw.columns, pd.MultiIndex):
    frame = raw[field].copy()
  else:
    frame = raw[[field]].copy()
    frame.columns = list(symbols)

  if isinstance(frame, pd.Series):
    frame = frame.to_frame(name=symbols[0])

  return frame.sort_index()


def download_market_data(
  symbols: tuple[str, ...],
  start: str,
  end: str | None,
) -> MarketData:
  raw = yf.download(
    list(symbols),
    start=start,
    end=end,
    auto_adjust=True,
    progress=False,
  )

  if raw.empty:
    raise RuntimeError('No market data returned. Check the symbols or date range.')

  close = _extract_frame(raw, 'Close', symbols).ffill().dropna()
  volume = _extract_frame(raw, 'Volume', symbols).reindex(close.index).ffill().fillna(0.0)
  returns = close.pct_change()

  return MarketData(close=close, volume=volume, returns=returns)
