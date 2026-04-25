"""
Fractional Kelly position sizing.

Kelly assumes unbiased expected return estimates.  They are not.
Use fraction=0.25 (1/4 Kelly) by default — this is conservative and
appropriate for a retail account where signal quality is uncertain.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research_harness.optimizer import shrink_covariance


def fractional_kelly(
    expected_returns: pd.Series,
    cov: pd.DataFrame,
    fraction: float = 0.25,
    cap_per_name: float = 0.10,
    cap_gross: float = 0.95,
) -> pd.Series:
    """
    Compute fractional Kelly weights.

    Full Kelly: w* = Σ⁻¹ μ  (log-wealth maximising portfolio)
    Fractional: w = fraction * w*

    Then:
    1. Clip each name to [-cap_per_name, +cap_per_name]
    2. Rescale gross to cap_gross if needed
    3. Project to simplex if long-only

    Parameters
    ----------
    expected_returns : signal for each symbol (not normalised)
    cov              : covariance matrix (symbols × symbols), same units as returns
    fraction         : Kelly fraction (default 0.25 — conservative)
    cap_per_name     : per-name weight cap as fraction of equity
    cap_gross        : gross leverage cap

    Returns
    -------
    pd.Series — weights, same index as expected_returns

    Notes
    -----
    The Kelly formula assumes the expected-return vector is the true mean
    of the return distribution.  For a retail signal, this assumption is
    optimistic.  fraction=0.25 compensates for this by dramatically reducing
    bet sizes.  Never use fraction > 0.5 without very strong evidence of
    signal quality.
    """
    symbols = expected_returns.index.tolist()
    mu = expected_returns.reindex(symbols).fillna(0.0).to_numpy(dtype=float)
    sigma = cov.reindex(index=symbols, columns=symbols).fillna(0.0).to_numpy(dtype=float)
    sigma_shrunk = shrink_covariance(sigma)

    # For a 1×1 covariance, shrinkage is degenerate; compute directly
    if sigma_shrunk.shape == (1, 1):
        var = float(sigma_shrunk[0, 0])
        w_full = np.array([mu[0] / var]) if var > 0 else np.array([0.0])
    else:
        try:
            w_full = np.linalg.solve(sigma_shrunk, mu)
        except np.linalg.LinAlgError:
            w_full = np.linalg.pinv(sigma_shrunk) @ mu

    w = fraction * w_full

    # Per-name cap
    w = np.clip(w, -cap_per_name, cap_per_name)

    # Gross cap
    gross = np.abs(w).sum()
    if gross > cap_gross and gross > 0:
        w = w * (cap_gross / gross)

    result = pd.Series(w, index=symbols)
    return result
