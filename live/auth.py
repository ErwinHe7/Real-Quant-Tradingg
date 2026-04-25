"""
Live trading authorization gate.

The authorization file (live/state/live_authorization.yaml) must:
  - exist and parse correctly
  - not be expired (expires_at > now)
  - not be revoked
  - have a valid SHA256 hash recorded in live/state/auth_hashes.jsonl

The agent is NEVER authorized to create or modify the authorization file.
The agent is NEVER authorized to add a new hash to auth_hashes.jsonl.

Only a human operator calls python -m live.tools.authorize to hash and
register the file after manually editing it.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AUTH_FILE = Path("live/state/live_authorization.yaml")
AUTH_HASHES_FILE = Path("live/state/auth_hashes.jsonl")
MAX_EXPIRY_DAYS = 30


class AuthorizationError(RuntimeError):
    """Raised when live trading is not authorized."""


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import]
    except ImportError:
        raise ImportError(
            "PyYAML is required to read the authorization file. "
            "Install with: pip install pyyaml"
        )
    with path.open() as f:
        return yaml.safe_load(f)


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        h.update(f.read())
    return h.hexdigest()


def _is_hash_registered(file_hash: str) -> bool:
    if not AUTH_HASHES_FILE.exists():
        return False
    with AUTH_HASHES_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("sha256") == file_hash:
                    return True
            except json.JSONDecodeError:
                continue
    return False


def validate_live_authorization(auth_file: Path = AUTH_FILE) -> dict[str, Any]:
    """
    Validate the live authorization file and return its parsed contents.

    Raises AuthorizationError if any check fails.

    Checks performed:
    1. File exists
    2. File parses as YAML
    3. Required fields present
    4. Not expired
    5. Not revoked
    6. SHA256 hash matches a registered entry in auth_hashes.jsonl
    """
    if not auth_file.exists():
        raise AuthorizationError(
            f"Live authorization file not found at {auth_file}. "
            "A human operator must create this file. See docs/RUNBOOK.md."
        )

    try:
        data = _load_yaml(auth_file)
    except Exception as exc:
        raise AuthorizationError(f"Failed to parse authorization file: {exc}") from exc

    required_fields = [
        "authorized_at", "authorized_by", "strategy", "universe",
        "max_gross_notional_usd", "max_per_name_usd", "expires_at", "revoked",
    ]
    for field in required_fields:
        if field not in data:
            raise AuthorizationError(f"Missing required field '{field}' in authorization file")

    # Check expiry
    try:
        expires_at = datetime.fromisoformat(str(data["expires_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuthorizationError(f"Invalid expires_at format: {exc}") from exc

    now = datetime.now(timezone.utc)
    if now > expires_at:
        raise AuthorizationError(
            f"Live authorization expired at {expires_at}. "
            "A human operator must create a new authorization file."
        )

    # Check not revoked
    if data.get("revoked", True):
        raise AuthorizationError("Live authorization is revoked.")

    # Validate max expiry window (30 days from authorized_at)
    try:
        authorized_at = datetime.fromisoformat(str(data["authorized_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuthorizationError(f"Invalid authorized_at format: {exc}") from exc

    from datetime import timedelta
    if (expires_at - authorized_at).days > MAX_EXPIRY_DAYS:
        raise AuthorizationError(
            f"Authorization window exceeds {MAX_EXPIRY_DAYS} days. "
            "Maximum allowed authorization duration is 30 days."
        )

    # Validate hash
    file_hash = _file_hash(auth_file)
    if not _is_hash_registered(file_hash):
        raise AuthorizationError(
            "Authorization file hash is not registered in auth_hashes.jsonl. "
            "Run 'python -m live.tools.authorize' after editing the file."
        )

    logger.info(
        "Live authorization validated: strategy=%s universe=%s expires=%s",
        data.get("strategy"), data.get("universe"), expires_at.isoformat(),
    )
    return data


def register_authorization(auth_file: Path = AUTH_FILE) -> str:
    """
    Hash the authorization file and append the hash to auth_hashes.jsonl.

    This must be called by a human operator AFTER manually editing the file.
    The agent is not authorized to call this.

    Returns the SHA256 hash.
    """
    if not auth_file.exists():
        raise FileNotFoundError(f"Authorization file not found: {auth_file}")

    file_hash = _file_hash(auth_file)
    entry = json.dumps({
        "ts": datetime.utcnow().isoformat(),
        "sha256": file_hash,
        "file": str(auth_file),
    })
    AUTH_HASHES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with AUTH_HASHES_FILE.open("a") as f:
        f.write(entry + "\n")
    logger.info("Authorization hash registered: %s", file_hash)
    return file_hash
