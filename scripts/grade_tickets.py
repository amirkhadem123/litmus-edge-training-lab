#!/usr/bin/env python3
"""
grade_tickets.py — Polling grader for Litmus Lab training tickets.

Runs continuously (or once with --once), polling Zendesk every 60 seconds for
solved training tickets that haven't been graded yet. When found, sends the
full ticket thread to Claude for grading and posts the result as an internal note.

Usage:
    python scripts/grade_tickets.py           # run continuously
    python scripts/grade_tickets.py --once    # grade pending tickets once and exit

Grading logic:
  - Finds tickets tagged 'litmus-lab-training' + status 'solved'
  - Skips tickets already tagged 'litmus-lab-graded'
  - Detects escalation via presence of 'escalate' tag
  - Loads the matching scenario YAML by 'scenario-{id}' tag
  - Calls Claude to grade the response thread
  - Posts grade as internal note, applies 'litmus-lab-graded' tag
"""

import sys
import time
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import yaml
from app.zendesk_client import ZendeskClient
from app.grader import grade_response, format_internal_note, GradeResult

SCENARIOS_DIR = Path(__file__).parent.parent / "scenarios"
POLL_INTERVAL = 60  # seconds


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


def grade_ticket(client: ZendeskClient, ticket: dict) -> None:
    ticket_id = ticket["id"]
    tags = ticket.get("tags", [])

    scenario_id = extract_scenario_id(tags)
    if not scenario_id:
        print(f"  [ticket {ticket_id}] No scenario tag found — skipping")
        return

    scenario = load_scenario_by_id(scenario_id)
    if not scenario:
        print(f"  [ticket {ticket_id}] Scenario '{scenario_id}' not found on disk — skipping")
        return

    print(f"  [ticket {ticket_id}] Grading scenario '{scenario_id}': {scenario['title']}")

    comments = client.get_comments(ticket_id)
    # Filter to public comments only — internal notes are system messages
    public_comments = [c for c in comments if c.get("public", True)]

    escalated = "escalate" in tags
    trainee_email = extract_trainee_email(client, ticket)

    try:
        grade: GradeResult = grade_response(scenario, public_comments, escalated)
    except Exception as e:
        print(f"  [ticket {ticket_id}] Grading failed: {e}")
        # Post a failure note so the trainer knows
        client.post_internal_note(
            ticket_id,
            f"⚠️ LITMUS LAB: Automatic grading failed for scenario {scenario_id}.\nError: {e}\nPlease grade manually.",
        )
        client.add_tags(ticket_id, ["litmus-lab-graded"])
        return

    note_body = format_internal_note(grade, scenario, trainee_email)
    client.post_internal_note(ticket_id, note_body)
    client.add_tags(ticket_id, ["litmus-lab-graded"])

    status = "PASSED" if grade.passed else "FAILED"
    action = "✅" if grade.action_correct else "❌ wrong action"
    print(f"  [ticket {ticket_id}] Done — {status} ({grade.score}/100) | action: {action}")


def find_ungraded_tickets(client: ZendeskClient) -> list[dict]:
    # Zendesk search: solved training tickets without the graded tag
    query = 'tags:litmus-lab-training status:solved -tags:litmus-lab-graded type:ticket'
    return client.search_tickets(query)


def run_once(client: ZendeskClient) -> int:
    """Grade all currently ungraded tickets. Returns count of tickets processed."""
    tickets = find_ungraded_tickets(client)
    if not tickets:
        print("No ungraded tickets found.")
        return 0

    print(f"Found {len(tickets)} ungraded ticket(s).")
    for ticket in tickets:
        grade_ticket(client, ticket)

    return len(tickets)


def main():
    once = "--once" in sys.argv

    client = ZendeskClient()

    if once:
        count = run_once(client)
        print(f"Done. {count} ticket(s) graded.")
        return

    print("Litmus Lab grader started. Polling every 60 seconds. Ctrl+C to stop.")
    while True:
        try:
            run_once(client)
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Poll error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
