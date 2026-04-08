"""
main.py — FastAPI application for the Litmus Lab ticket simulation.

Start with:
    uvicorn app.main:app --reload

Routes:
    GET  /                          — ticket queue
    GET  /new                       — create ticket form
    POST /tickets/new               — create ticket + redirect
    GET  /tickets/{id}              — ticket conversation view
    POST /tickets/{id}/reply        — submit trainee reply → trigger customer reply
    POST /tickets/{id}/solve        — grade and close ticket
"""

from pathlib import Path

import jinja2
import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.database import (
    add_answered_topic,
    add_comment,
    create_ticket,
    get_all_tickets,
    get_answered_topics,
    get_comments,
    get_ticket,
    init_db,
    set_escalated,
    solve_ticket,
)
from app.grader import format_internal_note, grade_response

load_dotenv()

app = FastAPI(title="Litmus Lab")

# Serve scenario screenshots as static files.
# Paths in YAML are relative to scenarios/screenshots/, e.g. "le-s01/foo.png".
# They are served at /screenshots/le-s01/foo.png.
app.mount(
    "/screenshots",
    StaticFiles(directory="scenarios/screenshots"),
    name="screenshots",
)

# Render templates directly with Jinja2 (bypasses Starlette's Jinja2Templates
# wrapper, which has a Python 3.14 incompatibility in its LRUCache).
# cache_size=0 disables template caching — fine for a local training tool.
_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader("app/templates"),
    cache_size=0,
)


def _render(template_name: str, **context) -> HTMLResponse:
    """Render a Jinja2 template and return an HTMLResponse."""
    template = _jinja_env.get_template(template_name)
    return HTMLResponse(template.render(**context))


SCENARIOS_DIR = Path("scenarios")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


# ── Scenario helpers ──────────────────────────────────────────────────────────

def load_scenario(scenario_id: str) -> dict | None:
    """Load a single scenario YAML by ID (e.g. 'le-s01')."""
    for path in SCENARIOS_DIR.glob(f"{scenario_id}-*.yaml"):
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return None


def load_all_scenarios() -> list[dict]:
    """Load all scenario YAMLs, sorted by filename."""
    scenarios = []
    for path in sorted(SCENARIOS_DIR.glob("le-s*.yaml")):
        with open(path, encoding="utf-8") as f:
            scenarios.append(yaml.safe_load(f))
    return scenarios


# ── Reply matching ────────────────────────────────────────────────────────────

def match_reply(
    comment_body: str,
    scenario: dict,
    answered_topics: list[str],
) -> tuple[str | None, list[str]]:
    """
    Match all triggered topics in the comment (Option A: multi-match).
    For each match, use repeat_reply if the topic was already answered (Option B).

    Returns:
        (combined_reply, newly_answered_topics)
        combined_reply is None if nothing matched (not even a fallback).
    """
    body_lower = comment_body.lower()
    matched_parts: list[str] = []
    newly_answered: list[str] = []

    for entry in scenario.get("scripted_replies", []):
        triggers = entry.get("triggers", [])
        if not any(trigger.lower() in body_lower for trigger in triggers):
            continue

        topic = entry.get("topic")
        if topic and topic in answered_topics:
            # Already covered — use the shorter repeat reply if provided
            repeat = entry.get("repeat_reply", "").strip()
            if repeat:
                matched_parts.append(repeat)
        else:
            matched_parts.append(entry["reply"].strip())
            if topic:
                newly_answered.append(topic)

    if matched_parts:
        return "\n\n".join(matched_parts), newly_answered

    fallback = scenario.get("fallback_reply", "").strip()
    return (fallback or None), []


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def queue(request: Request) -> HTMLResponse:
    """Ticket queue — shows all tickets with status and score."""
    tickets = get_all_tickets()
    for ticket in tickets:
        scenario = load_scenario(ticket["scenario_id"])
        ticket["scenario_title"] = scenario["title"] if scenario else ticket["scenario_id"]
    return _render("queue.html", tickets=tickets)


