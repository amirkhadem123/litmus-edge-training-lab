"""
litmus_utils.py — Low-level helpers for interacting with Litmus Edge.

This module contains utility functions that either:
  (a) Wrap SDK operations that need extra error handling, or
  (b) Make raw HTTP requests for endpoints the SDK does not expose directly
      (currently: Prometheus metrics for device status).

WHY RAW HTTP FOR DEVICE STATUS?
  The Litmus SDK's list_devices() GraphQL query does not return a Status or
  State field — it only returns configuration data (name, driver, properties).
  The only way to know if a device is currently running or stopped is to read
  the Prometheus metrics that DeviceHub exposes at GET /devicehub/metrics.
  These metrics are plain text in the standard Prometheus format, so we fetch
  them with the requests library and parse the relevant line ourselves.

  Example of the metric line we look for:
    loopedge_dh_device_state{alias="lab-machine-01", ...} 1
  Where 1 = running and 0 = stopped/error.

ABOUT LEConnection.get_url_headers():
  The SDK's LEConnection class has a method get_url_headers() that returns a
  tuple of (base_url, auth_headers). We use this to build authenticated HTTP
  requests without duplicating the OAuth2 token logic ourselves.
"""

import re
import requests
import logging

from litmussdk.devicehub.record import load_dh_record
from litmussdk.utils.conn import LEConnection


logger = logging.getLogger(__name__)


def get_driver_id_by_name(conn: LEConnection, driver_name: str) -> str:
    """
    Look up a DeviceHub driver's UUID by its display name.

    The SDK's Device model expects a driver UUID (e.g. '5BC98836-...' for the
    Generator driver), not a human-readable name string. This helper loads the
    cached driver record and searches by name, returning the UUID to pass as the
    'driver' argument when constructing a Device object.

    Args:
        conn:        An authenticated LEConnection (used to load the cached record).
        driver_name: The driver's display name exactly as shown in Litmus Edge,
                     e.g. "Generator".

    Returns:
        The driver's UUID string (uppercase).

    Raises:
        ValueError: if no driver with that name exists in the cached record.
    """
    record = load_dh_record(conn)
    for driver in record._drivers.values():
        if driver.name.lower() == driver_name.lower():
            return driver.id
    raise ValueError(
        f"No driver named '{driver_name}' found in the DeviceHub record. "
        f"Available names: {[d.name for d in record._drivers.values()]}"
    )


