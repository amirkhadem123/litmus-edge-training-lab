"""
Scenario SYS-01: The Locked-Out Engineer
Category: System | Difficulty: Beginner

WHAT THIS SCENARIO TEACHES:
  Litmus Edge uses a Role-Based Access Control (RBAC) system. The hierarchy is:

    Permissions → bundled into Roles → assigned to Groups → applied to Users

  A user who belongs only to a group with "Viewer" permissions can log in and
  see dashboards, but cannot add, modify, or delete any configuration. They
  will see "Access Denied" or "Forbidden" errors when trying to perform write
  operations in DeviceHub or elsewhere.

  This is a common support ticket: "A new engineer can log in but can't do
  anything." The fix is to move the user into a group with the correct
  service-level permissions (e.g. the Administrators group).

HOW THE BREAK WORKS:
  setup() creates a user called 'lab-user-bob' and adds them to the built-in
  'Viewers' group, which has View-only permissions across all services including
  DeviceHub. No custom role or group is created.

  The learner must move 'lab-user-bob' to a group that includes DeviceHub
  'Modify' access (e.g. the Administrators group).

WHY NOT A CUSTOM ROLE/GROUP:
  Litmus Edge 4.0.x does not expose a stable REST endpoint for assigning a
  custom role to a custom group. The /auth/v3/groups/{id}/roles PUT endpoint
  returns 404 for any role assignment. The built-in system groups (Viewers,
  Administrators) already have stable role assignments, so this scenario uses
  the Viewers group directly.

HOW VALIDATION WORKS:
  We scan all groups for ones that contain 'lab-user-bob', then inspect the
  permissions of every role attached to those groups. If any role has 'Modify'
  in its 'dh' (DeviceHub) permissions, the scenario is solved.

TEARDOWN:
  Only the lab user needs to be deleted — no custom group or role was created.

RESOURCE TRACKING:
  state.resources: [("user", username)]
"""

import logging

from litmussdk.system import users
from litmussdk.utils.conn import LEConnection

from scenarios.base import BaseScenario, ScenarioState
from litmus_utils import safe_delete_user


logger = logging.getLogger(__name__)

# The built-in Viewers system group — has View-only permissions on all services
# including DeviceHub. Guaranteed to exist on every Litmus Edge instance.
VIEWERS_GROUP_ID = "default_viewers_group"

LAB_USERNAME = "lab-user-bob"
LAB_USER_PASSWORD = "LabPassword123!"   # meets typical complexity requirements


