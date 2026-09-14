"""Phase F: company role -> canonical role mapping.

Contract guaranteed here:
- a fresh DB gains migration 0005 (two nullable roles columns + append-only
  role_mapping_events audit), idempotently, with FK SET NULL semantics;
- suggestions are on-demand, deterministic, above a confidence floor, sorted
  high-first, and carry literal explanations; ambiguous titles surface both
  candidates and never auto-select;
- confirming a mapping is the only write path (audit-mapped -> changed ->
  unmapped), validated server-side against the active reference pool;
- (un)mapping never touches the local role's title/description/skills, never
  deletes the role, never clears students' target references, and keeps
  company skills distinguishable from the canonical role's;
- ownership: owner company only (403 for other companies / students, 401
  guest) on all three endpoints; results are additive and existing list/feed/
  candidates behaviour is unchanged.
"""
import sqlite3

import pytest

import app.database as database
import app.models as models
import app.role_mapping as role_mapping

MIGRATION_0005 = "0005_company_role_mapping"
MIGRATION_0006 = "0006_saved_jobs_tracker"
MIGRATION_0007 = "0007_role_view_events"


# ------------------------------------------------------------------ helpers

def _file_db(tmp_path, name="phasef.db"):
    conn = sqlite3.connect(str(tmp_path / name))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _conn_columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _catalog_role_id(db, title):
    return db.execute(
        "SELECT id FROM roles WHERE title=? AND source='catalog' AND is_reference=1",
        (title,)).fetchone()["id"]


def _company_role_id(db, title, company_name):
    return db.execute(
        "SELECT r.id FROM roles r JOIN companies c ON c.id=r.company_id "
        "WHERE r.title=? AND c.name=?", (title, company_name)).fetchone()["id"]


def _catalog_company_id(db):
    return db.execute(
        "SELECT id FROM companies WHERE name=?",
        (models.CATALOG_COMPANY_NAME,)).fetchone()["id"]


def _company_id(db, name):
    return db.execute("SELECT id FROM companies WHERE name=?", (name,)).fetchone()["id"]


def _mk_role(db, company_id, title, skills, is_reference=0, source="company"):
    role = models.create_role(
        company_id, title,
        [{"name": n, "level": lvl, "category": "General"} for n, lvl in skills],
        description=f"desc {title}", is_reference=is_reference, source=source)
    return role["id"]


def _northstar_roles(client, h, role_title):
    items = [r for r in client.get("/api/roles", headers=h).json()["roles"]
             if r["title"] == role_title]
    assert items, f"no company role {role_title}"
    return items[0]


def _event_count(db):
    return db.execute("SELECT COUNT(*) AS c FROM role_mapping_events").fetchone()["c"]


# ------------------------------------------------------------------ migration 0005

def test_migration_0005_on_fresh_db(tmp_path):
    conn = _file_db(tmp_path)
    database.set_db_for_test(conn)
    try:
        database.init_db()
        applied = [m["migration_id"] for m in database.applied_migrations()]
        assert applied[-1] == "0013_tutor_conversations"
        assert {"canonical_role_id", "canonical_mapping_updated_at"} <= _conn_columns(conn, "roles")
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "role_mapping_events" in tables
        ev = _conn_columns(conn, "role_mapping_events")
        assert {"role_id", "action", "from_canonical_role_id", "to_canonical_role_id",
                "actor_user_id", "actor_role", "created_at"} <= ev
        assert database.run_migrations() == []
    finally:
        database.set_db_for_test()
        conn.close()


