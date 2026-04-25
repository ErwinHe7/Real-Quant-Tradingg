"""
Three-fold temporal validation splits for walk-forward research.

The key invariant: any reported metric must come from the *test* window of a
split whose hyperparameters were selected on the *select* window and whose
models were trained only on the *train* window.

No data from a later split may influence an earlier split's model fitting.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class TimeSplit:
    """
    A single train / select / test temporal split.

    Attributes
    ----------
    train   : (start, end) inclusive — model fitting window
    select  : (start, end) inclusive — hyperparameter selection window
    test    : (start, end) inclusive — final evaluation; touched ONCE
    split_id: zero-based index in the walk-forward sequence
    """
    train:    tuple[date, date]
    select:   tuple[date, date]
    test:     tuple[date, date]
    split_id: int

    def __post_init__(self) -> None:
        assert self.train[0] <= self.train[1], "train start must be <= end"
        assert self.train[1] < self.select[0], "select must start after train ends"
        assert self.select[0] <= self.select[1], "select start must be <= end"
        assert self.select[1] < self.test[0], "test must start after select ends"
        assert self.test[0] <= self.test[1], "test start must be <= end"


import pandas as pd


def make_walk_forward_splits(
    index: pd.DatetimeIndex,
    *,
    train_years: float,
    select_months: int,
    test_months: int,
    step_months: int,
) -> list[TimeSplit]:
    """
    Generate a list of non-overlapping walk-forward TimeSplits from *index*.

    Each split advances by *step_months* relative to the previous split's
    test start.  The train window grows (expanding window) up to
    *train_years* years, then rolls.

    Parameters
    ----------
    index         : sorted DatetimeIndex of trading dates
    train_years   : minimum training window length in years
    select_months : length of hyperparameter selection window in months
    test_months   : length of test window in months
    step_months   : how far to advance each split's test start

    Returns
    -------
    list[TimeSplit] — may be empty if the index is too short for even one split

    Invariants checked
    ------------------
    - train ends strictly before select starts
    - select ends strictly before test starts
    - test window lies within the provided index
    """
    if index.empty:
        return []

    all_dates = index.normalize().sort_values()
    min_date = all_dates[0].date()
    max_date = all_dates[-1].date()

    splits: list[TimeSplit] = []
    split_id = 0

    # Step through possible test-start dates
    train_end_approx = pd.Timestamp(min_date) + pd.DateOffset(years=train_years)
    select_end_approx = train_end_approx + pd.DateOffset(months=select_months)
    test_start_cursor = select_end_approx + pd.Timedelta(days=1)

    while True:
        test_start_ts = test_start_cursor
        test_end_ts = test_start_ts + pd.DateOffset(months=test_months) - pd.Timedelta(days=1)

        if test_end_ts.date() > max_date:
            break  # not enough data for a full test window

        # Find the actual trading-day boundaries within the index
        select_end_ts = test_start_ts - pd.Timedelta(days=1)
        select_start_ts = select_end_ts - pd.DateOffset(months=select_months) + pd.Timedelta(days=1)
        train_end_ts = select_start_ts - pd.Timedelta(days=1)

        # Expanding train: go back train_years from train_end
        train_start_ts = train_end_ts - pd.DateOffset(years=train_years) + pd.Timedelta(days=1)
        if train_start_ts.date() < min_date:
            train_start_ts = pd.Timestamp(min_date)

        # All windows must have at least one trading day
        train_dates = all_dates[(all_dates >= train_start_ts) & (all_dates <= train_end_ts)]
        select_dates = all_dates[(all_dates >= select_start_ts) & (all_dates <= select_end_ts)]
        test_dates = all_dates[(all_dates >= test_start_ts) & (all_dates <= test_end_ts)]

        if len(train_dates) < 20 or len(select_dates) < 5 or len(test_dates) < 5:
            test_start_cursor += pd.DateOffset(months=step_months)
            continue

        splits.append(
            TimeSplit(
                train=(train_dates[0].date(), train_dates[-1].date()),
                select=(select_dates[0].date(), select_dates[-1].date()),
                test=(test_dates[0].date(), test_dates[-1].date()),
                split_id=split_id,
            )
        )
        split_id += 1
        test_start_cursor += pd.DateOffset(months=step_months)

    return splits
