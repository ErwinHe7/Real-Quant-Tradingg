"""
OMS reconciliation — compare broker truth to local belief.

Runs:
  - on startup
  - after every fill batch
  - as a heartbeat every N minutes (configured by runner)

On small drift (within tolerance): log and update local state.
On large drift: engage the kill switch and write an incident file.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from live.broker.base import Broker

logger = logging.getLogger(__name__)

SMALL_DRIFT_TOLERANCE = 0.005   # 0.5% of equity — log only
LARGE_DRIFT_THRESHOLD = 0.02    # 2% of equity — engage kill switch


def reconcile(
    broker: "Broker",
    local_positions: dict[str, float],
    local_equity: float,
    kill_switch: "KillSwitch",
    incidents_dir: Path = Path("live/state/incidents"),
) -> dict:
    """
    Compare broker-reported positions and equity to local belief.

    Returns a reconciliation report dict.
    """
    from live.risk.breakers import KillSwitch  # avoid circular import at module level

    broker_account = broker.account()
    broker_positions = broker.positions()

    # Equity drift
    equity_drift = abs(broker_account.equity_usd - local_equity)
    equity_drift_pct = equity_drift / local_equity if local_equity > 0 else 0.0

    # Position drift: symbols in one but not the other
    local_syms = set(local_positions.keys())
    broker_syms = set(broker_positions.keys())
    extra_in_broker = broker_syms - local_syms
    missing_from_broker = local_syms - broker_syms

    # Quantity drift for shared symbols
    qty_drifts = {}
    for sym in local_syms & broker_syms:
        local_qty = local_positions[sym]
        broker_qty = broker_positions[sym].quantity
        diff = abs(local_qty - broker_qty)
        if diff > 1e-2:
            qty_drifts[sym] = {"local": local_qty, "broker": broker_qty, "diff": diff}

    report = {
        "ts": datetime.utcnow().isoformat(),
        "broker_equity": broker_account.equity_usd,
        "local_equity": local_equity,
        "equity_drift_pct": equity_drift_pct,
        "extra_in_broker": list(extra_in_broker),
        "missing_from_broker": list(missing_from_broker),
        "qty_drifts": qty_drifts,
        "status": "ok",
    }

    if (
        equity_drift_pct > LARGE_DRIFT_THRESHOLD
        or extra_in_broker
        or missing_from_broker
        or qty_drifts
    ):
        if equity_drift_pct > LARGE_DRIFT_THRESHOLD:
            report["status"] = "large_drift"
            reason = (
                f"Reconciliation mismatch: equity drift {equity_drift_pct:.1%}, "
                f"extra={list(extra_in_broker)}, missing={list(missing_from_broker)}, "
                f"qty_drifts={qty_drifts}"
            )
            kill_switch.engage(reason)
            logger.error("LARGE RECONCILIATION DRIFT — kill switch engaged: %s", reason)

            # Write incident file
            incidents_dir.mkdir(parents=True, exist_ok=True)
            ts_safe = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
            incident_path = incidents_dir / f"{ts_safe}-reconcile-mismatch.json"
            with incident_path.open("w") as f:
                json.dump(report, f, indent=2)
            logger.error("Incident written to %s", incident_path)
        else:
            report["status"] = "small_drift"
            logger.warning("Small reconciliation drift: %s", report)
    else:
        logger.info("Reconciliation OK: equity drift %.3f%%", equity_drift_pct * 100)

    return report
