"""
main.py — FastAPI application for the Litmus Lab ticket simulation.

Start with:
    uvicorn app.main:app --reload

Routes:
    GET  /                          — ticket queue
    GET  /new                       — create ticket form
    POST /tickets/new               — create ticket + redirect
    GET  /tickets/{id}              — ticket conversation view
    POST /tickets/{id}/reply        — submit trainee reply → trigger AI customer reply
    POST /tickets/{id}/solve        — grade and close ticket
"""

from pathlib import Path

import jinja2
import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.chat import generate_customer_reply
from app.database import (
    add_comment,
    create_ticket,
    get_all_tickets,
    get_comments,
    get_ticket,
    init_db,
    set_escalated,
    solve_ticket,
)
from app.grader import format_internal_note, grade_response

load_dotenv()

app = FastAPI(title="Litmus Lab")

app.mount(
    "/screenshots",
    StaticFiles(directory="scenarios/screenshots"),
    name="screenshots",
)

# Render templates directly with Jinja2 (bypasses Starlette's Jinja2Templates
# wrapper, which has a Python 3.14 incompatibility in its LRUCache).
_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader("app/templates"),
    cache_size=0,
)


def _render(template_name: str, **context) -> HTMLResponse:
    template = _jinja_env.get_template(template_name)
    return HTMLResponse(template.render(**context))


SCENARIOS_DIR = Path("scenarios")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


# ── Scenario helpers ──────────────────────────────────────────────────────────

def load_scenario(scenario_id: str) -> dict | None:
    for path in SCENARIOS_DIR.glob(f"{scenario_id}-*.yaml"):
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return None


def load_all_scenarios() -> list[dict]:
    scenarios = []
    for path in sorted(SCENARIOS_DIR.glob("*.yaml")):
        with open(path, encoding="utf-8") as f:
            scenarios.append(yaml.safe_load(f))
    return scenarios


# ── Cloudflare identity ───────────────────────────────────────────────────────

def _cf_email(request: Request) -> str | None:
    """Extract the authenticated user email injected by Cloudflare Access."""
    return request.headers.get("Cf-Access-Authenticated-User-Email")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def queue(request: Request) -> HTMLResponse:
    tickets = get_all_tickets()
    for ticket in tickets:
        scenario = load_scenario(ticket["scenario_id"])
        ticket["scenario_title"] = scenario["title"] if scenario else ticket["scenario_id"]
    return _render("queue.html", tickets=tickets)


@app.get("/new", response_class=HTMLResponse)
async def new_ticket_form(request: Request) -> HTMLResponse:
    scenarios = load_all_scenarios()
    return _render("new_ticket.html", scenarios=scenarios, cf_email=_cf_email(request))


@app.post("/tickets/new")
async def create_ticket_route(
    request: Request,
    scenario_id: str = Form(...),
    trainee: str = Form(...),
) -> RedirectResponse:
    scenario = load_scenario(scenario_id)
    if not scenario:
        return RedirectResponse("/new", status_code=303)

    # Fall back to the Cloudflare identity if the form field was left blank.
    trainee_name = trainee.strip() or _cf_email(request) or trainee.strip()

    ticket_id = create_ticket(scenario_id, trainee_name)
    initial_body = scenario["ticket"]["initial_message"].strip()
    add_comment(ticket_id, initial_body, "customer")

    return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)


@app.get("/tickets/{ticket_id}", response_class=HTMLResponse)
async def view_ticket(request: Request, ticket_id: int) -> HTMLResponse:
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
    """Save the trainee's reply and generate an AI customer response."""
    ticket = get_ticket(ticket_id)
    if not ticket or ticket["status"] == "solved":
        return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)

    scenario = load_scenario(ticket["scenario_id"])
    is_escalated = escalated is not None

    add_comment(ticket_id, body.strip(), "trainee")
    set_escalated(ticket_id, is_escalated)

    if scenario:
        conversation = get_comments(ticket_id)
        try:
            customer_reply = await generate_customer_reply(scenario, conversation)
            add_comment(ticket_id, customer_reply, "customer")
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("customer reply failed: %s: %s", type(exc).__name__, exc)

    return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)


@app.post("/tickets/{ticket_id}/solve")
async def solve(
    ticket_id: int,
    body: str = Form(""),
    escalated: str | None = Form(None),
) -> RedirectResponse:
    """Post optional final reply, grade the ticket, and mark it solved."""
    ticket = get_ticket(ticket_id)
    if not ticket or ticket["status"] == "solved":
        return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)

    scenario = load_scenario(ticket["scenario_id"])
    is_escalated = escalated is not None

    if body.strip():
        add_comment(ticket_id, body.strip(), "trainee")

    set_escalated(ticket_id, is_escalated)

    public_comments = [c for c in get_comments(ticket_id) if not c["is_internal"]]
    try:
        grade = grade_response(scenario, public_comments, is_escalated)
        solve_ticket(ticket_id, score=grade.score)
        note_body = format_internal_note(grade, scenario, ticket["trainee"])
    except Exception as exc:
        solve_ticket(ticket_id, score=None)
        note_body = (
            f"GRADING FAILED — ticket marked solved without a score.\n\n"
            f"Error: {type(exc).__name__}: {exc}\n\n"
            f"Check that LITMUS_API_BASE and LITMUS_API_KEY are set in .env."
        )

    add_comment(ticket_id, note_body, "system", is_internal=True)

    return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)
