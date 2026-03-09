"""
engine.py — The ScenarioEngine: manages scenario lifecycle and state.

This is the "brain" of the application. It is responsible for:

  1. CONNECTING        — creating the Litmus Edge API connection at startup.
  2. DRIVER CACHE      — downloading the DeviceHub driver record from the
                          connected Litmus Edge instance (required before any
                          device can be created via the SDK).
  3. LOADING scenarios — discovering all scenario classes at startup.
  4. RUNNING setup()   — injecting the Litmus API connection and starting
                          the timeout countdown.
  5. RUNNING validate() — forwarding the check to the active scenario.
  6. RUNNING teardown() — cleaning up resources and resetting state.
  7. TIMEOUT handling  — automatically calling teardown() if the learner
                          hasn't solved or reset the scenario within the
                          configured time limit.

IMPORTANT — ONE SCENARIO AT A TIME:
  Because each user gets their own Litmus Edge instance, and because
  scenarios manipulate live platform state (stopping services, creating
  devices), only one scenario can be active at a time. Trying to start
  a second scenario while one is running will return an error.

STATE STORAGE:
  State is kept in memory (a plain Python dict). This means if the app
  is restarted while a scenario is active, the in-progress state is lost.
  In that case, the broken state on Litmus Edge will persist until the
  learner manually resets via the "Force Reset All" admin button, which
  is shown prominently in the UI for exactly this reason.
"""

import asyncio
import importlib
import inspect
import logging
import os
import pkgutil
from datetime import datetime
from typing import Optional

from litmussdk.devicehub.record._cli import create_dh_cache
from litmussdk.devicehub.record._functions import get_version
from litmussdk.utils.conn import LEConnection, new_le_connection

import scenarios as scenarios_pkg
from scenarios.base import BaseScenario, ScenarioState


logger = logging.getLogger(__name__)


def _load_all_scenario_classes() -> dict[str, type[BaseScenario]]:
    """
    Automatically discover and load every BaseScenario subclass defined in
    the app/scenarios/ package.

    This uses Python's pkgutil to iterate over all .py files in the scenarios
    folder and import them. Any class that:
      - Inherits from BaseScenario, AND
      - Is not BaseScenario itself, AND
      - Has a non-empty 'id' class attribute
    is registered in the returned dictionary, keyed by its id.

    This means adding a new scenario requires only creating a new file in
    app/scenarios/ — nothing else needs to change.

    Returns:
        A dict mapping scenario id strings to scenario classes.
        Example: {"dh-01": StoppedDeviceScenario, "dh-02": NoTagsScenario, ...}
    """
    found: dict[str, type[BaseScenario]] = {}
    package_path = os.path.dirname(scenarios_pkg.__file__)

    for _, module_name, _ in pkgutil.iter_modules([package_path]):
        if module_name == "base":
            continue  # skip the abstract base module itself

        full_module_name = f"scenarios.{module_name}"
        try:
            module = importlib.import_module(full_module_name)
        except Exception as exc:
            logger.error("Failed to import scenario module '%s': %s", full_module_name, exc)
            continue

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BaseScenario)
                and obj is not BaseScenario
                and getattr(obj, "id", None)
            ):
                found[obj.id] = obj
                logger.debug("Registered scenario: %s (id=%s)", obj.__name__, obj.id)

    return found


