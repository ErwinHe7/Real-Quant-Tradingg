"""
Circuit breakers and kill switch.

All classes that persist state write to disk atomically (write-to-temp,
rename) so they survive process restart.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------

class BreakerState(Enum):
    ARMED = "armed"
    ENGAGED = "engaged"     # breaker fired; trading suspended
    COOLING = "cooling"     # drawdown breaker: waiting to re-arm


# ---------------------------------------------------------------------------
# Drawdown circuit breaker
# ---------------------------------------------------------------------------

class DrawdownBreaker:
    """
    Fires when portfolio equity falls more than *max_dd_pct* below its
    all-time high-water mark.  Requires a cool-off window of *cool_off_days*
    trading days before re-arming.
    """

    def __init__(
        self,
        max_dd_pct: float = 0.15,
        cool_off_days: int = 5,
        state_path: Optional[Path] = None,
    ) -> None:
        self.max_dd_pct = max_dd_pct
        self.cool_off_days = cool_off_days
        self._hwm: float = 0.0
        self._state = BreakerState.ARMED
        self._cool_off_until: Optional[datetime] = None
        if state_path:
            self._load(state_path)

    def update(self, equity_curve: "pd.Series") -> BreakerState:
        import pandas as pd
        if equity_curve.empty:
            return self._state

        # Update HWM from the full curve provided
        curve_max = float(equity_curve.max())
        self._hwm = max(self._hwm, curve_max)

        current_equity = float(equity_curve.iloc[-1])
        drawdown = (self._hwm - current_equity) / self._hwm if self._hwm > 0 else 0.0

        if self._state == BreakerState.COOLING:
            if self._cool_off_until and datetime.utcnow() >= self._cool_off_until:
                self._state = BreakerState.ARMED
                self._cool_off_until = None
            return self._state

        if self._state == BreakerState.ARMED and drawdown >= self.max_dd_pct:
            self._state = BreakerState.ENGAGED

        return self._state

    def disengage(self) -> None:
        """
        Move from ENGAGED to COOLING.  The cool-off clock starts now.
        Calling code must also reset the equity series reference.
        """
        if self._state == BreakerState.ENGAGED:
            self._state = BreakerState.COOLING
            self._cool_off_until = datetime.utcnow() + timedelta(days=self.cool_off_days)

    def _load(self, path: Path) -> None:
        if not path.exists():
            return
        with path.open() as f:
            d = json.load(f)
        self._hwm = float(d.get("hwm", 0.0))
        self._state = BreakerState(d.get("state", "armed"))
        cool = d.get("cool_off_until")
        self._cool_off_until = datetime.fromisoformat(cool) if cool else None

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "hwm": self._hwm,
            "state": self._state.value,
            "cool_off_until": self._cool_off_until.isoformat() if self._cool_off_until else None,
        }
        tmp = path.with_suffix(".tmp.json")
        with tmp.open("w") as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)

    @property
    def state(self) -> BreakerState:
        return self._state


# ---------------------------------------------------------------------------
# Daily loss circuit breaker
# ---------------------------------------------------------------------------

class DailyLossBreaker:
    """
    Fires when the day's P&L falls below *-max_loss_pct* of equity.
    Resets at midnight UTC.
    """

    def __init__(self, max_loss_pct: float = 0.03) -> None:
        self.max_loss_pct = max_loss_pct
        self._state = BreakerState.ARMED
        self._day_start_equity: float = 0.0
        self._last_date: Optional[str] = None

    def update(self, day_pnl: float, equity: float) -> BreakerState:
        today = datetime.utcnow().date().isoformat()
        if today != self._last_date:
            # New trading day — reset
            self._last_date = today
            self._day_start_equity = equity
            if self._state == BreakerState.ENGAGED:
                self._state = BreakerState.ARMED

        if self._state == BreakerState.ARMED and self._day_start_equity > 0:
            loss_pct = -day_pnl / self._day_start_equity
            if loss_pct >= self.max_loss_pct:
                self._state = BreakerState.ENGAGED

        return self._state

    @property
    def state(self) -> BreakerState:
        return self._state


# ---------------------------------------------------------------------------
# Kill switch (file-backed, process-independent)
# ---------------------------------------------------------------------------

class KillSwitch:
    """
    File-backed kill switch.  Presence of <state_root>/KILL means: do
    nothing, do not place orders.

    Disengaging requires a human-supplied token recorded in
    <state_root>/kill_switch_audit.jsonl.  The agent is not authorised to
    disengage on its own; `disengage()` validates that the caller is a human
    by requiring a non-empty, non-agent token string.

    The `AGENT` token is explicitly rejected.
    """

    _KILL_FILE = "KILL"
    _AUDIT_FILE = "kill_switch_audit.jsonl"
    _FORBIDDEN_TOKENS = {"AGENT", "SYSTEM", "AUTO", "AUTOMATED", "BOT"}

    def __init__(self, state_root: Path = Path("live/state")) -> None:
        self._state_root = state_root
        self._state_root.mkdir(parents=True, exist_ok=True)
        self._kill_path = state_root / self._KILL_FILE
        self._audit_path = state_root / self._AUDIT_FILE

    def is_engaged(self) -> bool:
        return self._kill_path.exists()

    def engage(self, reason: str) -> None:
        """Engage the kill switch.  Idempotent."""
        self._kill_path.write_text(reason or "unspecified reason")
        self._append_audit(event="engage", reason=reason, token="system")

    def disengage(self, human_token: str) -> None:
        """
        Disengage the kill switch.

        Parameters
        ----------
        human_token : a non-empty string provided by the human operator.
                      Must not be one of the forbidden automated tokens.

        Raises
        ------
        PermissionError
            If the token is empty or matches a forbidden automated token.
        FileNotFoundError
            If the kill switch is not currently engaged.
        """
        upper = human_token.strip().upper()
        if not human_token.strip():
            raise PermissionError("Kill switch disengage requires a non-empty human token.")
        if upper in self._FORBIDDEN_TOKENS:
            raise PermissionError(
                f"Token '{human_token}' is reserved for automated systems. "
                "Only a human operator may disengage the kill switch."
            )
        if not self.is_engaged():
            raise FileNotFoundError("Kill switch is not currently engaged.")

        self._kill_path.unlink(missing_ok=True)
        self._append_audit(event="disengage", reason="manual operator disengage", token=human_token)

    def read_reason(self) -> str:
        """Return the reason the kill switch was engaged, or empty string."""
        if not self._kill_path.exists():
            return ""
        try:
            return self._kill_path.read_text().strip()
        except OSError:
            return ""

    def _append_audit(self, event: str, reason: str, token: str) -> None:
        entry = json.dumps({
            "ts": datetime.utcnow().isoformat(),
            "event": event,
            "reason": reason,
            "token": token,
            "pid": os.getpid(),
        })
        with self._audit_path.open("a") as f:
            f.write(entry + "\n")
