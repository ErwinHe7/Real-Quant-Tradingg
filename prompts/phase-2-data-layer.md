# Phase 2 — Data Layer

Prerequisite: read `prompts/00-agent-charter.md` first. Phase 1 (moomoo skill
install, Python venv, `python -m research_harness.run` smoke test) is done.

## Goal

Replace the on-demand `yfinance` fetch with a cached, reproducible, point-in-time
historical store, and add a thin wrapper for moomoo realtime quotes that the
later live engine will consume. No strategy logic changes in this phase.

## Why This Matters

`research_harness/data.py` currently calls `yfinance.download` every run with
`auto_adjust=True` and `ffill().dropna()`. That:
- silently drops names that delisted in the window (survivorship bias),
- produces non-deterministic backtests (Yahoo data revises),
- cannot be reused across param sweeps without re-downloading.

A cache also unblocks Phase 3 (universe expansion) — pulling 100+ tickers
on every run is slow enough to bias the engineer toward small, snoopable
universes.

## Required Reading

- `research_harness/data.py` (current loader)
- `research_harness/config.py` (where universe is hard-coded)
- `research_harness/__main__.py`, `run.py` (entry points)
- moomoo skill: `~/.claude/skills/moomooapi/` (already installed)

## Deliverables

### D1. Local parquet cache

Create `research_harness/data_store.py` with:

```python
def load_prices(
    symbols: Sequence[str],
    start: str,
    end: str | None,
    *,
    source: Literal["yfinance", "moomoo"] = "yfinance",
    cache_root: Path = Path("data/cache"),
    refresh: bool = False,
) -> pd.DataFrame:
    """
    Returns a long-form frame with columns:
        date, symbol, open, high, low, close, adj_close, volume, source
    Adjustments are applied point-in-time: a row dated 2022-06-15 reflects
    only corporate actions known on or before 2022-06-15.
    """
```

Implementation rules:
- Cache one parquet file per `symbol` under `data/cache/<source>/<symbol>.parquet`.
- Each file stores **unadjusted** OHLCV plus a separate `corporate_actions`
  table (`data/cache/<source>/_corp/<symbol>.parquet`) so adjustments can be
  recomputed point-in-time.
- The public `load_prices` returns adjusted prices computed on the fly with
  knowledge cut off at each row's date.
- Cache hit / miss / partial-update logic uses file metadata, not directory
  listing — concurrent runs must not corrupt files.
- Failed downloads are retried with backoff and logged, never silently swallowed.

### D2. Universe definitions

Create `research_harness/universes.py`:

```python
ETF_CORE_4: tuple[str, ...]          # current SPY/QQQ/GLD/TLT (proposal track)
ETF_SECTOR_11: tuple[str, ...]       # 11 SPDR sector ETFs
SP500_LIQUID: tuple[str, ...]        # top-N S&P 500 names by 60-day median ADV
                                     # frozen as-of a stated date with comment
```

Each universe constant must include a docstring stating:
- selection rule
- as-of date
- known biases (e.g. SP500_LIQUID is survivorship-biased; document and warn)

### D3. moomoo realtime adapter (read-only, no orders)

Create `research_harness/feed/moomoo_feed.py`:

```python
class MoomooQuoteFeed:
    def __init__(self, host: str = "127.0.0.1", port: int = 11111): ...
    def connect(self) -> None: ...
    def subscribe(self, symbols: Sequence[str]) -> None: ...
    def latest_quote(self, symbol: str) -> Quote: ...
    def stream_bars(self, symbols: Sequence[str], interval: str) -> Iterator[Bar]: ...
    def close(self) -> None: ...
```

Wrap the moomoo OpenAPI Python SDK. No order-placing methods on this class —
quote read-only. If OpenD is not running, `connect()` raises a clear, typed
`OpenDUnavailable` error; do not silently fail or fall back.

### D4. Tests

Add `tests/test_data_store.py`:
- builds a tiny synthetic OHLCV frame, writes parquet, reads back, asserts
  point-in-time adjustment is correct on a synthetic split
- asserts that requesting a date range partially in cache and partially out
  produces a single contiguous frame
- asserts that a known-delisted ticker (use a local fixture, do not hit the
  network in tests) raises a typed `SymbolDelisted` warning, not a silent drop

Add `tests/test_universes.py`:
- asserts each universe constant is non-empty, sorted, deduplicated
- asserts docstrings mention as-of date and bias notes

Do **not** write tests that hit the network or moomoo OpenD. The realtime
adapter has an interface test only (mock the SDK).

### D5. Wire `research_harness/data.py` to the new store

Replace the body of `load_prices` in `data.py` with a call to
`data_store.load_prices`. Existing callers must keep working with no API
change. If the wide-frame shape is needed downstream, add a thin adapter,
do not change the cache representation.

### D6. Documentation

Add `docs/DATA.md`:
- where the cache lives, how to nuke and rebuild it,
- how to add a new source,
- how to register a new universe,
- the explicit list of biases in each shipped universe.

## Acceptance Criteria

1. `pytest tests/` passes; new tests cover the cases listed above.
2. `python -m research_harness.run --track proposal` runs end-to-end on the
   ETF_CORE_4 universe and produces the same metrics as before (within
   floating-point tolerance) — i.e. swapping the data layer does not change
   strategy output.
3. A second invocation of the same command completes in under 10% of the
   first run's time (cache hit).
4. `MoomooQuoteFeed` has interface tests but is **not** invoked by the
   research harness — that wiring is Phase 5's job.
5. `docs/DATA.md` is committed.
6. `artifacts/phase-2-report.md` exists and lists: files added, files
   modified, tests added, known limitations, and what is explicitly NOT done
   (e.g. "Polygon source is not implemented; interface allows it").

## Out Of Scope For Phase 2

- moomoo order-placing (Phase 5)
- new strategies or factor expansion (Phase 3)
- options chain data (deferred until Phase 5 or later)
- a full corporate-actions database — the point-in-time adjustment can use
  yfinance's split/dividend stream as the source of truth for now, but the
  schema must allow swapping to a higher-quality feed later.

## Stop Conditions

Stop and ask the user if:
- yfinance is rate-limited or its API changes shape mid-task,
- moomoo Python SDK installation requires `unlock_trade` or any privileged
  scope (it should not, for quote-only),
- the existing harness output drifts after the swap (this means the old
  loader was hiding a bug — surface it, do not paper over).
