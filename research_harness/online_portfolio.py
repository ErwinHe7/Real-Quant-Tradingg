from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def project_to_simplex(values: np.ndarray) -> np.ndarray:
  sorted_values = np.sort(values)[::-1]
  partial_sum = np.cumsum(sorted_values)
  rho = np.nonzero(sorted_values * np.arange(1, len(values) + 1) > (partial_sum - 1))[0]
  if len(rho) == 0:
    return np.full(len(values), 1.0 / len(values))
  threshold = (partial_sum[rho[-1]] - 1.0) / (rho[-1] + 1.0)
  projected = np.maximum(values - threshold, 0.0)
  total = projected.sum()
  if total <= 0:
    return np.full(len(values), 1.0 / len(values))
  return projected / total


def normalize_weights(values: np.ndarray) -> np.ndarray:
  clipped = np.clip(values, 0.0, None)
  total = clipped.sum()
  if total <= 0:
    return np.full(len(values), 1.0 / len(values))
  return clipped / total


def trailing_cumulative_return(window: np.ndarray) -> np.ndarray:
  return np.prod(window, axis=0) - 1.0


@dataclass(frozen=True)
class StrategyDefinition:
  key: str
  name: str
  family: str
  description: str
  complexity: str
  theory: str
  parameters: dict[str, float | int | str]


class OnlinePortfolioStrategy:
  definition: StrategyDefinition

  def __init__(self, definition: StrategyDefinition, n_assets: int) -> None:
    self.definition = definition
    self.n_assets = n_assets

  def allocate(self, history_gross_returns: np.ndarray) -> np.ndarray:
    raise NotImplementedError

  def update(self, chosen_weights: np.ndarray, realized_gross_returns: np.ndarray) -> None:
    return None


class EqualWeightStrategy(OnlinePortfolioStrategy):
  def __init__(self, n_assets: int) -> None:
    super().__init__(
      StrategyDefinition(
        key='equal_weight',
        name='Equal Weight (1/n)',
        family='Baseline',
        description='Uniform rebalancing sanity check and robust naive benchmark.',
        complexity='O(n)',
        theory='No regret guarantee; strong empirical baseline in allocation studies.',
        parameters={},
      ),
      n_assets,
    )

  def allocate(self, history_gross_returns: np.ndarray) -> np.ndarray:
    return np.full(self.n_assets, 1.0 / self.n_assets)


class ExponentiatedGradientStrategy(OnlinePortfolioStrategy):
  def __init__(self, n_assets: int, eta: float) -> None:
    super().__init__(
      StrategyDefinition(
        key='eg',
        name='Exponentiated Gradient',
        family='Online First Order',
        description='Multiplicative-weights portfolio update over the simplex.',
        complexity='O(n)',
        theory='Regret scales like O(sqrt(T log n)) against BCRP.',
        parameters={'eta': eta},
      ),
      n_assets,
    )
    self.eta = eta
    self.weights = np.full(n_assets, 1.0 / n_assets)

  def allocate(self, history_gross_returns: np.ndarray) -> np.ndarray:
    return self.weights.copy()

  def update(self, chosen_weights: np.ndarray, realized_gross_returns: np.ndarray) -> None:
    simple_returns = realized_gross_returns - 1.0
    self.weights = normalize_weights(chosen_weights * np.exp(self.eta * simple_returns))


class OnlineNewtonStepStrategy(OnlinePortfolioStrategy):
  def __init__(self, n_assets: int, beta: float, epsilon: float) -> None:
    super().__init__(
      StrategyDefinition(
        key='ons',
        name='Online Newton Step',
        family='Online Second Order',
        description='Second-order online update with curvature-aware adaptation.',
        complexity='O(n^2)',
        theory='For exp-concave log-wealth objectives, regret scales like O(n log T).',
        parameters={'beta': beta, 'epsilon': epsilon},
      ),
      n_assets,
    )
    self.beta = beta
    self.weights = np.full(n_assets, 1.0 / n_assets)
    self.matrix = np.eye(n_assets) * epsilon

  def allocate(self, history_gross_returns: np.ndarray) -> np.ndarray:
    return self.weights.copy()

  def update(self, chosen_weights: np.ndarray, realized_gross_returns: np.ndarray) -> None:
    portfolio_gross = max(float(chosen_weights @ realized_gross_returns), 1e-8)
    gradient = realized_gross_returns / portfolio_gross
    self.matrix += np.outer(gradient, gradient)
    try:
      direction = np.linalg.solve(self.matrix, gradient)
    except np.linalg.LinAlgError:
      direction = np.linalg.pinv(self.matrix) @ gradient
    candidate = chosen_weights + direction / self.beta
    self.weights = project_to_simplex(candidate)


