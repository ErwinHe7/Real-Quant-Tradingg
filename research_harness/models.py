from __future__ import annotations

import math

import numpy as np


class RidgeReturnModel:
  def __init__(self, alpha: float) -> None:
    self.alpha = alpha
    self.feature_mean: np.ndarray | None = None
    self.feature_scale: np.ndarray | None = None
    self.coefficients: np.ndarray | None = None
    self.intercept: float = 0.0

  def fit(self, features: np.ndarray, targets: np.ndarray) -> None:
    if features.ndim != 2 or len(features) == 0:
      raise ValueError('RidgeReturnModel.fit expects a non-empty 2D feature matrix.')

    self.feature_mean = features.mean(axis=0)
    self.feature_scale = features.std(axis=0)
    self.feature_scale[self.feature_scale < 1e-8] = 1.0

    scaled = (features - self.feature_mean) / self.feature_scale
    design = np.column_stack([np.ones(len(scaled)), scaled])
    penalty = np.eye(design.shape[1]) * self.alpha
    penalty[0, 0] = 0.0

    gram = design.T @ design + penalty
    rhs = design.T @ targets

    try:
      solution = np.linalg.solve(gram, rhs)
    except np.linalg.LinAlgError:
      solution = np.linalg.pinv(gram) @ rhs

    self.intercept = float(solution[0])
    self.coefficients = solution[1:]

  def predict(self, features: np.ndarray) -> np.ndarray:
    if self.feature_mean is None or self.feature_scale is None or self.coefficients is None:
      raise RuntimeError('RidgeReturnModel must be fit before predict is called.')

    scaled = (features - self.feature_mean) / self.feature_scale
    return self.intercept + scaled @ self.coefficients


