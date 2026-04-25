"""
Heartbeat monitor.

The runner touches a heartbeat file on each tick.  An external watchdog
(e.g. a cron job or Windows Task Scheduler) can detect stalled runners by
checking the file's modification time.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path


class Heartbeat:
    """Touch a heartbeat file on each tick."""

    def __init__(self, path: Path = Path("live/state/heartbeat.json")) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def beat(self, info: dict | None = None) -> None:
        payload = {
            "ts": datetime.utcnow().isoformat(),
            "unix": time.time(),
        }
        if info:
            payload.update(info)
        self._path.write_text(json.dumps(payload))

    def is_stale(self, max_age_seconds: float = 1800.0) -> bool:
        """Return True if the heartbeat file is older than max_age_seconds."""
        if not self._path.exists():
            return True
        age = time.time() - self._path.stat().st_mtime
        return age > max_age_seconds
