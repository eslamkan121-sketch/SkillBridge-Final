"""SQLite database setup and connection management.

Stores five record types: students, companies, roles, skills, assessment_attempts.
Uses Python's built-in sqlite3 module against a local file. A test override allows
in-memory databases for unit tests.
"""
import os
import sqlite3
import threading
from contextlib import contextmanager

DB_PATH = os.environ.get("SKILLBRIDGE_DB", os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skillbridge.db"
))

_override_conn = None
_local = threading.local()


def set_db_for_test(conn=None):
    """Point the database layer at a custom connection (e.g. in-memory for tests)."""
    global _override_conn
    _override_conn = conn


def _connect():
    """Return a SQLite connection.

    FastAPI runs requests on a threadpool, so concurrent requests execute on different
    threads. sqlite3 connections are not safe to share across threads (doing so causes
    `sqlite3.InterfaceError: bad parameter or other API misuse`). We therefore keep one
    open connection per thread: each thread gets its own connection, and nested
    get_cursor() blocks on the same thread reuse it (so uncommitted writes remain
    visible to reads within that request).
    """
    if _override_conn is not None:
        return _override_conn
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _local.conn = conn
    return conn


def get_connection():
    return _connect()


@contextmanager
def get_cursor():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    # The connection is per-thread (or the test override), so it is never closed here.


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('Student','Company','University Admin')),
    display_name TEXT NOT NULL,
    password_hash TEXT,
    password_salt TEXT,
    auth_provider TEXT NOT NULL DEFAULT 'local',
    google_sub TEXT,
    verified INTEGER NOT NULL DEFAULT 0,
    country TEXT,
    university TEXT,
    location TEXT,
    education_level TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS password_resets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS google_registrations (
    google_sub TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS universities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    country TEXT NOT NULL,
    name TEXT NOT NULL,
    UNIQUE(country, name)
);

CREATE TABLE IF NOT EXISTS cities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    country TEXT NOT NULL,
    name TEXT NOT NULL,
    UNIQUE(country, name)
);

CREATE TABLE IF NOT EXISTS email_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    university TEXT,
    target_role_id INTEGER REFERENCES roles(id) ON DELETE SET NULL,
    cv_filename TEXT,
    cohort_confirmed INTEGER NOT NULL DEFAULT 0,
    share_public INTEGER NOT NULL DEFAULT 0,
    education_level TEXT
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    industry TEXT NOT NULL,
    location TEXT
);

CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    is_reference INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'company',
    external_id TEXT
);

CREATE TABLE IF NOT EXISTS role_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    required_level TEXT NOT NULL CHECK(required_level IN ('Beginner','Intermediate','Advanced')),
    skill_kind TEXT NOT NULL DEFAULT 'essential',
    UNIQUE(role_id, skill_id)
);

CREATE TABLE IF NOT EXISTS self_reported_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    level TEXT NOT NULL CHECK(level IN ('Beginner','Intermediate','Advanced')),
    source TEXT NOT NULL DEFAULT 'cv',
    evidence TEXT,
    UNIQUE(student_id, skill_id)
);

CREATE TABLE IF NOT EXISTS verified_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    level TEXT NOT NULL CHECK(level IN ('Beginner','Intermediate','Advanced')),
    verified_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(student_id, skill_id)
);

CREATE TABLE IF NOT EXISTS learning_path_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    explanation TEXT,
    practice_exercise TEXT,
    mini_project TEXT,
    resources TEXT,
    roadmap TEXT,
    progress TEXT,
    generated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(student_id, skill_id)
);

CREATE TABLE IF NOT EXISTS tutor_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    tutor_id TEXT CHECK(tutor_id IN ('nova','axel','sage','vex')),
    skill_id INTEGER REFERENCES skills(id) ON DELETE SET NULL,
    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS assessment_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    questions TEXT NOT NULL,
    answers TEXT NOT NULL,
    score REAL NOT NULL,
    passed INTEGER NOT NULL DEFAULT 0,
    flags TEXT NOT NULL DEFAULT '[]',
    per_question TEXT,
    level_before TEXT NOT NULL,
    level_after TEXT NOT NULL,
    external_token TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS career_roadmaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
    roadmap TEXT NOT NULL,
    generated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(student_id, role_id)
);

CREATE TABLE IF NOT EXISTS learning_diagnostics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    questions TEXT NOT NULL,
    answers TEXT,
    score REAL,
    topic_results TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_learning_diagnostics_student_skill
    ON learning_diagnostics (student_id, skill_id, id);

CREATE TABLE IF NOT EXISTS personalized_paths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    diagnostic_id INTEGER NOT NULL REFERENCES learning_diagnostics(id) ON DELETE CASCADE,
    required_level TEXT,
    items TEXT NOT NULL,
    skipped_mastered TEXT NOT NULL DEFAULT '[]',
    stages TEXT NOT NULL DEFAULT '[]',
    progress TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_personalized_paths_student_skill
    ON personalized_paths (student_id, skill_id, id);

