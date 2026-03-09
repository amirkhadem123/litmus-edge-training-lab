"""
main.py — FastAPI application entry point for Litmus Lab.

This file does three things:
  1. Defines the app's lifespan (startup / shutdown logic).
  2. Registers all HTTP routes (URL → function mappings).
  3. Renders HTML responses using Jinja2 templates.

HOW FASTAPI WORKS (plain-language summary for beginners):
  FastAPI is a Python web framework. When a browser visits a URL, FastAPI
  calls the matching Python function (called a "route handler") and returns
  its result as an HTTP response.

  Routes are defined with decorators like @app.get("/") for GET requests
  (viewing a page) and @app.post("/path") for POST requests (submitting
  a form or clicking a button).

  Jinja2 templates are HTML files with placeholders ({{ variable }}) that
  get filled in with Python data before being sent to the browser.

LIFESPAN:
  The @asynccontextmanager function 'lifespan' runs code at startup (before
  'yield') and at shutdown (after 'yield'). We use it to:
    - Initialise the ScenarioEngine (create the Litmus API connection, load scenarios)
    - Run a force-reset on shutdown so no broken state is left on Litmus Edge
      if the app is stopped cleanly.

GLOBAL ENGINE INSTANCE:
  'engine' is a module-level ScenarioEngine object. It is created before the
  app starts and shared across all requests. This is safe because only one
  scenario can run at a time.
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from engine import ScenarioEngine


# ── Logging configuration ────────────────────────────────────────────────────
# basicConfig sets up a simple console logger. In production you might send
# these to a file or structured logging service.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ── Load environment variables from .env file ────────────────────────────────
# python-dotenv reads the .env file in the current directory (where the app
# is run from) and sets the values as environment variables. If a variable is
# already set in the environment (e.g. via Docker -e flag), it is not overwritten.
load_dotenv()


# ── Global engine instance ───────────────────────────────────────────────────
# Created here so it's accessible to all route handlers below.
engine = ScenarioEngine()


# ── App lifespan (startup and shutdown) ─────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Code inside the 'async with' block runs at startup.
    Code after 'yield' runs when the app shuts down.

    This pattern (called a context manager) ensures cleanup always happens,
    even if the app crashes or is stopped with Ctrl+C.
    """
    # STARTUP
    logger.info("Litmus Lab starting up…")
    try:
        engine.initialise()
        logger.info("ScenarioEngine ready. %d scenarios loaded.", len(engine.scenario_classes))
    except RuntimeError as exc:
        logger.critical("Engine initialisation failed: %s", exc)
        # The app will still start but API calls will fail.
        # This is intentional — we want the UI to be reachable so the user
        # can see the error message rather than a blank connection refused page.

    yield  # ← The app runs here, handling requests

    # SHUTDOWN
    logger.info("Litmus Lab shutting down…")
    result = engine.force_reset_all()
    logger.info("Shutdown cleanup: %s", result["message"])


# ── FastAPI app ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="Litmus Lab",
    description="Interactive troubleshooting trainer for Litmus Edge",
    version="0.1.0",
    lifespan=lifespan,
)

# Jinja2Templates points to the 'templates' subdirectory relative to this file.
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """
    Home page: lists all available scenarios with their status.

    The engine.list_scenarios() call returns a list of dicts that the
    template uses to render scenario cards.
    """
    scenarios = engine.list_scenarios()
    active = engine.active_scenario
    active_id = active.id if active else None

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "scenarios": scenarios,
            "active_id": active_id,
            "edge_url": os.environ.get("EDGE_URL", ""),
        },
    )


@app.get("/scenario/{scenario_id}", response_class=HTMLResponse)
async def scenario_detail(request: Request, scenario_id: str):
    """
    Scenario detail page: shows the full symptom, hints, and action buttons.
    """
    try:
        detail = engine.get_scenario_detail(scenario_id)
    except KeyError:
        return HTMLResponse(content=f"Scenario '{scenario_id}' not found.", status_code=404)

    # Check if this scenario has a service impact warning (only SYS-02 does)
    cls = engine.scenario_classes.get(scenario_id)
    service_warning = getattr(cls, "service_impact_warning", None) if cls else None

    return templates.TemplateResponse(
        "scenario.html",
        {
            "request": request,
            "scenario": detail,
            "service_warning": service_warning,
            "edge_url": os.environ.get("EDGE_URL", ""),
        },
    )


@app.post("/scenario/{scenario_id}/start")
async def start_scenario(scenario_id: str):
    """
    Start a scenario: calls setup() to inject the broken state.
    Returns JSON with success/failure and a message.
    """
    result = engine.start(scenario_id)
    status_code = 200 if result["success"] else 409  # 409 = Conflict (already running)
    return JSONResponse(content=result, status_code=status_code)


@app.post("/scenario/{scenario_id}/check")
async def check_scenario(scenario_id: str):
    """
    Validate the current state: calls validate() to see if the learner fixed it.
    Returns JSON with success/failure and a descriptive message.
    """
    result = engine.check(scenario_id)
    return JSONResponse(content=result)


@app.post("/scenario/{scenario_id}/hint")
async def get_hint(scenario_id: str):
    """
    Reveal the next hint for the active scenario.
    Returns JSON with the hint text and position info.
    """
    result = engine.next_hint(scenario_id)
    return JSONResponse(content=result)


@app.post("/scenario/{scenario_id}/reset")
async def reset_scenario(scenario_id: str):
    """
    Reset the active scenario: calls teardown() to clean up resources.
    Returns JSON with success/failure and a message.
    """
    result = engine.reset(scenario_id)
    return JSONResponse(content=result)


@app.post("/admin/force-reset")
async def force_reset():
    """
    Emergency reset: tears down whatever scenario is active, regardless of id.

    This endpoint exists for two reasons:
      1. If the app was restarted while a scenario was active (state lost),
         this provides a way to clean up the remaining broken state.
      2. For SYS-02 specifically, this ensures the analytics service is
         restarted even if the normal reset path is unavailable.

    Shown as a prominent 'Force Reset All' button on the home page.
    """
    result = engine.force_reset_all()
    return JSONResponse(content=result)


@app.get("/health")
async def health():
    """
    Simple liveness endpoint. Returns 200 OK if the app is running.
    Used by Docker health checks and monitoring tools.
    """
    connected = engine.conn is not None
    active = engine.active_scenario.id if engine.active_scenario else None
    return JSONResponse(content={
        "status": "ok",
        "litmus_connected": connected,
        "active_scenario": active,
    })
