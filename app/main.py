"""
main.py — FastAPI application for Litmus Lab v2.

Routes:
    GET  /                              → redirect to /dashboard or /login
    GET  /login                         → login form
    POST /login                         → verify credentials, set cookie, redirect to /dashboard
    GET  /register                      → registration form
    POST /register                      → create account, set cookie, redirect to /dashboard
    POST /logout                        → clear cookie, redirect to /login
    GET  /dashboard                     → certificate checkpoint cards + practice mode list
    GET  /attempt/{scenario_id}/new     → create attempt (check unlock) → redirect to attempt
    GET  /attempt/{attempt_id}          → conversation view
    POST /attempt/{attempt_id}/reply    → scripted customer reply
    POST /attempt/{attempt_id}/submit   → grade in background, redirect to results
    GET  /attempt/{attempt_id}/results  → poll for grade; show when ready
    GET  /admin                         → read-only admin view (password protected)
    POST /admin/reset-password          → admin: reset a trainee's password
    GET  /settings                      → per-user AI provider settings
    POST /settings                      → save per-user settings
    POST /settings/test                 → test AI connection using current user's settings
"""

import json
import logging
import os
from pathlib import Path

import httpx
import jinja2
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI

from app.database import (
    add_message,
    admin_reset_password,
    check_password,
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
    get_trainee,
    get_trainee_by_email,
    get_trainee_settings,
    hash_password,
    init_checkpoint_progress,
    init_db,
    init_trainee_settings,
    mark_attempt_graded,
    mark_attempt_grade_failed,
    reset_attempt_messages,
    set_trainee_setting,
    set_urgency_injected,
    submit_attempt,
    update_checkpoint_after_grade,
)
from app.grader import GradeResult, format_grade_display, grade_response
from app.scenarios import (
    build_customer_reply,
    load_certificate_scenarios,
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


def _load_ai_config(trainee_id: int) -> dict:
    """Load the trainee's personal AI settings, falling back to server env vars."""
    s = get_trainee_settings(trainee_id)
    provider = s.get("provider") or "claude"
    # LITMUS_HTTP_PROXY is a server-level setting (not per-user) for environments
    # where the AI endpoint is only reachable through a local proxy such as
    # Cloudflare WARP in gateway mode. Unset on production servers that have
    # direct network access to the AI endpoint.
    http_proxy = os.environ.get("LITMUS_HTTP_PROXY", "").strip() or None
    return {
        "provider":    provider,
        "api_base":    s.get("api_base") or os.environ.get("LITMUS_API_BASE", ""),
        "api_key":     s.get("api_key") or os.environ.get("LITMUS_API_KEY", ""),
        "grade_model": s.get("grade_model") or os.environ.get("LITMUS_GRADE_MODEL", "claude-haiku-4-5-20251001"),
        "ssl_verify":  provider in ("claude", "gemini"),
        "http_proxy":  http_proxy,
    }


# ── Session helpers ───────────────────────────────────────────────────────────

def _get_trainee_id(request: Request) -> int | None:
    try:
        return int(request.cookies.get("trainee_id", ""))
    except (ValueError, TypeError):
        return None


def _require_trainee(request: Request) -> int | None:
    return _get_trainee_id(request)


def _has_ai_key(trainee_id: int) -> bool:
    config = _load_ai_config(trainee_id)
    return bool(config["api_key"] and config["api_base"])


def _warp_error_msg(exc: Exception) -> str | None:
    """
    Return a human-readable message if the exception looks like a Cloudflare
    WARP connectivity failure, otherwise return None.

    Two known failure modes:
      1. Fully disconnected  — error contains "authenticate via the warp client"
      2. Session redirect    — WARP is running but the session expired; Cloudflare
                               returns a 302 HTML page instead of the API response,
                               which the OpenAI SDK surfaces as an APIStatusError
                               whose body contains "<html>" and "302"/"cloudflare".
    """
    text = str(exc).lower()
    is_warp = (
        "authenticate via the warp client" in text
        or ("<html>" in text and ("302" in text or "cloudflare" in text))
    )
    if not is_warp:
        return None
    return (
        "Cloudflare WARP connectivity issue — the AI endpoint returned a redirect "
        "page instead of an API response. Turn WARP off and back on, then try again. "
        "If WARP is running in gateway mode, set LITMUS_HTTP_PROXY in your .env."
    )


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup() -> None:
    init_db()


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.get("/")
async def root(request: Request):
    if _get_trainee_id(request):
        return RedirectResponse("/dashboard", status_code=303)
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    if _get_trainee_id(request):
        return RedirectResponse("/dashboard", status_code=303)
    return _render("login.html")


@app.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
) -> Response:
    email = email.strip().lower()
    trainee = get_trainee_by_email(email)
    if not trainee or not check_password(password, trainee["password_hash"]):
        return _render("login.html", error="Incorrect email or password.")

    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie("trainee_id", str(trainee["id"]), httponly=True, path="/")
    return response


