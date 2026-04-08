"""
database.py — SQLite persistence layer for the Litmus Lab ticket simulation.

Schema:
  tickets  — one row per training session (scenario + trainee)
  comments — the full conversation thread for each ticket

All functions use a context manager so connections are always closed promptly.
The DB file (litmus_lab.db) lives in the project root and is gitignored.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path("litmus_lab.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # lets us access columns by name
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables if they don't already exist. Safe to call on every startup."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tickets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                scenario_id TEXT    NOT NULL,
                trainee     TEXT    NOT NULL,
                status      TEXT    NOT NULL DEFAULT 'open',
                escalated   INTEGER NOT NULL DEFAULT 0,
                score       INTEGER,                          -- NULL until graded
                created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                solved_at   TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS comments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id   INTEGER NOT NULL REFERENCES tickets(id),
                body        TEXT    NOT NULL,
                author_type TEXT    NOT NULL,   -- 'customer' | 'trainee' | 'system'
                is_internal INTEGER NOT NULL DEFAULT 0,  -- 1 = internal note (grade)
                created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)


# ── Ticket operations ─────────────────────────────────────────────────────────

def create_ticket(scenario_id: str, trainee: str) -> int:
    """Insert a new ticket and return its auto-generated ID."""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO tickets (scenario_id, trainee) VALUES (?, ?)",
            (scenario_id, trainee),
        )
        return cur.lastrowid


def get_ticket(ticket_id: int) -> dict | None:
    """Return a single ticket as a dict, or None if not found."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_tickets() -> list[dict]:
    """Return all tickets, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tickets ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def set_escalated(ticket_id: int, value: bool) -> None:
    """Update the escalation flag for a ticket."""
    with _connect() as conn:
        conn.execute(
            "UPDATE tickets SET escalated = ? WHERE id = ?",
            (int(value), ticket_id),
        )


def solve_ticket(ticket_id: int, score: int | None = None) -> None:
    """Mark a ticket as solved and record the grade score."""
    with _connect() as conn:
        conn.execute(
            """UPDATE tickets
               SET status = 'solved', solved_at = CURRENT_TIMESTAMP, score = ?
               WHERE id = ?""",
            (score, ticket_id),
        )


# ── Comment operations ────────────────────────────────────────────────────────

def add_comment(
    ticket_id: int,
    body: str,
    author_type: str,
    is_internal: bool = False,
) -> int:
    """Append a comment to the ticket thread. Returns the new comment ID."""
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO comments (ticket_id, body, author_type, is_internal)
               VALUES (?, ?, ?, ?)""",
            (ticket_id, body, author_type, int(is_internal)),
        )
        return cur.lastrowid


def get_comments(ticket_id: int) -> list[dict]:
    """Return all comments for a ticket in chronological order."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM comments WHERE ticket_id = ? ORDER BY created_at ASC",
            (ticket_id,),
        ).fetchall()
        return [dict(r) for r in rows]
