"""
Universe definitions for the research harness.

Every constant below documents:
  - selection rule
  - as-of date (the date the list was frozen)
  - known biases

Adding a new universe
---------------------
1. Define a module-level tuple of uppercase ticker strings.
2. Add a docstring block following the pattern below.
3. Register it in docs/DATA.md under "Universe Definitions".
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# ETF_CORE_4  — proposal track / teaching example
# ---------------------------------------------------------------------------

ETF_CORE_4: tuple[str, ...] = ("GLD", "QQQ", "SPY", "TLT")
"""Proposal-track four-ETF universe.

Selection rule
    Four liquid, diversified US ETFs spanning equities (SPY, QQQ),
    bonds (TLT) and gold (GLD), chosen by the course for the online
    portfolio benchmark assignment.

As-of date
    2024-01-01 (hardcoded for course; not updated after that date).

Known biases
    - N=4 is statistically insufficient for cross-sectional claims.
    - Survivorship-free at this universe size (all four ETFs pre-date 2010).
    - Sector/factor diversification is limited; results from this universe
      do not generalise to broader equity strategies.

Usage
    Proposal track only. Do not use this universe to claim a live-tradable
    result; it is a teaching vehicle.
"""

# ---------------------------------------------------------------------------
# ETF_SECTOR_11  — eleven SPDR sector ETFs
# ---------------------------------------------------------------------------

ETF_SECTOR_11: tuple[str, ...] = (
    "XLB",   # Materials
    "XLC",   # Communication Services
    "XLE",   # Energy
    "XLF",   # Financials
    "XLI",   # Industrials
    "XLK",   # Technology
    "XLP",   # Consumer Staples
    "XLRE",  # Real Estate
    "XLU",   # Utilities
    "XLV",   # Health Care
    "XLY",   # Consumer Discretionary
)
"""Eleven SPDR Select Sector ETFs covering all S&P 500 GICS sectors.

Selection rule
    All eleven State Street SPDR Select Sector ETFs as of the as-of date.
    Excludes non-sector broad-market SPDR products (e.g. SPY itself).

As-of date
    2024-01-01.  XLRE launched 2015-10-07; the shortest history in this
    set therefore starts ~2015-10-07.

Known biases
    - Sector concentration: strategies trained on one regime (e.g. low-rate
      2010–2021) may not generalise to rate-rise environments.
    - Moderate survivorship risk: all eleven ETFs survived to 2024, but
      sectors that were later merged or discontinued in earlier eras would
      not appear here.
    - Liquidity is high for all members (>$500 M AUM each as of 2024), so
      market-impact estimates are conservative.
    - XLRE only has ~8 years of history; walk-forward splits must account
      for this short series.
"""

# ---------------------------------------------------------------------------
# SP500_LIQUID  — top-50 S&P 500 names by 60-day median ADV
# ---------------------------------------------------------------------------

SP500_LIQUID: tuple[str, ...] = (
    "AAPL",  "ABBV",  "ABT",   "ACN",   "ADBE",
    "AMD",   "AMGN",  "AMZN",  "AVGO",  "BAC",
    "BRK-B", "CAT",   "COST",  "CRM",   "CSCO",
    "CVX",   "DHR",   "GE",    "GOOG",  "GOOGL",
    "HD",    "INTU",  "ISRG",  "JNJ",   "JPM",
    "KO",    "LIN",   "LLY",   "MA",    "MCD",
    "META",  "MRK",   "MSFT",  "NFLX",  "NOW",
    "NVDA",  "ORCL",  "PEP",   "PG",    "PM",
    "RTX",   "SPGI",  "TMO",   "TSLA",  "TXN",
    "UNH",   "V",     "WFC",   "WMT",   "XOM",
)
"""Top-50 S&P 500 constituent ETFs by 60-day median average daily volume.

Selection rule
    Starting from the S&P 500 Index constituent list as of 2024-01-01,
    ranked by 60-calendar-day median ADV (shares × close price) over
    Nov–Dec 2023, top 50 selected.  BRK.B included as the liquid B-share.

As-of date
    2024-01-01.

KNOWN BIASES — READ THIS BEFORE USING
    1. SURVIVORSHIP BIAS (significant): every name in this list was in the
       S&P 500 and liquid as of 2024-01-01.  Companies that were delisted,
       merged, or dropped from the index before 2024 do not appear.
       Backtests on this universe will overstate returns for any historical
       window that includes companies that later dropped out.
    2. LIQUIDITY SELECTION BIAS: restricting to the top-50 by ADV further
       selects for mega-caps that outperformed.  Strategies trained here may
       not transfer to mid/small-cap names.
    3. FACTOR CONCENTRATION: mega-cap tech (AAPL, MSFT, AMZN, NVDA, GOOGL,
       META) collectively dominate; factor signals derived from this universe
       may proxy tech-sector exposure.

Mitigation
    Any cross-sectional result on this universe must include an explicit
    survivorship-bias warning in the report and should be validated on a
    point-in-time index membership database (e.g. Compustat or Bloomberg
    SPGI constituent history) before claiming live-tradability.
"""
