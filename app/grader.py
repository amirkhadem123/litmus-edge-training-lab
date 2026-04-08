"""
grader.py — LLM-agnostic grading for trainee responses.

Uses LiteLLM as the provider layer, which supports OpenAI, Anthropic, Google
Gemini, Azure, Mistral, and many others through a unified interface.

Configure via .env:
    LITMUS_MODEL=claude-haiku-4-5-20251001   # default
    LITMUS_MODEL=gpt-4o-mini
    LITMUS_MODEL=gemini/gemini-1.5-flash

Set the matching API key for your chosen provider:
    ANTHROPIC_API_KEY   → any claude-* model
    OPENAI_API_KEY      → any gpt-* model
    GEMINI_API_KEY      → any gemini/* model
"""

import json
import os
from dataclasses import dataclass

import litellm

# Suppress LiteLLM's verbose startup banner
litellm.suppress_debug_info = True


@dataclass
class GradeResult:
    score: int              # 0–100
    passed: bool            # score >= PASS_THRESHOLD
    action_correct: bool    # did trainee choose resolve vs. escalate correctly?
    feedback: str           # 2–3 paragraph written feedback for the trainee
    key_issues: list[str]   # specific strengths / gaps (bullet points)


PASS_THRESHOLD = 70

# Default model — override with LITMUS_MODEL env var.
# Examples: "gpt-4o-mini", "gemini/gemini-1.5-flash", "claude-haiku-4-5-20251001"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def _active_model() -> str:
    return os.environ.get("LITMUS_MODEL", DEFAULT_MODEL)


def grade_response(scenario: dict, ticket_thread: list[dict], escalated: bool) -> GradeResult:
    """
    Grade a trainee's full ticket response against the scenario rubric.

    Args:
        scenario:      Parsed scenario YAML dict.
        ticket_thread: List of comment dicts (in chronological order).
        escalated:     True if the trainee checked the escalation box.

    Returns:
        GradeResult with score, feedback, and key issues.
    """
    expected_action = scenario["expected_action"]  # "resolve" or "escalate"
    action_correct = (
        (expected_action == "escalate" and escalated)
        or (expected_action == "resolve" and not escalated)
    )

    transcript = _format_thread(ticket_thread)

    system_prompt = (
        "You are an expert Litmus Edge L0 customer support trainer. "
        "You are evaluating a trainee support analyst's response to a simulated support ticket. "
        "Be fair but rigorous. Score based on the rubric provided. "
        "Return ONLY valid JSON — no markdown, no explanation outside the JSON object."
    )

    user_prompt = f"""## Scenario Context

**Title:** {scenario['title']}
**Expected action:** {expected_action.upper()} (trainee should {"escalate to engineering" if expected_action == "escalate" else "provide a resolution guide to the customer"})
**Root cause:** {scenario['root_cause']}
{"**Escalation reason:** " + scenario.get('escalation_reason', '') if expected_action == 'escalate' else ""}
**Correct response summary:** {scenario.get('correct_response_summary', 'N/A')}

## Grading Rubric
{scenario['grading_rubric']}

## Trainee's Action
- Applied 'escalate' tag: {"YES" if escalated else "NO"}
- Expected: {"escalate" if expected_action == "escalate" else "resolve (do NOT escalate)"}
- Action correct: {"YES" if action_correct else "NO — this is a critical failure"}

## Full Ticket Thread (chronological)
{transcript}

## Your Task
Evaluate the trainee's response strictly according to the rubric above.
Return a JSON object with exactly these fields:
{{
  "score": <integer 0-100>,
  "feedback": "<2-3 paragraph written feedback addressed to the trainee>",
  "key_issues": ["<specific strength or gap>", "<another one>", ...]
}}

The score must reflect the rubric point deductions. Do not be lenient about critical failures."""

    response = litellm.completion(
        model=_active_model(),
        max_tokens=1024,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
    )

    raw = response.choices[0].message.content.strip()

    # Some models wrap JSON in a code fence despite instructions — strip it
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    result = json.loads(raw)

    score = max(0, min(100, int(result["score"])))
    return GradeResult(
        score=score,
        passed=score >= PASS_THRESHOLD,
        action_correct=action_correct,
        feedback=result["feedback"],
        key_issues=result.get("key_issues", []),
    )


def format_internal_note(grade: GradeResult, scenario: dict, trainee_name: str) -> str:
    """Format a GradeResult as a training grade report."""
    status_icon = "✅" if grade.passed else "❌"
    action_icon = "✅" if grade.action_correct else "❌"
    expected = scenario["expected_action"].upper()
    issues_block = "\n".join(f"  • {issue}" for issue in grade.key_issues)

    return f"""LITMUS LAB — TRAINING GRADE
{'─' * 50}
Trainee:         {trainee_name}
Scenario:        {scenario['id']} — {scenario['title']}
Expected action: {expected}
Model:           {_active_model()}

Score:           {grade.score}/100  {status_icon} {'PASSED' if grade.passed else 'FAILED'}
Correct action:  {action_icon} {'Yes' if grade.action_correct else 'No — wrong resolve/escalate decision'}

KEY OBSERVATIONS:
{issues_block if issues_block else '  (none recorded)'}

TRAINER FEEDBACK:
{grade.feedback}
{'─' * 50}"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_thread(comments: list[dict]) -> str:
    """Convert the local comment list into a readable transcript for the LLM."""
    author_labels = {
        "customer": "CUSTOMER",
        "trainee":  "TRAINEE",
        "system":   "SYSTEM",
    }
    lines = []
    for i, comment in enumerate(comments, 1):
        author_type = comment.get("author_type", "unknown")
        label = author_labels.get(author_type, author_type.upper())
        body = comment.get("body", "").strip()
        lines.append(f"[Comment {i} — {label}]\n{body}\n")
    return "\n".join(lines)
