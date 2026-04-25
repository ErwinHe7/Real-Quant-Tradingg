"""
Realistic cost model for US equity retail trading on moomoo.

Every strategy evaluation must use this model rather than the flat-bps
approximation.  The old `transaction_cost_bps` config parameter is kept
as a deprecated shim that logs a warning.

References
----------
- moomoo US commission: $0.0049/share, $0.99 minimum per order
  Source: https://www.moomoo.com/us/fee (retrieved 2024-01-01)
- SEC fee rate: $0.0000278 per $ of sale (2024 rate; updated annually)
  Source: https://www.sec.gov/rules/other/2023/34-98202.pdf
- FINRA TAF: $0.000166 per share sold, max $8.30 per order
  Source: https://www.finra.org/rules-guidance/rulebooks/finra-rules/7730 (2024)
- Spread proxy: (high - low) / close — approximates effective half-spread
  on a daily bar basis; understates intraday spread for illiquid names.
- Market impact: k * sqrt(notional / ADV20) bps, k=10 (conservative)
  Source: market-impact literature (Almgren et al., Kissell & Glantz)
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Published fee schedule — update annually
# ---------------------------------------------------------------------------

MOOMOO_PER_SHARE_USD: float = 0.0049          # $/share (moomoo US, 2024)
MOOMOO_MIN_PER_ORDER_USD: float = 0.99        # minimum per order

SEC_FEE_RATE: float = 0.0000278               # $ per $ sold (SEC 2024)
# Source: SEC Release No. 34-98202 (2024 fiscal year rate)

FINRA_TAF_PER_SHARE: float = 0.000166         # $ per share sold
FINRA_TAF_MAX_PER_ORDER: float = 8.30         # cap per order

IMPACT_K: float = 10.0                         # bps, assumed — label as such


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TradeCost:
    """
    Complete cost breakdown for a single order leg.

    All monetary values are in USD.  `bps` is total cost as basis points of
    notional.
    """
    commission_usd: float
    sec_fee_usd: float        # sell-side only
    finra_taf_usd: float      # sell-side only
    spread_cost_usd: float
    impact_usd: float
    total_usd: float
    bps: float                # total / notional * 10_000


# ---------------------------------------------------------------------------
# Individual charge calculators (pure functions)
# ---------------------------------------------------------------------------

def commission(shares: float, price: float) -> float:
    """moomoo US per-share commission with minimum."""
    raw = abs(shares) * MOOMOO_PER_SHARE_USD
    return max(raw, MOOMOO_MIN_PER_ORDER_USD) if shares != 0 else 0.0


def sec_fee(notional_sold: float) -> float:
    """SEC regulatory fee on the value of sells."""
    return max(notional_sold, 0.0) * SEC_FEE_RATE


def finra_taf(shares_sold: float) -> float:
    """FINRA Trading Activity Fee on shares sold."""
    raw = abs(min(shares_sold, 0.0)) * FINRA_TAF_PER_SHARE  # shares_sold is signed
    if shares_sold < 0:
        raw = abs(shares_sold) * FINRA_TAF_PER_SHARE
    return min(raw, FINRA_TAF_MAX_PER_ORDER)


def spread_cost(
    notional: float,
    high: float,
    low: float,
    close: float,
) -> float:
    """
    Half-spread proxy from daily bar OHLC.

    We use (high - low) / close as a proxy for the intraday spread.
    Half of that is the expected cost of crossing the spread once.

    This understates the true spread for illiquid names and overstates it
    for very liquid names during calm periods.  It is a reasonable
    unconditional proxy given only daily bars.
    """
    if close <= 0:
        return 0.0
    relative_spread = (high - low) / close
    half_spread = relative_spread / 2.0
    return abs(notional) * half_spread


def market_impact(notional: float, adv_usd: float) -> float:
    """
    Linear-in-sqrt market-impact model.

    impact_bps = k * sqrt(notional / ADV)

    Parameters
    ----------
    notional  : trade notional in USD (absolute value)
    adv_usd   : 20-day average daily value (shares × price) in USD

    This is labelled an ASSUMPTION calibrated to k=10 bps.
    It is not measured from the user's own fills.
    """
    if adv_usd <= 0:
        return 0.0
    participation = abs(notional) / adv_usd
    impact_bps = IMPACT_K * np.sqrt(participation)
    return abs(notional) * (impact_bps / 10_000.0)


# ---------------------------------------------------------------------------
# Aggregate trade cost
# ---------------------------------------------------------------------------

def compute_trade_cost(
    *,
    shares: float,            # positive = buy, negative = sell
    price: float,
    high: float,
    low: float,
    adv20_usd: float,
) -> TradeCost:
    """
    Compute the full cost of a single order leg.

    Parameters
    ----------
    shares      : signed share count (+ buy, - sell)
    price       : execution price (use close as proxy for backtests)
    high        : bar high (for spread proxy)
    low         : bar low (for spread proxy)
    adv20_usd   : 20-day average daily value in USD
    """
    notional = abs(shares * price)
    is_sell = shares < 0

    comm = commission(shares, price)
    sec = sec_fee(notional) if is_sell else 0.0
    finra = finra_taf(shares) if is_sell else 0.0
    spread = spread_cost(notional, high, low, price)
    impact = market_impact(notional, adv20_usd)

    total = comm + sec + finra + spread + impact
    bps = (total / notional * 10_000.0) if notional > 0 else 0.0

    return TradeCost(
        commission_usd=comm,
        sec_fee_usd=sec,
        finra_taf_usd=finra,
        spread_cost_usd=spread,
        impact_usd=impact,
        total_usd=total,
        bps=bps,
    )


# ---------------------------------------------------------------------------
# Portfolio-level round-trip cost (for backtest use)
# ---------------------------------------------------------------------------

def portfolio_cost_bps(
    old_weights: np.ndarray,
    new_weights: np.ndarray,
    prices: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    adv20_usd: np.ndarray,
    equity: float,
) -> float:
    """
    Estimate total round-trip cost in basis points of equity for a weight
    transition from *old_weights* to *new_weights*.

    This is used in backtests where we do not know exact share counts.

    Parameters
    ----------
    old_weights : weight vector before the trade
    new_weights : weight vector after the trade
    prices      : closing prices (proxy for execution price)
    highs       : bar highs (for spread proxy)
    lows        : bar lows (for spread proxy)
    adv20_usd   : 20-day ADV in USD per asset
    equity      : total portfolio equity in USD

    Returns
    -------
    Cost in bps of equity (e.g. 15.0 means 15 bps)
    """
    delta_weights = new_weights - old_weights
    total_cost_usd = 0.0

    for i, dw in enumerate(delta_weights):
        notional = abs(dw) * equity
        if notional < 1.0:
            continue

        # Determine approximate shares
        p = float(prices[i]) if prices[i] > 0 else 1.0
        shares = notional / p * (1.0 if dw >= 0 else -1.0)

        cost = compute_trade_cost(
            shares=shares,
            price=p,
            high=float(highs[i]),
            low=float(lows[i]),
            adv20_usd=float(adv20_usd[i]),
        )
        total_cost_usd += cost.total_usd

    return (total_cost_usd / equity * 10_000.0) if equity > 0 else 0.0


def legacy_cost_bps(turnover: float, transaction_cost_bps: float) -> float:
    """
    Deprecated shim for the old flat transaction_cost_bps assumption.

    Logs a warning so callers can migrate.
    """
    warnings.warn(
        "Using deprecated flat transaction_cost_bps assumption. "
        "Migrate to costs.portfolio_cost_bps() for accurate cost modelling.",
        DeprecationWarning,
        stacklevel=2,
    )
    return turnover * (transaction_cost_bps / 10_000.0)