class PermissionsScenario(BaseScenario):
    """
    SYS-01: A user is created and placed in the Viewers group (View-only).
    The learner must move them to a group with DeviceHub Modify access.
    """

    id = "sys-01"
    title = "The Locked-Out Engineer"
    category = "System"
    difficulty = "Beginner"

    symptom = (
        "A new support engineer's account ('lab-user-bob') was set up today. "
        "They can log into Litmus Edge without any problem, but every time they "
        "try to add a device, edit a tag, or make any change in DeviceHub, they "
        "get an 'Access Denied' or 'Forbidden' error. Read-only views work fine."
    )

    learning_objective = (
        "Understand Litmus Edge's RBAC model (Roles → Groups → Users) and know "
        "how to grant a user the correct service-level permissions."
    )

    hints = [
        "The user can log in, which means their account is active and their "
        "password is correct. The problem is about *what they are allowed to do*, "
        "not about their account status.",
        "Go to System > Access Control in the Litmus Edge UI. Look at the user "
        "'lab-user-bob' and check which group they belong to.",
        "The user is in the 'Viewers' group which has read-only permissions. "
        "Move them to the 'Administrators' group, or to any group whose role "
        "includes DeviceHub 'Modify' access.",
    ]

    timeout_minutes = 30

    def setup(self, conn: LEConnection, state: ScenarioState) -> None:
        """
        Create 'lab-user-bob' and add them to the built-in Viewers group.

        The Viewers group already exists on every Litmus Edge instance and has
        View-only permissions across all services. No custom role or group is
        needed — the user's restricted access comes from being in this group.

        Pre-cleanup deletes any previously orphaned user with this username
        before creating a fresh one.
        """
        logger.info("[SYS-01] Running setup: creating restricted user '%s'", LAB_USERNAME)

        # Clean up any leftover user from a previous partial run
        safe_delete_user(conn, LAB_USERNAME)

        # Create the lab user. All four positional arguments are required by
        # this version of the SDK (first_name, last_name, username, password).
        users.create_user(
            first_name="Bob",
            last_name="Engineer",
            username=LAB_USERNAME,
            password=LAB_USER_PASSWORD,
            le_connection=conn,
        )
        state.resources.append(("user", LAB_USERNAME))
        logger.info("[SYS-01] Created user '%s'", LAB_USERNAME)

        # Add the user to the built-in Viewers group.
        # SDK parameter is users_to_be_added (list of username strings).
        users.add_users_to_group(
            user_group_id=VIEWERS_GROUP_ID,
            users_to_be_added=[LAB_USERNAME],
            le_connection=conn,
        )
        logger.info(
            "[SYS-01] Added '%s' to Viewers group. Setup complete.", LAB_USERNAME
        )

    def validate(self, conn: LEConnection, state: ScenarioState) -> tuple[bool, str]:
        """
        Check whether the user's current groups include DeviceHub Modify.

        Scans all groups for ones containing 'lab-user-bob', then checks
        the permissions of every role on those groups.
        """
        try:
            all_groups = users.get_user_groups(le_connection=conn)
        except Exception as exc:
            return False, f"Could not query user groups: {exc}"

        for group in all_groups:
            group_id = group.get("groupId") or group.get("id") or ""
            group_name = group.get("groupName") or group.get("name") or ""

            try:
                details = users.get_user_group_details(group_id, le_connection=conn)
            except Exception:
                continue

            # Check if this group contains our lab user
            member_names = [
                u.get("username") or u.get("Username", "")
                for u in (details.get("users") or [])
            ]
            if LAB_USERNAME not in member_names:
                continue

            # This group contains lab-user-bob — check its roles for dh Modify
            for role in (details.get("roles") or []):
                role_id = role.get("roleId") or role.get("id") or ""
                if not role_id:
                    continue
                try:
                    base_url, headers = conn.get_url_headers()
                    import requests
                    r = requests.get(
                        f"{base_url}/auth/v3/roles/{role_id}",
                        headers=headers,
                        verify=conn.VALIDATE_CERTIFICATE,
                        timeout=conn.TIMEOUT_SECONDS,
                    )
                    r.raise_for_status()
                    permissions = r.json().get("permissions") or {}
                except Exception:
                    continue

                dh_perms = permissions.get("dh") or []
                if "Modify" in dh_perms:
                    return (
                        True,
                        f"Correct! 'lab-user-bob' now has DeviceHub Modify permissions "
                        f"via the group '{group_name}'. They can now add and edit devices. "
                        "Key takeaway: in Litmus Edge, permissions are granted through "
                        "Roles → Groups → Users. A user with only View access cannot "
                        "make any configuration changes.",
                    )

        return (
            False,
            "'lab-user-bob' still does not have DeviceHub Modify permissions. "
            "Go to System > Access Control and move the user to the Administrators "
            "group, or to any group whose role includes DeviceHub 'Modify' access.",
        )

    def teardown(self, conn: LEConnection, state: ScenarioState) -> None:
        """
        Delete the lab user. No custom group or role was created, so nothing
        else needs to be cleaned up.
        """
        user_names = [res_id for res_type, res_id in state.resources if res_type == "user"]
        for username in user_names:
            safe_delete_user(conn, username)
        logger.info("[SYS-01] Teardown complete.")