@app.get("/register", response_class=HTMLResponse)
async def register_form(request: Request) -> HTMLResponse:
    if _get_trainee_id(request):
        return RedirectResponse("/dashboard", status_code=303)
    return _render("register.html")


@app.post("/register")
async def register_submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm: str = Form(...),
) -> Response:
    name = name.strip()
    email = email.strip().lower()

    if not name or not email or not password:
        return _render("register.html", error="All fields are required.", name=name, email=email)

    if password != confirm:
        return _render("register.html", error="Passwords do not match.", name=name, email=email)

    if len(password) < 8:
        return _render("register.html", error="Password must be at least 8 characters.", name=name, email=email)

    if get_trainee_by_email(email):
        return _render("register.html", error="An account with that email already exists.", name=name, email=email)

    password_hash = hash_password(password)
    trainee_id = create_trainee(name, email, password_hash)
    init_checkpoint_progress(trainee_id)
    init_trainee_settings(trainee_id)

    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie("trainee_id", str(trainee_id), httponly=True, path="/")
    return response


@app.post("/logout")
async def logout() -> Response:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("trainee_id", path="/")
    return response


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, alert: str | None = None) -> HTMLResponse:
    trainee_id = _require_trainee(request)
    if not trainee_id:
        return RedirectResponse("/login", status_code=303)

    trainee = get_trainee(trainee_id)
    cp_progress = get_checkpoint_progress(trainee_id)
    cert_scenarios = load_certificate_scenarios()
    ai_configured = _has_ai_key(trainee_id)

    for s in cert_scenarios:
        cp = s.get("checkpoint")
        s["_progress"] = cp_progress.get(cp, {"status": "available", "best_score": None, "attempts_used": 0})

    return _render(
        "dashboard.html",
        trainee=trainee,
        cert_scenarios=cert_scenarios,
        cp_progress=cp_progress,
        ai_configured=ai_configured,
        alert=alert,
    )


# ── Attempt creation ──────────────────────────────────────────────────────────

@app.get("/attempt/{scenario_id}/new")
async def new_attempt(request: Request, scenario_id: str) -> Response:
    trainee_id = _require_trainee(request)
    if not trainee_id:
        return RedirectResponse("/login", status_code=303)

    scenario = load_scenario(scenario_id)
    if not scenario:
        return RedirectResponse("/dashboard", status_code=303)

    mode = scenario.get("mode", "practice")
    checkpoint = scenario.get("checkpoint")

    if mode == "certificate" and checkpoint:
        # Block certificate attempts if AI is not configured
        if not _has_ai_key(trainee_id):
            return RedirectResponse("/dashboard?alert=no_ai_key", status_code=303)

        cp_progress = get_checkpoint_progress(trainee_id)
        progress = cp_progress.get(checkpoint, {})
        status = progress.get("status", "available")
        attempt_number = 2 if status == "failed_reattempt_available" else 1
    else:
        attempt_number = 1

    existing = get_active_attempt(trainee_id, scenario_id)
    if existing:
        return RedirectResponse(f"/attempt/{existing['id']}", status_code=303)

    attempt_id = create_attempt(trainee_id, scenario_id, checkpoint, mode, attempt_number)
    add_message(attempt_id, "customer", scenario["ticket"]["initial_message"].strip())

    return RedirectResponse(f"/attempt/{attempt_id}", status_code=303)


# ── Attempt view ──────────────────────────────────────────────────────────────

@app.get("/attempt/{attempt_id}", response_class=HTMLResponse)
async def view_attempt(request: Request, attempt_id: int) -> HTMLResponse:
    trainee_id = _require_trainee(request)
    if not trainee_id:
        return RedirectResponse("/login", status_code=303)

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


# ── Reset attempt ─────────────────────────────────────────────────────────────

@app.post("/attempt/{attempt_id}/reset")
async def reset_attempt(request: Request, attempt_id: int) -> Response:
    trainee_id = _require_trainee(request)
    if not trainee_id:
        return RedirectResponse("/login", status_code=303)

    attempt = get_attempt(attempt_id)
    if not attempt or attempt["trainee_id"] != trainee_id or attempt["status"] != "in_progress":
        return RedirectResponse(f"/attempt/{attempt_id}", status_code=303)

    scenario = load_scenario(attempt["scenario_id"])
    reset_attempt_messages(attempt_id, scenario["ticket"]["initial_message"])
    return RedirectResponse(f"/attempt/{attempt_id}", status_code=303)


