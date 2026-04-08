#!/usr/bin/env python3
"""
create_ticket.py — Trainer CLI: create a Zendesk training ticket for a trainee.

Usage:
    python scripts/create_ticket.py <scenario-id> <trainee-email>

Examples:
    python scripts/create_ticket.py le-s01 jane.doe@company.com
    python scripts/create_ticket.py le-s05 john.smith@company.com

The script loads the scenario YAML, uploads any screenshots as attachments,
builds the ticket body, and creates the ticket in Zendesk assigned to the trainee.
"""

import sys
import os
from pathlib import Path

# Allow imports from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import yaml
from app.zendesk_client import ZendeskClient


SCENARIOS_DIR = Path(__file__).parent.parent / "scenarios"
SCREENSHOTS_DIR = SCENARIOS_DIR / "screenshots"


def load_scenario(scenario_id: str) -> dict:
    matches = list(SCENARIOS_DIR.glob(f"{scenario_id}-*.yaml"))
    if not matches:
        raise FileNotFoundError(
            f"No scenario file found for '{scenario_id}' in {SCENARIOS_DIR}"
        )
    with open(matches[0]) as f:
        return yaml.safe_load(f)


def build_ticket_body(scenario: dict, attachment_tokens: dict[str, str]) -> str:
    """Build the full ticket body in plain text."""
    customer = scenario["customer"]
    ticket = scenario["ticket"]

    # Diagnostic checklist
    checklist_lines = "\n".join(
        f"  {i}. {q}" for i, q in enumerate(scenario.get("diagnostic_checklist", []), 1)
    )

    # Screenshot references (Zendesk inline images need the upload token)
    attachments_note = ""
    if attachment_tokens:
        filenames = ", ".join(Path(p).name for p in ticket.get("attachments", []))
        attachments_note = f"\n📎 Attachments: {filenames}\n"

    body = f"""From: {customer['name']} ({customer['company']})
Litmus Edge version: {customer['le_version']}
{attachments_note}
---

{ticket['initial_message'].strip()}

---
🔍 Before you respond, consider these diagnostic questions:
{checklist_lines}

Please reply with either:
  A) Step-by-step instructions to resolve the issue, OR
  B) An escalation note (apply the 'escalate' tag and explain why this is above L0)"""

    return body


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    scenario_id = sys.argv[1]
    trainee_email = sys.argv[2]

    print(f"Loading scenario '{scenario_id}'...")
    try:
        scenario = load_scenario(scenario_id)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    client = ZendeskClient()

    # Upload screenshots
    attachment_tokens = {}
    for rel_path in scenario["ticket"].get("attachments", []):
        file_path = SCREENSHOTS_DIR / rel_path
        if not file_path.exists():
            print(f"  Warning: screenshot not found, skipping — {file_path}")
            continue
        print(f"  Uploading {file_path.name}...")
        token = client.upload_attachment(file_path)
        attachment_tokens[rel_path] = token

    # Build content
    body = build_ticket_body(scenario, attachment_tokens)
    subject = scenario["ticket"]["subject"]
    customer = scenario["customer"]
    tags = ["litmus-lab-training", f"scenario-{scenario['id']}"]

    print(f"Creating ticket: '{subject}'")
    print(f"  Assignee: {trainee_email}")
    print(f"  Tags: {tags}")

    ticket = client.create_ticket(
        subject=subject,
        body=body,
        requester_name=customer["name"],
        requester_email=f"training-customer+{scenario['id']}@litmuslab.internal",
        assignee_email=trainee_email,
        tags=tags,
    )

    # Attach uploaded screenshots to the ticket
    if attachment_tokens:
        client._put(
            f"/tickets/{ticket['id']}.json",
            {
                "ticket": {
                    "comment": {
                        "body": "📎 Screenshots attached.",
                        "public": False,
                        "uploads": list(attachment_tokens.values()),
                    }
                }
            },
        )

    subdomain = os.environ["ZENDESK_SUBDOMAIN"]
    ticket_url = f"https://{subdomain}.zendesk.com/agent/tickets/{ticket['id']}"
    print(f"\n✅ Ticket created: {ticket_url}")
    print(f"   Ticket ID: {ticket['id']}")
    print(f"   Status: {ticket['status']}")


if __name__ == "__main__":
    main()
