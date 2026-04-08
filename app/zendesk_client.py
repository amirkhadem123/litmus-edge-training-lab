"""
zendesk_client.py — Zendesk REST API wrapper for Litmus Lab.

Auth: HTTP Basic with email/token (email/token format required by Zendesk API).
Docs: https://developer.zendesk.com/api-reference/
"""

import base64
import os
from pathlib import Path

import requests


class ZendeskClient:
    def __init__(self):
        subdomain = os.environ["ZENDESK_SUBDOMAIN"]
        email = os.environ["ZENDESK_EMAIL"]
        token = os.environ["ZENDESK_API_TOKEN"]

        self.base_url = f"https://{subdomain}.zendesk.com/api/v2"
        # Zendesk token auth format: {email}/token:{api_token}
        credentials = f"{email}/token:{token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        self.headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str) -> dict:
        resp = requests.get(f"{self.base_url}{path}", headers=self.headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        resp = requests.post(
            f"{self.base_url}{path}", json=body, headers=self.headers, timeout=15
        )
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, body: dict) -> dict:
        resp = requests.put(
            f"{self.base_url}{path}", json=body, headers=self.headers, timeout=15
        )
        resp.raise_for_status()
        return resp.json()

    # ── Tickets ──────────────────────────────────────────────────────────────

    def create_ticket(
        self,
        subject: str,
        body: str,
        requester_name: str,
        requester_email: str,
        assignee_email: str,
        tags: list[str],
    ) -> dict:
        """Create a ticket and return the full ticket object."""
        payload = {
            "ticket": {
                "subject": subject,
                "comment": {"body": body, "public": False},
                "requester": {"name": requester_name, "email": requester_email},
                "assignee_id": self._get_user_id(assignee_email),
                "tags": tags,
                "status": "new",
            }
        }
        data = self._post("/tickets.json", payload)
        return data["ticket"]

    def get_ticket(self, ticket_id: int) -> dict:
        data = self._get(f"/tickets/{ticket_id}.json")
        return data["ticket"]

    def get_comments(self, ticket_id: int) -> list[dict]:
        data = self._get(f"/tickets/{ticket_id}/comments.json")
        return data["comments"]

    def add_tags(self, ticket_id: int, new_tags: list[str]) -> list[str]:
        """Add tags to a ticket without removing existing ones."""
        ticket = self.get_ticket(ticket_id)
        merged = list(set(ticket.get("tags", []) + new_tags))
        data = self._put(
            f"/tickets/{ticket_id}.json",
            {"ticket": {"tags": merged}},
        )
        return data["ticket"]["tags"]

    # ── Comments / Notes ─────────────────────────────────────────────────────

    def post_public_comment(self, ticket_id: int, body: str) -> dict:
        """Post a public comment (visible to the requester)."""
        data = self._put(
            f"/tickets/{ticket_id}.json",
            {"ticket": {"comment": {"body": body, "public": True}}},
        )
        return data["ticket"]

    def post_internal_note(self, ticket_id: int, body: str) -> dict:
        """Post an internal note (visible only to agents)."""
        data = self._put(
            f"/tickets/{ticket_id}.json",
            {"ticket": {"comment": {"body": body, "public": False}}},
        )
        return data["ticket"]

    # ── Attachments ──────────────────────────────────────────────────────────

    def upload_attachment(self, file_path: Path) -> str:
        """Upload a file and return the upload token."""
        url = f"{self.base_url}/uploads.json?filename={file_path.name}"
        # Attachment upload uses a different content-type — build headers manually
        upload_headers = {
            "Authorization": self.headers["Authorization"],
            "Content-Type": "application/octet-stream",
        }
        with open(file_path, "rb") as f:
            resp = requests.post(url, data=f, headers=upload_headers, timeout=30)
        resp.raise_for_status()
        return resp.json()["upload"]["token"]

    # ── Search / Lookup ──────────────────────────────────────────────────────

    def search_tickets(self, query: str) -> list[dict]:
        """Search tickets using Zendesk query syntax."""
        data = self._get(f"/search.json?query={requests.utils.quote(query)}")
        return data.get("results", [])

    def _get_user_id(self, email: str) -> int:
        """Look up a user's numeric ID by email."""
        data = self._get(f"/users/search.json?query=email:{requests.utils.quote(email)}")
        users = data.get("results", [])
        if not users:
            raise ValueError(f"No Zendesk user found with email: {email}")
        return users[0]["id"]
