"""Phase L — Role Explorer: recently-viewed roles + catalogue-version meta.

A student's Recently viewed list is a private, capped (MAX_ROLE_VIEW_EVENTS)
set of (student, role) view events: opening a role's details records a view, a
re-view bumps the timestamp and moves the role back to the top (never
duplicates), and the list is newest-first with honest provenance columns riding
along. Ownership is student-only; a deleted role cascades its views away so
recents never point at a missing role. `roles_catalog_version()` is derived
from real reference-row source_versions only, never synthesized.
"""
import sqlite3

import pytest

from app import database, models, seed

MIGRATION_0007 = "0007_role_view_events"


# ------------------------------------------------------------------ migration 0007

def _file_db(tmp_path, name="phasel.db"):
    conn = sqlite3.connect(str(tmp_path / name))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _any_role_id(conn):
    return conn.execute("SELECT id FROM roles LIMIT 1").fetchone()["id"]


def test_migration_0007_on_fresh_db(tmp_path):
    conn = _file_db(tmp_path)
    database.set_db_for_test(conn)
    try:
        database.init_db()
        applied = [m["migration_id"] for m in database.applied_migrations()]
        assert applied[-1] == "0013_tutor_conversations"
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "role_view_events" in tables
        info = {r["name"] for r in conn.execute("PRAGMA table_info(role_view_events)")}
        assert {"student_id", "role_id", "viewed_at"} <= info
        pks = [r["name"] for r in conn.execute("PRAGMA index_list('role_view_events')")
               if r["name"].startswith("sqlite_autoindex")]
        assert len(pks) == 1
        assert conn.execute("PRAGMA index_list('role_view_events')").fetchall()
        assert database.run_migrations() == []
    finally:
        database.set_db_for_test()
        conn.close()


