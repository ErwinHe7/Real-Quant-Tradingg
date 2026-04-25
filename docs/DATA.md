# Data Layer

## Overview

The research harness uses a local **parquet cache** to provide reproducible,
fast price data.  Every research run reads from the cache; only the first
run (or a forced `--refresh`) touches the network.

## Cache Location

```
data/cache/
├── yfinance/
│   ├── SPY.parquet           ← unadjusted OHLCV per symbol
│   ├── QQQ.parquet
│   └── _corp/
│       ├── SPY.parquet       ← corporate actions (splits, dividends)
│       └── QQQ.parquet
└── moomoo/                   ← reserved; not yet implemented
```

The cache root defaults to `data/cache/` relative to the working directory.
Pass `cache_root=Path("...")` to override.

## How to Nuke and Rebuild the Cache

```bash
rm -rf data/cache/
python -m research_harness.run --track proposal   # rebuilds from yfinance
```

Or force a refresh without deleting:

```bash
python -m research_harness.run --track proposal   # add --refresh flag once implemented
```

## Point-in-Time Adjustment

Adjusted close prices are computed **on the fly** from unadjusted prices plus
the corporate-actions table:

- A **2-for-1 split** on date D means all rows *before* D have their close
  divided by 2 — reflecting that an investor on date T < D would, in the
  future, see the split.
- Dividends are stored in the corporate-actions table but not yet folded into
  the adjustment (cash dividend adjustment requires knowing future prices;
  this is deferred to a higher-quality feed integration).
- The schema of the corporate-actions table is stable; swapping in a better
  data source (e.g. Polygon, Refinitiv) only requires providing a function
  that populates that table.

## How to Add a New Source

1. Implement a function `_download_<source>(symbol, start, end) -> (ohlcv_df, corp_df)`.
2. Add `"<source>"` to the `Literal` type annotation in `load_prices()`.
3. Add a dispatch branch in `load_prices()` to call the new function.
4. Write a unit test that mocks the download function and verifies cache
   read-back.

The `moomoo` source entry point is already reserved in the function signature
but raises `NotImplementedError`.  Phase 5 wires up the realtime adapter.

## How to Register a New Universe

1. Add a module-level tuple to `research_harness/universes.py`.
2. Add a docstring block stating: selection rule, as-of date, known biases.
3. Document it in this file under "Universe Definitions" below.
4. Register it in `tests/test_universes.py` under `ALL_UNIVERSES`.

## Universe Definitions

### ETF_CORE_4

| Property | Value |
|----------|-------|
| Members  | GLD, QQQ, SPY, TLT |
| As-of    | 2024-01-01 |
| Purpose  | Proposal track / teaching example |

**Biases**: N=4 is not statistically meaningful for cross-sectional claims.
All four ETFs survived to 2024 (no survivorship concern at this size, but
sector diversity is very limited).

### ETF_SECTOR_11

| Property | Value |
|----------|-------|
| Members  | 11 SPDR Select Sector ETFs (XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY) |
| As-of    | 2024-01-01 |
| Shortest history | XLRE launched 2015-10-07 |

**Biases**: Sector concentration, especially to the rate-rise regime
post-2022.  Moderate survivorship (all 11 survived to 2024).  Walk-forward
splits must respect XLRE's short history.

### SP500_LIQUID

| Property | Value |
|----------|-------|
| Members  | 50 S&P 500 names by 60-day median ADV as of Nov–Dec 2023 |
| As-of    | 2024-01-01 |

**SURVIVORSHIP BIAS (significant)**: every name was in the S&P 500 and
highly liquid as of 2024-01-01.  Companies delisted, merged, or dropped
before 2024 do not appear.  Any backtest result on this universe overstates
returns for any historical window that included names that subsequently
dropped out.

Any cross-sectional result on `SP500_LIQUID` must include this warning in
the phase report.

## Long-Form vs Wide-Form API

`load_prices()` returns a **long-form** DataFrame with columns:

```
date | symbol | open | high | low | close | adj_close | volume | source
```

`load_prices_wide()` is a convenience wrapper returning a **wide** DataFrame
(date × symbol) for a single field (default `adj_close`).

The internal `download_market_data()` used by the research harness calls
`load_prices_wide()` and returns a `MarketData` dataclass with `.close`,
`.volume`, and `.returns` wide frames.

## Known Limitations

- Dividends are stored but **not yet applied** to the adjusted price.  The
  adjustment uses splits only.  This understates adjusted returns for
  high-yield names.  Fixing this requires a higher-quality corporate-actions
  feed (Polygon, Refinitiv) and is deferred.
- `yfinance` data is best-effort and subject to revision.  The cache
  captures one snapshot; `refresh=True` overwrites it.  Deterministic
  research requires keeping the cache version-controlled or hashed.
- Delisted names raise a `SymbolDelisted` warning and return an empty
  frame; they do not appear in the cross-sectional result.  This is the
  correct behaviour for real-time use but introduces survivorship bias when
  constructing historical universes.
- Concurrent writes are made safe by a write-to-temp-then-rename pattern,
  but multi-process parallelism on Windows may still have edge cases.
