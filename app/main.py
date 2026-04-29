"""
main.py — FastAPI application for Litmus Lab v2.

Routes:
    GET  /                              → redirect to /dashboard or /start
    GET  /start                         → trainee name entry
    POST /start                         → create/load trainee, set cookie, redirect to /dashboard
    GET  /dashboard                     → certificate checkpoint cards + practice mode list
    GET  /attempt/{scenario_id}/new     → create attempt (check unlock) → redirect to attempt
    GET  /attempt/{attempt_id}          → conversation view
    POST /attempt/{attempt_id}/reply    → scripted customer reply
    POST /attempt/{attempt_id}/submit   → grade in background, redirect to results
    GET  /attempt/{attempt_id}/results  → poll for grade; show when ready
    GET  /admin                         → read-only admin view (password protected)
    GET  /settings                      → AI provider settings
    POST /settings                      → save settings
    POST /settings/test                 → test AI connection
"""

import json
import logging
import os
from pathlib import Path

import httpx
import jinja2
import yaml
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI

from app.database import (
    add_message,
    create_attempt,
    create_grade,
    create_trainee,
    get_active_attempt,
    get_all_trainees,
    get_attempt,
    get_attempts_for_trainee,
    get_checkpoint_progress,
    get_grade,
    get_messages,
    get_setting,
    get_trainee,
    get_trainee_by_name,
    init_checkpoint_progress,
    init_db,
    mark_attempt_graded,
    mark_attempt_grade_failed,
    set_setting,
    set_urgency_injected,
    submit_attempt,
    update_checkpoint_after_grade,
)
from app.grader import GradeResult, format_grade_display, grade_response
from app.scenarios import (
    build_customer_reply,
    load_certificate_scenarios,
    load_practice_scenarios,
    load_scenario,
)

load_dotenv()
log = logging.getLogger(__name__)

app = FastAPI(title="Litmus Lab")

app.mount(
    "/screenshots",
    StaticFiles(directory="scenarios/screenshots"),
    name="screenshots",
)

_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader("app/templates"),
    cache_size=0,
)


def _render(template_name: str, **context) -> HTMLResponse:
    template = _jinja_env.get_template(template_name)
    return HTMLResponse(template.render(**context))


# ── AI provider config ────────────────────────────────────────────────────────

PROVIDER_PRESETS = {
    "openwebui": {
        "label": "Open WebUI",
        "description": "Internal or custom OpenAI-compatible server",
        "api_base": "",
        "api_base_placeholder": "https://ai.internal.yourcompany.com/api",
        "api_base_editable": True,
        "grade_model": "claude-haiku-4-5-20251001",
    },
    "claude": {
        "label": "Anthropic Claude",
        "description": "claude-opus-4-7, claude-sonnet-4-6, claude-haiku-4-5",
        "api_base": "https://api.anthropic.com/v1",
        "api_base_placeholder": "",
        "api_base_editable": False,
        "grade_model": "claude-haiku-4-5-20251001",
    },
    "gemini": {
        "label": "Google Gemini",
        "description": "gemini-2.0-flash, gemini-1.5-pro, …",
        "api_base": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_base_placeholder": "",
        "api_base_editable": False,
        "grade_model": "gemini-2.0-flash",
    },
}


def _load_ai_config() -> dict:
    provider = get_setting("provider") or "openwebui"
    return {
        "provider":    provider,
        "api_base":    get_setting("api_base")    or os.environ.get("LITMUS_API_BASE", ""),
        "api_key":     get_setting("api_key")     or os.environ.get("LITMUS_API_KEY", ""),
        "grade_model": get_setting("grade_model") or os.environ.get("LITMUS_GRADE_MODEL", "claude-haiku-4-5-20251001"),
        "ssl_verify":  provider in ("claude", "gemini"),
    }


# ── Session helpers ───────────────────────────────────────────────────────────

def _get_trainee_id(request: Request) -> int | None:
    try:
        return int(request.cookies.get("trainee_id", ""))
    except (ValueError, TypeError):
        return None


def _require_trainee(request: Request) -> int | None:
    """Return trainee_id from cookie, or None (caller should redirect to /start)."""
    return _get_trainee_id(request)


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup() -> None:
    init_db()


# ── Core routes ───────────────────────────────────────────────────────────────

