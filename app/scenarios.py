"""
scenarios.py — Scenario loading and customer simulation for Litmus Lab v2.

Two customer simulation modes:

  AI-powered (default for certificate checkpoints):
    Scenarios define a `customer_persona` and `customer_knowledge` block.
    The customer is played by an LLM that stays in character, responds
    naturally to any phrasing, and gets genuinely confused by outlandish
    or impossible instructions.

  Keyword-triggered (legacy, for practice scenarios):
    Scenarios define `scripted_replies` and `fallback_reply`.
    The first matching keyword trigger wins; no match returns the fallback.
    Kept for backward compatibility — practice scenarios continue to work
    without change.

Grading reliability is not affected by the simulation mode: the grading
agent evaluates the full transcript regardless of how customer replies
were generated.
"""

from pathlib import Path

import httpx
import yaml
from openai import AsyncOpenAI

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


# ── Keyword-based customer simulation (legacy / practice scenarios) ────────────

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


# ── AI-powered customer simulation (certificate checkpoints) ──────────────────

def _build_customer_system_prompt(scenario: dict) -> str:
    """Construct the system prompt that defines the AI customer's character and constraints."""
    customer = scenario.get("customer", {})
    persona = scenario.get("customer_persona", "").strip()
    knowledge = scenario.get("customer_knowledge", {})

    litmus_certified = customer.get("litmus_certified", False)
    ui_access = customer.get("ui_access", True)
    tech_level = customer.get("technical_level", "low").upper()

    withheld_items = knowledge.get("withheld", [])
    if withheld_items:
        withheld_lines = [
            f'- Do NOT volunteer: "{item["info"]}" — only reveal this if the analyst asks about: {item["release_when"]}'
            for item in withheld_items
        ]
        withheld_text = "\n".join(withheld_lines)
    else:
        withheld_text = "None — share what you know freely when asked."

    cert_line = (
        "YES — familiar with the Litmus Edge UI; knows how to navigate to DeviceHub, "
        "Integrations, Flows, and other areas without being guided there step by step."
        if litmus_certified
        else
        "NO — not familiar with Litmus Edge UI terminology or layout; needs to be told "
        "exactly where to go and what to click."
    )

    return f"""You are playing the role of a real customer in a Litmus Edge support ticket simulation. Stay in character throughout — you are {customer.get("name", "a customer")}, not an AI assistant.

CUSTOMER PROFILE:
- Name: {customer.get("name", "Customer")}
- Role: {customer.get("role", "Unknown")}
- Company: {customer.get("company", "Unknown")}
- Litmus Edge version: {customer.get("le_version", "unknown")}
- Has completed Litmus User Certificate: {cert_line}
- Has direct access to Litmus Edge UI: {"YES" if ui_access else "NO — must involve a colleague to check the UI"}
- Technical level: {tech_level}

PERSONA:
{persona}

WHAT YOU CURRENTLY OBSERVE / KNOW:
{knowledge.get("observes", "").strip()}

WHAT YOU CAN DO WHEN INSTRUCTED:
{knowledge.get("can_do", "").strip()}

WHAT YOU DO NOT KNOW:
{knowledge.get("does_not_know", "").strip()}

INFORMATION TO WITHHOLD UNTIL SPECIFICALLY ASKED:
{withheld_text}

BEHAVIOUR RULES:
1. Respond naturally in plain language that matches your technical level. Never use jargon you would not know.
2. Only reveal withheld information when the analyst's question clearly matches the stated release condition. Do not hint at it.
3. If the analyst asks you to do something impossible, nonsensical, made-up, or outside your knowledge, respond with genuine confusion in plain language — the way a real non-technical person would. Do not give a robotic error message. Just say you do not understand and ask them to be more specific.
4. If a question is vague, answer as best you can but note what is unclear to you.
5. When directed to look at something in Litmus Edge, report exactly what you see on screen — status labels, badge colours, button text, error messages — as precisely as you can.
6. Keep responses short: 2–4 sentences is usually enough. You are a busy operations manager.
7. Do not volunteer the root cause or any technical information you do not actually know.
8. Never break character, acknowledge the simulation, or refer to yourself as an AI."""


async def get_ai_customer_reply(
    scenario: dict,
    messages: list[dict],
    api_config: dict,
) -> str:
    """
    Generate a natural customer reply using an LLM.

    The full conversation history (including the trainee's latest message,
    which must already be appended to `messages`) is sent as the chat context.
    The customer persona and knowledge constraints are encoded in the system prompt.
    """
    system_prompt = _build_customer_system_prompt(scenario)

    # Build chat history: customer messages → "assistant", trainee messages → "user"
    chat_messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        role = "assistant" if msg["sender"] == "customer" else "user"
        chat_messages.append({"role": role, "content": msg["content"]})

    proxy_kwargs = {"proxy": api_config["http_proxy"]} if api_config.get("http_proxy") else {}
    async with httpx.AsyncClient(
        verify=api_config.get("ssl_verify", True), **proxy_kwargs
    ) as http_client:
        client = AsyncOpenAI(
            base_url=api_config["api_base"],
            api_key=api_config["api_key"],
            http_client=http_client,
        )
        response = await client.chat.completions.create(
            model=api_config["grade_model"],
            max_tokens=300,
            temperature=0.7,
            messages=chat_messages,
        )

    return response.choices[0].message.content.strip()


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


async def build_customer_reply(
    scenario: dict,
    trainee_message: str,
    messages: list[dict],
    urgency_injected: bool,
    api_config: dict | None = None,
) -> tuple[str, bool]:
    """
    Build the full customer reply and indicate whether urgency was injected.

    Dispatches to AI-powered simulation if the scenario has a `customer_persona`
    block and api_config is provided; otherwise falls back to keyword matching.

    Returns:
        (reply_text, did_inject_urgency)
    """
    use_ai = "customer_persona" in scenario and api_config and api_config.get("api_key")

    if use_ai:
        reply = await get_ai_customer_reply(scenario, messages, api_config)
    else:
        reply = match_reply(scenario, trainee_message)

    if not urgency_injected and should_inject_urgency(scenario, get_customer_reply_count(messages)):
        urgency_text = scenario["urgency_injection"].get("text", "").strip()
        if urgency_text:
            reply = reply + "\n\n" + urgency_text
            return reply, True

    return reply, False
