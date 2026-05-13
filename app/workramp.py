"""
workramp.py — Workramp Academy API integration for Litmus Lab.

Called after a trainee passes a certificate checkpoint. Looks up (or creates)
the learner in the Workramp Academy by email, then updates a custom registration
field so a Workramp automation rule can mark the corresponding module complete.

Required env vars:
  WORKRAMP_API_KEY     — Bearer token (Workramp admin → Settings → API)
  WORKRAMP_ACADEMY_ID  — Academy ID (visible in admin URL or API settings)

Optional env vars (field name overrides):
  WORKRAMP_FIELD_CP1   — custom field API name for checkpoint 1 (default: litmus_cp1)
  WORKRAMP_FIELD_CP2   — custom field API name for checkpoint 2 (default: litmus_cp2)
  WORKRAMP_FIELD_CP3   — custom field API name for checkpoint 3 (default: litmus_cp3)

Workramp admin must:
  1. Create custom registration fields with the above API names in Workramp admin
  2. Create an automation rule: "when litmus_cp{N} = 'passed' → mark module complete"
"""

import logging
import os

import httpx

log = logging.getLogger(__name__)

_API_BASE = "https://app.workramp.com/api/v1"


def _is_configured() -> bool:
    return bool(os.environ.get("WORKRAMP_API_KEY") and os.environ.get("WORKRAMP_ACADEMY_ID"))


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.environ['WORKRAMP_API_KEY']}"}


def _get_contact_id(academy_id: str, email: str) -> str | None:
    """Look up a contact by email. Returns Workramp contact id or None."""
    with httpx.Client(timeout=10) as client:
        resp = client.get(
            f"{_API_BASE}/academies/{academy_id}/users",
            headers=_headers(),
            params={"email": email},
        )
    if resp.status_code == 200:
        users = resp.json().get("data", {}).get("users", [])
        if users:
            return users[0]["id"]
    else:
        log.warning("Workramp contact lookup failed (%d): %s", resp.status_code, resp.text[:200])
    return None


def _create_contact(academy_id: str, email: str, name: str) -> str | None:
    """Create a Workramp contact. Returns the new contact id or None."""
    with httpx.Client(timeout=10) as client:
        resp = client.post(
            f"{_API_BASE}/academies/{academy_id}/users",
            headers={**_headers(), "Content-Type": "application/json"},
            json={"email": email, "name": name},
        )
    if resp.status_code in (200, 201):
        return resp.json().get("id")
    log.warning("Workramp contact create failed (%d): %s", resp.status_code, resp.text[:200])
    return None


def _ensure_contact(academy_id: str, email: str, name: str) -> str | None:
    """Return the Workramp contact id for this email, creating the contact if needed."""
    contact_id = _get_contact_id(academy_id, email)
    if contact_id:
        return contact_id
    return _create_contact(academy_id, email, name)


def report_pass(email: str, name: str, checkpoint: int) -> None:
    """
    Mark a checkpoint pass on the learner's Workramp profile.
    Called from the grading background task. Never raises — logs all errors.
    """
    if not _is_configured():
        log.debug("Workramp integration not configured — skipping")
        return

    academy_id = os.environ["WORKRAMP_ACADEMY_ID"]
    field_name = os.environ.get(f"WORKRAMP_FIELD_CP{checkpoint}", f"litmus_cp{checkpoint}")

    try:
        contact_id = _ensure_contact(academy_id, email, name)
        if not contact_id:
            log.warning("Workramp: could not find or create contact for %s — skipping", email)
            return

        with httpx.Client(timeout=10) as client:
            resp = client.patch(
                f"{_API_BASE}/academies/{academy_id}/users/{contact_id}",
                headers={**_headers(), "Content-Type": "application/json"},
                json={"custom_registration_fields": {field_name: "passed"}},
            )

        if resp.status_code == 200:
            log.info("Workramp: set %s=%s for %s (contact %s)", field_name, "passed", email, contact_id)
        else:
            log.warning(
                "Workramp: field update failed for %s (%d): %s",
                email, resp.status_code, resp.text[:200],
            )
    except Exception as exc:
        log.error("Workramp: unexpected error for %s: %s: %s", email, type(exc).__name__, exc)
