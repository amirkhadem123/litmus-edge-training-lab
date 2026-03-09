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
  anything." The fix is to assign them to a group whose role includes the
  correct service-level permissions.

HOW THE BREAK WORKS:
  setup() creates:
    1. A role called 'lab-viewer-only' with only read-level ('View') permissions.
    2. A group called 'lab-restricted-group' assigned that role.
    3. A user called 'lab-user-bob' placed in that group.

  The learner must update the user's group (or the role's permissions) so that
  'lab-user-bob' has at least DeviceHub 'Modify' access.

HOW VALIDATION WORKS:
  We check the permissions on the role assigned to the user's group.
  Specifically, we look for 'dh' permissions that include 'Modify'.

TEARDOWN:
  Delete the user, the group, and the role — in that order, because
  Litmus Edge may reject deletion of a group that still has users.

RESOURCE TRACKING:
  state.resources stores tuples in the order they were created:
    ("role", role_id), ("group", group_id), ("user", username)
"""

import logging

from litmussdk.system import users
from litmussdk.utils.conn import LEConnection

from scenarios.base import BaseScenario, ScenarioState
from litmus_utils import safe_delete_sys_resources_by_name, safe_delete_user, safe_delete_user_group, safe_delete_user_role


logger = logging.getLogger(__name__)

LAB_ROLE_NAME = "lab-viewer-only"
LAB_GROUP_NAME = "lab-restricted-group"
LAB_USERNAME = "lab-user-bob"
LAB_USER_PASSWORD = "LabPassword123!"   # meets typical complexity requirements


class PermissionsScenario(BaseScenario):
    """
    SYS-01: A user is created with only Viewer permissions.
    The learner must update their role or group to grant DeviceHub access.
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
        "Check the role assigned to the group 'lab-restricted-group'. The role "
        "likely has only 'View' permissions. Update it to include 'Modify' for "
        "DeviceHub (dh), or move the user to a group with the Administrator role.",
    ]

    timeout_minutes = 30

    def setup(self, conn: LEConnection, state: ScenarioState) -> None:
        """
        Create a role with Viewer-only permissions, a group with that role,
        and a user in that group.

        Pre-cleanup is run first to delete any role/group/user left over from
        a previous partial run (e.g. after a container restart mid-scenario).
        """
        logger.info("[SYS-01] Running setup: creating restricted user '%s'", LAB_USERNAME)
        safe_delete_sys_resources_by_name(conn, LAB_USERNAME, LAB_GROUP_NAME, LAB_ROLE_NAME)

        # Step 1: Create a role with only read ('View') access.
        # The 'dh' permission covers DeviceHub. 'access' covers the general UI.
        # We intentionally omit 'Modify' from 'dh' to create the problem.
        role_result = users.add_user_role(
            name=LAB_ROLE_NAME,
            le_connection=conn,
            access=["View"],
            dh=["View"],          # DeviceHub: read-only — THE BUG
            events=["View"],
            sysinfo=["View"],
        )
        role_id = role_result.get("id") or role_result.get("ID", LAB_ROLE_NAME)
        state.resources.append(("role", role_id))
        logger.info("[SYS-01] Created role '%s' (id: %s)", LAB_ROLE_NAME, role_id)

        # Step 2: Create a group and assign the restrictive role to it.
        group_result = users.create_user_group(
            name=LAB_GROUP_NAME,
            le_connection=conn,
        )
        group_id = group_result.get("id") or group_result.get("ID", LAB_GROUP_NAME)
        state.resources.append(("group", group_id))
        logger.info("[SYS-01] Created group '%s' (id: %s)", LAB_GROUP_NAME, group_id)

        # Attach the role to the group
        users.update_user_group_name(
            user_group=group_id,
            name=LAB_GROUP_NAME,
            le_connection=conn,
        )

        # Step 3: Create the user and add them to the restricted group.
        users.create_user(
            username=LAB_USERNAME,
            password=LAB_USER_PASSWORD,
            le_connection=conn,
        )
        state.resources.append(("user", LAB_USERNAME))
        logger.info("[SYS-01] Created user '%s'", LAB_USERNAME)

        users.add_users_to_group(
            user_group_id=group_id,
            usernames=[LAB_USERNAME],
            le_connection=conn,
        )
        logger.info("[SYS-01] Added user '%s' to group '%s'. Setup complete.", LAB_USERNAME, LAB_GROUP_NAME)

    def validate(self, conn: LEConnection, state: ScenarioState) -> tuple[bool, str]:
        """
        Check whether the user's current permissions include DeviceHub Modify.

        We look up the user's group, get the role(s) on that group, and check
        for 'dh' permissions containing 'Modify'.
        """
        try:
            # Get current user details to find their group
            all_groups = users.get_user_groups(le_connection=conn)
        except Exception as exc:
            return False, f"Could not query user groups: {exc}"

        # Find any group that contains lab-user-bob and check its permissions
        for group in all_groups if isinstance(all_groups, list) else all_groups.get("groups", []):
            group_id = group.get("id") or group.get("ID", "")
            group_name = group.get("name") or group.get("Name", "")

            try:
                details = users.get_user_group_details(group_id, le_connection=conn)
            except Exception:
                continue

            # Check if this group contains our lab user
            member_names = [
                u.get("username") or u.get("Username", "")
                for u in (details.get("users") or details.get("Users") or [])
            ]
            if LAB_USERNAME not in member_names:
                continue

            # This group contains lab-user-bob — check the roles' permissions
            role_list = details.get("roles") or details.get("Roles") or []
            for role in role_list:
                permissions = role.get("permissions") or role.get("Permissions") or {}
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
            "Go to System > Access Control and update the role or group to include "
            "'Modify' access for DeviceHub.",
        )

    def teardown(self, conn: LEConnection, state: ScenarioState) -> None:
        """
        Delete user, group, and role in the correct order.
        Litmus Edge requires the user to be removed from the group before
        the group can be deleted.
        """
        # Collect IDs by type from the resources list
        user_names = [res_id for res_type, res_id in state.resources if res_type == "user"]
        group_ids = [res_id for res_type, res_id in state.resources if res_type == "group"]
        role_ids = [res_id for res_type, res_id in state.resources if res_type == "role"]

        for username in user_names:
            safe_delete_user(conn, username)
        for group_id in group_ids:
            safe_delete_user_group(conn, group_id)
        for role_id in role_ids:
            safe_delete_user_role(conn, role_id)

        logger.info("[SYS-01] Teardown complete.")
