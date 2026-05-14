"""
email_notify.py — Email notifications for Litmus Support Lab.

Sends a plain-text email to academy@litmus.io when a trainee passes a checkpoint.

Required env vars:
  SMTP_HOST      — SMTP server hostname (e.g. smtp.office365.com)

Optional env vars:
  SMTP_PORT      — SMTP port (default: 587)
  SMTP_USER      — SMTP login username (leave unset for unauthenticated relay)
  SMTP_PASSWORD  — SMTP login password
  SMTP_FROM      — Sender address (default: noreply@litmus.io)

If SMTP_HOST is not set, notifications are silently skipped.
"""

import logging
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

log = logging.getLogger(__name__)

NOTIFY_TO = "academy@litmus.io"


def _is_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST"))


def send_pass_email(trainee_email: str, trainee_name: str, checkpoint: int) -> None:
    """
    Send a checkpoint-passed notification to academy@litmus.io.
    Never raises — all errors are logged.
    """
    if not _is_configured():
        log.debug("SMTP not configured — skipping pass notification")
        return

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", 587))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    from_addr = os.environ.get("SMTP_FROM", "noreply@litmus.io")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    msg = EmailMessage()
    msg["Subject"] = f"Checkpoint {checkpoint} Passed — Litmus Support Lab"
    msg["From"] = from_addr
    msg["To"] = NOTIFY_TO
    msg.set_content(
        f"{trainee_name} has passed Checkpoint {checkpoint} of the "
        f"Litmus Support Lab certificate program.\n\n"
        f"Trainee name:  {trainee_name}\n"
        f"Trainee email: {trainee_email}\n"
        f"Checkpoint:    {checkpoint}\n"
        f"Completed at:  {timestamp}\n\n"
        f"— Litmus Support Lab (automated notification)"
    )

    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        log.info(
            "Pass notification sent to %s: %s passed CP%d",
            NOTIFY_TO, trainee_email, checkpoint,
        )
    except Exception as exc:
        log.error(
            "Failed to send pass notification for %s CP%d: %s: %s",
            trainee_email, checkpoint, type(exc).__name__, exc,
        )
