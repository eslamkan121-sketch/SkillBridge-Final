"""Phase B: ordered idempotent migrations, rollback-on-failure, request ids and
the additive error envelope.

Contract guaranteed here:
- a fresh DB gains the schema_migrations ledger and every migration runs once;
- a pre-ledger "legacy" DB is upgraded in place and keeps all existing rows;
- repeated startup never re-applies a recorded migration;
- one failing migration rolls the whole batch back (schema is never partial);
- API errors keep their existing ``detail`` and only gain a ``request_id``;
- every response carries an X-Request-Id header.
"""
import sqlite3

import pytest

import app.database as database
import app.models as models


MIGRATION_0001 = "0001_baseline_implied_schema"
MIGRATION_0002 = "0002_auth_sessions"
MIGRATION_0003 = "0003_canonical_roles"
MIGRATION_0004 = "0004_esco_import"
MIGRATION_0005 = "0005_company_role_mapping"
MIGRATION_0006 = "0006_saved_jobs_tracker"
MIGRATION_0007 = "0007_role_view_events"
MIGRATION_0008 = "0008_job_link_reports"
MIGRATION_0009 = "0009_copilot_config"
MIGRATION_0010 = "0010_copilot_onboarding"
MIGRATION_0011 = "0011_mentor_keys"
MIGRATION_0012 = "0012_tutor_memory"
EXPECTED_MIGRATIONS = [MIGRATION_0001, MIGRATION_0002, MIGRATION_0003,
                       MIGRATION_0004, MIGRATION_0005, MIGRATION_0006, MIGRATION_0007, MIGRATION_0008, MIGRATION_0009, MIGRATION_0010, MIGRATION_0011, MIGRATION_0012]


def _fresh_file_db(tmp_path, name="phaseb.db"):
    conn = sqlite3.connect(str(tmp_path / name))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def test_fresh_db_records_migration(tmp_path):
    conn = _fresh_file_db(tmp_path)
    database.set_db_for_test(conn)
    try:
        database.init_db()

        applied = database.applied_migrations()
        assert [m["migration_id"] for m in applied] == EXPECTED_MIGRATIONS
        for m in applied:
            assert m["applied_at"]

        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "schema_migrations" in tables
        assert "users" in tables and "roles" in tables
    finally:
        database.set_db_for_test()
        conn.close()


def test_repeated_startup_is_idempotent(tmp_path):
    conn = _fresh_file_db(tmp_path)
    database.set_db_for_test(conn)
    try:
        database.init_db()
        first = database.applied_migrations()

        # Second startup path: no pending work, ledger unchanged, no error.
        pending = database.run_migrations()
        assert pending == []
        assert database.applied_migrations() == first
        assert database.applied_migrations()[0]["migration_id"] == MIGRATION_0001
    finally:
        database.set_db_for_test()
        conn.close()


def test_legacy_db_upgraded_in_place(tmp_path):
    """A DB created by the old pre-ledger bootstrap (schema but no ledger, data
    already present) must be migrated without touching existing rows."""
    db_path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(str(db_path))
    legacy.row_factory = sqlite3.Row
    legacy.executescript(database.SCHEMA)
    legacy.execute("DELETE FROM users")
    legacy.execute(
        "INSERT INTO users (email, password, display_name, role) "
        "VALUES ('legacy@example.com', 'x', 'Legacy User', 'Student')"
    )
    legacy.commit()
    legacy.close()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    database.set_db_for_test(conn)
    try:
        database.init_db()

        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "schema_migrations" in tables

        kept = conn.execute(
            "SELECT email FROM users WHERE email='legacy@example.com'").fetchone()
        assert kept is not None and kept["email"] == "legacy@example.com"

        assert database.applied_migrations()[0]["migration_id"] == MIGRATION_0001
    finally:
        database.set_db_for_test()
        conn.close()


def test_failed_migration_rolls_back_fully(tmp_path):
    conn = _fresh_file_db(tmp_path)
    database.set_db_for_test(conn)

    def bad_migration(c):
        c.execute("CREATE TABLE IF NOT EXISTS half_done (id INTEGER PRIMARY KEY)")
        c.execute("INSERT INTO half_done VALUES (1)")
        raise RuntimeError("boom: simulated migration failure")

    try:
        with pytest.raises(RuntimeError, match="simulated migration failure"):
            database.run_migrations(conn=conn, migrations=[
                {"id": "9999_bad", "apply": bad_migration},
            ])

        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "half_done" not in tables
        assert "schema_migrations" not in tables

        # DB still healthy: the real migration set applies cleanly afterwards.
        pending = database.run_migrations()
        assert pending == EXPECTED_MIGRATIONS
        assert database.applied_migrations()[0]["migration_id"] == MIGRATION_0001
    finally:
        database.set_db_for_test()
        conn.close()