class MomentumStrategy(OnlinePortfolioStrategy):
  def __init__(self, n_assets: int, window: int, top_k: int) -> None:
    super().__init__(
      StrategyDefinition(
        key='momentum',
        name='Momentum',
        family='Heuristic',
        description='Overweight the strongest recent performers over a rolling window.',
        complexity='O(n)',
        theory='No regret guarantee; tends to benefit in trending markets.',
        parameters={'window': window, 'top_k': top_k},
      ),
      n_assets,
    )
    self.window = window
    self.top_k = top_k

  def allocate(self, history_gross_returns: np.ndarray) -> np.ndarray:
    if len(history_gross_returns) < self.window:
      return np.full(self.n_assets, 1.0 / self.n_assets)
    trailing = trailing_cumulative_return(history_gross_returns[-self.window :])
    ranking = np.argsort(trailing)[::-1][: self.top_k]
    weights = np.zeros(self.n_assets)
    weights[ranking] = 1.0 / len(ranking)
    return weights


class MeanReversionStrategy(OnlinePortfolioStrategy):
  def __init__(self, n_assets: int, window: int, top_k: int) -> None:
    super().__init__(
      StrategyDefinition(
        key='mean_reversion',
        name='Mean Reversion',
        family='Heuristic',
        description='Rotate toward recent laggards in the expectation of reversal.',
        complexity='O(n)',
        theory='No regret guarantee; can benefit in choppy or oscillating markets.',
        parameters={'window': window, 'top_k': top_k},
      ),
      n_assets,
    )
    self.window = window
    self.top_k = top_k

  def allocate(self, history_gross_returns: np.ndarray) -> np.ndarray:
    if len(history_gross_returns) < self.window:
      return np.full(self.n_assets, 1.0 / self.n_assets)
    trailing = trailing_cumulative_return(history_gross_returns[-self.window :])
    ranking = np.argsort(trailing)[: self.top_k]
    weights = np.zeros(self.n_assets)
    weights[ranking] = 1.0 / len(ranking)
    return weights


class ApproxUniversalPortfolioStrategy(OnlinePortfolioStrategy):
  def __init__(
    self,
    n_assets: int,
    samples: int,
    concentration: float,
    random_seed: int,
  ) -> None:
    super().__init__(
      StrategyDefinition(
        key='universal_portfolio',
        name='Approximate Universal Portfolio',
        family='Online Bayesian',
        description='Sampled Cover universal portfolio over constant rebalanced portfolios.',
        complexity='O(Mn)',
        theory='Asymptotically tracks BCRP; approximation quality depends on the sample budget M.',
        parameters={'samples': samples, 'concentration': concentration},
      ),
      n_assets,
    )
    rng = np.random.default_rng(random_seed)
    alpha = np.full(n_assets, concentration)
    self.samples = rng.dirichlet(alpha, size=samples)
    self.log_wealths = np.zeros(samples)

  def allocate(self, history_gross_returns: np.ndarray) -> np.ndarray:
    shifted = self.log_wealths - self.log_wealths.max()
    weights = np.exp(shifted)
    weights /= weights.sum()
    return normalize_weights(weights @ self.samples)

  def update(self, chosen_weights: np.ndarray, realized_gross_returns: np.ndarray) -> None:
    sample_gross = np.clip(self.samples @ realized_gross_returns, 1e-8, None)
    self.log_wealths += np.log(sample_gross)


@dataclass
class StrategyResult:
  definition: StrategyDefinition
  metrics: dict[str, float]
  latest_weights: dict[str, float]
  daily_records: pd.DataFrame


