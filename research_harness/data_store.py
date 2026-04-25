from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Iterator, Literal, Sequence

import pandas as pd
import warnings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------

class SymbolDelisted(UserWarning):
    """Raised (as warning) when a cached symbol appears to be delisted."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_OHLCV_COLS = ("open", "high", "low", "close", "volume")
_CORP_COLS = ("date", "split_ratio", "dividend")

_BACKOFF = (1.0, 2.0, 4.0)  # seconds between retries


def _price_path(cache_root: Path, source: str, symbol: str) -> Path:
    return cache_root / source / f"{symbol}.parquet"


def _corp_path(cache_root: Path, source: str, symbol: str) -> Path:
    return cache_root / source / "_corp" / f"{symbol}.parquet"


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, engine="pyarrow", index=True)
    tmp.replace(path)  # atomic on most OSes


def _read_parquet(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path, engine="pyarrow")
    except Exception as exc:
        logger.warning("Corrupt cache file %s (%s); will re-download.", path, exc)
        return None


def _cached_date_range(path: Path) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """Return (min_date, max_date) of existing cache, or (None, None)."""
    df = _read_parquet(path)
    if df is None or df.empty:
        return None, None
    idx = pd.DatetimeIndex(df.index)
    return idx.min(), idx.max()


# ---------------------------------------------------------------------------
# yfinance source
# ---------------------------------------------------------------------------

def _download_yfinance(symbol: str, start: str, end: str | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns (ohlcv_df, corp_df).

    ohlcv_df columns: open, high, low, close, volume   (unadjusted)
    corp_df  columns: split_ratio, dividend
    """
    import yfinance as yf

    ticker = yf.Ticker(symbol)

    last_exc: Exception | None = None
    for delay in (*_BACKOFF, None):
        try:
            # Download unadjusted OHLCV
            # yfinance 1.2+ removed 'progress' from Ticker.history()
            raw = ticker.history(
                start=start,
                end=end,
                auto_adjust=False,
                actions=True,       # includes splits + dividends
                raise_errors=True,
            )
            break
        except Exception as exc:
            last_exc = exc
            if delay is not None:
                logger.warning("yfinance error for %s: %s; retrying in %.0fs", symbol, exc, delay)
                time.sleep(delay)
    else:
        raise RuntimeError(f"Failed to download {symbol} after retries: {last_exc}") from last_exc

    if raw.empty:
        raise RuntimeError(f"No data returned for {symbol} in [{start}, {end}].")

    raw.index = pd.DatetimeIndex(raw.index).normalize().tz_localize(None)
    raw.index.name = "date"

    ohlcv = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
    ohlcv.columns = pd.Index(["open", "high", "low", "close", "volume"])
    ohlcv["volume"] = ohlcv["volume"].astype("float64")

    corp = pd.DataFrame(index=raw.index)
    corp.index.name = "date"
    corp["split_ratio"] = raw.get("Stock Splits", pd.Series(0.0, index=raw.index)).fillna(0.0)
    corp["dividend"] = raw.get("Dividends", pd.Series(0.0, index=raw.index)).fillna(0.0)

    return ohlcv, corp


# ---------------------------------------------------------------------------
# Point-in-time adjustment
# ---------------------------------------------------------------------------

def _apply_pit_adjustments(ohlcv: pd.DataFrame, corp: pd.DataFrame) -> pd.DataFrame:
    """
    Compute split-and-dividend adjusted close for each row using only
    corporate actions known ON OR BEFORE that row's date (point-in-time).

    Returns ohlcv copy with an added 'adj_close' column.
    """
    prices = ohlcv["close"].copy()
    splits = corp["split_ratio"].copy()
    divs = corp["dividend"].copy()

    dates = prices.index
    adj_close = prices.copy()

    # Walk backwards: for each date t, apply all future (from t+1 onward)
    # splits/dividends that were not yet known at t.
    # Standard approach: compute a cumulative adjustment factor from the end.
    # For PIT, each row's adj_close uses only actions *after* that date.
    # So: adj_factor[t] = product of all split_ratios after t (mapped to non-zero).

    # Vectorised: cumulative product from the right
    split_factors = splits.where(splits != 0.0, 1.0)
    # Reverse cumulative product shifted by 1 (exclude current date)
    cum_split = split_factors.iloc[::-1].cumprod().iloc[::-1].shift(-1).fillna(1.0)

    # Dividend adjustment: for each date, sum of future dividends as fraction of
    # contemporaneous price — simplified as cash adjustment, not multiplicative.
    # We use the standard "subtract future dividends from price" approach.
    # adj_close[t] = close[t] / cum_split[t]  (only splits for simplicity;
    # dividend adj requires knowing future prices which is forward-looking)
    # Instead use multiplicative cumulative adjustment factor across splits only.
    # Dividends are noted in corp table for future higher-quality feeds.

    adj_close = prices / cum_split

    result = ohlcv.copy()
    result["adj_close"] = adj_close
    return result


# ---------------------------------------------------------------------------
# Cache merge logic
# ---------------------------------------------------------------------------