def test_seed_keeps_migration_ledger_on_fresh_db(tmp_path):
    """The real bootstrap (seed.seed -> init_db) records the migration and the
    reference data is present, exactly like test_bootstrap but on a file DB."""
    import app.seed as seed_mod

    conn = _fresh_file_db(tmp_path)
    database.set_db_for_test(conn)
    try:
        seed_mod.seed()

        assert len(list(models.list_universities())) > 0
        assert database.applied_migrations()[0]["migration_id"] == MIGRATION_0001
    finally:
        database.set_db_for_test()
        conn.close()


def test_error_body_keeps_detail_and_gains_request_id(client, auth_headers):
    """Every error body must keep the existing ``detail`` (frontend and the whole
    suite read it) and additively carry a request_id; the header must exist."""
    # Routed 404 (auth-gated role lookup on a missing role).
    h = auth_headers("aisha@student.edu")
    r = client.get("/api/roles/9999999", headers=h)
    assert r.status_code == 404
    assert r.json()["detail"] == "Role not found"
    assert r.json()["request_id"]
    assert r.headers.get("x-request-id") == r.json()["request_id"]

    # Routed 401 (auth-gated role lookup with no credentials at all).
    banned = client.get("/api/roles/1")
    assert banned.status_code == 401
    assert "Not authenticated" in banned.json()["detail"]
    assert banned.json()["request_id"]
    assert banned.headers.get("x-request-id") == banned.json()["request_id"]


def test_success_responses_carry_request_id_header(client, auth_headers):
    r = client.get("/api/universities")
    assert r.status_code == 200
    assert r.headers.get("x-request-id")
    assert r.headers.get("x-response-time-ms")


def test_db_status_endpoint(client):
    r = client.get("/api/system/db-status")
    assert r.status_code == 200
    body = r.json()
    assert body["database"] == {"engine": "sqlite", "ok": True}
    assert body["migrations"]["applied_count"] >= 1
    # Applied rows are returned newest-last so the last entry is the latest migration.
    assert body["migrations"]["applied"][-1]["migration_id"] == MIGRATION_0012

    bounded = client.get("/api/system/db-status?limit=1")
    assert bounded.status_code == 200
    assert len(bounded.json()["migrations"]["applied"]) == 1

    bad = client.get("/api/system/db-status?limit=99999")
    assert bad.status_code == 400
    assert "request_id" in bad.json()


def test_field_length_helper_rejects_oversized_input(client):
    from app import main as main_mod

    payload = {"display_name": "x" * 500, "location": "Cairo"}
    with pytest.raises(Exception) as exc_info:
        main_mod._check_field_lengths(payload, main_mod._FIELD_LIMITS)
    assert exc_info.value.status_code == 400
    assert "display_name" in exc_info.value.detail

    fine = {"display_name": "Ali", "location": "Cairo"}
    assert main_mod._check_field_lengths(fine, main_mod._FIELD_LIMITS) is None


def test_unknown_role_column_missing_on_legacy_db_still_added(tmp_path):
    """Guard against a common legacy shape: a table exists but a column the
    baseline expects is absent - the ALTER path in 0001 must add it and keep the
    row intact."""
    db_path = tmp_path / "partial.db"
    partial = sqlite3.connect(str(db_path))
    partial.row_factory = sqlite3.Row
    partial.executescript(database.SCHEMA)
    partial.execute("DELETE FROM users")
    partial.execute(
        "INSERT INTO users (email, password, display_name, role) "
        "VALUES ('partial@example.com', 'x', 'Partial User', 'Student')"
    )
    partial.commit()
    partial.close()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    database.set_db_for_test(conn)
    try:
        database.init_db()
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        assert "password_hash" in columns
        assert conn.execute(
            "SELECT email FROM users WHERE email='partial@example.com'"
        ).fetchone() is not None
    finally:
        database.set_db_for_test()
        conn.close()
