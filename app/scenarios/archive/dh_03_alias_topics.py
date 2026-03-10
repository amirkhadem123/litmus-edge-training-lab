"""
Scenario DH-03: The Silent Alias
Category: DeviceHub | Difficulty: Intermediate

WHAT THIS SCENARIO TEACHES:
  Litmus Edge publishes tag values onto an internal NATS message bus.
  Each tag has two possible topic formats:

    Raw topic:    devicehub/<device-uuid>/<tag-uuid>
    Alias topic:  devicehub/alias/<device-name>/<tag-name>

  Raw topics always exist. Alias topics are a human-readable alternative
  that ONLY exist if "Alias Topics" is enabled on the device.

  Node-RED flows, cloud connectors, and integrations that subscribe by
  device/tag name (alias format) will receive NOTHING if alias topics are
  disabled — even if the device is running and tags are updating. This
  is a silent failure: no error message, just an empty stream.

HOW THE BREAK WORKS:
  setup() creates a Generator device with tags, but sets alias_topics=False.
  The device runs normally and raw topics work, but the alias topic namespace
  is absent.

HOW VALIDATION WORKS:
  We reload the device from the API and check the alias_topics field.
  If it is True, the learner has enabled it.

TEARDOWN:
  Delete the lab device.
"""

import logging

from litmussdk.devicehub import devices, tags
from litmussdk.devicehub.devices._models import Device
from litmussdk.devicehub.tags._models import Tag
from litmussdk.utils.conn import LEConnection

from scenarios.base import BaseScenario, ScenarioState
from litmus_utils import get_driver_id_by_name, safe_delete_device_by_name, safe_delete_devices_by_ids


logger = logging.getLogger(__name__)

LAB_DEVICE_NAME = "lab-plc-03"


class AliasTopicsScenario(BaseScenario):
    """
    DH-03: A Generator device is created with alias_topics=False.
    Flows and integrations that use alias-format subscriptions receive nothing.
    The learner must enable alias topics on the device.
    """

    id = "dh-03"
    title = "The Silent Alias"
    category = "DeviceHub"
    difficulty = "Intermediate"

    symptom = (
        "A Node-RED flow was configured to receive data from 'lab-plc-03' by subscribing "
        "to the topic 'devicehub/alias/lab-plc-03/#'. The device is running, tags are "
        "configured, and no errors are shown anywhere. But the flow receives absolutely "
        "no messages — the debug output is empty."
    )

    learning_objective = (
        "Understand the difference between raw topics and alias topics in Litmus Edge, "
        "and know how to enable alias topics on a device so that human-readable topic "
        "names work in flows and integrations."
    )

    hints = [
        "The flow is subscribing using the 'alias' topic format. This requires a specific "
        "setting to be enabled on the device in DeviceHub.",
        "Open DeviceHub and click on 'lab-plc-03' to view its configuration. Look for "
        "a setting related to 'alias' or 'alias topics'.",
        "Find the 'Alias Topics' toggle or checkbox in the device settings and enable it. "
        "The device may need to be restarted for the change to take effect.",
    ]

    timeout_minutes = 30

    def setup(self, conn: LEConnection, state: ScenarioState) -> None:
        """
        Create a Generator device with alias_topics=False and add tags to it.
        The device runs normally on raw topics, but alias subscriptions fail silently.
        """
        logger.info("[DH-03] Running setup: creating device '%s' with alias_topics=False", LAB_DEVICE_NAME)
        safe_delete_device_by_name(conn, LAB_DEVICE_NAME)

        # Note: alias_topics=False — this is the problem
        generator_id = get_driver_id_by_name(conn, "Generator")
        device = Device(
            name=LAB_DEVICE_NAME,
            driver=generator_id,
            description="Lab training device — do not use in production.",
            properties={},
            alias_topics=False,  # THE BUG: alias topics are disabled
            debug=False,
        )

        created_device = devices.create_device(device, le_connection=conn)
        state.resources.append(("device", created_device.id))

        # Add tags so the device looks active and has data to publish
        tag_objects = [
            Tag(
                device=created_device,
                name="S",
                tag_name=tag_name,
                description="Auto-generated lab tag.",
                value_type="int64",
                properties={"address": "1", "count": "1", "pollingInterval": "1000"},
                publish_cov=False,
            )
            for tag_name in ["speed", "torque"]
        ]
        tags.create_tags(tag_objects, le_connection=conn)

        logger.info(
            "[DH-03] Device '%s' created (id: %s) with alias_topics=False. Setup complete.",
            LAB_DEVICE_NAME,
            created_device.id,
        )

    def validate(self, conn: LEConnection, state: ScenarioState) -> tuple[bool, str]:
        """
        Reload the device from the API and check whether alias_topics is now True.
        """
        device_ids = [res_id for res_type, res_id in state.resources if res_type == "device"]
        if not device_ids:
            return False, "Lab device not found in scenario resources."

        from litmussdk.devicehub.devices import _functions as dev_funcs

        try:
            current_device = dev_funcs.list_device_by_id(device_ids[0], le_connection=conn)
        except Exception as exc:
            return False, f"Could not query device: {exc}"

        if current_device.alias_topics:
            return (
                True,
                "Correct! Alias topics are now enabled on 'lab-plc-03'. "
                "The flow will now receive messages on the 'devicehub/alias/lab-plc-03/#' "
                "topic. Key takeaway: alias topics are a device-level toggle — they don't "
                "affect raw topic delivery, only the human-readable alias namespace.",
            )
        else:
            return (
                False,
                "Alias topics are still disabled on 'lab-plc-03'. "
                "Open DeviceHub, go to the device settings, and enable the "
                "'Alias Topics' option.",
            )

    def teardown(self, conn: LEConnection, state: ScenarioState) -> None:
        """Delete the lab device."""
        device_ids = [res_id for res_type, res_id in state.resources if res_type == "device"]
        safe_delete_devices_by_ids(conn, device_ids)
        logger.info("[DH-03] Teardown complete.")