@app.get("/")
async def root(request: Request):
    if _get_trainee_id(request):
        return RedirectResponse("/dashboard", status_code=303)
    return RedirectResponse("/start", status_code=303)


@app.get("/start", response_class=HTMLResponse)
async def start_form(request: Request) -> HTMLResponse:
    if _get_trainee_id(request):
        return RedirectResponse("/dashboard", status_code=303)
    return _render("start.html")


@app.post("/start")
async def start_submit(request: Request, name: str = Form(...)) -> Response:
    name = name.strip()
    if not name:
        return _render("start.html", error="Please enter your name.")

    trainee = get_trainee_by_name(name)
    if trainee:
        trainee_id = trainee["id"]
    else:
        trainee_id = create_trainee(name)
        init_checkpoint_progress(trainee_id)

    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie("trainee_id", str(trainee_id), httponly=True, path="/")
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    trainee_id = _require_trainee(request)
    if not trainee_id:
        return RedirectResponse("/start", status_code=303)

    trainee = get_trainee(trainee_id)
    cp_progress = get_checkpoint_progress(trainee_id)
    cert_scenarios = load_certificate_scenarios()
    practice_scenarios = load_practice_scenarios()

    # Attach progress to each certificate scenario
    for s in cert_scenarios:
        cp = s.get("checkpoint")
        s["_progress"] = cp_progress.get(cp, {"status": "locked", "best_score": None, "attempts_used": 0})

    # For practice scenarios, find the most recent attempt status
    all_attempts = get_attempts_for_trainee(trainee_id)
    attempt_by_scenario = {}
    for a in all_attempts:
        sid = a["scenario_id"]
        if sid not in attempt_by_scenario or a["id"] > attempt_by_scenario[sid]["id"]:
            attempt_by_scenario[sid] = a

    for s in practice_scenarios:
        s["_last_attempt"] = attempt_by_scenario.get(s["id"])

    return _render(
        "dashboard.html",
        trainee=trainee,
        cert_scenarios=cert_scenarios,
        practice_scenarios=practice_scenarios,
        cp_progress=cp_progress,
    )


# ── Attempt creation ──────────────────────────────────────────────────────────

@app.get("/attempt/{scenario_id}/new")
async def new_attempt(request: Request, scenario_id: str) -> Response:
    trainee_id = _require_trainee(request)
    if not trainee_id:
        return RedirectResponse("/start", status_code=303)

    scenario = load_scenario(scenario_id)
    if not scenario:
        return RedirectResponse("/dashboard", status_code=303)

    mode = scenario.get("mode", "practice")
    checkpoint = scenario.get("checkpoint")

    # For certificate mode: check unlock and re-attempt limit
    if mode == "certificate" and checkpoint:
        cp_progress = get_checkpoint_progress(trainee_id)
        progress = cp_progress.get(checkpoint, {})
        status = progress.get("status", "locked")
        if status in ("locked", "failed_no_reattempt"):
            return RedirectResponse("/dashboard", status_code=303)

        # If re-attempting, set attempt_number to 2
        attempt_number = 2 if status == "failed_reattempt_available" else 1
    else:
        attempt_number = 1

    # Resume existing in-progress attempt if one exists
    existing = get_active_attempt(trainee_id, scenario_id)
    if existing:
        return RedirectResponse(f"/attempt/{existing['id']}", status_code=303)

    attempt_id = create_attempt(trainee_id, scenario_id, checkpoint, mode, attempt_number)
    # Post the customer's opening message as the first message
    add_message(attempt_id, "customer", scenario["ticket"]["initial_message"].strip())

    return RedirectResponse(f"/attempt/{attempt_id}", status_code=303)


# ── Attempt view ──────────────────────────────────────────────────────────────

@app.get("/attempt/{attempt_id}", response_class=HTMLResponse)
async def view_attempt(request: Request, attempt_id: int) -> HTMLResponse:
    trainee_id = _require_trainee(request)
    if not trainee_id:
        return RedirectResponse("/start", status_code=303)

    attempt = get_attempt(attempt_id)
    if not attempt or attempt["trainee_id"] != trainee_id:
        return RedirectResponse("/dashboard", status_code=303)

    scenario = load_scenario(attempt["scenario_id"])
    messages = get_messages(attempt_id)
    grade = get_grade(attempt_id) if attempt["status"] in ("graded", "grade_failed") else None
    trainee = get_trainee(trainee_id)

    return _render(
        "attempt.html",
        attempt=attempt,
        scenario=scenario,
        messages=messages,
        grade=grade,
        trainee=trainee,
    )


