"""
Volatility targeting for the risk layer.

Scale portfolio weights so that ex-ante portfolio vol ≈ target, capped
by max_gross.  Uses Ledoit-Wolf shrinkage (same path as the research
harness optimizer).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research_harness.optimizer import shrink_covariance


def scale_to_vol_target(
    weights: pd.Series,
    realised_cov: pd.DataFrame,
    target_annual_vol: float = 0.12,
    max_gross: float = 0.95,
) -> pd.Series:
    """
    Return scaled weights so that ex-ante portfolio vol ≈ target_annual_vol,
    capped by max_gross.

    Parameters
    ----------
    weights          : target weight series (symbols as index)
    realised_cov     : annualised covariance matrix of returns (symbols × symbols).
                       If daily, multiply by 252 before passing in.
    target_annual_vol: target portfolio volatility (annualised), default 12%
    max_gross        : gross-leverage cap after scaling

    Returns
    -------
    pd.Series — scaled weights, same index as input
    """
    if weights.empty:
        return weights.copy()

    # Align weights with covariance matrix
    symbols = [s for s in weights.index if s in realised_cov.columns]
    if not symbols:
        return weights.copy()

    w = weights.reindex(symbols).fillna(0.0).to_numpy(dtype=float)
    cov = realised_cov.loc[symbols, symbols].to_numpy(dtype=float)
    cov_shrunk = shrink_covariance(np.eye(1))  # warm up import
    cov_shrunk = shrink_covariance(cov.reshape(-1, len(symbols)) if cov.ndim == 1 else cov)

    # Annualise if needed: if trace/n is tiny (daily scale), multiply by 252
    mean_var = np.diag(cov_shrunk).mean()
    if mean_var < 0.001:
        cov_shrunk *= 252.0

    portfolio_var = float(w @ cov_shrunk @ w)
    if portfolio_var <= 0:
        return weights.copy()

    portfolio_vol = np.sqrt(portfolio_var)
    scale = target_annual_vol / portfolio_vol

    # Cap by max_gross
    scaled_w = w * scale
    gross = np.abs(scaled_w).sum()
    if gross > max_gross:
        scaled_w = scaled_w * (max_gross / gross)

    result = pd.Series(0.0, index=weights.index)
    result.loc[symbols] = scaled_w
    return result