@app.get("/new", response_class=HTMLResponse)
async def new_ticket_form(request: Request) -> HTMLResponse:
    """Create ticket form — trainer selects scenario and enters trainee name."""
    scenarios = load_all_scenarios()
    return _render("new_ticket.html", scenarios=scenarios)


@app.post("/tickets/new")
async def create_ticket_route(
    scenario_id: str = Form(...),
    trainee: str = Form(...),
) -> RedirectResponse:
    """Create a new ticket and post the customer's opening message."""
    scenario = load_scenario(scenario_id)
    if not scenario:
        return RedirectResponse("/new", status_code=303)

    ticket_id = create_ticket(scenario_id, trainee.strip())
    initial_body = scenario["ticket"]["initial_message"].strip()
    add_comment(ticket_id, initial_body, "customer")

    return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)


@app.get("/tickets/{ticket_id}", response_class=HTMLResponse)
async def view_ticket(request: Request, ticket_id: int) -> HTMLResponse:
    """Ticket conversation view."""
    ticket = get_ticket(ticket_id)
    if not ticket:
        return RedirectResponse("/", status_code=303)

    scenario = load_scenario(ticket["scenario_id"])
    comments = get_comments(ticket_id)

    public_comments = [c for c in comments if not c["is_internal"]]
    internal_notes  = [c for c in comments if c["is_internal"]]

    return _render(
        "ticket.html",
        ticket=ticket,
        scenario=scenario,
        public_comments=public_comments,
        internal_notes=internal_notes,
    )


@app.post("/tickets/{ticket_id}/reply")
async def reply(
    ticket_id: int,
    body: str = Form(...),
    escalated: str | None = Form(None),
) -> RedirectResponse:
    """
    Save the trainee's comment, update the escalation flag, and immediately
    post a customer reply if any scripted trigger matches.
    """
    ticket = get_ticket(ticket_id)
    if not ticket or ticket["status"] == "solved":
        return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)

    scenario = load_scenario(ticket["scenario_id"])
    is_escalated = escalated is not None

    add_comment(ticket_id, body.strip(), "trainee")
    set_escalated(ticket_id, is_escalated)

    if scenario:
        answered_topics = get_answered_topics(ticket_id)
        customer_reply, newly_answered = match_reply(body, scenario, answered_topics)
        if customer_reply:
            add_comment(ticket_id, customer_reply, "customer")
        for topic in newly_answered:
            add_answered_topic(ticket_id, topic)

    return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)


@app.post("/tickets/{ticket_id}/solve")
async def solve(
    ticket_id: int,
    body: str = Form(""),
    escalated: str | None = Form(None),
) -> RedirectResponse:
    """
    Optionally post a final trainee comment, then grade the ticket immediately
    using Claude and post the result as an internal note.
    """
    ticket = get_ticket(ticket_id)
    if not ticket or ticket["status"] == "solved":
        return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)

    scenario = load_scenario(ticket["scenario_id"])
    is_escalated = escalated is not None

    if body.strip():
        add_comment(ticket_id, body.strip(), "trainee")

    set_escalated(ticket_id, is_escalated)

    # Grade before closing so we can store the score on the ticket
    public_comments = [c for c in get_comments(ticket_id) if not c["is_internal"]]
    try:
        grade = grade_response(scenario, public_comments, is_escalated)
        solve_ticket(ticket_id, score=grade.score)
        note_body = format_internal_note(grade, scenario, ticket["trainee"])
    except Exception as exc:
        # LLM call failed (missing API key, network error, bad JSON, etc.)
        # Still mark the ticket solved so the trainee isn't stuck,
        # but post the error as the internal note so it's visible.
        solve_ticket(ticket_id, score=None)
        note_body = (
            f"GRADING FAILED — ticket marked solved without a score.\n\n"
            f"Error: {type(exc).__name__}: {exc}\n\n"
            f"Check that LITMUS_MODEL and the matching API key are set in .env, "
            f"then re-run the server."
        )

    add_comment(ticket_id, note_body, "system", is_internal=True)

    return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)
