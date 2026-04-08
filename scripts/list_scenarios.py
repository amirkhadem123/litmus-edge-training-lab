#!/usr/bin/env python3
"""
list_scenarios.py — List all available training scenarios.

Usage:
    python scripts/list_scenarios.py
    python scripts/list_scenarios.py --verbose
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

SCENARIOS_DIR = Path(__file__).parent.parent / "scenarios"


def load_all_scenarios() -> list[dict]:
    scenarios = []
    for path in sorted(SCENARIOS_DIR.glob("*.yaml")):
        with open(path) as f:
            scenarios.append(yaml.safe_load(f))
    return scenarios


def main():
    verbose = "--verbose" in sys.argv
    scenarios = load_all_scenarios()

    if not scenarios:
        print(f"No scenario YAML files found in {SCENARIOS_DIR}")
        sys.exit(1)

    # Column widths
    print(f"\n{'ID':<10} {'TYPE':<10} {'DIFF':<14} {'TITLE'}")
    print("─" * 70)

    for s in scenarios:
        action = s.get("expected_action", "?").upper()
        difficulty = s.get("difficulty", "?").capitalize()
        sid = s.get("id", "?")
        title = s.get("title", "?")

        action_label = f"[{action}]"
        print(f"{sid:<10} {action_label:<10} {difficulty:<14} {title}")

        if verbose:
            customer = s.get("customer", {})
            print(f"           Customer: {customer.get('name')} — {customer.get('company')} (LE {customer.get('le_version')})")
            checklist = s.get("diagnostic_checklist", [])
            if checklist:
                print(f"           Checklist: {len(checklist)} questions")
            attachments = s.get("ticket", {}).get("attachments", [])
            if attachments:
                print(f"           Screenshots: {len(attachments)} file(s)")
                for a in attachments:
                    path = SCENARIOS_DIR / "screenshots" / a
                    exists = "✅" if path.exists() else "❌ MISSING"
                    print(f"             {exists}  {a}")
            print()

    resolve_count = sum(1 for s in scenarios if s.get("expected_action") == "resolve")
    escalate_count = sum(1 for s in scenarios if s.get("expected_action") == "escalate")
    print(f"\nTotal: {len(scenarios)} scenarios  ({resolve_count} resolve, {escalate_count} escalate)")

    if not verbose:
        print("Run with --verbose to see screenshot status and checklist details.")


if __name__ == "__main__":
    main()
