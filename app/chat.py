"""
chat.py — AI-powered customer simulation for Litmus Lab.

Generates contextual customer replies using the scenario YAML's
customer_ai_context block. The AI plays the customer role, constrained
to what the scenario author says the customer knows and can reveal.
"""

import os

import httpx
from openai import AsyncOpenAI

_DEFAULT_CHAT_MODEL = "gpt-4o-mini"

_GENERIC_FALLBACK = (
    "I appreciate your reply. Could you be more specific about what steps "
    "I should follow? I want to make sure I do this correctly."
)


def _build_system_prompt(scenario: dict) -> str:
    customer = scenario.get("customer", {})
    ticket = scenario.get("ticket", {})
    ctx = scenario.get("customer_ai_context", {})

    name = customer.get("name", "the customer")
    company = customer.get("company", "")
    le_version = customer.get("le_version", "unknown")
    company_suffix = f" at {company}" if company else ""

    initial_message = ticket.get("initial_message", "").strip()
    knows = ctx.get("knows", "You have a support issue with Litmus Edge.").strip()
    does_not_know = ctx.get("does_not_know", "You don't know the technical root cause.").strip()
    behavior = ctx.get("behavior", "Be helpful and answer questions directly.").strip()

    return f"""You are {name}{company_suffix}.
You are using Litmus Edge version {le_version}.

SITUATION:
{initial_message}

WHAT YOU KNOW:
{knows}

WHAT YOU DO NOT KNOW:
{does_not_know}

BEHAVIOR RULES:
{behavior}

Stay in character at all times. Answer questions about what you can see in the UI when asked.
Do not reveal the root cause unless the support analyst explicitly identifies it and asks you to confirm.
Keep replies concise — 2–4 sentences. You are not a Litmus Edge technical expert."""


async def generate_customer_reply(
    scenario: dict,
    conversation_history: list[dict],
) -> str:
    """
    Generate an AI customer reply based on the scenario and full conversation.

    Args:
        scenario: Parsed scenario YAML dict (should contain customer_ai_context).
        conversation_history: Chronological list of comment dicts from get_comments(),
            including the initial customer message as the first entry.

    Returns:
        The AI-generated reply string.
        Returns a generic fallback if LITMUS_API_BASE or LITMUS_API_KEY are not set.
    """
    api_base = os.environ.get("LITMUS_API_BASE")
    api_key = os.environ.get("LITMUS_API_KEY")
    model = os.environ.get("LITMUS_CHAT_MODEL", _DEFAULT_CHAT_MODEL)

    if not api_base or not api_key:
        return _GENERIC_FALLBACK

    system_prompt = _build_system_prompt(scenario)
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    # Skip the first comment (the initial_message — already in the system prompt).
    # From the AI's perspective it IS the customer:
    #   trainee messages  → "user"   (the support analyst asking the customer)
    #   customer messages → "assistant" (prior AI replies)
    for comment in conversation_history[1:]:
        author = comment.get("author_type")
        body = (comment.get("body") or "").strip()
        if not body or author not in ("trainee", "customer"):
            continue
        role = "user" if author == "trainee" else "assistant"
        messages.append({"role": role, "content": body})

    # Use the OpenAI SDK directly with SSL verification disabled.
    # This is required for internal company endpoints with self-signed certs.
    async with httpx.AsyncClient(verify=False) as http_client:
        client = AsyncOpenAI(
            base_url=api_base,
            api_key=api_key,
            http_client=http_client,
        )
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=300,
        )
    return response.choices[0].message.content.strip()
