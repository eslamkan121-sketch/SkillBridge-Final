"""Regression tests for the fresh-install bootstrap path.

The biggest bug shipped was the seed ordering: ``init_db()`` created the sqlite
file, so ``seed.seed()`` never ran on a brand-new database and every reference
table (universities, roles, catalog, demo accounts) shipped empty. These tests
pin down the bootstrap and the offline jobs fallback.
"""
import os
import sqlite3

import app.database as database
import app.seed as seed_mod
import app.models as models


def test_fresh_db_is_seeded(tmp_path):
    """A never-existed DB (temp path) must come back fully seeded."""
    db_path = tmp_path / "fresh.db"
    # The file genuinely does not exist yet — this is the pre-connect check the
    # real on_startup relies on.
    assert not os.path.exists(str(db_path))
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    database.set_db_for_test(conn)

    try:
        # Mimic the exact bootstrap path main.on_startup takes on a fresh DB:
        # seed() runs the schema AND the reference data in one pass.
        seed_mod.seed()

        assert len(list(models.list_universities())) > 0
        assert len(list(models.list_roles())) > 0
        # A seeded demo account record exists.
        users = conn.execute(
            "SELECT * FROM users WHERE email=?", ("aisha@student.edu",)
        ).fetchall()
        assert len(users) == 1
        skills = conn.execute("SELECT COUNT(*) AS c FROM skills").fetchone()["c"]
        assert skills > 0
        yara = conn.execute(
            """
            SELECT r.title
            FROM students s
            JOIN roles r ON r.id = s.target_role_id
            WHERE s.email = ?
            """,
            ("yara@student.edu",),
        ).fetchone()
        assert yara is not None
        assert yara["title"] == "Cybersecurity Analyst"
    finally:
        database.set_db_for_test()
        conn.close()


def test_jobs_unavailable_without_network(monkeypatch, client, auth_headers):
    """The recent-jobs endpoint must return an honest ``unavailable`` empty
    response (never curated/demo jobs) when every feed is down."""
    import app.jobs as jobs_mod

    def boom(*args, **kwargs):
        raise OSError("no network in this test")

    monkeypatch.setattr(jobs_mod.httpx, "get", boom)
    # Make sure the module-level cache can't serve stale live data.
    jobs_mod.clear_job_cache()

    h = auth_headers("aisha@student.edu")
    r = client.get("/api/jobs/recent", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "unavailable"
    assert body["jobs"] == []


def test_jobs_requires_auth(client):
    """Recent jobs is an authenticated, student-facing surface."""
    r = client.get("/api/jobs/recent")
    assert r.status_code in (401, 403)
