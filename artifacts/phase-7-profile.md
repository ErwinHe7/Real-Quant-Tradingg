# Phase 7 — Performance Profile and Decision

**Date**: 2026-04-25
**Workload**: `python -m research_harness.phase3_runner` (full 3-universe walk-forward sweep)
**Tool**: `cProfile` (py-spy not available on Python 3.14/Windows; cProfile is sufficient)

---

## Profile Summary

**Total wall time**: 37.0s (before fix) / 35.1s (after)
**Total function calls**: 44.5 million

---

## Top 20 Hot Functions (by self-time, before fix)

| Rank | Function | Self-time (s) | Cumulative (s) | % of Total | Fix possible? |
|------|----------|--------------|----------------|------------|---------------|
| 1 | `curl_easy_perform` (yfinance HTTP) | 7.83 | 7.84 | 21% | No — network I/O |
| 2 | `numpy.asarray` (history list→array) | 5.57 | 5.60 | 15% | **Yes — applied** |
| 3 | `simulate_online_strategy` (loop) | 2.28 | 20.80 | 56% cumulative | Partly |
| 4 | `numpy.ufunc.reduce` (numpy ops) | 1.03 | 1.03 | 3% | No — already vectorized |
| 5 | `isinstance` checks | 0.78 | 1.34 | 2% | No — Python runtime |
| 6 | `pandas.arrow.__getitem__` | 0.74 | 1.02 | 2% | No — pandas internals |
| 7 | `normalize_weights` (545K calls) | 0.66 | 2.56 | 2% | Marginal |
| 8 | `parquet.write_table` | 0.59 | 0.59 | 2% | No — disk I/O |
| 9 | `pandas.xs` (row access, 240K calls) | 0.54 | 3.38 | 1.5% | Rewrite loop |
| 10 | `DatetimeIndex.get_loc` | 0.37 | 1.58 | 1% | No |
| 11 | `project_to_simplex` (46K calls) | 0.33 | 0.67 | 0.9% | Marginal |
| 12 | `pandas.get_loc` (248K calls) | 0.31 | 0.36 | 0.8% | No |
| 13 | `numpy.clip` | 0.31 | 1.25 | 0.8% | No — vectorized |
| 14 | `pandas.__getitem__` | 0.28 | 6.11 | 0.8% | No |
| 15 | `pandas._get_axis` | 0.27 | 0.34 | 0.7% | No |
| 16 | `numpy.ndarray.sum` | 0.24 | 1.12 | 0.6% | No — already compiled |
| 17 | `pandas.dtype._instancecheck` | 0.23 | 0.54 | 0.6% | No |
| 18 | `numpy.linalg.solve` (38K calls) | 0.22 | 0.46 | 0.6% | No — already LAPACK |
| 19 | `compute_bcrp_weights` | 0.22 | 0.49 | 0.6% | Already vectorized |
| 20 | `online_portfolio.allocate` (38K) | 0.18 | 0.46 | 0.5% | No |

---

## Fix Applied (Python, not Rust)

**Problem**: `simulate_online_strategy` called `np.asarray(history)` on a growing
Python list every tick — creating a new array of size t×N each step → O(T²) allocations.

**Fix**: Pre-allocate `history_buf = np.empty((n_steps, n_assets))` and use a view
`history_buf[:history_len]` on each step.

**Speedup**: 37.0s → 35.1s = 5% improvement. Modest because numpy's C-level
`asarray` from a list of arrays is already highly optimized.

**File changed**: `research_harness/online_portfolio.py:simulate_online_strategy`

---

## Decision: NO Rust Extension Warranted

**Criterion**: A function must take >5% of total time AND be fundamentally
numeric/loop-heavy AND not already vectorized.

### Analysis of candidates:

| Function | > 5%? | Not vectorized? | Fix with Rust? | Decision |
|----------|-------|-----------------|----------------|---------|
| `curl_easy_perform` | ✅ 21% | — | No (network I/O) | Skip |
| `numpy.asarray` | ✅ 15% | — | Already a C extension | Python fix applied |
| `simulate_online_strategy` | ✅ 56% cum | Python loop | Maybe | **Assessed below** |

**`simulate_online_strategy` analysis**: The loop's inner work is:
1. `np.asarray(history)` — fixed above
2. `strategy.allocate(history_array)` — dispatches to algorithm-specific allocate
3. `normalize_weights` — 3 numpy ops (clip, sum, divide) — already vectorized
4. Dot product, multiplication — numpy ufuncs

The remaining bottleneck is the Python loop overhead itself and the per-step
pandas `.loc[date]` access. Rewriting in Rust would require:
- Porting the online portfolio algorithms (EG, ONS, Universal Portfolio)
- Implementing pandas-compatible data structures
- Maintaining a Python fallback

**End-to-end speedup estimate**: The loop runs in ~18s total. Rust could plausibly
make it 3–5x faster in isolation, giving ~6–12s savings. But yfinance HTTP
(7.3s) and pandas/numpy overhead (~7s) are not amenable to Rust. The overall
workload would improve from 35s to ~25s — less than 2x end-to-end.

**Charter criterion**: "If end-to-end speedup is <2x, delete it."

### Conclusion: Phase 7 stops here.

The workload (35s total) is fast enough for its purpose (research, not HFT).
A Rust extension would add build complexity and maintenance burden for a
sub-2x speedup on a non-critical workload. Per the charter: "The goal is to
be faster where it matters and boring everywhere else."

---

## What Would Justify a Native Extension (for future reference)

1. Universe expansion to SP500 full (500 names) × full parameter sweep:
   estimated ~10–20 minutes without caching → profile first
2. Realtime tick processing for 100+ symbols → not this project's scope
3. Covariance matrix recomputation every minute → not this project's scope

---

## Tests After Optimization

`pytest tests/` → **135/135 passing** after the `np.asarray` fix.

The fix is a drop-in replacement; no API changes.
