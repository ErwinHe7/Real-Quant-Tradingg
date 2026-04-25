"""
OMS persistent state — survives process restarts.

Idempotent recovery: if the process dies between submit and ack-persist,
the next start reconciles from broker truth, not local belief.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.json")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2, default=str)
    tmp.replace(path)


class OMSState:
    """
    Persisted OMS state.  Loaded at startup; saved after each tick.

    Fields
    ------
    last_tick_ts    : ISO timestamp of the last completed tick
    pending_orders  : orders submitted but not yet confirmed as filled
    last_weights    : last approved target weights (symbol -> float)
    session_equity  : list of (ts, equity) for the current session
    """

    def __init__(self, state_path: Path) -> None:
        self._path = state_path
        self.last_tick_ts: str | None = None
        self.pending_orders: list[dict[str, Any]] = []
        self.last_weights: dict[str, float] = {}
        self.session_equity: list[tuple[str, float]] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with self._path.open() as f:
            data = json.load(f)
        self.last_tick_ts = data.get("last_tick_ts")
        self.pending_orders = data.get("pending_orders", [])
        self.last_weights = data.get("last_weights", {})
        self.session_equity = [tuple(x) for x in data.get("session_equity", [])]

    def save(self) -> None:
        _atomic_write(self._path, {
            "last_tick_ts": self.last_tick_ts,
            "pending_orders": self.pending_orders,
            "last_weights": self.last_weights,
            "session_equity": self.session_equity,
        })

    def record_tick(self, equity: float) -> None:
        ts = datetime.utcnow().isoformat()
        self.last_tick_ts = ts
        self.session_equity.append((ts, equity))
        self.save()
