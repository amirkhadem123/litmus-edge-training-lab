"""
Scenario SYS-02: The Dead Service
Category: System | Difficulty: Intermediate

WHAT THIS SCENARIO TEACHES:
  Litmus Edge hosts a number of services that can be enabled or disabled
  by an administrator. When a service is stopped, its functionality becomes
  unavailable without any error message to other users.

  Knowing WHERE to look for a stopped service (System > Device Management >
  Services) and HOW to restart it is an essential support skill.

HOW THE BREAK WORKS:
  setup() calls the Services API to stop the SSH service. After stopping it:
    - Engineers can no longer open an SSH session to the device.
    - All other platform functionality (DeviceHub, Flows, Analytics, cloud
      connectors) continues normally.

  The learner must navigate to the Services panel and re-enable SSH.

WHY SSH:
  Litmus Edge 4.0.x exposes a REST API for starting and stopping services,
  but only a limited set of services are controllable via this API.
  On this version, only the SSH service supports start/stop operations.
  The Services panel in the UI shows all services regardless of API access,
  so the troubleshooting workflow (find the red service → click Start) is
  identical regardless of which service is stopped.

  SERVICE API notes for LE 4.0.x:
    - Service name used by the API: "ssh" (not the systemd unit name)
    - GET  /dm/services/ssh  → {"status": "started"} or {"status": "stopped"}
    - PUT  /dm/services/ssh/stop  → 204
    - PUT  /dm/services/ssh/start → 204

HOW VALIDATION WORKS:
  GET /dm/services/ssh and check the 'status' field equals 'started'.

TEARDOWN (SAFETY NET):
  If SSH is still stopped when teardown fires, we start it.
  This ensures the platform is left in a clean state regardless of whether
  the learner solved the scenario.
"""

import logging

from litmussdk.system import services
from litmussdk.utils.conn import LEConnection

from scenarios.base import BaseScenario, ScenarioState
from litmus_utils import get_service_active_state


logger = logging.getLogger(__name__)

# The API service identifier for SSH on Litmus Edge 4.0.x.
# This is the short ID used by /dm/services — not the systemd unit name.
SERVICE_NAME = "ssh"

# The status string returned by GET /dm/services/ssh when the service is running.
STATUS_RUNNING = "started"


class ServiceStoppedScenario(BaseScenario):
    """
    SYS-02: The SSH service is stopped via the Services API.
    The learner must find and restart it through the Litmus Edge UI.

    ⚠️ This scenario modifies a real platform service. See module docstring.
    """

    id = "sys-02"
    title = "The Dead Service"
    category = "System"
    difficulty = "Intermediate"

    symptom = (
        "Your team reports they can no longer open SSH sessions to the Litmus Edge "
        "device — connections are refused. The Litmus Edge web UI is still accessible "
        "and all other platform features appear to be working normally. "
        "No one has changed any network or firewall settings."
    )

    learning_objective = (
        "Learn to use the Litmus Edge Services panel to identify a stopped service "
        "and restart it without rebooting the device."
    )

    hints = [
        "SSH being refused but the web UI working suggests the SSH service itself "
        "has been stopped — not a network or firewall issue.",
        "Go to System > Device Management > Services in the Litmus Edge UI. "
        "Look for a service called 'SSH' and check its status.",
        "Find the SSH entry in the Services list. Its status will show as stopped. "
        "Use the Start (or Enable) button to restart it.",
    ]

    # Shorter timeout — SSH being disabled affects real operations.
    timeout_minutes = 20

    # ── Class-level warning shown prominently in the UI ──────────────────────
    service_impact_warning = (
        "⚠️ This scenario stops the real SSH service on your Litmus Edge instance. "
        "SSH access to the device will be unavailable until you restart the service "
        "or the scenario resets automatically after "
        f"{timeout_minutes} minutes. If this app is restarted mid-scenario, use "
        "the 'Force Reset All' button on the home page to restore the service."
    )

    def setup(self, conn: LEConnection, state: ScenarioState) -> None:
        """
        Stop the SSH service using the Services API.

        Records the service name in state.resources so teardown() knows
        which service to restart if needed.
        """
        logger.info("[SYS-02] Running setup: stopping service '%s'", SERVICE_NAME)

        services.stop_and_disable_service(SERVICE_NAME, le_connection=conn)
        state.resources.append(("service", SERVICE_NAME))

        logger.info("[SYS-02] Service '%s' stopped. Setup complete.", SERVICE_NAME)

    def validate(self, conn: LEConnection, state: ScenarioState) -> tuple[bool, str]:
        """
        Check whether the SSH service is running again.

        GET /dm/services/ssh returns {"status": "started"} or {"status": "stopped"}.
        """
        status = get_service_active_state(conn, SERVICE_NAME)

        if status == STATUS_RUNNING:
            return (
                True,
                f"Correct! The SSH service is now running. "
                "Key takeaway: Litmus Edge services can be stopped independently. "
                "The Services panel under System > Device Management is your "
                "first stop when a platform feature or access method stops working.",
            )
        elif status == "stopped":
            return (
                False,
                "The SSH service is still stopped. Go to "
                "System > Device Management > Services, find 'SSH', "
                "and use the Start option.",
            )
        else:
            return (
                False,
                f"Could not determine the state of the SSH service "
                f"(got: {status!r}). Try checking again in a moment.",
            )

    def teardown(self, conn: LEConnection, state: ScenarioState) -> None:
        """
        Safety net: if SSH is not running, start it.

        This ensures the platform is left in a clean state even if the
        learner didn't solve the scenario or the timeout fired.
        """
        logger.info("[SYS-02] Teardown: checking if '%s' needs to be started.", SERVICE_NAME)

        current_status = get_service_active_state(conn, SERVICE_NAME)

        if current_status != STATUS_RUNNING:
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
            logger.info("[SYS-02] Service '%s' already running. No action needed.", SERVICE_NAME)

        logger.info("[SYS-02] Teardown complete.")
