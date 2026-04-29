"""
grader.py — Dimensional grading for Litmus Lab v2.

Grading uses a single Claude API call (or any OpenAI-compatible endpoint).
The LLM evaluates each rubric dimension independently and returns structured JSON.
Critical score penalties are applied in Python AFTER the JSON is parsed —
they are never left to the LLM.

AI config (api_base, api_key, model, ssl_verify) is injected by the caller.
"""

import json
from dataclasses import dataclass, field

import httpx
from openai import OpenAI

PASS_THRESHOLD = 70


@dataclass
class GradeResult:
    total_score: int
    passed: bool
    expected_action: str
    trainee_action: str
    correct_direction: bool
    dimensions: list[dict]        # [{name, max_points, score, feedback}, ...]
    overall_feedback: str
    raw_response: str = field(default="")


def grade_response(
    scenario: dict,
    messages: list[dict],
    trainee_action: str,
    *,
    api_base: str,
    api_key: str,
    model: str,
    ssl_verify: bool = True,
) -> GradeResult:
    """
    Grade a trainee's full attempt against the scenario's dimensional rubric.

    Args:
        scenario:       Parsed scenario YAML dict.
        messages:       Chronological list of message dicts (sender, content).
        trainee_action: "resolve" or "escalate" — what the trainee chose.
        api_base:       OpenAI-compatible API base URL.
        api_key:        API key.
        model:          Model name.
        ssl_verify:     False for internal endpoints with self-signed certs.

    Returns:
        GradeResult with dimensional scores and feedback.
    """
    expected_action = scenario["expected_action"]
    correct_direction = trainee_action == expected_action

    rubric = scenario.get("grading_rubric", {})
    dimensions = rubric.get("dimensions", [])
    pass_threshold = rubric.get("pass_threshold", PASS_THRESHOLD)

    transcript = _format_transcript(messages)
    dimensions_prompt = _format_dimensions_for_prompt(dimensions)

    red_herring_block = ""
    rh = scenario.get("red_herring", {})
    if rh.get("enabled"):
        red_herring_block = f"\n**Red herring:** {rh.get('description', '').strip()}\n"

    system_prompt = (
        "You are an expert Litmus Edge L0 customer support trainer evaluating a trainee's "
        "response to a simulated support ticket. Be fair but rigorous. "
        "Score each dimension independently based on the guidance provided. "
        "Return ONLY valid JSON — no markdown fences, no text outside the JSON object."
    )

    user_prompt = f"""## Scenario Context

**Title:** {scenario.get('title', '')}
**Checkpoint:** {scenario.get('checkpoint', 'Practice')}
**Expected action:** {expected_action.upper()}
**Root cause:** {scenario.get('root_cause', '').strip()}
{red_herring_block}
**Correct response summary:** {scenario.get('correct_response_summary', scenario.get('escalation_reason', 'N/A')).strip()}

## Trainee's Action
- Trainee chose: {trainee_action.upper()}
- Expected: {expected_action.upper()}
- Direction correct: {"YES" if correct_direction else "NO — critical failure"}

## Grading Dimensions
{dimensions_prompt}

## Full Conversation Transcript
{transcript}

## Your Task
Evaluate the trainee's performance against each dimension above.
For each dimension, assign a score within its point range and write one paragraph of feedback.
Also write an overall 2–3 paragraph summary.

Return a JSON object with EXACTLY this structure:
{{
  "total_score": <sum of all dimension scores, integer>,
  "sequence_skipped": <true if trainee jumped to conclusion without following elimination sequence, else false>,
  "dimensions": [
    {{
      "name": "<exact dimension name>",
      "max_points": <integer>,
      "score": <integer within 0..max_points>,
      "feedback": "<one paragraph>"
    }},
    ...
  ],
  "overall_feedback": "<2-3 paragraph summary>"
}}

The total_score MUST equal the sum of all dimension scores.
Do not soften penalties — apply rubric guidance strictly."""

    with httpx.Client(verify=ssl_verify) as http_client:
        client = OpenAI(
            base_url=api_base,
            api_key=api_key,
            http_client=http_client,
        )
        response = client.chat.completions.create(
            model=model,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
        )

    raw = response.choices[0].message.content.strip()

    # Strip markdown fences if LLM added them despite instructions
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    result = json.loads(raw)

    # Recompute total from dimension scores (prevents LLM from softening the sum)
    computed_total = sum(d["score"] for d in result.get("dimensions", []))
    result["total_score"] = computed_total

    # Apply critical penalties in code
    result = _apply_penalties(result, scenario, correct_direction)

    passed = result["total_score"] >= pass_threshold

    return GradeResult(
        total_score=result["total_score"],
        passed=passed,
        expected_action=expected_action,
        trainee_action=trainee_action,
        correct_direction=correct_direction,
        dimensions=result.get("dimensions", []),
        overall_feedback=result.get("overall_feedback", ""),
        raw_response=raw,
    )


