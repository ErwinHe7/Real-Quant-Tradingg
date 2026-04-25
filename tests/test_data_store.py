"""
Tests for research_harness.data_store.

All tests are offline — no network calls, no moomoo OpenD required.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research_harness.data_store import (
    SymbolDelisted,
    _apply_pit_adjustments,
    _price_path,
    _corp_path,
    _write_parquet,
    _read_parquet,
    load_prices,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ohlcv(dates: pd.DatetimeIndex) -> pd.DataFrame:
    n = len(dates)
    rng = np.random.default_rng(42)
    close = 100.0 + rng.standard_normal(n).cumsum()
    df = pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.002,
            "low": close * 0.997,
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, size=n).astype("float64"),
        },
        index=dates,
    )
    df.index.name = "date"
    return df


def _make_corp(dates: pd.DatetimeIndex, split_idx: int | None = None) -> pd.DataFrame:
    df = pd.DataFrame(
        {"split_ratio": 0.0, "dividend": 0.0},
        index=dates,
    )
    df.index.name = "date"
    if split_idx is not None:
        df.iloc[split_idx, df.columns.get_loc("split_ratio")] = 2.0
    return df


# ---------------------------------------------------------------------------
# Test: parquet round-trip
# ---------------------------------------------------------------------------

def test_parquet_roundtrip(tmp_path: Path) -> None:
    dates = pd.date_range("2022-01-03", periods=20, freq="B")
    ohlcv = _make_ohlcv(dates)
    path = tmp_path / "SPY.parquet"
    _write_parquet(ohlcv, path)
    loaded = _read_parquet(path)
    assert loaded is not None
    # Parquet does not preserve DatetimeIndex freq; check_freq=False to tolerate
    pd.testing.assert_frame_equal(loaded, ohlcv, check_freq=False)


def test_read_parquet_missing_returns_none(tmp_path: Path) -> None:
    result = _read_parquet(tmp_path / "nonexistent.parquet")
    assert result is None


# ---------------------------------------------------------------------------
# Test: point-in-time adjustment is correct after a synthetic 2-for-1 split
# ---------------------------------------------------------------------------

def test_pit_adjustment_synthetic_split() -> None:
    """
    Scenario
    --------
    Prices are flat at 100.0 for 10 days.
    A 2-for-1 split occurs on day 5 (index 5 in corp).
    For rows 0–4 (before the split date), cum_split applied forward means
    the split event is AFTER those rows, so adj_close[0:5] should be 50.0
    (price / 2) because the split is known in the future.
    For rows 5–9, the split is at or before their date, so they also reflect
    it. (Our implementation applies future splits to earlier rows.)

    Concretely: adj_close[t] = close[t] / (product of split_ratios after t)

    With a split_ratio=2 at index 5:
    - rows 0..4: cum_split = 2.0, adj_close = 100/2 = 50.0
    - rows 5..9: cum_split = 1.0 (shift(-1) after the split = no further splits),
                  adj_close = 100.0
    """
    dates = pd.date_range("2022-01-03", periods=10, freq="B")
    ohlcv = _make_ohlcv(dates)
    ohlcv["close"] = 100.0  # flat for clarity

    corp = _make_corp(dates, split_idx=5)
    adjusted = _apply_pit_adjustments(ohlcv, corp)

    assert "adj_close" in adjusted.columns

    # Rows before the split: adj_close should be half of close (100/2)
    pre_split = adjusted["adj_close"].iloc[:5]
    np.testing.assert_allclose(pre_split.values, 50.0, rtol=1e-9)

    # Rows from the split onward: no future split, adj_close = close = 100
    post_split = adjusted["adj_close"].iloc[5:]
    np.testing.assert_allclose(post_split.values, 100.0, rtol=1e-9)


def test_pit_no_split_adj_equals_close() -> None:
    """Without any splits, adj_close must equal close."""
    dates = pd.date_range("2022-01-03", periods=10, freq="B")
    ohlcv = _make_ohlcv(dates)
    corp = _make_corp(dates)  # no splits
    adjusted = _apply_pit_adjustments(ohlcv, corp)
    np.testing.assert_allclose(
        adjusted["adj_close"].values,
        adjusted["close"].values,
        rtol=1e-9,
    )


# ---------------------------------------------------------------------------
# Test: cache hit / miss / partial with synthetic yfinance stub
# ---------------------------------------------------------------------------

def _make_long_frame(symbol: str, dates: pd.DatetimeIndex, adj: float = 1.0) -> pd.DataFrame:
    ohlcv = _make_ohlcv(dates)
    ohlcv["close"] = 100.0 * adj
    rows = []
    for date, row in ohlcv.iterrows():
        rows.append({
            "date": date,
            "symbol": symbol,
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "adj_close": row["close"],
            "volume": row["volume"],
            "source": "yfinance",
        })
    return pd.DataFrame(rows)


def test_cache_write_and_read_back(tmp_path: Path) -> None:
    """
    Write a synthetic parquet cache directly, then verify load_prices
    reads it back and returns a correctly shaped long-form frame.
    """
    symbol = "FAKE"
    dates = pd.date_range("2022-01-03", periods=20, freq="B")
    ohlcv = _make_ohlcv(dates)
    corp = _make_corp(dates)

    price_p = _price_path(tmp_path, "yfinance", symbol)
    corp_p = _corp_path(tmp_path, "yfinance", symbol)
    _write_parquet(ohlcv, price_p)
    _write_parquet(corp, corp_p)

    # Patch yfinance download to never be called (cache should hit)
    import unittest.mock as mock
    with mock.patch("research_harness.data_store._download_yfinance") as mock_dl:
        result = load_prices(
            [symbol],
            start="2022-01-03",
            end="2022-01-28",
            cache_root=tmp_path,
        )
        mock_dl.assert_not_called()

    assert not result.empty
    assert set(result.columns) >= {"date", "symbol", "open", "high", "low", "close", "adj_close", "volume", "source"}
    assert (result["symbol"] == symbol).all()


def test_partial_cache_produces_contiguous_frame(tmp_path: Path) -> None:
    """
    Scenario: cache covers 2022-01-03 to 2022-01-21 (15 trading days).
    Request covers 2022-01-03 to 2022-02-11 (30 trading days).
    The missing tail (2022-01-24 to 2022-02-11) must be downloaded and
    merged, producing a single contiguous frame.
    """
    symbol = "FAKE2"
    dates_cached = pd.date_range("2022-01-03", periods=15, freq="B")
    dates_new = pd.date_range("2022-01-24", periods=15, freq="B")

    ohlcv_cached = _make_ohlcv(dates_cached)
    corp_cached = _make_corp(dates_cached)

    price_p = _price_path(tmp_path, "yfinance", symbol)
    corp_p = _corp_path(tmp_path, "yfinance", symbol)
    _write_parquet(ohlcv_cached, price_p)
    _write_parquet(corp_cached, corp_p)

    ohlcv_new = _make_ohlcv(dates_new)
    corp_new = _make_corp(dates_new)

    import unittest.mock as mock
    with mock.patch(
        "research_harness.data_store._download_yfinance",
        return_value=(ohlcv_new, corp_new),
    ) as mock_dl:
        result = load_prices(
            [symbol],
            start="2022-01-03",
            end="2022-02-11",
            cache_root=tmp_path,
        )
        mock_dl.assert_called_once()

    assert not result.empty
    result_dates = pd.DatetimeIndex(result["date"]).sort_values()
    # Should be contiguous (no gap larger than 3 calendar days = weekend)
    gaps = (result_dates[1:] - result_dates[:-1]).days
    assert (gaps <= 3).all(), f"Found gap > 3 calendar days: max gap = {gaps.max()}"
    # Must span both cached and new ranges
    assert result_dates.min() <= pd.Timestamp("2022-01-03")
    assert result_dates.max() >= pd.Timestamp("2022-02-11")


# ---------------------------------------------------------------------------
# Test: known-delisted ticker raises SymbolDelisted warning
# ---------------------------------------------------------------------------

def test_delisted_symbol_raises_warning(tmp_path: Path) -> None:
    """
    If yfinance returns empty data for a symbol (simulating a delisted name),
    load_prices must emit a SymbolDelisted warning rather than silently
    returning an empty frame without warning.
    """
    import unittest.mock as mock

    def _empty_download(symbol, start, end):
        raise RuntimeError(f"No data returned for {symbol} in [{start}, {end}].")

    with mock.patch("research_harness.data_store._download_yfinance", side_effect=_empty_download):
        with pytest.warns(SymbolDelisted):
            result = load_prices(
                ["DLST"],
                start="2020-01-01",
                end="2020-12-31",
                cache_root=tmp_path,
            )

    assert result.empty


# ---------------------------------------------------------------------------
# Test: return frame columns and dtypes
# ---------------------------------------------------------------------------

def test_long_frame_columns(tmp_path: Path) -> None:
    """load_prices must return exactly the documented column set."""
    symbol = "FAKE3"
    dates = pd.date_range("2022-01-03", periods=10, freq="B")
    ohlcv = _make_ohlcv(dates)
    corp = _make_corp(dates)
    _write_parquet(ohlcv, _price_path(tmp_path, "yfinance", symbol))
    _write_parquet(corp, _corp_path(tmp_path, "yfinance", symbol))

    import unittest.mock as mock
    with mock.patch("research_harness.data_store._download_yfinance") as mock_dl:
        result = load_prices([symbol], start="2022-01-03", end="2022-01-14", cache_root=tmp_path)
        mock_dl.assert_not_called()

    expected_cols = {"date", "symbol", "open", "high", "low", "close", "adj_close", "volume", "source"}
    assert set(result.columns) == expected_cols
    assert pd.api.types.is_datetime64_any_dtype(result["date"])
    # pandas 3.x may use StringDtype instead of object for string columns
    assert pd.api.types.is_string_dtype(result["symbol"])


# ---------------------------------------------------------------------------
# Test: unsupported source raises NotImplementedError
# ---------------------------------------------------------------------------

def test_unsupported_source_raises(tmp_path: Path) -> None:
    with pytest.raises(NotImplementedError, match="moomoo"):
        load_prices(["SPY"], "2022-01-01", None, source="moomoo", cache_root=tmp_path)  # type: ignore[arg-type]
