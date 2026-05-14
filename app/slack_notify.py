"""
slack_notify.py — Slack notifications for Litmus Support Lab.

Posts a message to a Slack channel when a trainee passes a certificate checkpoint.

Required env vars:
  SLACK_WEBHOOK_URL  — Incoming webhook URL from api.slack.com/apps

Optional env vars:
  LITMUS_HTTP_PROXY  — HTTP proxy URL (reused from AI config; set only in WARP
                       gateway/proxy mode — not needed for most deployments)

If SLACK_WEBHOOK_URL is not set, notifications are silently skipped.
"""

import logging
import os
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)


def send_pass_notification(trainee_email: str, trainee_name: str, checkpoint: int) -> None:
    """
    Post a checkpoint-passed message to Slack.
    Never raises — all errors are logged.
    """
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        log.debug("SLACK_WEBHOOK_URL not set — skipping pass notification")
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload = {
        "text": (
            f"✅ *Checkpoint {checkpoint} Passed — Litmus Support Lab*\n"
            f"*Name:* {trainee_name}\n"
            f"*Email:* {trainee_email}\n"
            f"*Completed:* {timestamp}"
        )
    }

    http_proxy = os.environ.get("LITMUS_HTTP_PROXY", "").strip() or None
    proxy_kwargs = {"proxy": http_proxy} if http_proxy else {}

    try:
        with httpx.Client(timeout=10, **proxy_kwargs) as client:
            resp = client.post(webhook_url, json=payload)
        if resp.status_code == 200:
            log.info(
                "Slack notification sent: %s passed CP%d", trainee_email, checkpoint
            )
        else:
            log.warning(
                "Slack notification failed (%d): %s", resp.status_code, resp.text[:200]
            )
    except Exception as exc:
        log.error(
            "Slack notification error for %s CP%d: %s: %s",
            trainee_email, checkpoint, type(exc).__name__, exc,
        )