def _apply_penalties(result: dict, scenario: dict, correct_direction: bool) -> dict:
    """Enforce critical score caps as defined in the scenario rubric. In-place."""
    rubric = scenario.get("grading_rubric", {})
    penalties = rubric.get("critical_penalties", [])
    checkpoint = scenario.get("checkpoint")

    for penalty in penalties:
        applies = checkpoint in penalty.get("applies_to_checkpoints", [])
        if not applies:
            continue

        condition = penalty["condition"]
        # YAML uses either "cap" or legacy "effect" key; both use "cap_at_N" format
        cap_str = penalty.get("cap", penalty.get("effect", "cap_at_0"))

        triggered = False
        if condition == "wrong_direction" and not correct_direction:
            triggered = True
        elif condition == "sequence_skipped" and result.get("sequence_skipped"):
            triggered = True

        if triggered:
            cap = int(cap_str.split("_")[-1])  # "cap_at_50" → 50
            result["total_score"] = min(result["total_score"], cap)

    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_transcript(messages: list[dict]) -> str:
    lines = []
    for i, msg in enumerate(messages, 1):
        sender = msg.get("sender", "unknown").upper()
        content = msg.get("content", "").strip()
        lines.append(f"[{i}] {sender}: {content}")
    return "\n\n".join(lines)


def _format_dimensions_for_prompt(dimensions: list[dict]) -> str:
    parts = []
    for d in dimensions:
        guidance = d.get("description", d.get("guidance", "")).strip()
        parts.append(
            f"**{d['name']}** ({d['max_points']} points)\n{guidance}"
        )
    return "\n\n".join(parts)


def format_grade_display(grade: GradeResult, scenario: dict, trainee_name: str, model: str) -> str:
    """Plain-text grade summary for display in attempt view (monospace block)."""
    checkpoint = scenario.get("checkpoint", "Practice")
    title = scenario.get("title", scenario.get("id", ""))
    status_icon = "✅ PASSED" if grade.passed else "❌ NOT PASSED"
    direction_icon = "✅" if grade.correct_direction else "❌"

    dim_scores = "\n".join(
        f"  {d['name']:<35} {d['score']}/{d['max_points']}"
        for d in grade.dimensions
    )

    dim_feedback = "\n\n".join(
        f"  {d['name']}\n  {d['feedback']}"
        for d in grade.dimensions
    )

    return f"""LITMUS LAB — CHECKPOINT {checkpoint} RESULT
{'─' * 50}
Trainee:          {trainee_name}
Checkpoint:       {checkpoint} — {title}
Expected action:  {grade.expected_action.upper()}
Trainee action:   {grade.trainee_action.upper()}

Score:            {grade.total_score}/100  {status_icon}
Direction:        {direction_icon} {'Correct' if grade.correct_direction else 'Wrong — penalty applied'}
Model:            {model}

DIMENSION SCORES:
{dim_scores}

FEEDBACK BY DIMENSION:
{dim_feedback}

OVERALL:
  {grade.overall_feedback}
{'─' * 50}"""