# ── Reply ─────────────────────────────────────────────────────────────────────

@app.post("/attempt/{attempt_id}/reply")
async def reply(attempt_id: int, request: Request, body: str = Form(...)) -> Response:
    trainee_id = _require_trainee(request)
    if not trainee_id:
        return JSONResponse({"error": "Not logged in."}, status_code=401)

    attempt = get_attempt(attempt_id)
    if not attempt or attempt["trainee_id"] != trainee_id or attempt["status"] != "in_progress":
        return JSONResponse({"error": "Attempt not found or not in progress."}, status_code=400)

    scenario = load_scenario(attempt["scenario_id"])
    body_text = body.strip()
    if not body_text:
        return JSONResponse({"error": "Reply cannot be empty."}, status_code=400)

    add_message(attempt_id, "trainee", body_text)

    messages = get_messages(attempt_id)
    ai_config = _load_ai_config(trainee_id)
    try:
        customer_reply, did_inject = await build_customer_reply(
            scenario,
            body_text,
            messages,
            bool(attempt["urgency_injected"]),
            api_config=ai_config,
        )
    except Exception as exc:
        log.error("Customer reply failed for attempt %d: %s: %s", attempt_id, type(exc).__name__, exc)
        warp_msg = _warp_error_msg(exc)
        customer_reply = (
            f"[System: {warp_msg}]"
            if warp_msg else
            f"[System: Customer reply failed ({type(exc).__name__}: {exc}). "
            "Check your AI settings at /settings.]"
        )
        did_inject = False

    add_message(attempt_id, "customer", customer_reply)

    if did_inject:
        set_urgency_injected(attempt_id)

    return JSONResponse({"trainee_message": body_text, "customer_reply": customer_reply})


# ── Submit ────────────────────────────────────────────────────────────────────

@app.post("/attempt/{attempt_id}/submit")
async def submit_attempt_route(
    attempt_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    action: str = Form(...),
    final_note: str = Form(""),
) -> Response:
    trainee_id = _require_trainee(request)
    if not trainee_id:
        return RedirectResponse("/login", status_code=303)

    attempt = get_attempt(attempt_id)
    if not attempt or attempt["trainee_id"] != trainee_id or attempt["status"] != "in_progress":
        return RedirectResponse(f"/attempt/{attempt_id}", status_code=303)

    if final_note.strip():
        add_message(attempt_id, "trainee", final_note.strip())

    submit_attempt(attempt_id, action)

    config = _load_ai_config(trainee_id)
    background_tasks.add_task(_run_grading, attempt_id, config)

    return RedirectResponse(f"/attempt/{attempt_id}/results", status_code=303)


