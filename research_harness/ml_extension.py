from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import HarnessConfig
from .features import FEATURE_COLUMNS, SEQUENCE_COLUMNS, FeatureStore
from .models import AttentionReturnModel, RidgeReturnModel
from .online_portfolio import StrategyDefinition, StrategyResult, compute_metrics, normalize_weights
from .optimizer import TransactionCostAwareOptimizer, shrink_covariance


@dataclass
class MLStrategyState:
  definition: StrategyDefinition
  equity: float
  current_holdings: np.ndarray
  latest_signals: dict[str, float]
  latest_weights: dict[str, float]
  daily_records: list[dict[str, object]]


def _one_hot(symbol: str, symbols: tuple[str, ...]) -> np.ndarray:
  return np.array([1.0 if candidate == symbol else 0.0 for candidate in symbols], dtype=float)


def _feature_vector(row: pd.Series, symbol: str, symbols: tuple[str, ...]) -> np.ndarray:
  return np.concatenate([row[list(FEATURE_COLUMNS)].to_numpy(dtype=float), _one_hot(symbol, symbols)])


def _sequence_tensor(
  symbol_frame: pd.DataFrame,
  date_index: int,
  sequence_length: int,
  symbol: str,
  symbols: tuple[str, ...],
) -> np.ndarray | None:
  if date_index < sequence_length - 1:
    return None

  window = symbol_frame.iloc[date_index - sequence_length + 1 : date_index + 1]
  values = window[list(SEQUENCE_COLUMNS)].to_numpy(dtype=float)
  if np.isnan(values).any():
    return None

  identity = np.repeat(_one_hot(symbol, symbols)[None, :], sequence_length, axis=0)
  return np.hstack([values, identity])


def _build_ridge_training_data(
  store: FeatureStore,
  symbol_frames: dict[str, pd.DataFrame],
  start_index: int,
  end_index: int,
) -> tuple[np.ndarray, np.ndarray]:
  features: list[np.ndarray] = []
  targets: list[float] = []

  for index in range(start_index, end_index + 1):
    for symbol in store.symbols:
      row = symbol_frames[symbol].iloc[index]
      if row[list(FEATURE_COLUMNS) + ['target_1d']].isna().any():
        continue
      features.append(_feature_vector(row, symbol, store.symbols))
      targets.append(float(row['target_1d']))

  return np.asarray(features), np.asarray(targets)


def _build_attention_training_data(
  store: FeatureStore,
  symbol_frames: dict[str, pd.DataFrame],
  start_index: int,
  end_index: int,
  config: HarnessConfig,
) -> tuple[np.ndarray, np.ndarray]:
  sequences: list[np.ndarray] = []
  targets: list[float] = []
  first_index = max(start_index, config.sequence_length - 1)

  for index in range(first_index, end_index + 1):
    for symbol in store.symbols:
      frame = symbol_frames[symbol]
      target = frame.iloc[index]['target_1d']
      sequence = _sequence_tensor(frame, index, config.sequence_length, symbol, store.symbols)
      if sequence is None or np.isnan(target):
        continue
      sequences.append(sequence)
      targets.append(float(target))

  if len(sequences) > config.attention_max_samples:
    rng = np.random.default_rng(config.random_seed + end_index)
    selected = rng.choice(len(sequences), size=config.attention_max_samples, replace=False)
    sequences = [sequences[idx] for idx in selected]
    targets = [targets[idx] for idx in selected]

  return np.asarray(sequences), np.asarray(targets)