def test_migration_0005_upgrades_pre_0005_db_and_keeps_rows(tmp_path):
    conn = _file_db(tmp_path)
    database.set_db_for_test(conn)
    try:
        pre = [m for m in database.MIGRATIONS if m["id"] not in (MIGRATION_0005, MIGRATION_0006, MIGRATION_0007)]
        database.run_migrations(conn=conn, migrations=pre)
        conn.execute("INSERT INTO companies (name, industry, location) "
                     "VALUES ('Old Co', 'AI', 'Cairo')")
        conn.execute("INSERT INTO roles (company_id, title, description, is_reference, source) "
                     "VALUES (1, 'Legacy Opening', 'kept', 0, 'company')")
        conn.commit()
        assert "role_mapping_events" not in {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        pending = database.run_migrations()
        assert pending == [MIGRATION_0005, MIGRATION_0006, MIGRATION_0007]
        kept = conn.execute("SELECT title FROM roles WHERE title='Legacy Opening'").fetchone()
        assert kept is not None
        canon_null = conn.execute(
            "SELECT canonical_role_id, canonical_mapping_updated_at FROM roles WHERE title=?",
            ("Legacy Opening",)).fetchone()
        assert canon_null["canonical_role_id"] is None
        assert canon_null["canonical_mapping_updated_at"] is None
    finally:
        database.set_db_for_test()
        conn.close()


def test_mapping_fk_behavior(db):
    canon = _mk_role(db, _catalog_company_id(db), "Fk Canonical", [("SQL", "Advanced")],
                     is_reference=1, source="catalog")
    local = _mk_role(db, _company_id(db, "Northstar Labs"), "Fk Local", [("SQL", "Advanced")])
    models.set_mapping(local, canon, {"id": 7, "role": "Company"})
    assert db.execute("SELECT canonical_role_id FROM roles WHERE id=?",
                      (local,)).fetchone()["canonical_role_id"] == canon
    db.execute("DELETE FROM roles WHERE id=?", (canon,))
    assert db.execute("SELECT canonical_role_id FROM roles WHERE id=?",
                      (local,)).fetchone()["canonical_role_id"] is None
    assert models.mapping_of(local) is None


# ------------------------------------------------------------------ suggestion engine

def test_confidence_labels_and_floor():
    assert role_mapping.confidence_label(0.80) == "High"
    assert role_mapping.confidence_label(0.70) == "High"
    assert role_mapping.confidence_label(0.45) == "Medium"
    assert role_mapping.confidence_label(0.44) == "Low"


def test_high_confidence_top_match_is_catalog_data_engineer(db):
    local = _company_role_id(db, "Data Engineer", "Northstar Labs")  # Northstar company role
    res = role_mapping.suggest_matches(local)
    assert res["mapped"] is None
    assert res["matches"], "expected at least one suggestion"
    top = res["matches"][0]
    assert top["title"] == "Data Engineer"
    assert top["source"] == "catalog"
    assert top["confidence_label"] == "High"
    assert 0.0 < top["confidence"] <= 1.0
    assert "Title shares" in top["explanation"] and "required skills" in top["explanation"]
    # sorted high-first
    confs = [m["confidence"] for m in res["matches"]]
    assert confs == sorted(confs, reverse=True)


def test_low_confidence_remains_unmapped(db):
    local = _mk_role(db, _company_id(db, "Northstar Labs"), "Legal Compliance Officer",
                     [("Communication", "Beginner"), ("Teamwork", "Beginner")])
    res = role_mapping.suggest_matches(local)
    assert res["matches"] == []
    assert res["mapped"] is None


def test_ambiguous_title_surfaces_both_with_no_auto_link(db):
    cat = _catalog_company_id(db)
    a = _mk_role(db, cat, "Data Analyst Prime", [("SQL", "Advanced"), ("Excel", "Advanced"),
                                                 ("Python", "Intermediate")],
                 is_reference=1, source="catalog")
    b = _mk_role(db, cat, "Data Analyst Prime", [("SQL", "Advanced"), ("Excel", "Advanced"),
                                                 ("Python", "Intermediate")],
                 is_reference=1, source="catalog")
    local = _mk_role(db, _company_id(db, "Northstar Labs"), "Data Analyst Prime",
                     [("SQL", "Advanced"), ("Excel", "Intermediate")])
    res = role_mapping.suggest_matches(local)
    top_titles = [m["title"] for m in res["matches"][:2]]
    assert top_titles == ["Data Analyst Prime", "Data Analyst Prime"]
    assert len(res["matches"]) >= 2
    assert res["ambiguous"] is True
    assert res["mapped"] is None          # nothing auto-selected


def test_skill_overlap_feeds_confidence(db):
    cat = _catalog_company_id(db)
    sharing = _mk_role(db, cat, "Marginal Overlap One",
                       [("SQL", "Advanced"), ("Excel", "Advanced")],
                       is_reference=1, source="catalog")
    distinct = _mk_role(db, cat, "Marginal Overlap Two",
                        [("SQL", "Advanced"), ("Robotics", "Advanced")],
                        is_reference=1, source="catalog")
    local = _mk_role(db, _company_id(db, "Northstar Labs"), "Marginal Overlap One Local",
                     [("SQL", "Advanced"), ("Excel", "Advanced")])
    res = role_mapping.suggest_matches(local)
    by_id = {m["role_id"]: m for m in res["matches"]}
    assert by_id[sharing]["confidence"] > by_id[distinct]["confidence"]


# ------------------------------------------------------------------ endpoints + audit

def test_confirm_mapping_persists_and_audits(client, auth_headers, db):
    h = auth_headers("hr@northstar.com")
    local = _northstar_roles(client, h, "Data Engineer")
    target = _catalog_role_id(db, "Data Engineer")  # catalog role
    r = client.post(f"/api/company/roles/{local['id']}/canonical-mapping",
                    headers=h, json={"canonical_role_id": target})
    assert r.status_code == 200
    body = r.json()
    assert body["canonical_role_id"] == target
    assert body["mapped"]["canonical_role_id"] == target
    assert body["mapped"]["mapped_title"] == "Data Engineer"
    assert body["mapping_updated_at"]
    assert _event_count(db) == 1
    action = db.execute("SELECT action, from_canonical_role_id, to_canonical_role_id, "
                        "actor_role FROM role_mapping_events").fetchone()
    assert action["action"] == "mapped"
    assert action["from_canonical_role_id"] is None
    assert action["to_canonical_role_id"] == target
    assert action["actor_role"] == "Company"
    # GET role now carries additive mapping fields
    role = client.get(f"/api/roles/{local['id']}", headers=h).json()
    assert role["canonical_role_id"] == target
    prov = client.get(f"/api/roles/{local['id']}/provenance", headers=h).json()
    assert prov["mapping"]["canonical_role_id"] == target


def test_change_mapping_appends_changed_event(client, auth_headers, db):
    h = auth_headers("hr@northstar.com")
    local = _northstar_roles(client, h, "Data Engineer")
    first = _catalog_role_id(db, "Data Engineer")
    second = _catalog_role_id(db, "Data Analyst")
    client.post(f"/api/company/roles/{local['id']}/canonical-mapping",
                headers=h, json={"canonical_role_id": first})
    r = client.post(f"/api/company/roles/{local['id']}/canonical-mapping",
                    headers=h, json={"canonical_role_id": second})
    assert r.status_code == 200
    history = client.get(f"/api/company/roles/{local['id']}/mapping-history", headers=h).json()
    assert [e["action"] for e in history] == ["changed", "mapped"]
    assert history[0]["from_canonical_role_id"] == first
    assert history[0]["to_canonical_role_id"] == second
    assert history[0]["to_title"] == "Data Analyst"
    assert history[0]["actor_role"] == "Company"


def test_reconfirm_same_target_is_noop(client, auth_headers, db):
    h = auth_headers("hr@northstar.com")
    local = _northstar_roles(client, h, "Data Engineer")
    target = _catalog_role_id(db, "Data Engineer")
    for _ in range(2):
        r = client.post(f"/api/company/roles/{local['id']}/canonical-mapping",
                        headers=h, json={"canonical_role_id": target})
        assert r.status_code == 200
    assert _event_count(db) == 1


def test_unmap_keeps_role_and_student_reference(client, auth_headers, db, login):
    h = auth_headers("hr@northstar.com")
    local = _northstar_roles(client, h, "Data Engineer")
    target = _catalog_role_id(db, "Data Engineer")
    client.post(f"/api/company/roles/{local['id']}/canonical-mapping",
                headers=h, json={"canonical_role_id": target})
    # a student pointing at this local role must keep the reference after unmap
    payload = login("aisha@student.edu")
    sid = payload["student"]["id"]
    models.update_student(sid, target_role_id=local["id"], cohort_confirmed=1)
    r = client.post(f"/api/company/roles/{local['id']}/canonical-mapping",
                    headers=h, json={"canonical_role_id": None})
    assert r.status_code == 200
    assert r.json()["canonical_role_id"] is None
    assert db.execute("SELECT title FROM roles WHERE id=?",
                      (local["id"],)).fetchone() is not None  # role still exists
    student = models.get_student(sid)
    assert student["target_role_id"] == local["id"]
    assert db.execute("SELECT action FROM role_mapping_events ORDER BY id DESC"
                      ).fetchone()["action"] == "unmapped"


def test_mapping_never_touches_local_role_bytes(client, auth_headers, db):
    h = auth_headers("hr@northstar.com")
    local = _northstar_roles(client, h, "Data Engineer")
    before = client.get(f"/api/roles/{local['id']}", headers=h).json()
    target = _catalog_role_id(db, "Data Engineer")
    client.post(f"/api/company/roles/{local['id']}/canonical-mapping",
                headers=h, json={"canonical_role_id": target})
    client.post(f"/api/company/roles/{local['id']}/canonical-mapping",
                headers=h, json={"canonical_role_id": None})
    after = client.get(f"/api/roles/{local['id']}", headers=h).json()
    assert after["title"] == before["title"]
    assert after["description"] == before["description"]
    assert [(s["skill_id"], s["required_level"]) for s in after["required_skills"]] == \
           [(s["skill_id"], s["required_level"]) for s in before["required_skills"]]


def test_company_skills_stay_distinguishable(client, auth_headers, db):
    h = auth_headers("hr@northstar.com")
    local = _northstar_roles(client, h, "Data Engineer")
    target = _catalog_role_id(db, "Data Engineer")
    client.post(f"/api/company/roles/{local['id']}/canonical-mapping",
                headers=h, json={"canonical_role_id": target})
    srcs = models.role_skill_sources(local["id"])
    assert len(srcs) == 4 and all(s["source"] == "company" for s in srcs.values())
    canon_skills = db.execute("SELECT COUNT(*) AS c FROM role_skills WHERE role_id=?",
                              (target,)).fetchone()["c"]
    assert canon_skills >= 12
    assert db.execute("SELECT COUNT(*) AS c FROM role_skills WHERE role_id=?",
                      (target,)).fetchone()["c"] != len(srcs)


def test_mapping_pool_validation(client, auth_headers, db):
    h = auth_headers("hr@northstar.com")
    local = _northstar_roles(client, h, "Data Engineer")
    signal_analyst = _company_role_id(db, "Data Analyst", "Signal Works")   # another company's local role
    # invalid type
    assert client.post(f"/api/company/roles/{local['id']}/canonical-mapping",
                       headers=h, json={"canonical_role_id": "bogus"}).status_code == 400
    # another company's local role is not in the canonical pool
    assert client.post(f"/api/company/roles/{local['id']}/canonical-mapping",
                       headers=h, json={"canonical_role_id": signal_analyst}).status_code == 400
    # self-mapping rejected
    assert client.post(f"/api/company/roles/{local['id']}/canonical-mapping",
                       headers=h, json={"canonical_role_id": local["id"]}).status_code == 400
    # deprecated reference roles are excluded from the pool
    cat = _catalog_company_id(db)
    dep = _mk_role(db, cat, "Deprecated Canonical", [("SQL", "Advanced")],
                   is_reference=1, source="catalog")
    db.execute("UPDATE roles SET canonical_status='deprecated' WHERE id=?", (dep,))
    assert client.post(f"/api/company/roles/{local['id']}/canonical-mapping",
                       headers=h, json={"canonical_role_id": dep}).status_code == 400


def test_authz_matrix(client, auth_headers, db):
    local = _company_role_id(db, "Data Engineer", "Northstar Labs")   # Northstar's own role
    other = auth_headers("hr@signal.com")
    student = auth_headers("aisha@student.edu")
    for path in (f"/api/company/roles/{local}/canonical-matches",
                 f"/api/company/roles/{local}/mapping-history"):
        assert client.get(path, headers=other).status_code == 403
        assert client.get(path, headers=student).status_code == 403
        assert client.get(path).status_code == 401
    assert client.post(f"/api/company/roles/{local}/canonical-mapping",
                       headers=other, json={"canonical_role_id": None}).status_code == 403
    assert client.post(f"/api/company/roles/{local}/canonical-mapping",
                       headers=student, json={"canonical_role_id": None}).status_code == 403
    assert client.post(f"/api/company/roles/{local}/canonical-mapping",
                       json={"canonical_role_id": None}).status_code == 401
    owner = auth_headers("hr@northstar.com")
    assert client.get(f"/api/company/roles/{local}/canonical-matches", headers=owner).status_code == 200
    assert client.get(f"/api/company/roles/{local}/mapping-history", headers=owner).status_code == 200


def test_suggestions_are_ephemeral_and_mapping_needs_confirm(client, auth_headers, db):
    """Suggestions never write anything; only the confirm POST persists."""
    h = auth_headers("hr@northstar.com")
    local = _northstar_roles(client, h, "Data Engineer")
    assert _event_count(db) == 0
    res = client.get(f"/api/company/roles/{local['id']}/canonical-matches", headers=h)
    assert res.status_code == 200
    assert res.json()["mapped"] is None
    assert _event_count(db) == 0
    target = _catalog_role_id(db, "Data Engineer")
    client.post(f"/api/company/roles/{local['id']}/canonical-mapping",
                headers=h, json={"canonical_role_id": target})
    assert _event_count(db) == 1


def test_compatibility_additive(db, client, auth_headers):
    h = auth_headers("hr@northstar.com")
    before_company = len(models.list_roles())
    before_feed = len(models.list_feed_roles())
    local = _northstar_roles(client, h, "Data Engineer")
    target = _catalog_role_id(db, "Data Engineer")
    client.post(f"/api/company/roles/{local['id']}/canonical-mapping",
                headers=h, json={"canonical_role_id": target})
    assert len(models.list_roles()) == before_company
    assert len(models.list_feed_roles()) == before_feed
    role = client.get(f"/api/roles/{local['id']}", headers=h).json()
    assert role["canonical_role_id"] == target
    assert role["canonical_mapping_updated_at"]


def test_pool_only_contains_active_reference_roles(db):
    cat = _catalog_company_id(db)
    local = _mk_role(db, _company_id(db, "Northstar Labs"), "Pool Guard Local",
                     [("SQL", "Advanced")])
    _mk_role(db, cat, "Pool Canonical", [("SQL", "Advanced")], is_reference=1, source="catalog")
    dep = _mk_role(db, cat, "Pool Deprecated", [("SQL", "Advanced")],
                   is_reference=1, source="catalog")
    db.execute("UPDATE roles SET canonical_status='superseded' WHERE id=?", (dep,))
    pool = models.canonical_mapping_pool()
    assert all(r["is_reference"] == 1 and (r["canonical_status"] or "active") == "active"
               for r in pool)
    assert all(r["id"] != local for r in pool)
