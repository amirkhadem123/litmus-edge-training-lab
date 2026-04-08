#!/usr/bin/env python3
"""
grade_tickets.py — Polling engine for Litmus Lab: replies and grading.

Runs continuously (or once with --once), polling Zendesk every 60 seconds.
Each poll cycle does two things in order:

  1. REPLY WATCH — checks active (unsolved) training tickets for new trainee
     comments and posts scripted customer replies when a trigger matches.

  2. GRADE — checks newly solved training tickets and grades the full response
     thread with Claude, posting the result as an internal note.

Running both in one script means trainers only need to start one process.

Usage:
    python scripts/grade_tickets.py           # run continuously
    python scripts/grade_tickets.py --once    # one poll cycle then exit

Grading logic:
  - Finds tickets tagged 'litmus-lab-training' + status 'solved'
  - Skips tickets already tagged 'litmus-lab-graded'
  - Detects escalation via presence of 'escalate' tag
  - Loads the matching scenario YAML by 'scenario-{id}' tag
  - Calls Claude to grade the response thread
  - Posts grade as internal note, applies 'litmus-lab-graded' tag

Reply logic:
  - Finds unsolved tickets tagged 'litmus-lab-training'
  - For each new public comment from the trainee, checks scenario's
    scripted_replies triggers (case-insensitive keyword match)
  - Posts matching reply authored as the ticket requester ('customer' voice)
  - State persisted in _reply_state.json (gitignored)
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import yaml
from app.zendesk_client import ZendeskClient
from app.grader import grade_response, format_internal_note, GradeResult
from app.reply_watcher import watch_active_tickets

SCENARIOS_DIR = Path(__file__).parent.parent / "scenarios"
POLL_INTERVAL = 60  # seconds


# ── Shared helpers ────────────────────────────────────────────────────────────

def load_scenario_by_id(scenario_id: str) -> dict | None:
    matches = list(SCENARIOS_DIR.glob(f"{scenario_id}-*.yaml"))
    if not matches:
        return None
    with open(matches[0]) as f:
        return yaml.safe_load(f)


def extract_scenario_id(tags: list[str]) -> str | None:
    for tag in tags:
        if tag.startswith("scenario-"):
            return tag[len("scenario-"):]
    return None


def extract_trainee_email(client: ZendeskClient, ticket: dict) -> str:
    assignee_id = ticket.get("assignee_id")
    if not assignee_id:
        return "unknown"
    try:
        data = client._get(f"/users/{assignee_id}.json")
        return data["user"]["email"]
    except Exception:
        return f"user_id:{assignee_id}"


# ── Grading ───────────────────────────────────────────────────────────────────

def grade_ticket(client: ZendeskClient, ticket: dict) -> None:
    ticket_id = ticket["id"]
    tags = ticket.get("tags", [])

    scenario_id = extract_scenario_id(tags)
    if not scenario_id:
        print(f"  [ticket {ticket_id}] No scenario tag — skipping")
        return

    scenario = load_scenario_by_id(scenario_id)
    if not scenario:
        print(f"  [ticket {ticket_id}] Scenario '{scenario_id}' not found on disk — skipping")
        return

    print(f"  [ticket {ticket_id}] Grading '{scenario_id}': {scenario['title']}")

    comments = client.get_comments(ticket_id)
    # Pass only public comments — internal notes are system messages, not trainee work
    public_comments = [c for c in comments if c.get("public", True)]

    escalated = "escalate" in tags
    trainee_email = extract_trainee_email(client, ticket)

    try:
        grade: GradeResult = grade_response(scenario, public_comments, escalated)
    except Exception as e:
        print(f"  [ticket {ticket_id}] Grading failed: {e}")
        client.post_internal_note(
            ticket_id,
            f"⚠️ LITMUS LAB: Automatic grading failed for scenario {scenario_id}.\n"
            f"Error: {e}\nPlease grade manually.",
        )
        client.add_tags(ticket_id, ["litmus-lab-graded"])
        return

    note_body = format_internal_note(grade, scenario, trainee_email)
    client.post_internal_note(ticket_id, note_body)
    client.add_tags(ticket_id, ["litmus-lab-graded"])

    status = "PASSED" if grade.passed else "FAILED"
    action = "✅" if grade.action_correct else "❌ wrong action"
    print(f"  [ticket {ticket_id}] Done — {status} ({grade.score}/100) | action: {action}")


def run_grader(client: ZendeskClient) -> int:
    """Grade all currently ungraded solved tickets. Returns count processed."""
    query = "tags:litmus-lab-training status:solved -tags:litmus-lab-graded type:ticket"
    tickets = client.search_tickets(query)

    if not tickets:
        return 0

    print(f"  [grader] {len(tickets)} ungraded ticket(s) found")
    for ticket in tickets:
        grade_ticket(client, ticket)

    return len(tickets)


# ── Main poll loop ────────────────────────────────────────────────────────────

def poll(client: ZendeskClient, service_account_id: int) -> None:
    """One full poll cycle: reply watch first, then grade."""
    # Step 1 — post scripted replies to active tickets
    watch_active_tickets(client, load_scenario_by_id, service_account_id)

    # Step 2 — grade newly solved tickets
    run_grader(client)


def main():
    once = "--once" in sys.argv

    client = ZendeskClient()
    service_account_id = client.get_me()["id"]
    print(f"Service account ID: {service_account_id}")

    if once:
        poll(client, service_account_id)
        print("Done.")
        return

    print(f"Litmus Lab poller started (reply watch + grader). "
          f"Polling every {POLL_INTERVAL}s. Ctrl+C to stop.")
    while True:
        try:
            poll(client, service_account_id)
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Poll error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
