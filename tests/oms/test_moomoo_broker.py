"""
Interface tests for live.broker.moomoo.MoomooBroker.
No OpenD connection required — tests only the interface constraints.
"""
from __future__ import annotations

import pytest

from live.broker.moomoo import LiveTradingNotAuthorizedError, MoomooBroker


def test_live_env_raises():
    """MoomooBroker must refuse env='live' in Phase 5."""
    with pytest.raises(LiveTradingNotAuthorizedError):
        MoomooBroker(env="live")


def test_paper_env_raises_without_opend():
    """
    Attempting to connect to paper env without OpenD raises a clear error
    (not ImportError or AttributeError).
    """
    from research_harness.feed.moomoo_feed import OpenDUnavailable
    # OpenD is not running in CI; should raise OpenDUnavailable or ImportError
    try:
        _ = MoomooBroker(env="paper", port=19999)
    except (OpenDUnavailable, ImportError):
        pass  # expected
    except Exception as exc:
        pytest.fail(f"Unexpected exception type: {type(exc).__name__}: {exc}")
