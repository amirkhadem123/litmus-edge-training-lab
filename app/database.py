"""
database.py — SQLite persistence layer for Litmus Lab v2.

Schema:
  trainees           — one row per trainee (name-based identity)
  attempts           — one training attempt per scenario per trainee
  messages           — conversation thread for each attempt
  grades             — dimensional grading result per attempt
  checkpoint_progress — denormalised checkpoint status per trainee (fast dashboard reads)
  settings           — AI provider configuration (key/value)

All functions open and close connections promptly via context managers.
WAL mode enabled for safe concurrent access.
DB path defaults to project root; override with LITMUS_DATA_DIR env var.
"""

import json
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("LITMUS_DATA_DIR", ".")) / "litmus_lab.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create tables. Drops legacy v1 tables (tickets, comments) if present."""
    with _connect() as conn:
        # Remove v1 tables — no production data to preserve
        conn.executescript("""
            DROP TABLE IF EXISTS comments;
            DROP TABLE IF EXISTS tickets;
        """)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trainees (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS attempts (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                trainee_id       INTEGER NOT NULL REFERENCES trainees(id),
                scenario_id      TEXT    NOT NULL,
                checkpoint       INTEGER,
                mode             TEXT    NOT NULL,
                status           TEXT    NOT NULL DEFAULT 'in_progress',
                attempt_number   INTEGER NOT NULL DEFAULT 1,
                trainee_action   TEXT,
                urgency_injected INTEGER NOT NULL DEFAULT 0,
                created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
                submitted_at     DATETIME
            );

            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id INTEGER NOT NULL REFERENCES attempts(id),
                sender     TEXT    NOT NULL,
                content    TEXT    NOT NULL,
                sequence   INTEGER NOT NULL,
                timestamp  DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS grades (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id        INTEGER NOT NULL REFERENCES attempts(id) UNIQUE,
                total_score       INTEGER NOT NULL,
                passed            INTEGER NOT NULL,
                expected_action   TEXT    NOT NULL,
                trainee_action    TEXT    NOT NULL,
                correct_direction INTEGER NOT NULL,
                dimension_scores  TEXT    NOT NULL,
                overall_feedback  TEXT    NOT NULL,
                raw_response      TEXT,
                created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS checkpoint_progress (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                trainee_id    INTEGER NOT NULL REFERENCES trainees(id),
                checkpoint    INTEGER NOT NULL,
                status        TEXT    NOT NULL DEFAULT 'locked',
                best_score    INTEGER,
                attempts_used INTEGER NOT NULL DEFAULT 0,
                unlocked_at   DATETIME,
                updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(trainee_id, checkpoint)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)


# ── Trainee operations ────────────────────────────────────────────────────────

def get_trainee_by_name(name: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM trainees WHERE LOWER(name) = LOWER(?)", (name,)
        ).fetchone()
        return dict(row) if row else None


def create_trainee(name: str) -> int:
    with _connect() as conn:
        cur = conn.execute("INSERT INTO trainees (name) VALUES (?)", (name,))
        return cur.lastrowid


def get_trainee(trainee_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM trainees WHERE id = ?", (trainee_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_trainees() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM trainees ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ── Attempt operations ────────────────────────────────────────────────────────

def create_attempt(
    trainee_id: int,
    scenario_id: str,
    checkpoint: int | None,
    mode: str,
    attempt_number: int = 1,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO attempts
               (trainee_id, scenario_id, checkpoint, mode, attempt_number)
               VALUES (?, ?, ?, ?, ?)""",
            (trainee_id, scenario_id, checkpoint, mode, attempt_number),
        )
        return cur.lastrowid


def get_attempt(attempt_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM attempts WHERE id = ?", (attempt_id,)
        ).fetchone()
        return dict(row) if row else None


def get_active_attempt(trainee_id: int, scenario_id: str) -> dict | None:
    """Return an in-progress attempt for this trainee+scenario, or None."""
    with _connect() as conn:
        row = conn.execute(
            """SELECT * FROM attempts
               WHERE trainee_id = ? AND scenario_id = ? AND status = 'in_progress'
               ORDER BY created_at DESC LIMIT 1""",
            (trainee_id, scenario_id),
        ).fetchone()
        return dict(row) if row else None


def get_attempts_for_trainee(trainee_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM attempts WHERE trainee_id = ? ORDER BY created_at DESC",
            (trainee_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def submit_attempt(attempt_id: int, trainee_action: str) -> None:
    with _connect() as conn:
        conn.execute(
            """UPDATE attempts
               SET status = 'submitted', trainee_action = ?, submitted_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (trainee_action, attempt_id),
        )


def mark_attempt_graded(attempt_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE attempts SET status = 'graded' WHERE id = ?", (attempt_id,)
        )


def mark_attempt_grade_failed(attempt_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE attempts SET status = 'grade_failed' WHERE id = ?", (attempt_id,)
        )


def set_urgency_injected(attempt_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE attempts SET urgency_injected = 1 WHERE id = ?", (attempt_id,)
        )


# ── Message operations ────────────────────────────────────────────────────────

def add_message(attempt_id: int, sender: str, content: str) -> int:
    with _connect() as conn:
        seq = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM messages WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO messages (attempt_id, sender, content, sequence) VALUES (?, ?, ?, ?)",
            (attempt_id, sender, content, seq),
        )
        return cur.lastrowid


def get_messages(attempt_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE attempt_id = ? ORDER BY sequence ASC",
            (attempt_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Grade operations ──────────────────────────────────────────────────────────

def create_grade(
    attempt_id: int,
    total_score: int,
    passed: bool,
    expected_action: str,
    trainee_action: str,
    correct_direction: bool,
    dimension_scores: list[dict],
    overall_feedback: str,
    raw_response: str | None = None,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO grades
               (attempt_id, total_score, passed, expected_action, trainee_action,
                correct_direction, dimension_scores, overall_feedback, raw_response)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                attempt_id,
                total_score,
                int(passed),
                expected_action,
                trainee_action,
                int(correct_direction),
                json.dumps(dimension_scores),
                overall_feedback,
                raw_response,
            ),
        )
        return cur.lastrowid


def get_grade(attempt_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM grades WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
        if not row:
            return None
        g = dict(row)
        g["dimension_scores"] = json.loads(g["dimension_scores"])
        return g


# ── Checkpoint progress operations ────────────────────────────────────────────

def init_checkpoint_progress(trainee_id: int) -> None:
    """Create progress rows for checkpoints 1–3. CP1 available, 2 and 3 locked."""
    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO checkpoint_progress (trainee_id, checkpoint, status, unlocked_at)
               VALUES (?, 1, 'available', CURRENT_TIMESTAMP)""",
            (trainee_id,),
        )
        for cp in (2, 3):
            conn.execute(
                """INSERT OR IGNORE INTO checkpoint_progress (trainee_id, checkpoint, status)
                   VALUES (?, ?, 'locked')""",
                (trainee_id, cp),
            )


def get_checkpoint_progress(trainee_id: int) -> dict[int, dict]:
    """Return {1: {status, best_score, attempts_used}, 2: ..., 3: ...}"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM checkpoint_progress WHERE trainee_id = ? ORDER BY checkpoint",
            (trainee_id,),
        ).fetchall()
        return {row["checkpoint"]: dict(row) for row in rows}


def update_checkpoint_after_grade(
    trainee_id: int,
    checkpoint: int,
    passed: bool,
    score: int,
) -> None:
    """Update checkpoint_progress and unlock next checkpoint if passed."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM checkpoint_progress WHERE trainee_id = ? AND checkpoint = ?",
            (trainee_id, checkpoint),
        ).fetchone()
        if not row:
            return

        attempts_used = row["attempts_used"] + 1
        best_score = max(score, row["best_score"] or 0)

        if passed:
            new_status = "passed"
        elif attempts_used >= 2:
            new_status = "failed_no_reattempt"
        else:
            new_status = "failed_reattempt_available"

        conn.execute(
            """UPDATE checkpoint_progress
               SET status = ?, best_score = ?, attempts_used = ?, updated_at = CURRENT_TIMESTAMP
               WHERE trainee_id = ? AND checkpoint = ?""",
            (new_status, best_score, attempts_used, trainee_id, checkpoint),
        )

        # Unlock next checkpoint if this one was just passed
        if passed and checkpoint < 3:
            conn.execute(
                """UPDATE checkpoint_progress
                   SET status = 'available', unlocked_at = CURRENT_TIMESTAMP,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE trainee_id = ? AND checkpoint = ? AND status = 'locked'""",
                (trainee_id, checkpoint + 1),
            )


# ── Settings operations ───────────────────────────────────────────────────────

def get_setting(key: str) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