def run_ml_extension_track(
  market_returns: pd.DataFrame,
  store: FeatureStore,
  config: HarnessConfig,
  regimes: pd.Series,
) -> dict[str, object]:
  dates = list(store.dates)
  symbol_frames = {symbol: store.symbol_frame(symbol) for symbol in config.symbols}
  optimizer = TransactionCostAwareOptimizer(
    risk_aversion=config.risk_aversion,
    turnover_penalty=config.turnover_penalty,
    max_weight=config.max_weight,
  )

  strategy_states = {
    'ridge_alpha': MLStrategyState(
      definition=StrategyDefinition(
        key='ridge_alpha',
        name='Rolling Ridge Alpha',
        family='Statistical Baseline',
        description='Cross-sectional ridge regression over transparent handcrafted features.',
        complexity='Refit every K days',
        theory='Industry-style linear alpha baseline with strong interpretability.',
        parameters={'alpha': config.ridge_alpha, 'train_window': config.train_window},
      ),
      equity=1.0,
      current_holdings=np.full(len(config.symbols), 1.0 / len(config.symbols)),
      latest_signals={},
      latest_weights={},
      daily_records=[],
    ),
    'attention_alpha': MLStrategyState(
      definition=StrategyDefinition(
        key='attention_alpha',
        name='Attention Sequence Alpha',
        family='Transformer Extension',
        description='Lightweight attention forecaster over recent feature sequences.',
        complexity='Refit every K days',
        theory='Transformer-style sequence model extension inspired by modern quant research.',
        parameters={'hidden_size': config.attention_hidden_size, 'sequence_length': config.sequence_length},
      ),
      equity=1.0,
      current_holdings=np.full(len(config.symbols), 1.0 / len(config.symbols)),
      latest_signals={},
      latest_weights={},
      daily_records=[],
    ),
    'blend_alpha': MLStrategyState(
      definition=StrategyDefinition(
        key='blend_alpha',
        name='Blended Alpha Portfolio',
        family='Industry Extension',
        description='Blend statistical and attention signals, then pass them through deterministic optimization.',
        complexity='Refit every K days',
        theory='Matches the research pattern used by many quant firms: alpha model plus optimizer plus risk control.',
        parameters={'blend': '50/50', 'risk_aversion': config.risk_aversion},
      ),
      equity=1.0,
      current_holdings=np.full(len(config.symbols), 1.0 / len(config.symbols)),
      latest_signals={},
      latest_weights={},
      daily_records=[],
    ),
  }

  earliest_feature_index = max(config.train_window, config.sequence_length, 30)
  ridge_model: RidgeReturnModel | None = None
  attention_model: AttentionReturnModel | None = None
  cost_rate = config.transaction_cost_bps / 10_000.0

  for current_index in range(earliest_feature_index, len(dates) - 1):
    if (
      ridge_model is None
      or attention_model is None
      or (current_index - earliest_feature_index) % config.refit_every == 0
    ):
      train_start = max(0, current_index - config.train_window)
      train_end = current_index - 1
      ridge_features, ridge_targets = _build_ridge_training_data(store, symbol_frames, train_start, train_end)
      attention_sequences, attention_targets = _build_attention_training_data(
        store,
        symbol_frames,
        train_start,
        train_end,
        config,
      )
      if len(ridge_features) == 0 or len(attention_sequences) == 0:
        continue

      ridge_model = RidgeReturnModel(alpha=config.ridge_alpha)
      ridge_model.fit(ridge_features, ridge_targets)

      attention_model = AttentionReturnModel(
        input_size=attention_sequences.shape[-1],
        hidden_size=config.attention_hidden_size,
        learning_rate=config.attention_learning_rate,
        epochs=config.attention_epochs,
        l2=config.attention_l2,
        random_seed=config.random_seed + current_index,
      )
      attention_model.fit(attention_sequences, attention_targets)

    current_date = dates[current_index]
    next_date = dates[current_index + 1]
    ridge_signals: list[float] = []
    attention_signals: list[float] = []

    for symbol in config.symbols:
      frame = symbol_frames[symbol]
      row = frame.loc[current_date]
      ridge_vector = _feature_vector(row, symbol, config.symbols)
      sequence = _sequence_tensor(frame, current_index, config.sequence_length, symbol, config.symbols)
      if sequence is None:
        raise RuntimeError(f'Not enough history to build a sequence for {symbol} on {current_date}.')
      ridge_signals.append(float(ridge_model.predict(ridge_vector[None, :])[0]))
      attention_signals.append(float(attention_model.predict(sequence)))

    signal_map = {
      'ridge_alpha': np.asarray(ridge_signals, dtype=float),
      'attention_alpha': np.asarray(attention_signals, dtype=float),
      'blend_alpha': 0.5 * (np.asarray(ridge_signals, dtype=float) + np.asarray(attention_signals, dtype=float)),
    }

    return_window = market_returns.iloc[max(1, current_index - config.covariance_window + 1) : current_index + 1]
    covariance = shrink_covariance(return_window.dropna().to_numpy(dtype=float))
    next_simple_returns = market_returns.loc[next_date, list(config.symbols)].to_numpy(dtype=float)
    next_gross_returns = 1.0 + next_simple_returns

    for name, expected_returns in signal_map.items():
      state = strategy_states[name]
      target_weights = optimizer.allocate(expected_returns, covariance, state.current_holdings)
      turnover = 0.5 * float(np.abs(target_weights - state.current_holdings).sum())
      gross_factor = float(target_weights @ next_gross_returns)
      net_factor = max(gross_factor * (1.0 - cost_rate * turnover), 1e-8)
      state.equity *= net_factor
      state.daily_records.append(
        {
          'date': next_date.strftime('%Y-%m-%d'),
          'decision_date': current_date.strftime('%Y-%m-%d'),
          'strategy': name,
          'track': 'ml_extension',
          'gross_factor': gross_factor,
          'net_simple_return': net_factor - 1.0,
          'turnover': turnover,
          'cost_paid': cost_rate * turnover,
          'equity': state.equity,
          'regime': regimes.loc[next_date],
          'top_symbol': config.symbols[int(np.argmax(target_weights))],
        }
      )
      state.latest_signals = {
        symbol: float(value) for symbol, value in zip(config.symbols, expected_returns, strict=False)
      }
      state.latest_weights = {
        symbol: float(value) for symbol, value in zip(config.symbols, target_weights, strict=False)
      }
      state.current_holdings = normalize_weights(target_weights * next_gross_returns)

  results: dict[str, StrategyResult] = {}
  for name, state in strategy_states.items():
    daily_frame = pd.DataFrame(state.daily_records)
    equity_curve = np.concatenate([[1.0], daily_frame['equity'].to_numpy(dtype=float)])
    results[name] = StrategyResult(
      definition=state.definition,
      metrics=compute_metrics(daily_frame, equity_curve),
      latest_weights=state.latest_weights,
      daily_records=daily_frame,
    )

  leader = max(results.values(), key=lambda item: item.metrics['annualized_return'])
  daily_performance = pd.concat(
    [result.daily_records for result in results.values()],
    ignore_index=True,
  )

  return {
    'track_key': 'ml_extension',
    'track_name': 'Industry Extension',
    'primary_metric': 'annualized_return',
    'leader': leader.definition.key,
    'strategies': results,
    'daily_performance': daily_performance,
  }