CREATE TABLE IF NOT EXISTS learning_lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    personalized_path_id INTEGER NOT NULL REFERENCES personalized_paths(id) ON DELETE CASCADE,
    competency TEXT NOT NULL,
    title TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('learn', 'review')),
    content_json TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'not_started' CHECK(state IN ('not_started', 'in_progress', 'completed')),
    mini_check_result_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    UNIQUE(student_id, personalized_path_id, competency)
);
CREATE INDEX IF NOT EXISTS idx_learning_lessons_student_path
    ON learning_lessons (student_id, personalized_path_id, competency);

CREATE TABLE IF NOT EXISTS learning_practice_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    personalized_path_id INTEGER NOT NULL REFERENCES personalized_paths(id) ON DELETE CASCADE,
    lesson_id INTEGER NOT NULL REFERENCES learning_lessons(id) ON DELETE CASCADE,
    competency TEXT NOT NULL,
    answer TEXT NOT NULL,
    practice_task_json TEXT,
    score REAL NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('needs_review', 'ready')),
    strengths TEXT NOT NULL DEFAULT '[]',
    missing_points TEXT NOT NULL DEFAULT '[]',
    feedback TEXT NOT NULL,
    next_action TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('ai', 'fallback')),
    remediation_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_learning_practice_attempts_lesson
    ON learning_practice_attempts (student_id, lesson_id, id);

CREATE TABLE IF NOT EXISTS tutor_preferences (
    student_id INTEGER PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
    tutor_id TEXT NOT NULL CHECK(tutor_id IN ('nova','axel','sage','vex')),
    mode TEXT,
    language TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS active_assessments (
    student_id INTEGER PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    external_token TEXT,
    integrity_events TEXT NOT NULL DEFAULT '[]',
    webcam_gate_passed INTEGER NOT NULL DEFAULT 0,
    webcam_gate_checked_at TEXT,
    webcam_gate_meta TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS scenario_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    scenario_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'in_progress' CHECK(status IN ('in_progress', 'completed')),
    state_json TEXT,
    decisions_json TEXT NOT NULL DEFAULT '[]',
    evidence_viewed_json TEXT NOT NULL DEFAULT '[]',
    hints_used INTEGER NOT NULL DEFAULT 0,
    score REAL,
    skill_scores_json TEXT,
    skill_deltas_json TEXT NOT NULL DEFAULT '[]',
    strengths_json TEXT NOT NULL DEFAULT '[]',
    improvements_json TEXT NOT NULL DEFAULT '[]',
    feedback_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_scenario_attempts_student
    ON scenario_attempts (student_id, scenario_id, id);

CREATE TABLE IF NOT EXISTS saved_roles (
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    saved_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (student_id, role_id)
);
"""


def _migrate():
    """Lightweight in-place migration so databases created before an iteration
    keep working: add any columns that the current schema introduced."""
    additions = [
        ("users", "password_hash", "TEXT"),
        ("users", "password_salt", "TEXT"),
        ("users", "auth_provider", "TEXT NOT NULL DEFAULT 'local'"),
        ("users", "google_sub", "TEXT"),
        ("users", "verified", "INTEGER NOT NULL DEFAULT 0"),
        ("users", "country", "TEXT"),
        ("users", "university", "TEXT"),
        ("users", "location", "TEXT"),
        ("users", "education_level", "TEXT"),
        ("companies", "location", "TEXT"),
        ("students", "cohort_confirmed", "INTEGER NOT NULL DEFAULT 0"),
        ("students", "share_public", "INTEGER NOT NULL DEFAULT 0"),
        ("students", "university", "TEXT"),
        ("students", "education_level", "TEXT"),
        ("roles", "is_reference", "INTEGER NOT NULL DEFAULT 0"),
        ("roles", "source", "TEXT NOT NULL DEFAULT 'company'"),
        ("roles", "external_id", "TEXT"),
        ("role_skills", "skill_kind", "TEXT NOT NULL DEFAULT 'essential'"),
        ("learning_path_items", "resources", "TEXT"),
        ("learning_path_items", "roadmap", "TEXT"),
        ("learning_path_items", "progress", "TEXT"),
        ("learning_path_items", "blueprint_version", "TEXT"),
        ("learning_path_items", "blueprint_competencies", "TEXT"),
        ("learning_path_items", "plan_modules", "TEXT"),
        ("assessment_attempts", "per_question", "TEXT"),
        ("assessment_attempts", "external_token", "TEXT"),
        ("learning_practice_attempts", "practice_task_json", "TEXT"),
        ("learning_practice_attempts", "remediation_json", "TEXT"),
        ("tutor_preferences", "mode", "TEXT"),
        ("tutor_preferences", "language", "TEXT"),
        ("tutor_messages", "tutor_id", "TEXT"),
        ("active_assessments", "external_token", "TEXT"),
        ("active_assessments", "integrity_events", "TEXT NOT NULL DEFAULT '[]'"),
        ("active_assessments", "webcam_gate_passed", "INTEGER NOT NULL DEFAULT 0"),
        ("active_assessments", "webcam_gate_checked_at", "TEXT"),
        ("active_assessments", "webcam_gate_meta", "TEXT NOT NULL DEFAULT '{}'"),
        ("self_reported_skills", "evidence", "TEXT"),
    ]
    conn = _connect()
    for table, column, ddl in additions:
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    conn.commit()


def init_db():
    with get_cursor() as conn:
        conn.executescript(SCHEMA)
    _migrate()
