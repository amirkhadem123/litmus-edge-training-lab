"""
scenarios.py — Scenario loading and scripted customer simulation for Litmus Lab v2.

Customer replies are keyword-triggered (not generative). Every trainee who asks
the right question gets the right scripted response. Grading reliability depends
on this bounded conversation behaviour.
"""

from pathlib import Path

import yaml

SCENARIOS_DIR = Path("scenarios")


# ── Loading ───────────────────────────────────────────────────────────────────

def load_scenario(scenario_id: str) -> dict | None:
    """Load a scenario YAML by its id field. Returns None if not found."""
    for path in SCENARIOS_DIR.glob("*.yaml"):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if data.get("id") == scenario_id:
                return data
    return None


def load_all_scenarios() -> list[dict]:
    scenarios = []
    for path in sorted(SCENARIOS_DIR.glob("*.yaml")):
        with open(path, encoding="utf-8") as f:
            scenarios.append(yaml.safe_load(f))
    return scenarios


def load_certificate_scenarios() -> list[dict]:
    """Return certificate scenarios sorted by checkpoint number."""
    return sorted(
        [s for s in load_all_scenarios() if s.get("mode") == "certificate"],
        key=lambda s: s.get("checkpoint", 99),
    )


def load_practice_scenarios() -> list[dict]:
    """Return practice scenarios sorted by id."""
    return sorted(
        [s for s in load_all_scenarios() if s.get("mode") == "practice"],
        key=lambda s: s.get("id", ""),
    )


# ── Keyword-based customer simulation ─────────────────────────────────────────

def match_reply(scenario: dict, trainee_message: str) -> str:
    """
    Case-insensitive partial keyword match against scripted_replies.
    Returns the first matching scripted reply, or the fallback_reply.
    Scenario authors should order triggers from most-specific to least-specific.
    """
    msg = trainee_message.lower()
    for reply_block in scenario.get("scripted_replies", []):
        triggers = reply_block.get("triggers", [])
        if any(trigger.lower() in msg for trigger in triggers):
            return reply_block["reply"].strip()
    return scenario.get(
        "fallback_reply",
        "I'm not sure what you mean. Could you be more specific about what to look for?",
    ).strip()


# ── Urgency injection (Checkpoint 3 only) ─────────────────────────────────────

def get_customer_reply_count(messages: list[dict]) -> int:
    """Count how many customer messages have been sent in this attempt so far."""
    return sum(1 for m in messages if m["sender"] == "customer")


def should_inject_urgency(scenario: dict, current_customer_count: int) -> bool:
    """
    Return True if urgency text should be appended to the NEXT customer reply.
    Fires exactly once: when the count of prior customer replies equals
    trigger_after_customer_message (i.e., the next reply will be reply N).
    """
    ui = scenario.get("urgency_injection", {})
    if not ui.get("enabled"):
        return False
    trigger = ui.get("trigger_after_customer_message", 999)
    return current_customer_count + 1 == trigger


def build_customer_reply(
    scenario: dict,
    trainee_message: str,
    messages: list[dict],
    urgency_injected: bool,
) -> tuple[str, bool]:
    """
    Build the full customer reply string and indicate whether urgency was injected.

    Returns:
        (reply_text, did_inject_urgency)
    """
    reply = match_reply(scenario, trainee_message)

    if not urgency_injected and should_inject_urgency(scenario, get_customer_reply_count(messages)):
        urgency_text = scenario["urgency_injection"].get("text", "").strip()
        if urgency_text:
            reply = reply + "\n\n" + urgency_text
            return reply, True

    return reply, False