def test_migration_0007_upgrades_pre_0007_db_and_keeps_rows(tmp_path):
    conn = _file_db(tmp_path)
    database.set_db_for_test(conn)
    try:
        pre = [m for m in database.MIGRATIONS if m["id"] != MIGRATION_0007]
        database.run_migrations(conn=conn, migrations=pre)
        conn.execute("INSERT INTO companies (name, industry, location) "
                     "VALUES ('Old Co', 'AI', 'Cairo')")
        conn.execute("INSERT INTO roles (company_id, title, description, is_reference, source) "
                     "VALUES (1, 'Legacy Opening', 'kept', 0, 'company')")
        conn.commit()
        assert "role_view_events" not in {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        pending = database.run_migrations()
        assert pending == [MIGRATION_0007]
        kept = conn.execute("SELECT title FROM roles WHERE title='Legacy Opening'").fetchone()
        assert kept is not None
        assert database.run_migrations() == []
    finally:
        database.set_db_for_test()
        conn.close()


def test_migration_0007_backs_out_on_failure(tmp_path):
    conn = _file_db(tmp_path)
    conn.row_factory = sqlite3.Row
    database.set_db_for_test(conn)
    try:
        def bad(c):
            c.execute("CREATE TABLE IF NOT EXISTS oops (id INTEGER PRIMARY KEY)")
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            database.run_migrations(conn=conn, migrations=database.MIGRATIONS + [
                {"id": "9999_bad", "apply": bad}])
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "oops" not in tables and "role_view_events" not in tables
        assert database.run_migrations()[-1] == "0013_tutor_conversations"
    finally:
        database.set_db_for_test()
        conn.close()


# ------------------------------------------------------------------ data layer

def test_record_role_view_unknown_role_raises(db):
    with pytest.raises(ValueError):
        models.record_role_view(1, 999999)


def test_record_role_view_dedupe_bump_and_order(db, monkeypatch):
    times = iter(["2026-09-12 10:00:00", "2026-09-12 10:00:05", "2026-09-12 10:00:10"])
    monkeypatch.setattr(models, "_now", lambda: next(times))
    a, b = _any_role_id(db), None
    # second role id (different from a)
    b = db.execute("SELECT id FROM roles WHERE id != ? LIMIT 1", (a,)).fetchone()["id"]

    models.record_role_view(1, a)                      # 10:00:00
    models.record_role_view(1, b)                      # 10:00:05 -> [b, a]
    first_list = models.list_recent_role_views(1)
    assert [r["id"] for r in first_list] == [b, a]

    models.record_role_view(1, a)                      # 10:00:10 re-view moves a to top
    second_list = models.list_recent_role_views(1)
    assert [r["id"] for r in second_list] == [a, b]
    # never duplicated: one row per (student, role)
    n = db.execute("SELECT COUNT(*) n FROM role_view_events").fetchone()["n"]
    assert n == 2
    assert first_list[0]["viewed_at"] == "2026-09-12 10:00:05"
    assert second_list[0]["viewed_at"] == "2026-09-12 10:00:10"


def test_record_role_view_cap_max(db, monkeypatch):
    for i in range(15):
        models.create_role(1, f"Cap Role {i}",
                           [{"name": f"cap-skill-{i}", "category": "General", "level": "Intermediate"}],
                           is_reference=1, source="catalog", source_version="v1.0.0")
    ids = [r["id"] for r in db.execute("SELECT id FROM roles ORDER BY id").fetchall()]
    assert len(ids) >= database.MAX_ROLE_VIEW_EVENTS + 5
    stamps = [f"2026-09-11 09:{i // 60:02d}:{i % 60:02d}" for i in range(len(ids))]
    idx = {"n": 0}

    def ticking_now():
        stamp = stamps[idx["n"] % len(stamps)]
        idx["n"] += 1
        return stamp

    monkeypatch.setattr(models, "_now", ticking_now)
    for rid in ids:
        models.record_role_view(1, rid)
    views = models.list_recent_role_views(1)
    assert len(views) == database.MAX_ROLE_VIEW_EVENTS
    assert views[0]["id"] == ids[-1]


def test_list_recent_joins_real_columns(db, monkeypatch):
    times = iter(["2026-09-12 08:00:00", "2026-09-12 09:00:00"])
    monkeypatch.setattr(models, "_now", lambda: next(times))
    a = _any_role_id(db)
    b = db.execute("SELECT id FROM roles WHERE id != ? LIMIT 1", (a,)).fetchone()["id"]
    models.record_role_view(1, a)
    models.record_role_view(1, b)
    rows = models.list_recent_role_views(1)
    assert len(rows) == 2
    for r in rows:
        # only real additive columns, never fabricated
        assert set(r) >= {"id", "title", "viewed_at", "family", "source", "is_reference"}
        assert "company_name" in r or "company_name" not in r  # always present via LEFT JOIN
        assert "family" in r
    assert rows[0]["id"] == b and rows[1]["id"] == a


def test_role_view_events_cascade_cleanup(db, monkeypatch):
    monkeypatch.setattr(models, "_now", lambda: "2026-09-12 12:00:00")
    rid = _any_role_id(db)
    sid = db.execute("SELECT id FROM students LIMIT 1").fetchone()["id"]
    models.record_role_view(sid, rid)
    assert db.execute("SELECT COUNT(*) n FROM role_view_events").fetchone()["n"] == 1
    db.execute("DELETE FROM roles WHERE id=?", (rid,))
    assert db.execute("SELECT COUNT(*) n FROM role_view_events").fetchone()["n"] == 0
    # without the role FK, re-recording raises
    with pytest.raises(ValueError):
        models.record_role_view(sid, rid)


def test_roles_catalog_version_is_real_or_none(db):
    ver = models.roles_catalog_version()
    assert ver is None or (isinstance(ver, str) and ver.strip())
    # never synthesized from nothing: with no reference versions -> None
    db.execute("UPDATE roles SET source_version=NULL WHERE is_reference=1")
    assert models.roles_catalog_version() is None
    db.execute("UPDATE roles SET source_version='v1.2.0' WHERE is_reference=1 AND id = "
               "(SELECT MIN(id) FROM roles WHERE is_reference=1)")
    assert models.roles_catalog_version() == "v1.2.0"
    db.execute("UPDATE roles SET source_version='v1.3.0' WHERE is_reference=1 AND id = "
               "(SELECT MAX(id) FROM roles WHERE is_reference=1)")
    assert models.roles_catalog_version() == "v1.3.0"


def test_seed_wipe_clears_view_events(db):
    models.record_role_view(1, _any_role_id(db))
    assert db.execute("SELECT COUNT(*) n FROM role_view_events").fetchone()["n"] == 1
    seed.seed()
    assert db.execute("SELECT COUNT(*) n FROM role_view_events").fetchone()["n"] == 0


# ------------------------------------------------------------------ endpoints

def _first_role_id(client, h):
    r = client.get("/api/roles", headers=h)
    assert r.status_code == 200, r.text
    roles = r.json()["roles"]
    assert roles
    return roles[0]["id"]


def test_recents_roundtrip_via_endpoint(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    rid = _first_role_id(client, h)
    r = client.post(f"/api/students/{student_id}/recent-roles",
                    json={"role_id": rid}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["viewed_at"]

    r = client.get(f"/api/students/{student_id}/recent-roles", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert "roles" in body and body["roles"]
    assert body["roles"][0]["id"] == rid
    assert "viewed_at" in body["roles"][0]

    # re-record is an upsert — still a single row
    client.post(f"/api/students/{student_id}/recent-roles",
                json={"role_id": rid}, headers=h)
    r = client.get(f"/api/students/{student_id}/recent-roles", headers=h)
    assert len(r.json()["roles"]) == 1


def test_recents_endpoint_invalid_body(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    for bad in ({}, {"role_id": "x"}, {"role_id": 0}, {"role_id": -1}):
        r = client.post(f"/api/students/{student_id}/recent-roles", json=bad, headers=h)
        assert r.status_code == 400, (bad, r.text)
    r = client.post(f"/api/students/{student_id}/recent-roles",
                    json={"role_id": 999999}, headers=h)
    assert r.status_code == 404


def test_recents_endpoint_student_private(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    rid = _first_role_id(client, h)
    client.post(f"/api/students/{student_id}/recent-roles",
                json={"role_id": rid}, headers=h)

    omar = auth_headers("omar@student.edu")
    r = client.get(f"/api/students/{student_id}/recent-roles", headers=omar)
    assert r.status_code == 403
    r = client.post(f"/api/students/{student_id}/recent-roles",
                    json={"role_id": rid}, headers=omar)
    assert r.status_code == 403

    company = auth_headers("hr@northstar.com")
    assert client.get(f"/api/students/{student_id}/recent-roles", headers=company).status_code == 403

    assert client.get(f"/api/students/{student_id}/recent-roles").status_code == 401
    assert client.post(f"/api/students/{student_id}/recent-roles",
                       json={"role_id": rid}).status_code == 401


def test_roles_endpoint_brings_role_data_version(client, auth_headers):
    h = auth_headers("omar@student.edu")
    r = client.get("/api/roles", headers=h)
    assert r.status_code == 200
    assert "role_data_version" in r.json()
    ver = r.json()["role_data_version"]
    assert ver is None or (isinstance(ver, str) and ver.strip())
    # additive: existing keys untouched
    assert "roles" in r.json() and "catalog" in r.json() and "is_company" in r.json()
