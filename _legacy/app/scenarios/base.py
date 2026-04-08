"""
Base class for all Litmus Lab training scenarios.

Every scenario in this application (e.g. "stopped device", "missing tags") inherits
from BaseScenario and must implement three methods:
  - setup()    → uses the Litmus API to create a broken/misconfigured state
  - validate() → checks whether the learner has fixed the problem
  - teardown() → cleans up everything the scenario created

This design means each scenario is self-contained. Adding a new scenario is as
simple as writing a new Python class — no other files need to change.

HOW SCENARIOS WORK (plain-language summary):
  1. The learner picks a scenario from the web UI.
  2. The app calls setup(), which uses the official Litmus SDK to create a
     problem on the live Litmus Edge instance (e.g. stops a device).
  3. The learner opens the Litmus Edge UI in another browser tab and tries
     to find and fix the problem.
  4. The learner clicks "Check My Solution" in the app.
  5. The app calls validate(), which queries the Litmus API to see if the
     problem has been resolved, and reports pass/fail.
  6. When the learner resets (or the timeout fires), teardown() deletes
     everything the scenario created so the platform is clean again.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from litmussdk.utils.conn import LEConnection


@dataclass
class ScenarioState:
    """
    Holds the runtime state of a scenario that is currently active.

    This is separate from the scenario definition itself so that the same
    scenario class can be used over and over — the class describes *what*
    the scenario is, and ScenarioState tracks *where the learner is* in it.

    Attributes:
        active:        True while a scenario is running (setup was called but
                       teardown has not yet been called).
        started_at:    The datetime when the learner started this scenario.
                       Used to calculate elapsed time and enforce the timeout.
        completed:     True once validate() returns success. The scenario stays
                       visible but shows a "Completed" badge.
        hints_used:    How many hints the learner has revealed so far.
        resources:     A list of (resource_type, resource_id) tuples for
                       everything setup() created. teardown() uses this list
                       to know exactly what to delete. Each scenario appends
                       to this list as it creates resources.
    """

    active: bool = False
    started_at: Optional[datetime] = None
    completed: bool = False
    hints_used: int = 0
    resources: list = field(default_factory=list)


class BaseScenario(ABC):
    """
    Abstract base class that every training scenario must inherit from.

    Subclasses define the scenario content (title, symptom, hints) as
    class-level attributes, and implement the three abstract methods
    (setup, validate, teardown) as instance methods.

    The LEConnection object (which handles authentication against the
    Litmus Edge API) is passed in by the ScenarioEngine at runtime.
    Scenarios never manage their own authentication.

    Example of a minimal concrete scenario:

        class MyScenario(BaseScenario):
            id = "my-01"
            title = "My Scenario"
            category = "DeviceHub"
            difficulty = "Beginner"
            symptom = "Something is broken."
            learning_objective = "Learn how to fix it."
            hints = ["Look here.", "Try this.", "The answer is X."]

            def setup(self, conn, state):
                # break something using the SDK
                ...

            def validate(self, conn, state):
                # check if it's been fixed
                return True, "Well done!"

            def teardown(self, conn, state):
                # clean up everything setup() created
                ...
    """

    # ── Scenario metadata (must be set by each subclass) ──────────────────────

    id: str
    """Unique short identifier, e.g. 'dh-01'. Used in URL paths."""

    title: str
    """Human-readable title shown on the scenario card and detail page."""

    category: str
    """High-level grouping. Currently 'DeviceHub' or 'System'."""

    difficulty: str
    """'Beginner' or 'Intermediate'. Shown as a badge on the UI."""

    symptom: str
    """
    What the learner observes — written from the perspective of an operator
    who noticed a problem. Never states the cause; that's what the learner
    must discover.
    """

    learning_objective: str
    """One sentence describing what the learner will understand after fixing this."""

    hints: list[str]
    """
    Ordered list of hints, from vague to near-explicit.
    The learner can reveal them one at a time.
    """

    timeout_minutes: int = 30
    """
    How long the scenario stays active before the engine automatically calls
    teardown(). Prevents the platform from being left in a broken state if the
    learner walks away.
    """

    # ── Ticket metadata (used by the ticket-based UX) ─────────────────────────

    ticket_number: str = ""
    """Support ticket number shown in the UI, e.g. 'TKT-0042'."""

    priority: str = "Medium"
    """Ticket priority: 'High', 'Medium', or 'Low'. Controls badge colour."""

    customer: str = ""
    """Customer or team name that submitted the ticket, e.g. 'Acme Manufacturing'."""

    # ── Abstract methods (must be implemented by each subclass) ───────────────

    @abstractmethod
    def setup(self, conn: LEConnection, state: ScenarioState) -> None:
        """
        Create the broken/misconfigured state on the Litmus Edge instance.

        Guidelines:
        - Prefix all created resource names with 'lab-' so they are clearly
          identifiable as lab resources and not real production config.
        - Append every created resource to state.resources as a tuple:
              state.resources.append(("device", created_device.id))
          This ensures teardown() can find and delete them reliably.
        - Do not catch exceptions here — let them bubble up so the engine
          can report setup failures clearly to the user.

        Args:
            conn:  The authenticated LEConnection to the Litmus Edge API.
            state: The ScenarioState object for this run. Append resource
                   IDs here as you create them.
        """
        ...

    @abstractmethod
    def validate(self, conn: LEConnection, state: ScenarioState) -> tuple[bool, str]:
        """
        Check whether the learner has fixed the problem.

        This method queries the live Litmus Edge API and compares the current
        state against the expected "fixed" state. It does NOT attempt to fix
        anything itself — it only observes and reports.

        Returns:
            A tuple of (success: bool, message: str).
            - If success is True, the message congratulates the learner and
              explains what was fixed.
            - If success is False, the message describes what is still wrong
              (without giving away the solution).

        Args:
            conn:  The authenticated LEConnection to the Litmus Edge API.
            state: The ScenarioState object for this run.
        """
        ...

    @abstractmethod
    def teardown(self, conn: LEConnection, state: ScenarioState) -> None:
        """
        Delete all resources that setup() created.

        Teardown must be safe to call multiple times (idempotent) — if a
        resource has already been deleted (e.g. the learner deleted it as
        part of their fix), the method should catch the resulting error and
        continue rather than crashing.

        Args:
            conn:  The authenticated LEConnection to the Litmus Edge API.
            state: The ScenarioState object for this run. Use state.resources
                   to find the IDs of things that need to be deleted.
        """
        ...