def get_device_running_state(conn: LEConnection, device_name: str) -> bool | None:
    """
    Check whether a named device is currently running by reading DeviceHub's
    Prometheus metrics endpoint.

    The Litmus SDK's GraphQL API does not expose device run/stop state, so we
    fall back to the Prometheus metrics endpoint (/devicehub/metrics) which
    DeviceHub exposes for monitoring. We look for a metric line whose 'alias'
    label matches the device name.

    Args:
        conn:        An authenticated LEConnection.
        device_name: The exact name (alias) of the device as configured in
                     DeviceHub (e.g. "lab-machine-01").

    Returns:
        True  if the device is found and its state metric equals 1 (running).
        False if the device is found and its state metric equals 0 (stopped).
        None  if no matching metric line is found (device may not exist yet,
              or the metric name differs on this version of Litmus Edge).
    """
    base_url, headers = conn.get_url_headers()
    url = f"{base_url}/devicehub/metrics"

    try:
        response = requests.get(
            url,
            headers=headers,
            verify=conn.VALIDATE_CERTIFICATE,
            timeout=conn.TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Failed to fetch DeviceHub Prometheus metrics: %s", exc)
        return None

    metrics_text = response.text

    # Prometheus metric lines look like:
    #   loopedge_dh_device_state{alias="lab-machine-01",id="some-uuid",...} 1
    #
    # We search for any line that:
    #   1. Contains "device_state" (the metric name)
    #   2. Contains the device name inside alias="..."
    #   3. Ends with a numeric value (0 or 1)
    #
    # We use a regex that is deliberately loose on the label order and
    # surrounding content so it works across minor Litmus Edge version changes.
    pattern = re.compile(
        r'[^\n]*device_state\{[^\}]*alias="'
        + re.escape(device_name)
        + r'"[^\}]*\}\s+([\d.]+)',
        re.IGNORECASE,
    )
    match = pattern.search(metrics_text)

    if match:
        value = float(match.group(1))
        logger.debug(
            "Device '%s' state metric value: %s", device_name, value
        )
        return value == 1.0

    # Try the reverse label order (alias might appear in a different position)
    pattern_rev = re.compile(
        r'[^\n]*device_state\{[^\}]*"'
        + re.escape(device_name)
        + r'"[^\}]*\}\s+([\d.]+)',
        re.IGNORECASE,
    )
    match_rev = pattern_rev.search(metrics_text)
    if match_rev:
        value = float(match_rev.group(1))
        return value == 1.0

    logger.warning(
        "No device_state metric found for device '%s'. "
        "The device may not exist yet or the metric name has changed.",
        device_name,
    )
    return None


def get_service_active_state(conn: LEConnection, service_name: str) -> str | None:
    """
    Return the systemd ActiveState string for a named Litmus Edge service.

    Litmus Edge exposes a REST endpoint for querying the status of its internal
    services (which are managed by systemd). This function fetches that status
    and returns the 'ActiveState' field, which will be one of:
      "active"        — the service is running normally
      "inactive"      — the service is stopped
      "failed"        — the service crashed or failed to start
      "activating"    — the service is in the process of starting

    Args:
        conn:         An authenticated LEConnection.
        service_name: The systemd service name, e.g. "loopedge-analytics2".

    Returns:
        The ActiveState string if the call succeeds, or None on failure.
    """
    base_url, headers = conn.get_url_headers()
    url = f"{base_url}/dm/services/{service_name}"

    try:
        response = requests.get(
            url,
            headers=headers,
            verify=conn.VALIDATE_CERTIFICATE,
            timeout=conn.TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        # The response is a dict that contains systemd unit properties.
        # We look for ActiveState first, then fall back to common variants.
        state = (
            data.get("ActiveState")
            or data.get("active_state")
            or data.get("status")
        )
        return state
    except requests.RequestException as exc:
        logger.warning(
            "Failed to fetch service status for '%s': %s", service_name, exc
        )
        return None
    except (ValueError, KeyError) as exc:
        logger.warning(
            "Unexpected response format for service '%s': %s", service_name, exc
        )
        return None


def safe_delete_device_by_name(conn: LEConnection, device_name: str) -> None:
    """
    Delete a device by display name if it exists, silently ignoring errors.

    Used at the start of setup() to clean up any device left over from a
    previous partial run (e.g. after a container restart mid-scenario).

    Args:
        conn:        An authenticated LEConnection.
        device_name: The device's display name (e.g. "lab-machine-01").
    """
    from litmussdk.devicehub import devices  # local import avoids circular refs

    try:
        all_devices = devices.list_devices(le_connection=conn)
        matching = [d for d in all_devices if d.name == device_name]
        if matching:
            ids = [d.id for d in matching if d.id]
            devices.delete_devices_by_ids(ids, le_connection=conn)
            logger.info("Pre-setup cleanup: deleted existing device '%s' (ids: %s)", device_name, ids)
    except Exception as exc:
        logger.warning("Pre-setup cleanup failed for device '%s': %s", device_name, exc)


def safe_delete_devices_by_ids(conn: LEConnection, device_ids: list[str]) -> None:
    """
    Delete a list of devices by ID, silently ignoring errors for devices that
    no longer exist (e.g. because the learner already deleted them).

    This is used in teardown() so that teardown is always safe to call even if
    the learner has already cleaned up some resources themselves.

    Args:
        conn:       An authenticated LEConnection.
        device_ids: List of DeviceHub device UUID strings to delete.
    """
    if not device_ids:
        return
    from litmussdk.devicehub import devices  # local import avoids circular refs

    try:
        devices.delete_devices_by_ids(device_ids, le_connection=conn)
        logger.info("Deleted devices: %s", device_ids)
    except Exception as exc:
        # Log but do not re-raise — teardown must not crash
        logger.warning("Could not delete devices %s: %s", device_ids, exc)


def safe_delete_user(conn: LEConnection, username: str) -> None:
    """
    Delete a user account by username, ignoring errors if it doesn't exist.

    Args:
        conn:     An authenticated LEConnection.
        username: The username string (login name) of the user to delete.
    """
    from litmussdk.system import users  # local import avoids circular refs

    try:
        users.delete_user(username, le_connection=conn)
        logger.info("Deleted user: %s", username)
    except Exception as exc:
        logger.warning("Could not delete user '%s': %s", username, exc)


def safe_delete_user_group(conn: LEConnection, group_id: str) -> None:
    """
    Delete a user group by its ID, ignoring errors if it doesn't exist.

    Args:
        conn:     An authenticated LEConnection.
        group_id: The group ID string returned when the group was created.
    """
    from litmussdk.system import users  # local import avoids circular refs

    try:
        users.delete_user_group(group_id, le_connection=conn)
        logger.info("Deleted user group: %s", group_id)
    except Exception as exc:
        logger.warning("Could not delete user group '%s': %s", group_id, exc)


def safe_delete_user_role(conn: LEConnection, role_id: str) -> None:
    """
    Delete a user role by its ID, ignoring errors if it doesn't exist.

    Args:
        conn:    An authenticated LEConnection.
        role_id: The role ID string returned when the role was created.
    """
    from litmussdk.system import users  # local import avoids circular refs

    try:
        users.delete_user_role(role_id, le_connection=conn)
        logger.info("Deleted user role: %s", role_id)
    except Exception as exc:
        logger.warning("Could not delete user role '%s': %s", role_id, exc)


