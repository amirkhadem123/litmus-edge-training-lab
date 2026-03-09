"""
Scenario SYS-02: The Dead Service
Category: System | Difficulty: Intermediate

WHAT THIS SCENARIO TEACHES:
  Litmus Edge is built as ~25 independent services managed by systemd.
  Most of these services are shown as coloured status indicators on the
  Litmus Edge main dashboard (green = running, red = stopped/failed).

  When a service stops, the features it provides become unavailable — but
  the rest of the platform keeps running. Analytics stopping won't affect
  device connectivity, for example.

  Knowing WHERE to look for a stopped service (the dashboard status panel,
  or System > Support > Component Status) and HOW to restart it
  (System > Device Management > Services) is an essential support skill.

HOW THE BREAK WORKS:
  setup() calls the Services API to stop 'loopedge-analytics2', which is
  the analytics calculation engine. After stopping it:
    - The Analytics module indicator on the Litmus Edge dashboard turns red.
    - Any configured analytics calculations stop producing output.
    - Everything else (DeviceHub, Flows, cloud connectors) continues normally.

⚠️ IMPORTANT RISK NOTE:
  This scenario stops a REAL platform service. If the app crashes or is
  restarted while this scenario is active, teardown() will not run and
  the service will remain stopped. The 'Force Reset All' button on the
  home page will restart it. If that also fails, the service can be
  restarted manually from the Litmus Edge UI under:
    System > Device Management > Services > loopedge-analytics2 > Start

HOW VALIDATION WORKS:
  We call the Services API to get the current ActiveState of
  'loopedge-analytics2'. If it is 'active', the learner has restarted it.

TEARDOWN (SAFETY NET):
  If the service is not already running when teardown fires, we start it.
  This ensures the platform is left in a clean state regardless of whether
  the learner solved the scenario.
"""

import logging

from litmussdk.system import services
from litmussdk.utils.conn import LEConnection

from scenarios.base import BaseScenario, ScenarioState
from litmus_utils import get_service_active_state


logger = logging.getLogger(__name__)

# The systemd service name for the Litmus Edge analytics engine.
# This is the internal name used by all loopedge-* services.
SERVICE_NAME = "loopedge-analytics2"


class ServiceStoppedScenario(BaseScenario):
    """
    SYS-02: The analytics service is stopped via the Services API.
    The learner must find and restart it through the Litmus Edge UI.

    ⚠️ This scenario modifies a real platform service. See module docstring.
    """

    id = "sys-02"
    title = "The Dead Service"
    category = "System"
    difficulty = "Intermediate"

    symptom = (
        "Analytics calculations that were producing output this morning have completely "
        "stopped. No new results are being written. Looking at the main Litmus Edge "
        "dashboard, one of the module status indicators is showing red. "
        "Device connectivity and data collection appear to be working fine."
    )

    learning_objective = (
        "Learn to use the Litmus Edge module status dashboard and the Services panel "
        "to identify a stopped system service and restart it."
    )

    hints = [
        "Look at the module status indicators on the Litmus Edge main dashboard "
        "(the coloured circles at the bottom of the page). One of them is red.",
        "The red indicator corresponds to the Analytics module. Go to "
        "System > Device Management > Services to see the list of running services.",
        "Find 'loopedge-analytics2' in the services list. Its status will show "
        "as stopped or inactive. Use the Start button to restart it.",
    ]

    # Shorter timeout for this scenario because it affects a real service.
    # If the learner walks away, we want to restore the service sooner.
    timeout_minutes = 20

    # ── Class-level warning shown prominently in the UI ──────────────────────
    # The UI template checks for this attribute and renders it in a warning box.
    service_impact_warning = (
        "⚠️ This scenario stops the real 'loopedge-analytics2' service on your "
        "Litmus Edge instance. Analytics calculations will be unavailable until "
        "you restart the service or the scenario resets automatically after "
        f"{timeout_minutes} minutes. If this app is restarted mid-scenario, use "
        "the 'Force Reset All' button on the home page to restore the service."
    )

    def setup(self, conn: LEConnection, state: ScenarioState) -> None:
        """
        Stop the analytics service using the Services API.

        We record the service name in state.resources so teardown() knows
        which service to restart if needed.
        """
        logger.info("[SYS-02] Running setup: stopping service '%s'", SERVICE_NAME)

        services.stop_and_disable_service(SERVICE_NAME, le_connection=conn)
        state.resources.append(("service", SERVICE_NAME))

        logger.info("[SYS-02] Service '%s' stopped. Setup complete.", SERVICE_NAME)

    def validate(self, conn: LEConnection, state: ScenarioState) -> tuple[bool, str]:
        """
        Check whether the analytics service is running again.
        """
        active_state = get_service_active_state(conn, SERVICE_NAME)

        if active_state == "active":
            return (
                True,
                f"Correct! '{SERVICE_NAME}' is now active. Analytics calculations "
                "will resume shortly. "
                "Key takeaway: Litmus Edge services can be stopped, restarted, or "
                "fail independently. The dashboard status indicators and the Services "
                "panel under System are your first stop when a platform feature goes dark.",
            )
        elif active_state in ("inactive", "failed"):
            return (
                False,
                f"The service '{SERVICE_NAME}' is still {active_state}. "
                "Go to System > Device Management > Services, find "
                f"'{SERVICE_NAME}', and use the Start option.",
            )
        elif active_state == "activating":
            return (
                False,
                f"The service '{SERVICE_NAME}' is currently starting up. "
                "Wait a few seconds and check again.",
            )
        else:
            return (
                False,
                f"Could not determine the state of '{SERVICE_NAME}' "
                f"(got: {active_state!r}). Try checking again in a moment.",
            )

    def teardown(self, conn: LEConnection, state: ScenarioState) -> None:
        """
        Safety net: if the service is not running, start it.

        This ensures the platform is clean even if the learner didn't solve
        the scenario, the timeout fired, or the app was restarted.
        """
        logger.info("[SYS-02] Teardown: checking if '%s' needs to be started.", SERVICE_NAME)

        current_state = get_service_active_state(conn, SERVICE_NAME)

        if current_state != "active":
            try:
                services.start_and_enable_service(SERVICE_NAME, le_connection=conn)
                logger.info("[SYS-02] Service '%s' started by teardown.", SERVICE_NAME)
            except Exception as exc:
                logger.warning(
                    "[SYS-02] Could not start service '%s' during teardown: %s",
                    SERVICE_NAME,
                    exc,
                )
        else:
            logger.info("[SYS-02] Service '%s' already active. No action needed.", SERVICE_NAME)

        logger.info("[SYS-02] Teardown complete.")
