"""
reply_watcher.py — Scripted customer reply engine for Litmus Lab.

When a trainee comments on an active training ticket, this module checks
the comment text against the scenario's scripted_replies triggers and posts
a matching reply authored as the ticket's requester (the 'customer').

This creates a realistic back-and-forth support conversation without needing
a live customer or a human trainer to play the customer role.

HOW TRIGGER MATCHING WORKS:
  Each scripted reply has a list of trigger keywords. The trainee's comment
  is checked (case-insensitive) for any of those keywords. The first matching
  reply wins. If no reply matches and the scenario has a fallback_reply, that
  is sent instead. If there is no fallback, no reply is posted.

  This teaches trainees to ask precise, targeted questions. A vague comment
  gets no additional information.

STATE TRACKING:
  Processed comment IDs are stored in _reply_state.json at the repo root.
  This file is gitignored. It ensures we never post duplicate replies if
  the poller runs multiple times before a new comment appears.

  State format:
  {
    "<ticket_id>": {
      "requester_id": 12345,
      "processed_comment_ids": [1001, 1002, 1003]
    }
  }
"""

import json
from pathlib import Path

STATE_FILE = Path(__file__).parent.parent / "_reply_state.json"


# ── State persistence ─────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Trigger matching ──────────────────────────────────────────────────────────

def match_reply(comment_body: str, scenario: dict) -> str | None:
    """
    Return the body of the first scripted reply whose triggers appear in
    the comment, or the fallback_reply if nothing matches, or None.
    """
    body_lower = comment_body.lower()

    for entry in scenario.get("scripted_replies", []):
        triggers = entry.get("triggers", [])
        if any(trigger.lower() in body_lower for trigger in triggers):
            return entry["reply"].strip()

    # No trigger matched — return fallback if defined
    return scenario.get("fallback_reply", "").strip() or None


# ── Per-ticket processing ─────────────────────────────────────────────────────

def process_ticket(client, scenario: dict, ticket: dict, service_account_id: int) -> None:
    """
    Check a single active ticket for new trainee comments and post replies.
    Mutates and saves state after each processed comment.
    """
    ticket_id = ticket["id"]
    state = load_state()
    key = str(ticket_id)

    if key not in state:
        state[key] = {
            "requester_id": ticket["requester_id"],
            "processed_comment_ids": [],
        }

    ticket_state = state[key]
    processed = set(ticket_state["processed_comment_ids"])
    requester_id = ticket_state["requester_id"]

    comments = client.get_comments(ticket_id)

    for comment in comments:
        comment_id = comment["id"]

        if comment_id in processed:
            continue

        # Skip our own messages (service account) and internal notes
        if comment["author_id"] == service_account_id or not comment.get("public", True):
            processed.add(comment_id)
            continue

        # New public comment from trainee — attempt to match a reply
        reply_body = match_reply(comment.get("body", ""), scenario)

        if reply_body:
            client.post_comment_as_requester(ticket_id, reply_body, requester_id)
            print(f"    [ticket {ticket_id}] Replied to comment {comment_id}")
        else:
            print(f"    [ticket {ticket_id}] No trigger matched for comment {comment_id} — no reply sent")

        processed.add(comment_id)

    ticket_state["processed_comment_ids"] = list(processed)
    save_state(state)


# ── Batch processing (called by grade_tickets.py) ─────────────────────────────

def watch_active_tickets(client, load_scenario_by_id, service_account_id: int) -> None:
    """
    Find all active (unsolved) training tickets and process new replies.
    Called once per poll cycle from grade_tickets.py.

    Args:
        client:               ZendeskClient instance
        load_scenario_by_id:  callable(scenario_id: str) -> dict | None
        service_account_id:   user ID of the Litmus Lab service account
    """
    tickets = client.get_active_training_tickets()

    if not tickets:
        return

    print(f"  [reply watcher] {len(tickets)} active ticket(s) to check")

    for ticket in tickets:
        tags = ticket.get("tags", [])
        scenario_id = _extract_scenario_id(tags)

        if not scenario_id:
            continue

        scenario = load_scenario_by_id(scenario_id)
        if not scenario or not scenario.get("scripted_replies"):
            continue  # scenario has no scripted replies defined

        process_ticket(client, scenario, ticket, service_account_id)


def _extract_scenario_id(tags: list[str]) -> str | None:
    for tag in tags:
        if tag.startswith("scenario-"):
            return tag[len("scenario-"):]
    return None
