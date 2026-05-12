"""
database.py — SQLite persistence layer for Litmus Lab v2.

Schema:
  trainees            — one row per user account (email + password_hash)
  trainee_settings    — per-user AI provider configuration
  attempts            — one training attempt per scenario per trainee
  messages            — conversation thread for each attempt
  grades              — dimensional grading result per attempt
  checkpoint_progress — denormalised checkpoint status per trainee (fast dashboard reads)

All functions open and close connections promptly via context managers.
WAL mode enabled for safe concurrent access.
DB path defaults to project root; override with LITMUS_DATA_DIR env var.
"""

import json
import os
import sqlite3
from pathlib import Path

import bcrypt

DB_PATH = Path(os.environ.get("LITMUS_DATA_DIR", ".")) / "litmus_lab.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create all tables. Migrates from name-only schema to email+password if needed."""
    with _connect() as conn:
        # Remove legacy v1 tables
        conn.executescript("""
            DROP TABLE IF EXISTS comments;
            DROP TABLE IF EXISTS tickets;
        """)

        # Detect if trainees table needs migration (old schema lacks email column)
        cursor = conn.execute("PRAGMA table_info(trainees)")
        columns = {row["name"] for row in cursor.fetchall()}
        if columns and "email" not in columns:
            # Old name-only schema — drop all tables for a clean slate
            conn.executescript("""
                DROP TABLE IF EXISTS checkpoint_progress;
                DROP TABLE IF EXISTS grades;
                DROP TABLE IF EXISTS messages;
                DROP TABLE IF EXISTS attempts;
                DROP TABLE IF EXISTS trainee_settings;
                DROP TABLE IF EXISTS trainees;
            """)

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trainees (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL,
                email         TEXT    NOT NULL,
                password_hash TEXT    NOT NULL,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_trainees_email
                ON trainees(email);

            CREATE TABLE IF NOT EXISTS trainee_settings (
                trainee_id  INTEGER PRIMARY KEY REFERENCES trainees(id),
                provider    TEXT NOT NULL DEFAULT 'claude',
                api_base    TEXT NOT NULL DEFAULT '',
                api_key     TEXT NOT NULL DEFAULT '',
                grade_model TEXT NOT NULL DEFAULT 'claude-haiku-4-5-20251001'
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
        """)


# ── Trainee auth operations ────────────────────────────────────────────────────

def hash_password(plaintext: str) -> str:
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()


def check_password(plaintext: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plaintext.encode(), hashed.encode())
    except Exception:
        return False


def get_trainee_by_email(email: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM trainees WHERE LOWER(email) = LOWER(?)", (email.strip(),)
        ).fetchone()
        return dict(row) if row else None


def create_trainee(name: str, email: str, password_hash: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO trainees (name, email, password_hash) VALUES (?, ?, ?)",
            (name.strip(), email.strip().lower(), password_hash),
        )
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


def admin_reset_password(trainee_id: int, new_password_hash: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE trainees SET password_hash = ? WHERE id = ?",
            (new_password_hash, trainee_id),
        )


# ── Per-user AI settings ──────────────────────────────────────────────────────

def init_trainee_settings(trainee_id: int) -> None:
    """Insert default settings row. Pre-populate from server env vars if set."""
    provider    = os.environ.get("LITMUS_PROVIDER", "claude")
    api_base    = os.environ.get("LITMUS_API_BASE", "")
    api_key     = os.environ.get("LITMUS_API_KEY", "")
    grade_model = os.environ.get("LITMUS_GRADE_MODEL", "claude-haiku-4-5-20251001")
    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO trainee_settings
               (trainee_id, provider, api_base, api_key, grade_model)
               VALUES (?, ?, ?, ?, ?)""",
            (trainee_id, provider, api_base, api_key, grade_model),
        )


def get_trainee_settings(trainee_id: int) -> dict:
    """Return the trainee's AI settings, falling back to env-var defaults."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM trainee_settings WHERE trainee_id = ?", (trainee_id,)
        ).fetchone()
    if row:
        return dict(row)
    # No row yet — return env-var defaults without writing to DB
    return {
        "trainee_id":  trainee_id,
        "provider":    os.environ.get("LITMUS_PROVIDER", "claude"),
        "api_base":    os.environ.get("LITMUS_API_BASE", ""),
        "api_key":     os.environ.get("LITMUS_API_KEY", ""),
        "grade_model": os.environ.get("LITMUS_GRADE_MODEL", "claude-haiku-4-5-20251001"),
    }


def set_trainee_setting(trainee_id: int, key: str, value: str) -> None:
    allowed = {"provider", "api_base", "api_key", "grade_model"}
    if key not in allowed:
        return
    with _connect() as conn:
        # Ensure row exists
        conn.execute(
            "INSERT OR IGNORE INTO trainee_settings (trainee_id) VALUES (?)",
            (trainee_id,),
        )
        conn.execute(
            f"UPDATE trainee_settings SET {key} = ? WHERE trainee_id = ?",
            (value, trainee_id),
        )


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


def reset_attempt_messages(attempt_id: int, initial_message: str) -> None:
    """Wipe all messages for an attempt and re-seed with the opening customer message.
    Also clears urgency_injected so urgency fires again on replay."""
    with _connect() as conn:
        conn.execute("DELETE FROM messages WHERE attempt_id = ?", (attempt_id,))
        conn.execute(
            "UPDATE attempts SET urgency_injected = 0 WHERE id = ?", (attempt_id,)
        )
        conn.execute(
            "INSERT INTO messages (attempt_id, sender, content, sequence) VALUES (?, ?, ?, 1)",
            (attempt_id, "customer", initial_message.strip()),
        )


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

        if passed and checkpoint < 3:
            conn.execute(
                """UPDATE checkpoint_progress
                   SET status = 'available', unlocked_at = CURRENT_TIMESTAMP,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE trainee_id = ? AND checkpoint = ? AND status = 'locked'""",
                (trainee_id, checkpoint + 1),
            )