def classify_volatility_regime(returns: pd.DataFrame, window: int) -> pd.Series:
  equal_weight = returns.mean(axis=1)
  realized_vol = equal_weight.rolling(window).std()
  threshold = float(realized_vol.median(skipna=True))
  regimes = np.where(realized_vol >= threshold, 'high_vol', 'low_vol')
  return pd.Series(regimes, index=returns.index).fillna('warmup')


def compute_bcrp_weights(gross_returns: np.ndarray, iterations: int = 2500) -> np.ndarray:
  n_assets = gross_returns.shape[1]
  weights = np.full(n_assets, 1.0 / n_assets)
  for step in range(iterations):
    portfolio_gross = np.clip(gross_returns @ weights, 1e-8, None)
    gradient = (gross_returns / portfolio_gross[:, None]).mean(axis=0)
    learning_rate = 0.15 / np.sqrt(step + 1.0)
    candidate = weights + learning_rate * gradient
    new_weights = project_to_simplex(candidate)
    if np.linalg.norm(new_weights - weights, ord=1) < 1e-8:
      weights = new_weights
      break
    weights = new_weights
  return weights


def simulate_constant_rebalanced_portfolio(
  key: str,
  name: str,
  weights: np.ndarray,
  gross_returns: pd.DataFrame,
  regimes: pd.Series,
  symbols: tuple[str, ...],
) -> StrategyResult:
  dates = gross_returns.index
  wealth = 1.0
  log_wealth = 0.0
  equity_curve = [wealth]
  records: list[dict[str, object]] = []

  for date, gross_vector in zip(dates, gross_returns.to_numpy(dtype=float), strict=False):
    gross_factor = float(weights @ gross_vector)
    wealth *= gross_factor
    log_wealth += np.log(max(gross_factor, 1e-8))
    equity_curve.append(wealth)
    records.append(
      {
        'date': date.strftime('%Y-%m-%d'),
        'strategy': key,
        'track': 'proposal_core',
        'gross_factor': gross_factor,
        'net_simple_return': gross_factor - 1.0,
        'turnover': 0.0,
        'cost_paid': 0.0,
        'equity': wealth,
        'regime': regimes.loc[date],
        'top_symbol': symbols[int(np.argmax(weights))],
      }
    )

  daily_frame = pd.DataFrame(records)
  metrics = compute_metrics(daily_frame, np.asarray(equity_curve), benchmark_log_wealth=log_wealth)
  metrics['regret_vs_bcrp'] = 0.0

  return StrategyResult(
    definition=StrategyDefinition(
      key=key,
      name=name,
      family='Offline Oracle',
      description='Best constant rebalanced portfolio in hindsight.',
      complexity='Offline convex optimization',
      theory='Upper bound benchmark for regret against the best fixed portfolio.',
      parameters={},
    ),
    metrics=metrics,
    latest_weights={
      symbol: float(value) for symbol, value in zip(symbols, weights, strict=False)
    },
    daily_records=daily_frame,
  )


def compute_metrics(
  daily_frame: pd.DataFrame,
  equity_curve: np.ndarray,
  benchmark_log_wealth: float | None = None,
) -> dict[str, float]:
  net_returns = daily_frame['net_simple_return'].to_numpy(dtype=float)
  final_wealth = float(equity_curve[-1])
  cumulative_log_wealth = float(np.log(np.clip(equity_curve[-1], 1e-8, None)))
  daily_std = net_returns.std(ddof=1) if len(net_returns) > 1 else 0.0
  sharpe = 0.0 if daily_std == 0 else net_returns.mean() / daily_std * np.sqrt(252.0)
  running_peak = np.maximum.accumulate(equity_curve)
  drawdown = equity_curve / np.clip(running_peak, 1e-8, None) - 1.0
  metrics = {
    'final_wealth': final_wealth,
    'cumulative_return': final_wealth - 1.0,
    'cumulative_log_wealth': cumulative_log_wealth,
    'annualized_return': final_wealth ** (252.0 / max(len(net_returns), 1)) - 1.0,
    'sharpe': float(sharpe),
    'max_drawdown': float(abs(drawdown.min())),
    'avg_turnover': float(daily_frame['turnover'].mean()),
    'cost_drag': float(daily_frame['cost_paid'].sum()),
    'hit_rate': float((daily_frame['net_simple_return'] > 0).mean()),
    'high_vol_avg_return': float(
      daily_frame.loc[daily_frame['regime'] == 'high_vol', 'net_simple_return'].mean()
    ),
    'low_vol_avg_return': float(
      daily_frame.loc[daily_frame['regime'] == 'low_vol', 'net_simple_return'].mean()
    ),
    'regret_vs_bcrp': float(benchmark_log_wealth - cumulative_log_wealth)
    if benchmark_log_wealth is not None
    else 0.0,
  }
  return metrics