# ── Reply ─────────────────────────────────────────────────────────────────────

@app.post("/attempt/{attempt_id}/reply")
async def reply(attempt_id: int, request: Request, body: str = Form(...)) -> Response:
    trainee_id = _require_trainee(request)
    if not trainee_id:
        return RedirectResponse("/start", status_code=303)

    attempt = get_attempt(attempt_id)
    if not attempt or attempt["trainee_id"] != trainee_id or attempt["status"] != "in_progress":
        return RedirectResponse(f"/attempt/{attempt_id}", status_code=303)

    scenario = load_scenario(attempt["scenario_id"])
    body_text = body.strip()
    if not body_text:
        return RedirectResponse(f"/attempt/{attempt_id}", status_code=303)

    # Save trainee message
    add_message(attempt_id, "trainee", body_text)

    # Build scripted customer reply (with optional urgency injection)
    messages = get_messages(attempt_id)
    customer_reply, did_inject = build_customer_reply(
        scenario,
        body_text,
        messages,
        bool(attempt["urgency_injected"]),
    )

    add_message(attempt_id, "customer", customer_reply)

    if did_inject:
        set_urgency_injected(attempt_id)

    return RedirectResponse(f"/attempt/{attempt_id}", status_code=303)


# ── Submit ────────────────────────────────────────────────────────────────────

@app.post("/attempt/{attempt_id}/submit")
async def submit(
    attempt_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    action: str = Form(...),       # "resolve" or "escalate"
    final_note: str = Form(""),
) -> Response:
    trainee_id = _require_trainee(request)
    if not trainee_id:
        return RedirectResponse("/start", status_code=303)

    attempt = get_attempt(attempt_id)
    if not attempt or attempt["trainee_id"] != trainee_id or attempt["status"] != "in_progress":
        return RedirectResponse(f"/attempt/{attempt_id}", status_code=303)

    if final_note.strip():
        add_message(attempt_id, "trainee", final_note.strip())

    submit_attempt(attempt_id, action)

    config = _load_ai_config()
    background_tasks.add_task(_run_grading, attempt_id, config)

    return RedirectResponse(f"/attempt/{attempt_id}/results", status_code=303)


def _run_grading(attempt_id: int, config: dict) -> None:
    """Background task: grade attempt, write result to DB, update checkpoint progress."""
    try:
        attempt = get_attempt(attempt_id)
        scenario = load_scenario(attempt["scenario_id"])
        messages = get_messages(attempt_id)
        trainee_action = attempt["trainee_action"] or "resolve"

        grade = grade_response(
            scenario,
            messages,
            trainee_action,
            api_base=config["api_base"],
            api_key=config["api_key"],
            model=config["grade_model"],
            ssl_verify=config["ssl_verify"],
        )

        create_grade(
            attempt_id=attempt_id,
            total_score=grade.total_score,
            passed=grade.passed,
            expected_action=grade.expected_action,
            trainee_action=grade.trainee_action,
            correct_direction=grade.correct_direction,
            dimension_scores=grade.dimensions,
            overall_feedback=grade.overall_feedback,
            raw_response=grade.raw_response,
        )

        mark_attempt_graded(attempt_id)

        if attempt.get("checkpoint") and attempt.get("mode") == "certificate":
            update_checkpoint_after_grade(
                attempt["trainee_id"],
                attempt["checkpoint"],
                grade.passed,
                grade.total_score,
            )

    except Exception as exc:
        log.error("Grading failed for attempt %d: %s: %s", attempt_id, type(exc).__name__, exc)
        # Store a failure grade so the results page doesn't spin forever
        try:
            create_grade(
                attempt_id=attempt_id,
                total_score=0,
                passed=False,
                expected_action=scenario.get("expected_action", "resolve"),
                trainee_action=attempt.get("trainee_action", "resolve"),
                correct_direction=False,
                dimension_scores=[],
                overall_feedback=(
                    f"GRADING FAILED — {type(exc).__name__}: {exc}\n\n"
                    "Check AI settings at /settings."
                ),
                raw_response=None,
            )
        except Exception:
            pass
        mark_attempt_grade_failed(attempt_id)


