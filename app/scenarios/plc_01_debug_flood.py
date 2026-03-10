"""
Scenario PLC-01: Device Left in Debug Mode
Ticket: TKT-0042 | Priority: High
Customer: Acme Manufacturing — OT Operations Team

WHAT THIS SCENARIO TEACHES:
  In production environments, leaving a DeviceHub device in debug (verbose
  logging) mode generates thousands of log entries per hour. This is a real
  mistake that can fill log storage partitions and degrade system performance.
  The learner must locate the misconfigured device and disable debug mode.

HOW THE BREAK WORKS:
  1. setup() creates a Generator device named 'lab-plc-controller' with
     debug=True. The device is running normally and tags publish data, so
     there is no obvious operational symptom from the data perspective.
  2. The only way to discover the problem is to inspect the device's
     configuration in DeviceHub and notice the debug toggle is enabled.

HOW VALIDATION WORKS:
  We re-read the device from the Litmus Edge API using its ID (stored in
  state.resources during setup) and check the 'debug' attribute on the
  returned device object. This is the same pattern used in DH-03 to check
  the 'alias_topics' field.

TEARDOWN:
  The device and all its tags are deleted. If the learner already deleted
  the device themselves, the safe_delete helper absorbs the error.
"""

import logging

from litmussdk.devicehub import devices, tags
from litmussdk.devicehub.devices._functions import list_device_by_id
from litmussdk.devicehub.devices._models import Device
from litmussdk.devicehub.tags._models import Tag
from litmussdk.utils.conn import LEConnection

from scenarios.base import BaseScenario, ScenarioState
from litmus_utils import get_driver_id_by_name, safe_delete_device_by_name, safe_delete_devices_by_ids


logger = logging.getLogger(__name__)

LAB_DEVICE_NAME = "lab-plc-controller"


class DebugFloodScenario(BaseScenario):
    """
    PLC-01: A Generator device is created with debug=True.
    Data flows normally, but verbose logging is flooding storage.
    The learner must find the device, open its configuration, and disable debug mode.
    """

    id = "plc-01"
    title = "DeviceHub flooding log storage — suspected misconfiguration on PLC controller"
    category = "DeviceHub"
    difficulty = "Intermediate"

    ticket_number = "TKT-0042"
    priority = "High"
    customer = "Acme Manufacturing — OT Operations Team"

    symptom = (
        "Since last Tuesday our log management system has been alerting on abnormal volume "
        "originating from the Litmus Edge DeviceHub service. Disk usage on the historian server "
        "increased 40 GB in 48 hours. Our sysadmin traced the source to verbose output from a "
        "device called 'lab-plc-controller'. The device appears to be running normally — we can "
        "see tag values updating in the dashboard — but the log volume is unsustainable. "
        "We need this resolved urgently before it fills the partition and takes down the historian."
    )

    learning_objective = (
        "Understand how debug/verbose logging mode on a DeviceHub device affects platform "
        "performance, and know where to find and disable the setting."
    )

    hints = [
        "Log flooding from DeviceHub is typically caused by a device polling too aggressively "
        "or running in verbose/debug mode. Start by reviewing the configuration of each device "
        "in DeviceHub — not just whether it is running, but what settings it has.",
        "In Litmus Edge DeviceHub, each device has an advanced setting for 'Debug Mode' or "
        "'Verbose Logging'. This toggle is usually hidden under an 'Edit' or 'Advanced' section. "
        "Check the configuration of 'lab-plc-controller' specifically.",
        "Open DeviceHub → find 'lab-plc-controller' → click Edit (the pencil icon). Look for "
        "a 'Debug' toggle — it should be set to Off in a production environment. Disable it "
        "and save the device. Then click 'Mark Resolved' to verify.",
    ]

    timeout_minutes = 30

    def setup(self, conn: LEConnection, state: ScenarioState) -> None:
        """
        Create a Generator device with debug=True and three working tags.

        Steps:
          1. Pre-clean any orphaned device with this name from a previous run.
          2. Look up the Generator driver UUID from the cached driver record.
          3. Create the device with debug=True (the injected fault). The device
             starts running normally — data flows — so it doesn't look broken.
          4. Add three sinusoidal tags so the device looks like a real, active
             PLC controller with sensor readings.
        """
        logger.info("[PLC-01] Running setup: creating device '%s' with debug=True", LAB_DEVICE_NAME)
        safe_delete_device_by_name(conn, LAB_DEVICE_NAME)

        generator_id = get_driver_id_by_name(conn, "Generator")
        device = Device(
            name=LAB_DEVICE_NAME,
            driver=generator_id,
            description="Production PLC controller — Line 3 assembly.",
            properties={},
            alias_topics=True,
            debug=True,
        )

        created_device = devices.create_device(device, le_connection=conn)
        state.resources.append(("device", created_device.id))
        logger.info("[PLC-01] Device created with id: %s", created_device.id)

        tag_objects = [
            Tag(
                device=created_device,
                name="S",
                tag_name=tag_name,
                description="Auto-generated lab tag.",
                value_type="float64",
                properties={"address": "1", "count": "1", "pollingInterval": "1000"},
                publish_cov=False,
            )
            for tag_name in ["motor_speed", "conveyor_load", "temperature"]
        ]
        tags.create_tags(tag_objects, le_connection=conn)
        logger.info("[PLC-01] Created 3 tags. Setup complete.")

    def validate(self, conn: LEConnection, state: ScenarioState) -> tuple[bool, str]:
        """
        Re-read the device from Litmus Edge and check whether debug mode is off.

        The device ID was stored in state.resources during setup, so we can
        load it directly by ID rather than searching by name.
        """
        device_ids = [res_id for res_type, res_id in state.resources if res_type == "device"]
        if not device_ids:
            return (
                False,
                "Could not find the lab device record. The device may have been deleted. "
                "Use Reset to clean up and start again.",
            )

        try:
            current_device = list_device_by_id(device_ids[0], le_connection=conn)
        except Exception as exc:
            logger.warning("[PLC-01] Could not load device for validation: %s", exc)
            return (
                False,
                "Could not read the device configuration from Litmus Edge. "
                "Check that the device still exists and try again.",
            )

        if not current_device.debug:
            return (
                True,
                "Ticket resolved. Debug mode has been disabled on 'lab-plc-controller'. "
                "Log volume will return to normal levels. In production, always ensure "
                "debug mode is turned off after any diagnostic session.",
            )
        else:
            return (
                False,
                "Debug mode is still enabled on 'lab-plc-controller'. Open DeviceHub, "
                "find the device, click Edit, and turn off the Debug toggle. Save the "
                "device and then click 'Mark Resolved' again.",
            )

    def teardown(self, conn: LEConnection, state: ScenarioState) -> None:
        """
        Delete the lab device (and its tags, which Litmus Edge removes automatically).
        """
        device_ids = [res_id for res_type, res_id in state.resources if res_type == "device"]
        safe_delete_devices_by_ids(conn, device_ids)
        logger.info("[PLC-01] Teardown complete.")