def simulate_online_strategy(
  strategy: OnlinePortfolioStrategy,
  gross_returns: pd.DataFrame,
  regimes: pd.Series,
  transaction_cost_bps: float,
  benchmark_log_wealth: float,
  symbols: tuple[str, ...],
) -> StrategyResult:
  wealth = 1.0
  equity_curve = [wealth]
  records: list[dict[str, object]] = []
  post_return_weights: np.ndarray | None = None
  cost_rate = transaction_cost_bps / 10_000.0
  # Pre-allocate history buffer to avoid O(T^2) np.asarray(list) allocation
  n_steps = len(gross_returns)
  n_assets = len(symbols)
  history_buf = np.empty((n_steps, n_assets), dtype=float)
  history_len = 0
  latest_weights = np.full(n_assets, 1.0 / n_assets)

  for date, gross_vector in zip(gross_returns.index, gross_returns.to_numpy(dtype=float), strict=False):
    history_array = history_buf[:history_len]  # view, no copy
    target_weights = normalize_weights(strategy.allocate(history_array))
    if post_return_weights is None:
      turnover = 0.0
    else:
      turnover = 0.5 * float(np.abs(target_weights - post_return_weights).sum())

    gross_factor = float(target_weights @ gross_vector)
    net_factor = max(gross_factor * (1.0 - cost_rate * turnover), 1e-8)
    wealth *= net_factor
    equity_curve.append(wealth)
    cost_paid = cost_rate * turnover
    records.append(
      {
        'date': date.strftime('%Y-%m-%d'),
        'strategy': strategy.definition.key,
        'track': 'proposal_core',
        'gross_factor': gross_factor,
        'net_simple_return': net_factor - 1.0,
        'turnover': turnover,
        'cost_paid': cost_paid,
        'equity': wealth,
        'regime': regimes.loc[date],
        'top_symbol': symbols[int(np.argmax(target_weights))],
      }
    )

    post_return_weights = normalize_weights(target_weights * gross_vector)
    latest_weights = target_weights
    strategy.update(target_weights, gross_vector)
    history_buf[history_len] = gross_vector
    history_len += 1

  daily_frame = pd.DataFrame(records)
  metrics = compute_metrics(daily_frame, np.asarray(equity_curve), benchmark_log_wealth=benchmark_log_wealth)

  return StrategyResult(
    definition=strategy.definition,
    metrics=metrics,
    latest_weights={
      symbol: float(value) for symbol, value in zip(symbols, latest_weights, strict=False)
    },
    daily_records=daily_frame,
  )


def build_online_strategies(
  n_assets: int,
  eg_eta: float,
  ons_beta: float,
  ons_epsilon: float,
  universal_samples: int,
  universal_concentration: float,
  momentum_window: int,
  mean_reversion_window: int,
  top_k: int,
  random_seed: int,
) -> list[OnlinePortfolioStrategy]:
  return [
    EqualWeightStrategy(n_assets),
    ExponentiatedGradientStrategy(n_assets, eg_eta),
    OnlineNewtonStepStrategy(n_assets, ons_beta, ons_epsilon),
    ApproxUniversalPortfolioStrategy(
      n_assets,
      samples=universal_samples,
      concentration=universal_concentration,
      random_seed=random_seed,
    ),
    MomentumStrategy(n_assets, window=momentum_window, top_k=top_k),
    MeanReversionStrategy(n_assets, window=mean_reversion_window, top_k=top_k),
  ]
