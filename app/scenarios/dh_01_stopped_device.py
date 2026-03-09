"""
Scenario DH-01: The Stopped Device
Category: DeviceHub | Difficulty: Beginner

WHAT THIS SCENARIO TEACHES:
  Every device in Litmus Edge has a lifecycle: it can be running (actively
  polling or subscribing to data) or stopped (configured but idle). A stopped
  device produces zero data, which is easy to mistake for a connection failure
  or a misconfiguration. This scenario teaches the learner to distinguish
  between "stopped" and "broken" by reading the device status indicator.

HOW THE BREAK WORKS:
  1. setup() creates a Generator device — a built-in Litmus Edge driver that
     simulates a PLC by generating dummy integer values continuously.
     This means no real hardware is needed.
  2. Three tags are added to the device so the dashboard looks realistic.
  3. The device is then STOPPED via the SDK. From the learner's perspective,
     the device exists and is configured correctly, but publishes 0 messages.

HOW VALIDATION WORKS:
  We use the Prometheus metrics endpoint (/devicehub/metrics) to read the
  current state of the device. The metric 'loopedge_dh_device_state' has
  a value of 1 when running and 0 when stopped. See litmus_utils.py for
  the parsing logic.

TEARDOWN:
  The device (and all its tags, which Litmus Edge deletes automatically
  when a device is deleted) is removed. If the learner already deleted
  the device themselves, the safe_delete helper absorbs the error.

GENERATOR DRIVER PROPERTIES:
  The Generator driver requires a 'updateRate' property (in milliseconds)
  that controls how often it produces new values. We use 1000ms (1 second).
  Generator tags use a 'name' of 'int' (integer register) and require a
  'valueType' of 'int'.
"""

import logging

from litmussdk.devicehub import devices, tags
from litmussdk.devicehub.devices._models import Device
from litmussdk.devicehub.tags._models import Tag
from litmussdk.utils.conn import LEConnection

from scenarios.base import BaseScenario, ScenarioState
from litmus_utils import get_device_running_state, safe_delete_devices_by_ids


logger = logging.getLogger(__name__)

# The exact name we will give the lab device.
# Using 'lab-' prefix makes it clearly identifiable as a training resource.
LAB_DEVICE_NAME = "lab-machine-01"


class StoppedDeviceScenario(BaseScenario):
    """
    DH-01: A Generator device is created with tags, then stopped.
    The learner must start it again via the DeviceHub UI.
    """

    id = "dh-01"
    title = "The Stopped Device"
    category = "DeviceHub"
    difficulty = "Beginner"

    symptom = (
        "A device called 'lab-machine-01' appears in DeviceHub and looks correctly "
        "configured, but the main dashboard shows 0 messages published for this device. "
        "Operators report that data stopped arriving about an hour ago. No error messages "
        "are visible."
    )

    learning_objective = (
        "Understand the difference between a device that is 'configured' and one that "
        "is actively 'running', and know how to start a stopped device."
    )

    hints = [
        "Open DeviceHub and look at the list of devices. Pay attention to the status "
        "column or indicator next to 'lab-machine-01'.",
        "There is a difference between a device being present in the list and a device "
        "that is actively running. Look for a run/stop state indicator.",
        "The device is in a stopped state. Find the action menu or button that lets you "
        "start a stopped device and apply it to 'lab-machine-01'.",
    ]

    timeout_minutes = 30

    def setup(self, conn: LEConnection, state: ScenarioState) -> None:
        """
        Create a Generator device with three integer tags, then stop it.

        Steps:
          1. Build a Device object using the 'generator' driver name.
             The SDK automatically resolves the string 'generator' to the
             full Driver object with its property definitions.
          2. Set the 'updateRate' property to 1000 (milliseconds).
          3. Create the device via the API — it starts running by default.
          4. Create three integer tags so the device looks realistic.
          5. Stop the device — this is the "break".
        """
        logger.info("[DH-01] Running setup: creating and stopping device '%s'", LAB_DEVICE_NAME)

        # Step 1–2: Build the Device object.
        # 'driver' can be passed as a plain string — the SDK's DriverField
        # validator resolves it to the correct Driver object automatically.
        device = Device(
            name=LAB_DEVICE_NAME,
            driver="generator",
            description="Lab training device — do not use in production.",
            properties={"updateRate": "1000"},
            alias_topics=True,
            debug=False,
        )

        # Step 3: Create the device. It starts in a running state by default.
        created_device = devices.create_device(device, le_connection=conn)
        state.resources.append(("device", created_device.id))
        logger.info("[DH-01] Device created with id: %s", created_device.id)

        # Step 4: Create three integer tags under the new device.
        # Generator 'int' registers produce random integer values.
        tag_objects = [
            Tag(
                device=created_device,
                name="int",
                tag_name=tag_name,
                description="Auto-generated lab tag.",
                value_type="int",
                properties={"readWrite": "Read Only"},
                publish_cov=False,
            )
            for tag_name in ["temperature", "pressure", "flow_rate"]
        ]
        tags.create_tags(tag_objects, le_connection=conn)
        logger.info("[DH-01] Created 3 tags on device.")

        # Step 5: STOP the device — this is the problem the learner must fix.
        devices.stop_device(created_device, le_connection=conn)
        logger.info("[DH-01] Device stopped. Setup complete.")

    def validate(self, conn: LEConnection, state: ScenarioState) -> tuple[bool, str]:
        """
        Check if the device is running by reading the Prometheus metrics endpoint.

        A return of True means the learner has successfully started the device.
        """
        is_running = get_device_running_state(conn, LAB_DEVICE_NAME)

        if is_running is True:
            return (
                True,
                "Correct! 'lab-machine-01' is now running and publishing data. "
                "You found that the device was in a stopped state and started it. "
                "Remember: a device can be fully configured but produce no data "
                "if it is stopped.",
            )
        elif is_running is False:
            return (
                False,
                "The device is still stopped. Open DeviceHub, find 'lab-machine-01', "
                "and look for an option to start it.",
            )
        else:
            # get_device_running_state returned None — metric not found
            return (
                False,
                "Could not determine device status from metrics. The device may still "
                "be starting up — wait a few seconds and try again.",
            )

    def teardown(self, conn: LEConnection, state: ScenarioState) -> None:
        """
        Delete the lab device (and its tags, which Litmus Edge removes automatically).
        """
        device_ids = [res_id for res_type, res_id in state.resources if res_type == "device"]
        safe_delete_devices_by_ids(conn, device_ids)
        logger.info("[DH-01] Teardown complete.")
