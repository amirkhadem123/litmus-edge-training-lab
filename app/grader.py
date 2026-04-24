"""
grader.py — LLM-agnostic grading for trainee responses.

AI config (api_base, api_key, model) is injected by the caller (main.py),
which reads it from the database settings (with env-var fallback).
"""

import json
from dataclasses import dataclass

import httpx
from openai import OpenAI

PASS_THRESHOLD = 70


@dataclass
class GradeResult:
    score: int
    passed: bool
    action_correct: bool
    feedback: str
    key_issues: list[str]


def grade_response(
    scenario: dict,
    ticket_thread: list[dict],
    escalated: bool,
    *,
    api_base: str,
    api_key: str,
    model: str,
    ssl_verify: bool = True,
) -> GradeResult:
    """
    Grade a trainee's full ticket response against the scenario rubric.

    Args:
        scenario:      Parsed scenario YAML dict.
        ticket_thread: List of comment dicts (chronological, public only).
        escalated:     True if the trainee checked the escalation box.
        api_base:      OpenAI-compatible API base URL.
        api_key:       API key for the endpoint.
        model:         Model name to use for grading.
        ssl_verify:    Set False for internal endpoints with self-signed certificates.

    Returns:
        GradeResult with score, feedback, and key issues.
    """
    expected_action = scenario["expected_action"]
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

    with httpx.Client(verify=ssl_verify) as http_client:
        client = OpenAI(
            base_url=api_base,
            api_key=api_key,
            http_client=http_client,
        )
        response = client.chat.completions.create(
            model=model,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
        )

    raw = response.choices[0].message.content.strip()

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


def format_internal_note(
    grade: GradeResult,
    scenario: dict,
    trainee_name: str,
    *,
    model: str,
) -> str:
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
Model:           {model}

Score:           {grade.score}/100  {status_icon} {'PASSED' if grade.passed else 'FAILED'}
Correct action:  {action_icon} {'Yes' if grade.action_correct else 'No — wrong resolve/escalate decision'}

KEY OBSERVATIONS:
{issues_block if issues_block else '  (none recorded)'}

TRAINER FEEDBACK:
{grade.feedback}
{'─' * 50}"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_thread(comments: list[dict]) -> str:
    """Convert the comment list into a readable transcript for the LLM."""
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
