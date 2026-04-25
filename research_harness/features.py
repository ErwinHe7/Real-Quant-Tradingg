from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import MarketData

FEATURE_COLUMNS = (
  'ret_1d',
  'ret_5d',
  'ret_10d',
  'ret_20d',
  'vol_5d',
  'vol_20d',
  'drawdown_20d',
  'volume_ratio_5_20',
  'xsec_mom_5d',
  'xsec_reversal_1d',
)

SEQUENCE_COLUMNS = (
  'ret_1d',
  'ret_5d',
  'ret_10d',
  'vol_5d',
  'vol_20d',
  'drawdown_20d',
  'xsec_mom_5d',
  'volume_ratio_5_20',
)


def _row_zscore(frame: pd.DataFrame) -> pd.DataFrame:
  mean = frame.mean(axis=1)
  std = frame.std(axis=1).replace(0, np.nan)
  z = frame.sub(mean, axis=0).div(std, axis=0)
  return z.fillna(0.0)


@dataclass
class FeatureStore:
  panel: pd.DataFrame
  symbols: tuple[str, ...]

  @property
  def dates(self) -> pd.Index:
    return self.panel.index.get_level_values('date').unique().sort_values()

  def symbol_frame(self, symbol: str) -> pd.DataFrame:
    return self.panel.xs(symbol, level='symbol').sort_index()


def build_feature_store(market: MarketData, symbols: tuple[str, ...]) -> FeatureStore:
  close = market.close
  returns = market.returns
  volume = market.volume

  cross_momentum = _row_zscore(close.pct_change(5))
  cross_reversal = -_row_zscore(returns)
  volume_ratio = volume.rolling(5).mean().div(volume.rolling(20).mean()).sub(1.0)

  frames: list[pd.DataFrame] = []

  for symbol in symbols:
    frame = pd.DataFrame(index=close.index)
    frame['ret_1d'] = returns[symbol]
    frame['ret_5d'] = close[symbol].pct_change(5)
    frame['ret_10d'] = close[symbol].pct_change(10)
    frame['ret_20d'] = close[symbol].pct_change(20)
    frame['vol_5d'] = returns[symbol].rolling(5).std()
    frame['vol_20d'] = returns[symbol].rolling(20).std()
    frame['drawdown_20d'] = close[symbol].div(close[symbol].rolling(20).max()).sub(1.0)
    frame['volume_ratio_5_20'] = volume_ratio[symbol]
    frame['xsec_mom_5d'] = cross_momentum[symbol]
    frame['xsec_reversal_1d'] = cross_reversal[symbol]
    frame['target_1d'] = returns[symbol].shift(-1)
    frame['close'] = close[symbol]
    frames.append(frame)

  panel = (
    pd.concat(frames, keys=symbols, names=['symbol', 'date'])
    .swaplevel()
    .sort_index()
  )

  return FeatureStore(panel=panel, symbols=symbols)
