"""
Tests for research_harness.validation — TimeSplit and make_walk_forward_splits.

Verifies:
  - Monotonicity: train < select < test
  - No leakage: select window never overlaps train or test
  - Coverage: dates inside the index produce at least one split
  - Short index returns empty list
  - TimeSplit invariant checks on bad input
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from research_harness.validation import TimeSplit, make_walk_forward_splits


# ---------------------------------------------------------------------------
# TimeSplit dataclass invariants
# ---------------------------------------------------------------------------

def test_timesplit_good() -> None:
    s = TimeSplit(
        train=(date(2020, 1, 2), date(2021, 12, 31)),
        select=(date(2022, 1, 3), date(2022, 6, 30)),
        test=(date(2022, 7, 1), date(2022, 12, 30)),
        split_id=0,
    )
    assert s.split_id == 0


def test_timesplit_rejects_overlapping_train_select() -> None:
    with pytest.raises(AssertionError):
        TimeSplit(
            train=(date(2020, 1, 2), date(2022, 6, 30)),
            select=(date(2022, 1, 3), date(2022, 9, 30)),  # overlaps train end
            test=(date(2022, 10, 1), date(2022, 12, 30)),
            split_id=0,
        )


def test_timesplit_rejects_overlapping_select_test() -> None:
    with pytest.raises(AssertionError):
        TimeSplit(
            train=(date(2020, 1, 2), date(2021, 12, 31)),
            select=(date(2022, 1, 3), date(2022, 9, 30)),
            test=(date(2022, 6, 1), date(2022, 12, 30)),  # overlaps select end
            split_id=0,
        )


# ---------------------------------------------------------------------------
# make_walk_forward_splits
# ---------------------------------------------------------------------------

def _long_index() -> pd.DatetimeIndex:
    """Generates ~5 years of trading days starting 2018-01-02."""
    return pd.date_range("2018-01-02", "2023-12-29", freq="B")


def test_splits_not_empty_for_long_index() -> None:
    idx = _long_index()
    splits = make_walk_forward_splits(
        idx,
        train_years=2.0,
        select_months=3,
        test_months=3,
        step_months=3,
    )
    assert len(splits) > 0, "Expected at least one split for a 5-year index"


def test_splits_empty_for_short_index() -> None:
    idx = pd.date_range("2022-01-03", periods=50, freq="B")
    splits = make_walk_forward_splits(
        idx,
        train_years=2.0,
        select_months=3,
        test_months=3,
        step_months=3,
    )
    assert len(splits) == 0


def test_no_leakage_train_select() -> None:
    """train end must be strictly before select start for every split."""
    idx = _long_index()
    splits = make_walk_forward_splits(
        idx, train_years=2.0, select_months=3, test_months=3, step_months=3
    )
    for s in splits:
        assert s.train[1] < s.select[0], (
            f"Split {s.split_id}: train end {s.train[1]} >= select start {s.select[0]}"
        )


def test_no_leakage_select_test() -> None:
    """select end must be strictly before test start for every split."""
    idx = _long_index()
    splits = make_walk_forward_splits(
        idx, train_years=2.0, select_months=3, test_months=3, step_months=3
    )
    for s in splits:
        assert s.select[1] < s.test[0], (
            f"Split {s.split_id}: select end {s.select[1]} >= test start {s.test[0]}"
        )


def test_splits_monotone_split_ids() -> None:
    idx = _long_index()
    splits = make_walk_forward_splits(
        idx, train_years=2.0, select_months=3, test_months=3, step_months=3
    )
    ids = [s.split_id for s in splits]
    assert ids == list(range(len(splits))), f"Split IDs not monotone: {ids}"


def test_test_windows_non_overlapping() -> None:
    """Each split's test start must be >= the previous split's test end."""
    idx = _long_index()
    splits = make_walk_forward_splits(
        idx, train_years=2.0, select_months=3, test_months=3, step_months=3
    )
    for prev, curr in zip(splits, splits[1:]):
        assert curr.test[0] > prev.test[0], (
            f"Split {curr.split_id} test starts at or before split {prev.split_id}: "
            f"{curr.test[0]} vs {prev.test[0]}"
        )


def test_test_dates_within_index() -> None:
    """All test dates must lie within the provided index."""
    idx = _long_index()
    splits = make_walk_forward_splits(
        idx, train_years=2.0, select_months=3, test_months=3, step_months=3
    )
    idx_min = idx[0].date()
    idx_max = idx[-1].date()
    for s in splits:
        assert s.test[0] >= idx_min
        assert s.test[1] <= idx_max, (
            f"Split {s.split_id} test end {s.test[1]} > index max {idx_max}"
        )


def test_multiple_splits_coverage() -> None:
    """A 5-year index with 2-year train + 3M select + 3M test + 3M step
    should produce roughly 4 splits."""
    idx = _long_index()
    splits = make_walk_forward_splits(
        idx, train_years=2.0, select_months=3, test_months=3, step_months=3
    )
    assert len(splits) >= 2, f"Expected >= 2 splits, got {len(splits)}"


# ---------------------------------------------------------------------------
# Costs module tests
# ---------------------------------------------------------------------------

def test_commission_minimum() -> None:
    from research_harness.costs import commission, MOOMOO_MIN_PER_ORDER_USD
    # 1 share at $1 → raw = $0.0049, minimum kicks in
    assert commission(1.0, 1.0) == MOOMOO_MIN_PER_ORDER_USD


def test_commission_large_order() -> None:
    from research_harness.costs import commission, MOOMOO_PER_SHARE_USD
    # 1000 shares at $100 → $4.90 > $0.99 minimum
    assert commission(1000.0, 100.0) == pytest.approx(1000.0 * MOOMOO_PER_SHARE_USD)


def test_sec_fee_only_on_sells() -> None:
    from research_harness.costs import compute_trade_cost
    buy = compute_trade_cost(shares=100.0, price=50.0, high=51.0, low=49.0, adv20_usd=1e6)
    sell = compute_trade_cost(shares=-100.0, price=50.0, high=51.0, low=49.0, adv20_usd=1e6)
    assert buy.sec_fee_usd == 0.0
    assert sell.sec_fee_usd > 0.0


def test_finra_taf_only_on_sells() -> None:
    from research_harness.costs import compute_trade_cost
    buy = compute_trade_cost(shares=100.0, price=50.0, high=51.0, low=49.0, adv20_usd=1e6)
    sell = compute_trade_cost(shares=-100.0, price=50.0, high=51.0, low=49.0, adv20_usd=1e6)
    assert buy.finra_taf_usd == 0.0
    assert sell.finra_taf_usd > 0.0


def test_total_cost_positive() -> None:
    from research_harness.costs import compute_trade_cost
    cost = compute_trade_cost(shares=500.0, price=100.0, high=101.0, low=99.0, adv20_usd=5e6)
    assert cost.total_usd > 0.0
    assert cost.bps > 0.0


def test_zero_shares_zero_cost() -> None:
    from research_harness.costs import compute_trade_cost
    cost = compute_trade_cost(shares=0.0, price=100.0, high=101.0, low=99.0, adv20_usd=1e6)
    # Commission is 0 (no trade); spread and impact are 0 (0 notional)
    assert cost.commission_usd == 0.0
    assert cost.total_usd == 0.0


def test_legacy_shim_warns() -> None:
    from research_harness.costs import legacy_cost_bps
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = legacy_cost_bps(0.1, 5.0)
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
    assert result == pytest.approx(0.1 * 5.0 / 10_000.0)