class AttentionReturnModel:
  def __init__(
    self,
    input_size: int,
    hidden_size: int,
    learning_rate: float,
    epochs: int,
    l2: float,
    random_seed: int,
  ) -> None:
    self.input_size = input_size
    self.hidden_size = hidden_size
    self.learning_rate = learning_rate
    self.epochs = epochs
    self.l2 = l2
    self.random_seed = random_seed
    self.target_scale = 100.0
    self.sequence_mean: np.ndarray | None = None
    self.sequence_scale: np.ndarray | None = None
    self.wq: np.ndarray | None = None
    self.wk: np.ndarray | None = None
    self.wv: np.ndarray | None = None
    self.wo: np.ndarray | None = None
    self.wskip: np.ndarray | None = None
    self.bias: float = 0.0
    self.loss_history: list[float] = []

  def _standardize(self, sequences: np.ndarray) -> np.ndarray:
    flat = sequences.reshape(-1, sequences.shape[-1])
    self.sequence_mean = flat.mean(axis=0)
    self.sequence_scale = flat.std(axis=0)
    self.sequence_scale[self.sequence_scale < 1e-8] = 1.0
    return (sequences - self.sequence_mean) / self.sequence_scale

  def fit(self, sequences: np.ndarray, targets: np.ndarray) -> None:
    if sequences.ndim != 3 or len(sequences) == 0:
      raise ValueError('AttentionReturnModel.fit expects a non-empty 3D tensor.')

    rng = np.random.default_rng(self.random_seed)
    scaled_sequences = self._standardize(sequences)
    scaled_targets = targets * self.target_scale
    feature_count = scaled_sequences.shape[-1]
    scale = 1.0 / math.sqrt(max(feature_count, 1))

    self.wq = rng.normal(0.0, scale, size=(feature_count, self.hidden_size))
    self.wk = rng.normal(0.0, scale, size=(feature_count, self.hidden_size))
    self.wv = rng.normal(0.0, scale, size=(feature_count, self.hidden_size))
    self.wo = rng.normal(0.0, 0.05, size=self.hidden_size)
    self.wskip = rng.normal(0.0, 0.05, size=feature_count)
    self.bias = 0.0
    self.loss_history = []

    sqrt_hidden = math.sqrt(self.hidden_size)

    for epoch in range(self.epochs):
      grad_wq = np.zeros_like(self.wq)
      grad_wk = np.zeros_like(self.wk)
      grad_wv = np.zeros_like(self.wv)
      grad_wo = np.zeros_like(self.wo)
      grad_wskip = np.zeros_like(self.wskip)
      grad_bias = 0.0
      loss = 0.0

      for sequence, target in zip(scaled_sequences, scaled_targets, strict=False):
        q_matrix = sequence @ self.wq
        k_matrix = sequence @ self.wk
        v_matrix = sequence @ self.wv
        query = q_matrix[-1]
        scores = (k_matrix @ query) / sqrt_hidden
        scores -= scores.max()
        attention = np.exp(scores)
        attention /= attention.sum()
        context = attention @ v_matrix
        last = sequence[-1]
        prediction = float(context @ self.wo + last @ self.wskip + self.bias)
        residual = prediction - target
        loss += 0.5 * residual * residual

        grad_prediction = residual
        grad_wo += context * grad_prediction
        grad_wskip += last * grad_prediction
        grad_bias += grad_prediction

        grad_context = self.wo * grad_prediction
        grad_attention = v_matrix @ grad_context
        grad_v = np.outer(attention, grad_context)

        softmax_term = grad_attention - np.dot(grad_attention, attention)
        grad_scores = attention * softmax_term
        grad_k = np.outer(grad_scores, query) / sqrt_hidden
        grad_query = (k_matrix.T @ grad_scores) / sqrt_hidden
        grad_q = np.zeros_like(q_matrix)
        grad_q[-1] = grad_query

        grad_wq += sequence.T @ grad_q
        grad_wk += sequence.T @ grad_k
        grad_wv += sequence.T @ grad_v

      sample_count = float(len(scaled_sequences))
      grad_wq = grad_wq / sample_count + self.l2 * self.wq
      grad_wk = grad_wk / sample_count + self.l2 * self.wk
      grad_wv = grad_wv / sample_count + self.l2 * self.wv
      grad_wo = grad_wo / sample_count + self.l2 * self.wo
      grad_wskip = grad_wskip / sample_count + self.l2 * self.wskip
      grad_bias /= sample_count

      grad_norm = math.sqrt(
        float(np.sum(grad_wq ** 2) + np.sum(grad_wk ** 2) + np.sum(grad_wv ** 2))
        + float(np.sum(grad_wo ** 2) + np.sum(grad_wskip ** 2) + grad_bias ** 2)
      )
      if grad_norm > 5.0:
        clip = 5.0 / grad_norm
        grad_wq *= clip
        grad_wk *= clip
        grad_wv *= clip
        grad_wo *= clip
        grad_wskip *= clip
        grad_bias *= clip

      learning_rate = self.learning_rate * (0.92 ** (epoch // 10))
      self.wq -= learning_rate * grad_wq
      self.wk -= learning_rate * grad_wk
      self.wv -= learning_rate * grad_wv
      self.wo -= learning_rate * grad_wo
      self.wskip -= learning_rate * grad_wskip
      self.bias -= learning_rate * grad_bias
      self.loss_history.append(loss / sample_count)

  def predict(self, sequence: np.ndarray) -> float:
    if (
      self.sequence_mean is None
      or self.sequence_scale is None
      or self.wq is None
      or self.wk is None
      or self.wv is None
      or self.wo is None
      or self.wskip is None
    ):
      raise RuntimeError('AttentionReturnModel must be fit before predict is called.')

    standardized = (sequence - self.sequence_mean) / self.sequence_scale
    q_matrix = standardized @ self.wq
    k_matrix = standardized @ self.wk
    v_matrix = standardized @ self.wv
    query = q_matrix[-1]
    scores = (k_matrix @ query) / math.sqrt(self.hidden_size)
    scores -= scores.max()
    attention = np.exp(scores)
    attention /= attention.sum()
    context = attention @ v_matrix
    last = standardized[-1]
    prediction = float(context @ self.wo + last @ self.wskip + self.bias)
    return prediction / self.target_scale
