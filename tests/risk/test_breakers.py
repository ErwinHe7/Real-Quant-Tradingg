"""
Tests for live.risk.breakers — DrawdownBreaker, DailyLossBreaker, KillSwitch.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from live.risk.breakers import BreakerState, DailyLossBreaker, DrawdownBreaker, KillSwitch


# ---------------------------------------------------------------------------
# DrawdownBreaker
# ---------------------------------------------------------------------------

def test_drawdown_breaker_arms_initially():
    b = DrawdownBreaker(max_dd_pct=0.15, cool_off_days=5)
    eq = pd.Series([100.0, 101.0, 102.0])
    state = b.update(eq)
    assert state == BreakerState.ARMED


def test_drawdown_breaker_fires_on_large_dd():
    b = DrawdownBreaker(max_dd_pct=0.15)
    eq = pd.Series([100.0, 110.0, 93.0])  # DD from 110 = (110-93)/110 = 15.5% > 15%
    state = b.update(eq)
    assert state == BreakerState.ENGAGED


def test_drawdown_breaker_does_not_fire_below_threshold():
    b = DrawdownBreaker(max_dd_pct=0.15)
    eq = pd.Series([100.0, 110.0, 96.0])  # DD = (110-96)/110 = 12.7% < 15%
    state = b.update(eq)
    assert state == BreakerState.ARMED


def test_drawdown_cool_off_required_before_rearm():
    b = DrawdownBreaker(max_dd_pct=0.15, cool_off_days=5)
    eq = pd.Series([100.0, 110.0, 93.0])  # fires
    b.update(eq)
    assert b.state == BreakerState.ENGAGED

    b.disengage()
    assert b.state == BreakerState.COOLING
    # Should still be cooling (cool-off not expired)
    b.update(pd.Series([93.0, 95.0]))
    assert b.state == BreakerState.COOLING


def test_drawdown_breaker_survives_disk_roundtrip(tmp_path):
    """Write state to disk, re-load, verify state is preserved."""
    path = tmp_path / "drawdown.json"
    b = DrawdownBreaker(max_dd_pct=0.15)
    eq = pd.Series([100.0, 110.0, 93.0])
    b.update(eq)
    assert b.state == BreakerState.ENGAGED

    b.save(path)

    b2 = DrawdownBreaker(max_dd_pct=0.15, state_path=path)
    assert b2.state == BreakerState.ENGAGED


# ---------------------------------------------------------------------------
# DailyLossBreaker
# ---------------------------------------------------------------------------

def test_daily_loss_breaker_arms_initially():
    b = DailyLossBreaker(max_loss_pct=0.03)
    state = b.update(day_pnl=0.0, equity=10_000.0)
    assert state == BreakerState.ARMED


def test_daily_loss_breaker_fires():
    b = DailyLossBreaker(max_loss_pct=0.03)
    # day_start set on first call
    b.update(day_pnl=0.0, equity=10_000.0)
    # Now simulate $400 loss on $10K = 4% > 3%
    state = b.update(day_pnl=-400.0, equity=9_600.0)
    assert state == BreakerState.ENGAGED


def test_daily_loss_breaker_does_not_fire_below_threshold():
    b = DailyLossBreaker(max_loss_pct=0.03)
    b.update(day_pnl=0.0, equity=10_000.0)
    state = b.update(day_pnl=-200.0, equity=9_800.0)  # 2% loss
    assert state == BreakerState.ARMED


# ---------------------------------------------------------------------------
# KillSwitch
# ---------------------------------------------------------------------------

def test_kill_switch_not_engaged_initially(tmp_path):
    ks = KillSwitch(state_root=tmp_path)
    assert not ks.is_engaged()


def test_kill_switch_engage_and_check(tmp_path):
    ks = KillSwitch(state_root=tmp_path)
    ks.engage("test reason")
    assert ks.is_engaged()
    assert ks.read_reason() == "test reason"


def test_kill_switch_disengage_requires_human_token(tmp_path):
    ks = KillSwitch(state_root=tmp_path)
    ks.engage("test")
    with pytest.raises(PermissionError):
        ks.disengage("")  # empty token


def test_kill_switch_rejects_agent_token(tmp_path):
    ks = KillSwitch(state_root=tmp_path)
    ks.engage("test")
    with pytest.raises(PermissionError, match="reserved"):
        ks.disengage("AGENT")


def test_kill_switch_rejects_system_token(tmp_path):
    ks = KillSwitch(state_root=tmp_path)
    ks.engage("test")
    with pytest.raises(PermissionError):
        ks.disengage("SYSTEM")


def test_kill_switch_accepts_human_token(tmp_path):
    ks = KillSwitch(state_root=tmp_path)
    ks.engage("test")
    ks.disengage("Alice-2026-04-25")
    assert not ks.is_engaged()


def test_kill_switch_disengage_when_not_engaged_raises(tmp_path):
    ks = KillSwitch(state_root=tmp_path)
    with pytest.raises(FileNotFoundError):
        ks.disengage("human-token")


def test_kill_switch_audit_log_written(tmp_path):
    """Engaging and disengaging must write to the audit log."""
    ks = KillSwitch(state_root=tmp_path)
    ks.engage("reason A")
    ks.disengage("operator-Bob")
    audit_path = tmp_path / "kill_switch_audit.jsonl"
    assert audit_path.exists()
    lines = audit_path.read_text().strip().split("\n")
    assert len(lines) == 2
    engage_entry = json.loads(lines[0])
    disengage_entry = json.loads(lines[1])
    assert engage_entry["event"] == "engage"
    assert disengage_entry["event"] == "disengage"
    assert disengage_entry["token"] == "operator-Bob"


def test_kill_switch_survives_process_restart(tmp_path):
    """
    Simulate process restart by creating a new KillSwitch pointing to the
    same state_root.  The new instance must see the engaged state.
    """
    ks1 = KillSwitch(state_root=tmp_path)
    ks1.engage("process-1 engaged")

    # New "process"
    ks2 = KillSwitch(state_root=tmp_path)
    assert ks2.is_engaged()
    assert ks2.read_reason() == "process-1 engaged"
