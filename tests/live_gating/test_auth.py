"""
Tests for live.auth — authorization gate for live trading.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _write_auth(path: Path, **overrides) -> None:
    """Write a valid authorization YAML file."""
    import yaml  # type: ignore[import]
    now = datetime.now(timezone.utc)
    data = {
        "authorized_at": now.isoformat(),
        "authorized_by": "TestOperator",
        "strategy": "ons",
        "universe": "ETF_SECTOR_11",
        "max_gross_notional_usd": 1000,
        "max_per_name_usd": 200,
        "trading_days": ["mon", "tue", "wed", "thu", "fri"],
        "expires_at": (now + timedelta(days=14)).isoformat(),
        "revoked": False,
    }
    data.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        yaml.dump(data, f)


def _register_hash(path: Path, hashes_file: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        h.update(f.read())
    digest = h.hexdigest()
    hashes_file.parent.mkdir(parents=True, exist_ok=True)
    with hashes_file.open("a") as f:
        f.write(json.dumps({"ts": datetime.utcnow().isoformat(), "sha256": digest, "file": str(path)}) + "\n")
    return digest


def _valid_auth_setup(tmp_path: Path):
    """Create a valid, registered auth file and return paths."""
    import yaml  # type: ignore[import]
    auth_file = tmp_path / "live_authorization.yaml"
    hashes_file = tmp_path / "auth_hashes.jsonl"
    _write_auth(auth_file)
    _register_hash(auth_file, hashes_file)
    return auth_file, hashes_file


def _patch_auth_paths(tmp_path: Path, auth_file: Path, hashes_file: Path):
    """Monkey-patch module-level paths for testing."""
    import live.auth as auth_mod
    auth_mod.AUTH_FILE = auth_file
    auth_mod.AUTH_HASHES_FILE = hashes_file


# ---------------------------------------------------------------------------
# Valid authorization
# ---------------------------------------------------------------------------

def test_valid_auth_passes(tmp_path):
    try:
        import yaml  # type: ignore[import]
    except ImportError:
        pytest.skip("PyYAML not installed")

    auth_file, hashes_file = _valid_auth_setup(tmp_path)
    _patch_auth_paths(tmp_path, auth_file, hashes_file)

    from live.auth import validate_live_authorization
    data = validate_live_authorization(auth_file)
    assert data["strategy"] == "ons"


# ---------------------------------------------------------------------------
# Missing file
# ---------------------------------------------------------------------------

def test_missing_auth_file_raises(tmp_path):
    from live.auth import AuthorizationError, validate_live_authorization
    with pytest.raises(AuthorizationError, match="not found"):
        validate_live_authorization(tmp_path / "nonexistent.yaml")


# ---------------------------------------------------------------------------
# Expired authorization
# ---------------------------------------------------------------------------

def test_expired_auth_raises(tmp_path):
    try:
        import yaml  # type: ignore[import]
    except ImportError:
        pytest.skip("PyYAML not installed")

    auth_file, hashes_file = _valid_auth_setup(tmp_path)
    # Overwrite with expired file
    _write_auth(
        auth_file,
        authorized_at=(datetime.now(timezone.utc) - timedelta(days=20)).isoformat(),
        expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    )
    _register_hash(auth_file, hashes_file)
    _patch_auth_paths(tmp_path, auth_file, hashes_file)

    from live.auth import AuthorizationError, validate_live_authorization
    with pytest.raises(AuthorizationError, match="expired"):
        validate_live_authorization(auth_file)


# ---------------------------------------------------------------------------
# Revoked authorization
# ---------------------------------------------------------------------------

def test_revoked_auth_raises(tmp_path):
    try:
        import yaml  # type: ignore[import]
    except ImportError:
        pytest.skip("PyYAML not installed")

    auth_file, hashes_file = _valid_auth_setup(tmp_path)
    _write_auth(auth_file, revoked=True)
    _register_hash(auth_file, hashes_file)
    _patch_auth_paths(tmp_path, auth_file, hashes_file)

    from live.auth import AuthorizationError, validate_live_authorization
    with pytest.raises(AuthorizationError, match="revoked"):
        validate_live_authorization(auth_file)


# ---------------------------------------------------------------------------
# Tampered file (hash mismatch)
# ---------------------------------------------------------------------------

def test_tampered_auth_raises(tmp_path):
    try:
        import yaml  # type: ignore[import]
    except ImportError:
        pytest.skip("PyYAML not installed")

    auth_file, hashes_file = _valid_auth_setup(tmp_path)

    # Tamper with the file after hashing
    with auth_file.open("a") as f:
        f.write("\n# tampered\n")

    _patch_auth_paths(tmp_path, auth_file, hashes_file)

    from live.auth import AuthorizationError, validate_live_authorization
    with pytest.raises(AuthorizationError, match="hash"):
        validate_live_authorization(auth_file)


# ---------------------------------------------------------------------------
# Expiry window too long
# ---------------------------------------------------------------------------

def test_expiry_too_long_raises(tmp_path):
    try:
        import yaml  # type: ignore[import]
    except ImportError:
        pytest.skip("PyYAML not installed")

    auth_file, hashes_file = _valid_auth_setup(tmp_path)
    from datetime import timedelta, timezone
    now = datetime.now(timezone.utc)
    _write_auth(
        auth_file,
        authorized_at=now.isoformat(),
        expires_at=(now + timedelta(days=60)).isoformat(),  # 60 days > 30 max
    )
    _register_hash(auth_file, hashes_file)
    _patch_auth_paths(tmp_path, auth_file, hashes_file)

    from live.auth import AuthorizationError, validate_live_authorization
    with pytest.raises(AuthorizationError, match="30 days"):
        validate_live_authorization(auth_file)


# ---------------------------------------------------------------------------
# Runner refuses live mode without valid auth
# ---------------------------------------------------------------------------

def test_runner_refuses_without_auth(tmp_path):
    """
    python -m live.runner --broker moomoo-live (not yet supported) or any live path
    should be refused without a valid auth file.

    This tests that MoomooBroker refuses env='live' directly.
    """
    from live.broker.moomoo import LiveTradingNotAuthorizedError, MoomooBroker
    with pytest.raises(LiveTradingNotAuthorizedError):
        MoomooBroker(env="live")


# ---------------------------------------------------------------------------
# Equity comparison
# ---------------------------------------------------------------------------

def test_equity_compare_no_divergence(tmp_path):
    from live.monitor.equity_compare import EquityComparison
    from live.risk.breakers import KillSwitch
    ks = KillSwitch(state_root=tmp_path)
    ec = EquityComparison(
        backtest_mean_daily=0.0004,
        backtest_std_daily=0.005,
        divergence_days=3,
        state_path=tmp_path / "eq_compare.json",
    )
    # Live and paper match
    report = ec.update(10_000.0, 10_000.0, ks)
    assert report["action"] == "ok"
    assert not ks.is_engaged()


def test_equity_compare_divergence_triggers_kill_switch(tmp_path):
    from live.monitor.equity_compare import EquityComparison
    from live.risk.breakers import KillSwitch
    ks = KillSwitch(state_root=tmp_path)
    ec = EquityComparison(
        backtest_mean_daily=0.0004,
        backtest_std_daily=0.002,    # tight std — 2σ = 0.4%
        divergence_days=3,
        state_path=tmp_path / "eq_compare.json",
    )
    # Need 1 warmup call + 3 divergent calls to trigger (first call sets prev equity)
    for i in range(4):
        # Live loses 2%, paper holds flat — 2% diff >> 2 × 0.2% std
        ec.update(10_000.0 * (0.98 ** (i + 1)), 10_000.0, ks)

    assert ks.is_engaged()
    assert "live_paper_divergence" in ks.read_reason()


# ---------------------------------------------------------------------------
# Drill simulation: kill switch fires in injected failure scenario
# ---------------------------------------------------------------------------

def test_drill_kill_switch_fires_on_injected_recon_mismatch(tmp_path):
    """
    Drill scenario: inject a reconciliation mismatch.
    The kill switch must fire.
    """
    from live.broker.paper import PaperBroker
    from live.oms.reconcile import reconcile
    from live.risk.breakers import KillSwitch
    broker = PaperBroker(state_root=tmp_path, initial_cash=10_000.0)
    ks = KillSwitch(state_root=tmp_path)

    # Inject: local belief says equity is $100K but broker says $10K
    report = reconcile(
        broker=broker,
        local_positions={},
        local_equity=100_000.0,  # large mismatch
        kill_switch=ks,
        incidents_dir=tmp_path / "incidents",
    )
    assert ks.is_engaged()
    assert report["status"] == "large_drift"


def test_drill_kill_switch_fires_on_stalled_heartbeat(tmp_path):
    """
    Drill scenario: heartbeat file is stale.
    is_stale() should detect it.
    """
    import time
    from live.monitor.health import Heartbeat
    hb = Heartbeat(path=tmp_path / "heartbeat.json")
    # Write a heartbeat
    hb.beat()
    # Artificially age the file
    import os
    old_time = time.time() - 3600  # 1 hour old
    os.utime(hb._path, (old_time, old_time))
    assert hb.is_stale(max_age_seconds=1800.0)  # stale after 30 min
