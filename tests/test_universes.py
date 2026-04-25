"""
Tests for research_harness.universes.

Verifies structural invariants (non-empty, sorted, deduplicated) and that
docstrings contain required metadata (as-of date and bias notes).
"""
from __future__ import annotations

import inspect

import pytest

from research_harness.universes import ETF_CORE_4, ETF_SECTOR_11, SP500_LIQUID

ALL_UNIVERSES = [
    ("ETF_CORE_4", ETF_CORE_4),
    ("ETF_SECTOR_11", ETF_SECTOR_11),
    ("SP500_LIQUID", SP500_LIQUID),
]


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, universe", ALL_UNIVERSES)
def test_non_empty(name: str, universe: tuple) -> None:
    assert len(universe) > 0, f"{name} must not be empty"


@pytest.mark.parametrize("name, universe", ALL_UNIVERSES)
def test_sorted(name: str, universe: tuple) -> None:
    assert list(universe) == sorted(universe), (
        f"{name} must be sorted alphabetically; "
        f"first out-of-order pair: "
        + str(next((a, b) for a, b in zip(universe, universe[1:]) if a > b))
    )


@pytest.mark.parametrize("name, universe", ALL_UNIVERSES)
def test_deduplicated(name: str, universe: tuple) -> None:
    assert len(universe) == len(set(universe)), (
        f"{name} contains duplicate tickers: "
        f"{[t for t in universe if universe.count(t) > 1]}"
    )


@pytest.mark.parametrize("name, universe", ALL_UNIVERSES)
def test_all_uppercase(name: str, universe: tuple) -> None:
    non_upper = [t for t in universe if t != t.upper()]
    assert not non_upper, f"{name} contains non-uppercase tickers: {non_upper}"


# ---------------------------------------------------------------------------
# ETF_CORE_4 specific
# ---------------------------------------------------------------------------

def test_etf_core_4_contains_expected_tickers() -> None:
    assert set(ETF_CORE_4) == {"GLD", "QQQ", "SPY", "TLT"}


def test_etf_sector_11_has_eleven_members() -> None:
    assert len(ETF_SECTOR_11) == 11


def test_sp500_liquid_has_fifty_members() -> None:
    assert len(SP500_LIQUID) == 50


# ---------------------------------------------------------------------------
# Docstring metadata checks
# ---------------------------------------------------------------------------

import research_harness.universes as _mod


def _get_var_docstring(varname: str) -> str:
    """
    Extract the string literal immediately following a variable assignment
    from the module docstring stubs.  We use the module's __doc__-adjacent
    attribute pattern: for module-level variables, docstrings are stored
    directly as the next string literal in the source.
    """
    source = inspect.getsource(_mod)
    # Find the variable name and then look for the triple-quoted string after it
    idx = source.find(f"{varname}:")
    if idx == -1:
        return ""
    snippet = source[idx:]
    # Find the first triple-quoted string
    for q in ('"""', "'''"):
        start = snippet.find(q)
        if start == -1:
            continue
        end = snippet.find(q, start + 3)
        if end == -1:
            continue
        return snippet[start + 3 : end]
    return ""


@pytest.mark.parametrize("varname", ["ETF_CORE_4", "ETF_SECTOR_11", "SP500_LIQUID"])
def test_docstring_mentions_as_of_date(varname: str) -> None:
    doc = _get_var_docstring(varname)
    assert "as-of" in doc.lower() or "as of" in doc.lower(), (
        f"{varname} docstring must mention 'as-of date' or 'as of date'"
    )


@pytest.mark.parametrize("varname", ["ETF_CORE_4", "ETF_SECTOR_11", "SP500_LIQUID"])
def test_docstring_mentions_bias(varname: str) -> None:
    doc = _get_var_docstring(varname)
    assert "bias" in doc.lower(), (
        f"{varname} docstring must mention known biases"
    )


# ---------------------------------------------------------------------------
# Test: moomoo_feed interface (no OpenD connection required)
# ---------------------------------------------------------------------------

def test_moomoo_feed_raises_without_opend() -> None:
    """connect() must raise OpenDUnavailable when OpenD is not running."""
    from research_harness.feed.moomoo_feed import MoomooQuoteFeed, OpenDUnavailable

    # Use a port that is almost certainly not listening
    feed = MoomooQuoteFeed(host="127.0.0.1", port=19999)
    with pytest.raises(OpenDUnavailable):
        feed.connect()


def test_moomoo_feed_requires_connect_before_subscribe() -> None:
    """subscribe() before connect() raises OpenDUnavailable."""
    from research_harness.feed.moomoo_feed import MoomooQuoteFeed, OpenDUnavailable

    feed = MoomooQuoteFeed(host="127.0.0.1", port=19999)
    with pytest.raises(OpenDUnavailable):
        feed.subscribe(["SPY"])


def test_moomoo_feed_requires_connect_before_latest_quote() -> None:
    """latest_quote() before connect() raises OpenDUnavailable."""
    from research_harness.feed.moomoo_feed import MoomooQuoteFeed, OpenDUnavailable

    feed = MoomooQuoteFeed()
    with pytest.raises(OpenDUnavailable):
        feed.latest_quote("SPY")


def test_moomoo_feed_dataclasses_frozen() -> None:
    """Quote and Bar must be frozen dataclasses (immutable)."""
    from research_harness.feed.moomoo_feed import Bar, Quote

    q = Quote(symbol="SPY", last_price=400.0, bid=399.9, ask=400.1, volume=1_000_000, timestamp=1.0)
    with pytest.raises((AttributeError, TypeError)):
        q.last_price = 999.0  # type: ignore[misc]

    b = Bar(symbol="SPY", interval="1d", open=398.0, high=402.0, low=397.0, close=400.0, volume=5_000_000, timestamp=1.0)
    with pytest.raises((AttributeError, TypeError)):
        b.close = 999.0  # type: ignore[misc]