def _run_grading(attempt_id: int, config: dict) -> None:
    """Background task: grade attempt, write result to DB, update checkpoint progress."""
    attempt = None
    scenario = None
    try:
        attempt = get_attempt(attempt_id)
        scenario = load_scenario(attempt["scenario_id"])
        messages = get_messages(attempt_id)
        trainee_action = attempt["trainee_action"] or "resolve"

        # Pre-flight: refuse to call API if no key configured
        if not config.get("api_key") or not config.get("api_base"):
            raise ValueError(
                "AI API key or endpoint not configured. "
                "Visit /settings to add your API credentials."
            )

        grade = grade_response(
            scenario,
            messages,
            trainee_action,
            api_base=config["api_base"],
            api_key=config["api_key"],
            model=config["grade_model"],
            ssl_verify=config["ssl_verify"],
            http_proxy=config.get("http_proxy"),
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
            if grade.passed:
                trainee = get_trainee(attempt["trainee_id"])
                if trainee:
                    from app.workramp import report_pass
                    report_pass(trainee["email"], trainee["name"], attempt["checkpoint"])

    except Exception as exc:
        log.error("Grading failed for attempt %d: %s: %s", attempt_id, type(exc).__name__, exc)
        warp_msg = _warp_error_msg(exc)
        failure_detail = warp_msg or str(exc)
        try:
            create_grade(
                attempt_id=attempt_id,
                total_score=0,
                passed=False,
                expected_action=(scenario or {}).get("expected_action", "resolve"),
                trainee_action=(attempt or {}).get("trainee_action", "resolve"),
                correct_direction=False,
                dimension_scores=[],
                overall_feedback=failure_detail,
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
        return RedirectResponse("/login", status_code=303)

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
        workramp_return_url=os.environ.get("WORKRAMP_RETURN_URL", ""),
    )


# ── Admin ─────────────────────────────────────────────────────────────────────

def _check_admin(request: Request) -> bool:
    admin_password = os.environ.get("LITMUS_ADMIN_PASSWORD", "")
    provided = request.query_params.get("pw", "")
    return bool(admin_password and provided == admin_password)


@app.get("/admin", response_class=HTMLResponse)
async def admin(request: Request, reset_done: str | None = None) -> HTMLResponse:
    if not _check_admin(request):
        return HTMLResponse("<h2>Access denied</h2><p>Add ?pw=... to the URL.</p>", status_code=403)

    trainees = get_all_trainees()
    for t in trainees:
        t["cp_progress"] = get_checkpoint_progress(t["id"])
        t["attempts"] = get_attempts_for_trainee(t["id"])

    pw = request.query_params.get("pw", "")
    return _render("admin.html", trainees=trainees, admin_pw=pw, reset_done=reset_done)


@app.post("/admin/reset-password")
async def admin_reset(
    request: Request,
    trainee_id: int = Form(...),
    new_password: str = Form(...),
) -> Response:
    if not _check_admin(request):
        return HTMLResponse("<h2>Access denied</h2>", status_code=403)
    pw = request.query_params.get("pw", "")
    if len(new_password) < 8:
        return RedirectResponse(f"/admin?pw={pw}&reset_done=error_short", status_code=303)
    admin_reset_password(trainee_id, hash_password(new_password))
    return RedirectResponse(f"/admin?pw={pw}&reset_done={trainee_id}", status_code=303)


@app.get("/admin/attempt/{attempt_id}", response_class=HTMLResponse)
async def admin_attempt(request: Request, attempt_id: int) -> HTMLResponse:
    if not _check_admin(request):
        return HTMLResponse("<h2>Access denied</h2><p>Add ?pw=... to the URL.</p>", status_code=403)

    attempt = get_attempt(attempt_id)
    if not attempt:
        return HTMLResponse("<h2>Not found</h2>", status_code=404)
    trainee = get_trainee(attempt["trainee_id"])
    messages = get_messages(attempt_id)
    grade = get_grade(attempt_id)
    pw = request.query_params.get("pw", "")
    return _render("admin_attempt.html", attempt=attempt, trainee=trainee,
                   messages=messages, grade=grade, admin_pw=pw)


# ── Settings routes ───────────────────────────────────────────────────────────

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: str | None = None) -> HTMLResponse:
    trainee_id = _require_trainee(request)
    if not trainee_id:
        return RedirectResponse("/login", status_code=303)

    config = _load_ai_config(trainee_id)
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
    request: Request,
    provider:    str = Form(...),
    api_base:    str = Form(...),
    api_key:     str = Form(""),
    grade_model: str = Form(...),
) -> Response:
    trainee_id = _require_trainee(request)
    if not trainee_id:
        return RedirectResponse("/login", status_code=303)

    set_trainee_setting(trainee_id, "provider",    provider.strip())
    set_trainee_setting(trainee_id, "api_base",    api_base.strip())
    set_trainee_setting(trainee_id, "grade_model", grade_model.strip())
    if api_key.strip():
        set_trainee_setting(trainee_id, "api_key", api_key.strip())

    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/test")
async def test_connection(request: Request) -> JSONResponse:
    trainee_id = _require_trainee(request)
    if not trainee_id:
        return JSONResponse({"ok": False, "message": "Not logged in."})

    config = _load_ai_config(trainee_id)
    if not config["api_base"] or not config["api_key"]:
        return JSONResponse({"ok": False, "message": "API Endpoint URL and API Key are required."})
    try:
        proxy_kwargs = {"proxy": config["http_proxy"]} if config.get("http_proxy") else {}
        async with httpx.AsyncClient(verify=config["ssl_verify"], **proxy_kwargs) as http_client:
            client = AsyncOpenAI(
                base_url=config["api_base"],
                api_key=config["api_key"],
                http_client=http_client,
            )
            response = await client.chat.completions.create(
                model=config["grade_model"],
                messages=[{"role": "user", "content": "Reply with the single word: ok"}],
                max_tokens=50,
            )
        raw = response.choices[0].message.content
        reply_text = (raw or "").strip()
        if not reply_text:
            return JSONResponse({"ok": False, "message": "Connected but model returned empty content. Try a different model or check your Open WebUI model configuration."})
        return JSONResponse({"ok": True, "message": f"Connected. Model replied: {reply_text!r}"})
    except Exception as exc:
        warp_msg = _warp_error_msg(exc)
        msg = warp_msg or f"{type(exc).__name__}: {exc}"
        return JSONResponse({"ok": False, "message": msg})