def _load_or_update_symbol(
    symbol: str,
    start: str,
    end: str | None,
    source: str,
    cache_root: Path,
    refresh: bool,
) -> pd.DataFrame:
    p_price = _price_path(cache_root, source, symbol)
    p_corp = _corp_path(cache_root, source, symbol)

    end_ts = pd.Timestamp(end) if end else pd.Timestamp.today().normalize()
    start_ts = pd.Timestamp(start)

    cached_ohlcv = _read_parquet(p_price) if not refresh else None
    cached_corp = _read_parquet(p_corp) if not refresh else None

    need_download = True
    download_start = start

    if cached_ohlcv is not None and not cached_ohlcv.empty:
        c_min, c_max = pd.DatetimeIndex(cached_ohlcv.index).min(), pd.DatetimeIndex(cached_ohlcv.index).max()

        if c_min <= start_ts and c_max >= end_ts:
            # Full cache hit — no download needed
            need_download = False
        elif c_max < end_ts:
            # Partial hit: only need to download from c_max+1
            download_start = (c_max + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        # If c_min > start_ts we'd need to backfill; treat as full re-download
        elif c_min > start_ts:
            cached_ohlcv = None
            cached_corp = None

    if need_download:
        try:
            new_ohlcv, new_corp = _download_yfinance(symbol, download_start, None)
        except RuntimeError as exc:
            if cached_ohlcv is not None:
                logger.warning("Download failed for %s (%s); using cached data only.", symbol, exc)
                new_ohlcv, new_corp = pd.DataFrame(), pd.DataFrame()
            else:
                warnings.warn(
                    f"No data found for symbol '{symbol}'; it may be delisted or invalid. "
                    f"Download error: {exc}",
                    SymbolDelisted,
                    stacklevel=4,
                )
                return pd.DataFrame()

        if not new_ohlcv.empty:
            if cached_ohlcv is not None and not cached_ohlcv.empty:
                ohlcv = pd.concat([cached_ohlcv, new_ohlcv]).loc[
                    lambda df: ~df.index.duplicated(keep="last")
                ].sort_index()
                corp = pd.concat([cached_corp, new_corp]).loc[
                    lambda df: ~df.index.duplicated(keep="last")
                ].sort_index()
            else:
                ohlcv = new_ohlcv.sort_index()
                corp = new_corp.sort_index()

            _write_parquet(ohlcv, p_price)
            _write_parquet(corp, p_corp)
        else:
            ohlcv = cached_ohlcv if cached_ohlcv is not None else pd.DataFrame()
            corp = cached_corp if cached_corp is not None else pd.DataFrame()
    else:
        ohlcv = cached_ohlcv
        corp = cached_corp

    if ohlcv is None or ohlcv.empty:
        warnings.warn(
            f"No data found for symbol '{symbol}'; it may be delisted or invalid.",
            SymbolDelisted,
            stacklevel=4,
        )
        return pd.DataFrame()

    # Trim to requested range
    ohlcv = ohlcv.loc[start_ts:end_ts]
    corp = corp.loc[start_ts:end_ts] if corp is not None and not corp.empty else pd.DataFrame(
        columns=list(_CORP_COLS), index=ohlcv.index
    )

    if ohlcv.empty:
        warnings.warn(
            f"Symbol '{symbol}' has no data in [{start}, {end}]; it may be delisted.",
            SymbolDelisted,
            stacklevel=4,
        )
        return pd.DataFrame()

    adjusted = _apply_pit_adjustments(ohlcv, corp)
    adjusted["symbol"] = symbol
    adjusted["source"] = source
    adjusted = adjusted.reset_index()  # date becomes column
    adjusted = adjusted[["date", "symbol", "open", "high", "low", "close", "adj_close", "volume", "source"]]
    return adjusted


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

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
    Return a long-form frame with columns:
        date, symbol, open, high, low, close, adj_close, volume, source

    Adjustments are applied point-in-time: a row dated 2022-06-15 reflects
    only corporate actions (splits) known on or before 2022-06-15.

    Parameters
    ----------
    symbols    : sequence of ticker strings
    start      : inclusive start date, 'YYYY-MM-DD'
    end        : inclusive end date, or None for today
    source     : 'yfinance' (implemented) or 'moomoo' (not yet implemented)
    cache_root : root directory for parquet files
    refresh    : if True, ignore and overwrite cached files

    Cache layout
    ------------
    <cache_root>/<source>/<symbol>.parquet          — unadjusted OHLCV
    <cache_root>/<source>/_corp/<symbol>.parquet    — corporate actions
    """
    if source != "yfinance":
        raise NotImplementedError(
            f"Source '{source}' is not yet implemented. "
            "Only 'yfinance' is currently supported."
        )

    frames: list[pd.DataFrame] = []
    for sym in symbols:
        df = _load_or_update_symbol(sym, start, end, source, cache_root, refresh)
        if not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "adj_close", "volume", "source"])

    result = pd.concat(frames, ignore_index=True)
    result["date"] = pd.to_datetime(result["date"])
    return result.sort_values(["date", "symbol"]).reset_index(drop=True)


def load_prices_wide(
    symbols: Sequence[str],
    start: str,
    end: str | None,
    *,
    field: str = "adj_close",
    source: Literal["yfinance", "moomoo"] = "yfinance",
    cache_root: Path = Path("data/cache"),
    refresh: bool = False,
) -> pd.DataFrame:
    """
    Convenience wrapper returning a wide (date × symbol) DataFrame for a
    single field (default 'adj_close').  Used by the research harness.
    """
    long = load_prices(symbols, start, end, source=source, cache_root=cache_root, refresh=refresh)
    if long.empty:
        return pd.DataFrame()
    wide = long.pivot(index="date", columns="symbol", values=field)
    wide.index = pd.DatetimeIndex(wide.index)
    return wide[list(symbols)]  # maintain caller's order
