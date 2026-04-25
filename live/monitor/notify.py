"""
Notification stub.

Default: no-op.  Missing credentials do not crash the runner.
Plug in Slack / Telegram / email by setting environment variables.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def send_alert(subject: str, body: str) -> None:
    """
    Send an alert notification.

    Currently a no-op stub.  Set NOTIFY_BACKEND=slack|email and the
    corresponding credentials environment variables to enable.
    """
    backend = os.environ.get("NOTIFY_BACKEND", "").lower()
    if not backend:
        logger.info("NOTIFY [%s]: %s", subject, body)
        return

    if backend == "slack":
        _send_slack(subject, body)
    elif backend == "email":
        _send_email(subject, body)
    else:
        logger.warning("Unknown NOTIFY_BACKEND '%s'; skipping notification", backend)


def _send_slack(subject: str, body: str) -> None:
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook:
        logger.warning("SLACK_WEBHOOK_URL not set; skipping Slack notification")
        return
    import urllib.request, urllib.error
    import json
    payload = json.dumps({"text": f"*{subject}*\n{body}"}).encode()
    try:
        req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except urllib.error.URLError as exc:
        logger.warning("Slack notification failed: %s", exc)


def _send_email(subject: str, body: str) -> None:
    # Stub — implement with smtplib if desired
    logger.info("EMAIL [%s]: %s", subject, body)
