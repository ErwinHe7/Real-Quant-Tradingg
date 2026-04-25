"""
Tests for live.risk.sizing — fractional Kelly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from live.risk.sizing import fractional_kelly


def _diagonal_cov(n: int, var: float = 0.0001) -> pd.DataFrame:
    """Diagonal covariance for simple test cases."""
    symbols = [f"S{i}" for i in range(n)]
    return pd.DataFrame(np.eye(n) * var, index=symbols, columns=symbols)


def test_kelly_positive_signal_positive_weight():
    """When all expected returns are positive, weights must be positive (long-only)."""
    symbols = ["A", "B", "C"]
    mu = pd.Series({"A": 0.01, "B": 0.005, "C": 0.002})
    cov = _diagonal_cov(3)
    cov.index = cov.columns = symbols
    w = fractional_kelly(mu, cov, fraction=0.25, cap_per_name=0.10, cap_gross=0.95)
    assert (w >= 0).all()


def test_kelly_negative_signal_negative_weight():
    """When expected returns are negative, Kelly produces negative weights."""
    symbols = ["A", "B"]
    mu = pd.Series({"A": -0.01, "B": -0.005})
    cov = _diagonal_cov(2)
    cov.index = cov.columns = symbols
    w = fractional_kelly(mu, cov, fraction=0.25, cap_per_name=0.50, cap_gross=1.0)
    assert (w <= 0).all()


def test_kelly_respects_per_name_cap():
    symbols = ["A"]
    mu = pd.Series({"A": 1.0})  # very strong signal
    cov = _diagonal_cov(1)
    cov.index = cov.columns = symbols
    w = fractional_kelly(mu, cov, fraction=0.25, cap_per_name=0.10, cap_gross=0.95)
    assert w["A"] <= 0.10 + 1e-9


def test_kelly_respects_gross_cap():
    n = 5
    symbols = [f"S{i}" for i in range(n)]
    mu = pd.Series({s: 0.10 for s in symbols})
    cov = _diagonal_cov(n, var=0.0001)
    cov.index = cov.columns = symbols
    w = fractional_kelly(mu, cov, fraction=0.25, cap_per_name=0.30, cap_gross=0.95)
    assert w.abs().sum() <= 0.95 + 1e-6


def test_kelly_zero_signal_zero_or_small_weights():
    """Near-zero expected returns should produce near-zero weights."""
    symbols = ["A", "B"]
    mu = pd.Series({"A": 0.0, "B": 0.0})
    cov = _diagonal_cov(2)
    cov.index = cov.columns = symbols
    w = fractional_kelly(mu, cov, fraction=0.25, cap_per_name=0.10, cap_gross=0.95)
    assert w.abs().max() < 0.01


def test_kelly_mixed_signs():
    """Positive and negative signals should produce positive and negative weights."""
    symbols = ["A", "B"]
    mu = pd.Series({"A": 0.01, "B": -0.01})
    cov = _diagonal_cov(2)
    cov.index = cov.columns = symbols
    w = fractional_kelly(mu, cov, fraction=0.25, cap_per_name=0.30, cap_gross=1.0)
    assert w["A"] > 0
    assert w["B"] < 0