class ScenarioEngine:
    """
    Central controller for scenario lifecycle management.

    One instance of ScenarioEngine is created when the FastAPI application
    starts (in the lifespan handler in main.py) and lives for the entire
    duration of the app's lifetime.

    Attributes:
        conn:           The LEConnection used for all Litmus API calls.
                        Created once from environment variables at startup.
        scenario_classes: Dict of all available scenario classes, keyed by id.
        active_scenario: The currently running scenario instance, or None.
        active_state:   The ScenarioState for the currently running scenario.
        _timeout_task:  The asyncio background task that fires teardown() when
                        the timeout elapses.
    """

    def __init__(self):
        self.conn: Optional[LEConnection] = None
        self.scenario_classes: dict[str, type[BaseScenario]] = {}
        self.active_scenario: Optional[BaseScenario] = None
        self.active_state: Optional[ScenarioState] = None
        self._timeout_task: Optional[asyncio.Task] = None

    def initialise(self) -> None:
        """
        Set up the engine: create the Litmus API connection and load scenarios.

        Called once during app startup. Reads connection parameters from
        environment variables (or .env file):
          EDGE_URL               — base URL of the Litmus Edge instance
          EDGE_API_CLIENT_ID     — OAuth2 client ID
          EDGE_API_CLIENT_SECRET — OAuth2 client secret
          VALIDATE_CERTIFICATE   — set to 'false' for self-signed certs (default: true)

        Raises:
            RuntimeError: if required environment variables are missing.
        """
        edge_url = os.environ.get("EDGE_URL", "")
        client_id = os.environ.get("EDGE_API_CLIENT_ID", "")
        client_secret = os.environ.get("EDGE_API_CLIENT_SECRET", "")
        validate_cert_str = os.environ.get("VALIDATE_CERTIFICATE", "true").lower()
        validate_cert = validate_cert_str not in ("false", "0", "no")

        if not all([edge_url, client_id, client_secret]):
            raise RuntimeError(
                "Missing required environment variables. "
                "Please set EDGE_URL, EDGE_API_CLIENT_ID, and EDGE_API_CLIENT_SECRET "
                "in your .env file or container environment."
            )

        self.conn = new_le_connection(
            edge_url=edge_url,
            client_id=client_id,
            client_secret=client_secret,
            validate_certificate=validate_cert,
        )
        logger.info("Litmus Edge connection established to: %s", edge_url)

        # Download the DeviceHub driver record cache for the connected Litmus Edge
        # version. This is required before any device can be created via the SDK.
        # create_dh_cache() is a no-op if the version is already cached.
        try:
            dh_version = get_version(self.conn)
            logger.info("Downloading DeviceHub driver record for version %s …", dh_version)
            create_dh_cache(dh_version, self.conn)
            logger.info("DeviceHub driver record ready (version %s).", dh_version)
        except Exception as exc:
            logger.warning("Could not download DeviceHub driver record: %s", exc)

        self.scenario_classes = _load_all_scenario_classes()
        logger.info(
            "Loaded %d scenarios: %s",
            len(self.scenario_classes),
            list(self.scenario_classes.keys()),
        )

    # ── Public API (called by main.py route handlers) ─────────────────────────

    def list_scenarios(self) -> list[dict]:
        """
        Return a list of all available scenarios as plain dicts, suitable for
        rendering in the Jinja2 template.

        Each dict contains:
          id, title, category, difficulty, symptom, learning_objective,
          timeout_minutes, is_active (bool), is_completed (bool),
          hints_revealed (int), total_hints (int)
        """
        result = []
        for scenario_id, cls in self.scenario_classes.items():
            is_active = (
                self.active_scenario is not None
                and self.active_scenario.id == scenario_id
            )
            is_completed = (
                is_active
                and self.active_state is not None
                and self.active_state.completed
            )
            hints_revealed = (
                self.active_state.hints_used
                if is_active and self.active_state
                else 0
            )
            result.append({
                "id": cls.id,
                "title": cls.title,
                "category": cls.category,
                "difficulty": cls.difficulty,
                "symptom": cls.symptom,
                "learning_objective": cls.learning_objective,
                "timeout_minutes": cls.timeout_minutes,
                "is_active": is_active,
                "is_completed": is_completed,
                "hints_revealed": hints_revealed,
                "total_hints": len(cls.hints),
            })
        return result

    def get_scenario_detail(self, scenario_id: str) -> dict:
        """
        Return full details for a single scenario, including revealed hints
        and current active state.

        Args:
            scenario_id: The id string of the scenario to look up.

        Returns:
            A dict with all scenario metadata plus runtime state fields.

        Raises:
            KeyError: if no scenario with the given id exists.
        """
        if scenario_id not in self.scenario_classes:
            raise KeyError(f"No scenario with id '{scenario_id}'")

        cls = self.scenario_classes[scenario_id]
        is_active = (
            self.active_scenario is not None
            and self.active_scenario.id == scenario_id
        )
        state = self.active_state if is_active else ScenarioState()

        # Only reveal hints the learner has actually requested
        revealed_hints = cls.hints[: state.hints_used]

        elapsed_seconds = None
        if is_active and state.started_at:
            elapsed_seconds = int(
                (datetime.utcnow() - state.started_at).total_seconds()
            )

        return {
            "id": cls.id,
            "title": cls.title,
            "category": cls.category,
            "difficulty": cls.difficulty,
            "symptom": cls.symptom,
            "learning_objective": cls.learning_objective,
            "timeout_minutes": cls.timeout_minutes,
            "total_hints": len(cls.hints),
            "is_active": is_active,
            "is_completed": state.completed,
            "hints_used": state.hints_used,
            "revealed_hints": revealed_hints,
            "elapsed_seconds": elapsed_seconds,
        }

    def start(self, scenario_id: str) -> dict:
        """
        Start a scenario: run its setup() and arm the timeout.

        Args:
            scenario_id: The id string of the scenario to start.

        Returns:
            A dict with {"success": True/False, "message": str}.

        Side effects:
            - Calls setup() on the scenario, which creates resources on Litmus Edge.
            - Starts an asyncio background task to auto-teardown on timeout.
        """
        if self.active_scenario is not None:
            return {
                "success": False,
                "message": (
                    f"Another scenario ('{self.active_scenario.id}') is already active. "
                    "Please reset it before starting a new one."
                ),
            }

        if scenario_id not in self.scenario_classes:
            return {"success": False, "message": f"Unknown scenario '{scenario_id}'"}

        cls = self.scenario_classes[scenario_id]
        scenario = cls()
        state = ScenarioState(active=True, started_at=datetime.utcnow())

        try:
            scenario.setup(self.conn, state)
        except Exception as exc:
            logger.exception("setup() failed for scenario '%s'", scenario_id)
            return {
                "success": False,
                "message": f"Setup failed: {exc}. Check that Litmus Edge is reachable.",
            }

        self.active_scenario = scenario
        self.active_state = state
        self._arm_timeout(scenario.timeout_minutes)

        logger.info("Started scenario '%s'", scenario_id)
        return {
            "success": True,
            "message": f"Scenario '{cls.title}' is now active. Switch to Litmus Edge to investigate.",
        }

    def check(self, scenario_id: str) -> dict:
        """
        Run the active scenario's validate() and return the result.

        Args:
            scenario_id: Must match the currently active scenario's id.

        Returns:
            A dict with {"success": True/False, "message": str}.
        """
        if self.active_scenario is None or self.active_scenario.id != scenario_id:
            return {
                "success": False,
                "message": "This scenario is not currently active. Start it first.",
            }

        try:
            passed, message = self.active_scenario.validate(self.conn, self.active_state)
        except Exception as exc:
            logger.exception("validate() failed for scenario '%s'", scenario_id)
            return {
                "success": False,
                "message": f"Validation error: {exc}",
            }

        if passed:
            self.active_state.completed = True
            self._cancel_timeout()
            logger.info("Scenario '%s' completed successfully.", scenario_id)

        return {"success": passed, "message": message}

    def next_hint(self, scenario_id: str) -> dict:
        """
        Reveal the next hint for the active scenario.

        Hints are revealed one at a time. Once all hints have been revealed,
        further calls return the last hint again with a note.

        Args:
            scenario_id: Must match the currently active scenario's id.

        Returns:
            A dict with {"hint": str, "hint_number": int, "total_hints": int}.
        """
        if self.active_scenario is None or self.active_scenario.id != scenario_id:
            return {"hint": "This scenario is not active.", "hint_number": 0, "total_hints": 0}

        hints = self.active_scenario.hints
        total = len(hints)

        if self.active_state.hints_used < total:
            self.active_state.hints_used += 1

        current_index = self.active_state.hints_used - 1
        hint_text = hints[current_index] if hints else "No hints available."

        return {
            "hint": hint_text,
            "hint_number": self.active_state.hints_used,
            "total_hints": total,
        }

    def reset(self, scenario_id: str) -> dict:
        """
        Tear down the active scenario and reset all state.

        Calls the scenario's teardown() to delete all resources created by
        setup(). Safe to call even if setup() only partially completed —
        individual safe_delete helpers in litmus_utils.py swallow errors for
        resources that no longer exist.

        Args:
            scenario_id: Must match the currently active scenario's id.

        Returns:
            A dict with {"success": True/False, "message": str}.
        """
        if self.active_scenario is None or self.active_scenario.id != scenario_id:
            return {
                "success": False,
                "message": "This scenario is not currently active.",
            }

        self._cancel_timeout()
        self._run_teardown()
        return {"success": True, "message": "Scenario reset. The platform has been cleaned up."}

    def force_reset_all(self) -> dict:
        """
        Emergency reset: tear down the active scenario regardless of which one
        it is, and ensure all created resources are cleaned up.

        This is exposed via the /admin/force-reset route and shown as a
        prominent button in the UI. It exists specifically to handle the case
        where the app was restarted mid-scenario (losing timeout state) or
        where SYS-02 left a service stopped.

        Returns:
            A dict with {"success": bool, "message": str}.
        """
        if self.active_scenario is None:
            return {"success": True, "message": "No active scenario to reset."}

        self._cancel_timeout()
        self._run_teardown()
        return {
            "success": True,
            "message": "Force reset complete. All lab resources have been cleaned up.",
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _run_teardown(self) -> None:
        """Run teardown() and clear all engine state."""
        if self.active_scenario and self.active_state:
            try:
                self.active_scenario.teardown(self.conn, self.active_state)
                logger.info("Teardown complete for scenario '%s'", self.active_scenario.id)
            except Exception as exc:
                logger.exception(
                    "teardown() raised an exception for scenario '%s': %s",
                    self.active_scenario.id,
                    exc,
                )
        self.active_scenario = None
        self.active_state = None

    def _arm_timeout(self, minutes: int) -> None:
        """Start an asyncio task that calls teardown after `minutes` minutes."""
        self._cancel_timeout()

        async def _timeout_task():
            await asyncio.sleep(minutes * 60)
            if self.active_scenario:
                logger.warning(
                    "Timeout reached for scenario '%s'. Running teardown.",
                    self.active_scenario.id,
                )
                self._run_teardown()

        # asyncio.get_event_loop() works here because FastAPI runs inside an
        # asyncio event loop, so this call is always made in an async context.
        try:
            loop = asyncio.get_event_loop()
            self._timeout_task = loop.create_task(_timeout_task())
        except RuntimeError:
            logger.warning("Could not schedule timeout task (no running event loop).")

    def _cancel_timeout(self) -> None:
        """Cancel the pending timeout task, if one exists."""
        if self._timeout_task and not self._timeout_task.done():
            self._timeout_task.cancel()
        self._timeout_task = None
