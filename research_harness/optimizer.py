from __future__ import annotations

import numpy as np


def shrink_covariance(returns_window: np.ndarray) -> np.ndarray:
  sample = np.cov(returns_window, rowvar=False)
  if sample.ndim == 0:
    sample = np.array([[float(sample)]])

  diagonal = np.diag(np.diag(sample))
  shrunk = 0.75 * sample + 0.25 * diagonal
  shrunk += np.eye(shrunk.shape[0]) * 1e-6
  return shrunk


def project_to_capped_simplex(values: np.ndarray, cap: float) -> np.ndarray:
  if cap * len(values) < 1.0:
    raise ValueError('cap is too small to allocate a full portfolio.')

  low = float(values.min() - cap)
  high = float(values.max())

  for _ in range(80):
    midpoint = (low + high) / 2.0
    projected = np.clip(values - midpoint, 0.0, cap)
    if projected.sum() > 1.0:
      low = midpoint
    else:
      high = midpoint

  projected = np.clip(values - high, 0.0, cap)
  total = projected.sum()
  if total <= 0:
    return np.full(len(values), 1.0 / len(values))

  return projected / total


class TransactionCostAwareOptimizer:
  def __init__(self, risk_aversion: float, turnover_penalty: float, max_weight: float) -> None:
    self.risk_aversion = risk_aversion
    self.turnover_penalty = turnover_penalty
    self.max_weight = max_weight

  def allocate(
    self,
    expected_returns: np.ndarray,
    covariance: np.ndarray,
    previous_weights: np.ndarray,
  ) -> np.ndarray:
    risk_matrix = covariance * self.risk_aversion + np.eye(len(expected_returns)) * 1e-4

    try:
      raw = np.linalg.solve(risk_matrix, expected_returns)
    except np.linalg.LinAlgError:
      raw = np.linalg.pinv(risk_matrix) @ expected_returns

    target = project_to_capped_simplex(raw, self.max_weight)
    blended = (1.0 - self.turnover_penalty) * target + self.turnover_penalty * previous_weights
    return project_to_capped_simplex(blended, self.max_weight)

  @staticmethod
  def trading_cost(weights: np.ndarray, previous_weights: np.ndarray, transaction_cost_bps: float) -> float:
    turnover = np.abs(weights - previous_weights).sum()
    return turnover * (transaction_cost_bps / 10_000.0)
