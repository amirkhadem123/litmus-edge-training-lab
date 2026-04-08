"""
Scenario DH-02: The Tagless Device
Category: DeviceHub | Difficulty: Beginner

WHAT THIS SCENARIO TEACHES:
  In Litmus Edge, connecting a device and configuring tags are two separate
  steps. A device can be fully connected and running — green status, no errors
  — and still produce zero data if no tags have been configured on it.
  Tags are the individual data points (registers, topics, OPC-UA nodes) that
  the device driver reads and publishes to the platform's message bus.

  This is a common real-world mistake: someone adds a device to DeviceHub,
  confirms it connects, and assumes data will flow. It won't until tags are
  explicitly added.

HOW THE BREAK WORKS:
  setup() creates a running Generator device with zero tags.
  The device status will show green (it IS connected and running), but
  the dashboard will show 0 tags and 0 data points for this device.

HOW VALIDATION WORKS:
  We call list_registers_from_single_device() and count the returned tags.
  If the count is >= 1, the learner has added at least one tag.

TEARDOWN:
  Delete the device. All tags under the device are automatically removed
  by Litmus Edge when the device is deleted.
"""

import logging

from litmussdk.devicehub import devices, tags
from litmussdk.devicehub.devices._models import Device
from litmussdk.utils.conn import LEConnection

from scenarios.base import BaseScenario, ScenarioState
from litmus_utils import get_driver_id_by_name, safe_delete_device_by_name, safe_delete_devices_by_ids


logger = logging.getLogger(__name__)

LAB_DEVICE_NAME = "lab-quality-sensor-02"


class NoTagsScenario(BaseScenario):
    """
    DH-02: A Generator device is created and left running, but with no tags.
    The learner must add at least one tag to it.
    """

    id = "dh-02"
    title = "The Tagless Device"
    category = "DeviceHub"
    difficulty = "Beginner"

    symptom = (
        "A device called 'lab-quality-sensor-02' was recently added to DeviceHub. "
        "It shows a green connected status and no error messages. However, no data "
        "from this device appears anywhere — not in DataHub, not in Flows, not on "
        "the dashboard. The tag count for this device shows 0."
    )

    learning_objective = (
        "Understand that connecting a device and configuring tags are two separate "
        "steps in Litmus Edge, and know how to add tags to an existing device."
    )

    hints = [
        "The device is connected and running. Check the device's tag list inside DeviceHub.",
        "Click on 'lab-quality-sensor-02' in DeviceHub to open its detail view. "
        "Look at the Tags section — how many tags are configured?",
        "The device has no tags. Use the 'Add Tag' option inside the device to create "
        "at least one tag. For a Generator device, choose the 'S' register type.",
    ]

    timeout_minutes = 30

    def setup(self, conn: LEConnection, state: ScenarioState) -> None:
        """
        Create a Generator device but deliberately add no tags.

        The device is left in a running state — the problem is not that the
        device is broken, but that no data points have been configured on it.
        """
        logger.info("[DH-02] Running setup: creating tagless device '%s'", LAB_DEVICE_NAME)
        safe_delete_device_by_name(conn, LAB_DEVICE_NAME)

        generator_id = get_driver_id_by_name(conn, "Generator")
        device = Device(
            name=LAB_DEVICE_NAME,
            driver=generator_id,
            description="Lab training device — do not use in production.",
            properties={},
            alias_topics=True,
            debug=False,
        )

        # Create the device — it starts running automatically.
        # We deliberately do NOT create any tags.
        created_device = devices.create_device(device, le_connection=conn)
        state.resources.append(("device", created_device.id))

        logger.info(
            "[DH-02] Device '%s' created (id: %s) with 0 tags. Setup complete.",
            LAB_DEVICE_NAME,
            created_device.id,
        )

    def validate(self, conn: LEConnection, state: ScenarioState) -> tuple[bool, str]:
        """
        Check that at least one tag now exists on the device.

        We find the device by name, then list its tags. Any tag count >= 1 counts as success.
        """
        # Find the device from the resource list
        device_ids = [res_id for res_type, res_id in state.resources if res_type == "device"]
        if not device_ids:
            return False, "Lab device not found. The scenario may not have been set up correctly."

        from litmussdk.devicehub.devices import _functions as dev_funcs
        from litmussdk.devicehub import tags as tag_module

        try:
            device = dev_funcs.list_device_by_id(device_ids[0], le_connection=conn)
            device_tags = tag_module.list_registers_from_single_device(device, le_connection=conn)
        except Exception as exc:
            return False, f"Could not query device tags: {exc}"

        tag_count = len(device_tags)

        if tag_count >= 1:
            return (
                True,
                f"Well done! You added {tag_count} tag(s) to 'lab-quality-sensor-02'. "
                "Data will now flow to DataHub and be available in Flows. "
                "Remember: a connected device is only the first step — tags define "
                "what data is actually collected.",
            )
        else:
            return (
                False,
                "The device still has no tags. Open DeviceHub, click on "
                "'lab-quality-sensor-02', and use the Add Tag option to create "
                "at least one data point.",
            )

    def teardown(self, conn: LEConnection, state: ScenarioState) -> None:
        """Delete the lab device (tags are removed automatically by Litmus Edge)."""
        device_ids = [res_id for res_type, res_id in state.resources if res_type == "device"]
        safe_delete_devices_by_ids(conn, device_ids)
        logger.info("[DH-02] Teardown complete.")