# ── Results ───────────────────────────────────────────────────────────────────

@app.get("/attempt/{attempt_id}/results", response_class=HTMLResponse)
async def results(request: Request, attempt_id: int) -> HTMLResponse:
    trainee_id = _require_trainee(request)
    if not trainee_id:
        return RedirectResponse("/start", status_code=303)

    attempt = get_attempt(attempt_id)
    if not attempt or attempt["trainee_id"] != trainee_id:
        return RedirectResponse("/dashboard", status_code=303)

    scenario = load_scenario(attempt["scenario_id"])
    messages = get_messages(attempt_id)
    grade = get_grade(attempt_id)
    trainee = get_trainee(trainee_id)

    return _render(
        "results.html",
        attempt=attempt,
        scenario=scenario,
        messages=messages,
        grade=grade,
        trainee=trainee,
    )


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
async def admin(request: Request) -> HTMLResponse:
    admin_password = os.environ.get("LITMUS_ADMIN_PASSWORD", "")
    provided = request.query_params.get("pw", "")
    if not admin_password or provided != admin_password:
        return HTMLResponse(
            "<h2>Access denied</h2><p>Add ?pw=... to the URL.</p>",
            status_code=403,
        )

    trainees = get_all_trainees()
    for t in trainees:
        t["cp_progress"] = get_checkpoint_progress(t["id"])
        t["attempts"] = get_attempts_for_trainee(t["id"])

    return _render("admin.html", trainees=trainees)


@app.get("/admin/attempt/{attempt_id}", response_class=HTMLResponse)
async def admin_attempt(request: Request, attempt_id: int) -> HTMLResponse:
    admin_password = os.environ.get("LITMUS_ADMIN_PASSWORD", "")
    provided = request.query_params.get("pw", "")
    if not admin_password or provided != admin_password:
        return HTMLResponse(
            "<h2>Access denied</h2><p>Add ?pw=... to the URL.</p>",
            status_code=403,
        )

    attempt = get_attempt(attempt_id)
    if not attempt:
        return HTMLResponse("<h2>Not found</h2>", status_code=404)
    trainee = get_trainee(attempt["trainee_id"])
    messages = get_messages(attempt_id)
    grade = get_grade(attempt_id)
    return _render("admin_attempt.html", attempt=attempt, trainee=trainee, messages=messages, grade=grade)


# ── Settings routes ───────────────────────────────────────────────────────────

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: str | None = None) -> HTMLResponse:
    config = _load_ai_config()
    has_key = bool(config["api_key"])
    presets_json = json.dumps(PROVIDER_PRESETS)
    return _render(
        "settings.html",
        config=config,
        has_key=has_key,
        saved=saved,
        presets_json=presets_json,
    )


@app.post("/settings")
async def save_settings(
    provider:    str = Form(...),
    api_base:    str = Form(...),
    api_key:     str = Form(""),
    grade_model: str = Form(...),
) -> RedirectResponse:
    set_setting("provider",    provider.strip())
    set_setting("api_base",    api_base.strip())
    set_setting("grade_model", grade_model.strip())
    if api_key.strip():
        set_setting("api_key", api_key.strip())
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/test")
async def test_connection(request: Request) -> JSONResponse:
    config = _load_ai_config()
    if not config["api_base"] or not config["api_key"]:
        return JSONResponse({"ok": False, "message": "API Endpoint URL and API Key are required."})
    try:
        async with httpx.AsyncClient(verify=config["ssl_verify"]) as http_client:
            client = AsyncOpenAI(
                base_url=config["api_base"],
                api_key=config["api_key"],
                http_client=http_client,
            )
            response = await client.chat.completions.create(
                model=config["grade_model"],
                messages=[{"role": "user", "content": "Reply with the single word: ok"}],
                max_tokens=10,
            )
        reply = response.choices[0].message.content.strip()
        return JSONResponse({"ok": True, "message": f"Connected. Model replied: {reply!r}"})
    except Exception as exc:
        return JSONResponse({"ok": False, "message": f"{type(exc).__name__}: {exc}"})
