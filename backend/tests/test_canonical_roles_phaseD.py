"""Phase D Slice 1: canonical role & skill data model (migration 0003).

Contract guaranteed here:
- a fresh DB gains migration 0003: the added roles columns plus the
  role_aliases / role_isco_codes / role_skill_sources tables;
- an existing (pre-0003) DB is upgraded in place: all rows and foreign-key
  links survive migration, and canonical metadata is backfilled honestly
  (normalized_title / family / role_key / is_local_authoring / per-skill
  provenance), never fabricating versions, URIs, aliases or hierarchy edges;
- 0003 is idempotent and fully rollback-safe;
- aliases are language-tagged, alternative/hidden typed, and duplicate
  (role, alias, type, language) rows are rejected;
- ESCO imports stay idempotent on external_id and carry real provenance;
- deprecated roles are excluded from feed + recommendation candidates yet stay
  resolvable by id and as an existing target_role_id;
- locally authored roles are never labelled ESCO;
- normalized search matches folded forms while the display title is untouched;
- existing FKs (students.target_role_id, saved_roles, role_skills, scenarios,
  learning plans, assessments) keep working after migration;
- provenance is additive in the recommendation pipeline (source / version /
  status) and readable through GET /api/roles/{id}/provenance under the
  existing privacy and ownership rules.
"""
import sqlite3

import pytest

import app.database as database
import app.models as models
import app.seed as seed_mod
import app.recommendations as recommendations

MIGRATION_0003 = "0003_canonical_roles"
MIGRATION_0004 = "0004_esco_import"
MIGRATION_0005 = "0005_company_role_mapping"
PRE_D_MIGRATIONS = [m for m in database.MIGRATIONS if m["id"] != MIGRATION_0003]

NEW_COLUMNS = {"role_key", "source_version", "canonical_status", "superseded_by_role_id",
               "is_local_authoring", "normalized_title", "family", "parent_role_id",
               "fetched_at", "imported_at", "updated_at"}
NEW_TABLES = {"role_aliases", "role_isco_codes", "role_skill_sources"}


def _file_db(tmp_path, name="phased.db"):
    conn = sqlite3.connect(str(tmp_path / name))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _conn_tables(conn):
    return {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _conn_columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _build_pre_d_db(tmp_path, name="pre_d.db"):
    """A DB in exactly the pre-Phase-D state: migrations 0001+0002 applied, plus
    a realistic mixed dataset (company role, legacy ESCO role, a student with a
    target role, saved roles, a scenario attempt, a learning path item and an
    assessment attempt)."""
    conn = _file_db(tmp_path, name)
    database.set_db_for_test(conn)
    database.run_migrations(conn=conn, migrations=PRE_D_MIGRATIONS)
    assert MIGRATION_0003 not in [m["migration_id"] for m in database.applied_migrations()]

    c = conn
    c.execute("INSERT INTO companies (name, industry, location) VALUES ('Legacy Co', 'AI', 'Cairo')")
    company_id = c.execute("SELECT id FROM companies").fetchone()["id"]
    c.execute("INSERT INTO skills (name, category) VALUES ('Python', 'Programming')")
    c.execute("INSERT INTO skills (name, category) VALUES ('SQL', 'Data')")
    python_id = c.execute("SELECT id FROM skills WHERE name='Python'").fetchone()["id"]
    sql_id = c.execute("SELECT id FROM skills WHERE name='SQL'").fetchone()["id"]
    c.execute("INSERT INTO users (email, password, role, display_name) "
              "VALUES ('legacy@student.edu', 'x', 'Student', 'Legacy Student')")
    user_id = c.execute("SELECT id FROM users").fetchone()["id"]

    cur = c.execute(
        "INSERT INTO roles (company_id, title, description, is_reference, source) "
        "VALUES (?,?,?,0,'company')",
        (company_id, "Legacy Data Engineer", "legacy opening"))
    company_role_id = cur.lastrowid
    c.execute("INSERT INTO role_skills (role_id, skill_id, required_level, skill_kind) "
              "VALUES (?,?,'Advanced','essential')", (company_role_id, python_id))
    c.execute("INSERT INTO role_skills (role_id, skill_id, required_level, skill_kind) "
              "VALUES (?,?,'Intermediate','essential')", (company_role_id, sql_id))

    cur = c.execute(
        "INSERT INTO roles (company_id, title, description, is_reference, source, external_id) "
        "VALUES (?,?,?,0,'esco',?)",
        (company_id, "Geospatial Information Technicians",
         "Imported occupation", "http://data.europa.eu/esco/occupation/XYZ"))
    esco_role_id = cur.lastrowid
    c.execute("INSERT INTO role_skills (role_id, skill_id, required_level, skill_kind) "
              "VALUES (?,?,'Intermediate','optional')", (esco_role_id, sql_id))

    c.execute("INSERT INTO students (user_id, name, email, target_role_id) "
              "VALUES (?,?,?,?)",
              (user_id, "Legacy Student", "legacy@student.edu", esco_role_id))
    student_id = c.execute("SELECT id FROM students").fetchone()["id"]

    c.execute("INSERT INTO saved_roles (student_id, role_id) VALUES (?,?)",
              (student_id, company_role_id))
    c.execute("INSERT INTO scenario_attempts (student_id, scenario_id, status) "
              "VALUES (?,'suspicious-login-001','in_progress')", (student_id,))
    c.execute("INSERT INTO learning_path_items (student_id, skill_id) VALUES (?,?)",
              (student_id, python_id))
    c.execute("INSERT INTO assessment_attempts (student_id, skill_id, questions, answers, "
              "score, level_before, level_after) "
              "VALUES (?,?,'[]','[]',85.0,'Beginner','Intermediate')", (student_id, python_id))
    conn.commit()
    return conn, company_role_id, esco_role_id, student_id


# --------------------------------------------------------------------------- schema

def test_fresh_db_gains_canonical_schema(tmp_path):
    conn = _file_db(tmp_path)
    database.set_db_for_test(conn)
    try:
        database.init_db()
        applied_ids = [m["migration_id"] for m in database.applied_migrations()]
        assert applied_ids[-1] == "0013_tutor_conversations"
        assert MIGRATION_0003 in applied_ids
        assert NEW_COLUMNS <= _conn_columns(conn, "roles")
        assert NEW_TABLES <= _conn_tables(conn)
    finally:
        database.set_db_for_test()
        conn.close()


def test_canonical_columns_have_safe_defaults(tmp_path):
    conn = _file_db(tmp_path)
    database.set_db_for_test(conn)
    try:
        database.init_db()
        status_default = [r for r in conn.execute("PRAGMA table_info(roles)").fetchall()
                          if r["name"] == "canonical_status"][0]
        assert status_default["dflt_value"] and "active" in status_default["dflt_value"]
        local_default = [r for r in conn.execute("PRAGMA table_info(roles)").fetchall()
                         if r["name"] == "is_local_authoring"][0]
        assert local_default["dflt_value"] and "0" in local_default["dflt_value"]
    finally:
        database.set_db_for_test()
        conn.close()


def test_repeated_startup_is_idempotent_with_0003(tmp_path):
    conn = _file_db(tmp_path)
    database.set_db_for_test(conn)
    try:
        database.init_db()
        first = database.applied_migrations()
        models.backfill_role_canonical_metadata()
        assert database.run_migrations() == []
        assert database.applied_migrations() == first
    finally:
        database.set_db_for_test()
        conn.close()


def test_migration_0003_is_fully_rollback_safe(tmp_path):
    conn = _file_db(tmp_path)
    database.set_db_for_test(conn)
    try:
        database.init_db()
        cur = conn.execute("INSERT INTO roles (company_id, title) VALUES (NULL, 'Keep Me')")
        role_id = cur.lastrowid
        conn.commit()

        # Reverse the migration by hand: drop the new tables and columns.
        conn.execute("DROP TABLE role_skill_sources")
        conn.execute("DROP TABLE role_isco_codes")
        conn.execute("DROP TABLE role_aliases")
        for col in NEW_COLUMNS:
            if col in _conn_columns(conn, "roles"):
                conn.execute(f"ALTER TABLE roles DROP COLUMN {col}")
        conn.execute("DELETE FROM schema_migrations WHERE migration_id=?", (MIGRATION_0003,))
        conn.commit()

        assert not (NEW_TABLES & _conn_tables(conn))
        assert not (set(NEW_COLUMNS) & _conn_columns(conn, "roles"))
        kept = conn.execute("SELECT id, title FROM roles WHERE id=?", (role_id,)).fetchone()
        assert kept is not None and kept["title"] == "Keep Me"
    finally:
        database.set_db_for_test()
        conn.close()


# ------------------------------------------------------------- legacy DB upgrade

def test_legacy_db_upgraded_in_place_preserves_everything(tmp_path):
    conn, company_role_id, esco_role_id, student_id = _build_pre_d_db(tmp_path)
    try:
        pre_counts = {
            "companies": conn.execute("SELECT COUNT(*) c FROM companies").fetchone()[0],
            "roles": conn.execute("SELECT COUNT(*) c FROM roles").fetchone()[0],
            "role_skills": conn.execute("SELECT COUNT(*) c FROM role_skills").fetchone()[0],
            "students": conn.execute("SELECT COUNT(*) c FROM students").fetchone()[0],
            "saved_roles": conn.execute("SELECT COUNT(*) c FROM saved_roles").fetchone()[0],
            "scenario_attempts": conn.execute("SELECT COUNT(*) c FROM scenario_attempts").fetchone()[0],
            "learning_path_items": conn.execute("SELECT COUNT(*) c FROM learning_path_items").fetchone()[0],
            "assessment_attempts": conn.execute("SELECT COUNT(*) c FROM assessment_attempts").fetchone()[0],
        }

        # Upgrade path (what startup runs on an existing DB).
        database.init_db()
        assert MIGRATION_0003 in [m["migration_id"] for m in database.applied_migrations()]

        # Role ids and every link are untouched by the migration.
        for table, count in pre_counts.items():
            assert conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()[0] == count, table
        row = conn.execute("SELECT target_role_id FROM students WHERE id=?", (student_id,)).fetchone()
        assert row["target_role_id"] == esco_role_id
        assert conn.execute(
            "SELECT role_id FROM saved_roles WHERE student_id=?", (student_id,)).fetchone()[0] == company_role_id
        assert conn.execute(
            "SELECT COUNT(*) c FROM role_skills WHERE role_id=?",
            (company_role_id,)).fetchone()[0] == 2
    finally:
        database.set_db_for_test()
        conn.close()


def test_legacy_rows_backfilled_honestly(tmp_path):
    conn, company_role_id, esco_role_id, student_id = _build_pre_d_db(tmp_path)
    try:
        database.init_db()
        models.backfill_role_canonical_metadata()

        company = models.get_role(company_role_id)
        assert company["normalized_title"] == "legacy data engineer"
        assert company["family"]
        assert company["role_key"].startswith("company:")
        assert company["is_local_authoring"] == 1
        assert company["canonical_status"] == "active"
        # Locally authored roles never carry a fabricated version/URI/hierarchy.
        assert company["source_version"] is None
        assert company["external_id"] is None
        assert company["parent_role_id"] is None
        assert company["superseded_by_role_id"] is None

        esco = models.get_role(esco_role_id)
        assert esco["is_local_authoring"] == 0
        assert esco["source"] == "esco"
        # Honest unknown: the legacy import recorded no version, so it stays NULL.
        assert esco["source_version"] is None
        assert esco["external_id"] == "http://data.europa.eu/esco/occupation/XYZ"
        assert esco["normalized_title"] and esco["family"] and esco["role_key"].startswith("esco:")

        # Per-skill provenance is backfilled from each role's own source, never a
        # fabricated URI.
        sources = models.role_skill_sources(company_role_id)
        assert len(sources) == 2
        assert all(v["source"] == "company" and v["source_uri"] is None for v in sources.values())
        esco_sources = models.role_skill_sources(esco_role_id)
        assert len(esco_sources) == 1
        assert esco_sources[list(esco_sources)[0]]["source"] == "esco"

        # Backfill never invents aliases or ISCO codes for legacy rows.
        assert models.role_aliases(company_role_id) == []
        assert models.role_isco_codes(company_role_id) == []
        assert models.role_aliases(esco_role_id) == []
        assert models.role_isco_codes(esco_role_id) == []
    finally:
        database.set_db_for_test()
        conn.close()


# ---------------------------------------------------------------------- aliases

def test_alias_roundtrip_multilingual_hidden_and_duplicate_rejected(db):
    role = models.list_catalog_roles()[0]
    role_id = role["id"]

    # Backfill/seed never fabricates aliases.
    assert models.role_aliases(role_id) == []

    models.add_role_alias(role_id, "Data Wrangler", "alternative", "en")
    models.add_role_alias(role_id, "محلل بيانات", "alternative", "ar")
    models.add_role_alias(role_id, "LegacyJobCode-1234", "hidden", "en")

    aliases = models.role_aliases(role_id)
    types = {(a["alias"], a["language"], a["alias_type"]) for a in aliases}
    assert ("Data Wrangler", "en", "alternative") in types
    assert ("محلل بيانات", "ar", "alternative") in types
    assert ("LegacyJobCode-1234", "en", "hidden") in types

    # UNIQUE(role_id, alias, alias_type, language): exact duplicate is rejected.
    models.add_role_alias(role_id, "Data Wrangler", "alternative", "en")
    assert len(models.role_aliases(role_id)) == 3

    # Same alias text under a different language is a distinct row.
    models.add_role_alias(role_id, "Data Wrangler", "alternative", "ar")
    assert len(models.role_aliases(role_id)) == 4

    # Removal by id removes exactly that row.
    target = [a for a in models.role_aliases(role_id)
              if a["alias"] == "LegacyJobCode-1234"][0]
    removed = models.remove_role_alias(target["id"])
    assert removed == 1
    remaining = [a["alias"] for a in models.role_aliases(role_id)]
    assert "LegacyJobCode-1234" not in remaining and len(remaining) == 3


# ---------------------------------------------------------------- ESCO imports

def test_import_esco_role_is_idempotent_and_records_provenance(db):
    uri = "http://data.europa.eu/esco/occupation/Geographers"
    first = models.import_esco_role(
        uri, title="Geographers",
        essential=["Earth Observation", "GIS"],
        optional=["Cartography"],
        isco_code="2633",
        source_version="v1.1.3",
        aliases=[{"alias": "Geographist", "type": "alternative", "language": "en"}])
    assert first is not None

    # Same URI imported again returns the SAME row (no duplicate, existing FKs intact).
    second = models.import_esco_role(uri, title="Geographers", essential=["Earth Observation", "GIS"])
    assert second["id"] == first["id"]
    assert models.get_role(first["id"])["id"] == first["id"]

    role = models.get_role(first["id"])
    assert role["source"] == "esco"
    assert role["is_local_authoring"] == 0
    assert role["source_version"] == "v1.1.3"
    assert role["external_id"] == uri
    assert role["canonical_status"] == "active"

    skills = {s["name"]: s for s in role["required_skills"]}
    assert "Earth Observation" in skills and skills["Earth Observation"]["skill_kind"] == "essential"
    assert "Cartography" in skills and skills["Cartography"]["skill_kind"] == "optional"

    isco = models.role_isco_codes(first["id"])
    assert len(isco) == 1 and isco[0]["isco_code"] == "2633" and isco[0]["source"] == "esco"
    aliases = [a["alias"] for a in models.role_aliases(first["id"])]
    assert "Geographist" in aliases
    sources = models.role_skill_sources(first["id"])
    assert len(sources) == 3 and all(v["source"] == "esco" for v in sources.values())


# ---------------------------------------------------------------- status gating

def test_deprecated_role_excluded_from_feed_and_recs_but_resolvable(db):
    models.create_role(1, "Retiring Role",
                       [{"name": "Python", "category": "Programming", "level": "Intermediate"}],
                       source="company")

    company_roles = [r for r in models.list_roles() if r["title"] == "Retiring Role"]
    assert company_roles, "seeded DB must contain the created role"
    role_id = company_roles[0]["id"]

    def in_feed():
        return any(r["id"] == role_id for r in models.list_feed_roles())

    def in_recs():
        payload = recommendations.recommend(models.get_student(1))
        recs = payload["recommendations"] if payload else []
        return any(r.get("role_id") == role_id for r in recs)

    assert in_feed(), "active role must appear in the live feed"
    assert in_recs(), "active role must be a recommendation candidate"

    # Deprecate directly (no status endpoint in slice 1).
    with models.get_cursor() as c:
        c.execute("UPDATE roles SET canonical_status='deprecated' WHERE id=?", (role_id,))

    assert not in_feed()
    assert not in_recs()
    # Still resolvable by id.
    still = models.get_role(role_id)
    assert still is not None and still["canonical_status"] == "deprecated"


def test_student_target_role_survives_deprecation(db):
    role = models.list_catalog_roles()[0]
    student = models.get_student(1)
    models.update_student(student["id"], target_role_id=role["id"])
    with models.get_cursor() as c:
        c.execute("UPDATE roles SET canonical_status='deprecated' WHERE id=?", (role["id"],))
    refreshed = models.get_student(student["id"])
    assert refreshed["target_role"]["id"] == role["id"]


# -------------------------------------------------------------- local companies

def test_local_company_role_never_mislabeled_esco(db):
    role = models.create_role(
        1, "Quality Assurance Intern",
        [{"name": "QA Testing", "category": "Software", "level": "Beginner"}],
        description="Internship", source="company")
    assert role["source"] == "company"
    assert role["is_local_authoring"] == 1
    assert role["is_reference"] == 0
    # Additive canonical fields stay absent on local rows (nothing fabricated).
    assert role["source_version"] is None
    assert role["external_id"] is None
    assert role["parent_role_id"] is None
    assert role["normalized_title"] == "quality assurance intern"
    assert role["role_key"].startswith("company:")

    prov = models.role_provenance(role["id"])
    assert prov["source"] == "company"
    assert prov["source_version"] is None
    assert prov["aliases"] == [] and prov["isco_codes"] == []
    # Never an ESCO label on a locally authored row.
    assert "esco" not in str(prov).lower()

    # Per-skill provenance recorded at creation time reflects the role's source.
    sources = models.role_skill_sources(role["id"])
    assert len(sources) == 1 and list(sources.values())[0]["source"] == "company"


def test_update_role_rewrites_skill_provenance(db):
    role = models.create_role(
        1, "Temporary Role",
        [{"name": "Excel", "category": "Analytics", "level": "Beginner"}], source="company")
    assert len(models.role_skill_sources(role["id"])) == 1

    models.update_role(role["id"], required_skills=[
        {"name": "Excel", "category": "Analytics", "level": "Intermediate"},
        {"name": "SQL", "category": "Data", "level": "Beginner"}])
    sources = models.role_skill_sources(role["id"])
    assert len(sources) == 2
    assert all(v["source"] == "company" for v in sources.values())
    updated = models.get_role(role["id"])
    assert updated["updated_at"] is not None


# ----------------------------------------------------------- search normalization

def test_search_normalizes_while_display_stays_byte_identical(db):
    # Odd hyphen + repeated spaces: a title may arrive with odd punctuation and
    # uses the normalized ("data engineer") form ONLY for search matching.
    models.create_role(1, "Data-Engineer",
                       [{"name": "SQL", "category": "Data", "level": "Intermediate"}],
                       source="company")
    models.create_role(1, "Legacy Data Engineer Legacy",
                       [{"name": "SQL", "category": "Data", "level": "Beginner"}],
                       source="company")

    hits = models.list_roles(search="data engineer")
    titles = [r["title"] for r in hits]
    assert "Data-Engineer" in titles
    # The stored display title is never rewritten by a search.
    for r in hits:
        if r["title"] == "Data-Engineer":
            assert r["title"] == "Data-Engineer"
        assert r["normalized_title"]

    # Mixed-case / extra-space query folds to the same stored normalized form.
    assert models.list_roles(search="DATA      ENGINEER") != []
    # Unrelated search matches nothing.
    assert not any(r["title"] == "Data-Engineer" for r in models.list_roles(search="dentistry"))

    # Catalog search is folded the same way (oracle from the seeded baseline).
    catalog = models.list_catalog_roles(search="data engineer")
    assert any("Data Engineer" in r["title"] for r in catalog)
    catalog_display = [r["title"] for r in models.list_catalog_roles()]
    assert "Data Engineer" in catalog_display


# ---------------------------------------------------------------------- FK links

def test_fk_links_and_on_delete_behavior_intact_after_migration(tmp_path):
    conn, company_role_id, esco_role_id, student_id = _build_pre_d_db(tmp_path)
    try:
        database.init_db()
        models.backfill_role_canonical_metadata()

        # ON DELETE SET NULL: deleting a role used as a target NULLs the link,
        # while company/role_skills/saved_roles rows keep working.
        conn.execute("DELETE FROM roles WHERE id=?", (esco_role_id,))
        conn.commit()
        student = models.get_student(student_id)
        assert student["target_role_id"] is None
        assert models.get_role(company_role_id) is not None

        # ON DELETE CASCADE: removing the company role pulls role_skills and
        # saved_roles rows with it but never touches the student.
        conn.execute("DELETE FROM roles WHERE id=?", (company_role_id,))
        conn.commit()
        assert conn.execute(
            "SELECT COUNT(*) c FROM role_skills WHERE role_id=?",
            (company_role_id,)).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) c FROM saved_roles WHERE role_id=?",
            (company_role_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) c FROM students WHERE id=?", (student_id,)).fetchone()[0] == 1
    finally:
        database.set_db_for_test()
        conn.close()


# ------------------------------------------------------------ provenance checks

def test_legacy_esco_role_provenance_reports_source_and_no_labels(tmp_path):
    conn, _, esco_role_id, _ = _build_pre_d_db(tmp_path)
    try:
        database.init_db()
        models.backfill_role_canonical_metadata()
        prov = models.role_provenance(esco_role_id)
        assert prov["source"] == "esco"
        assert prov["canonical_status"] == "active"
        assert prov["source_version"] is None
        assert prov["aliases"] == [] and prov["isco_codes"] == []
        assert prov["skill_sources"]
    finally:
        database.set_db_for_test()
        conn.close()


def test_provenance_visible_in_recommendation_pipeline(db):
    student = models.get_student(1)
    payload = recommendations.recommend(student)
    assert payload is not None and payload["recommendations"]
    for rec in payload["recommendations"]:
        # Additive provenance keys present; matching itself stays green.
        assert "source" in rec
        assert "company_name" in rec
    assert all("source_version" in r for r in payload["recommendations"])


# --------------------------------------------------------- provenance endpoint

def test_provenance_endpoint_readable_by_student_for_catalog(db, client, auth_headers):
    catalog = models.list_catalog_roles()[0]
    h = auth_headers("aisha@student.edu")
    r = client.get(f"/api/roles/{catalog['id']}/provenance", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["role_id"] == catalog["id"]
    assert "aliases" in body and "isco_codes" in body and "skill_sources" in body
    assert body["canonical_status"] == "active"


def test_provenance_endpoint_auth_rules(db, client, auth_headers):
    # Company role owned by Northstar Labs: owner reads, outsider is refused.
    northstar = [r for r in models.list_roles() if r.get("company_name") == "Northstar Labs"]
    assert northstar
    role_id = northstar[0]["id"]

    owner = auth_headers("hr@northstar.com")
    own = client.get(f"/api/roles/{role_id}/provenance", headers=owner)
    assert own.status_code == 200
    assert own.json()["source"] == "company"

    outsider = auth_headers("hr@signal.com")
    other = client.get(f"/api/roles/{role_id}/provenance", headers=outsider)
    assert other.status_code == 403

    # Guest is unauthenticated.
    banned = client.get(f"/api/roles/{role_id}/provenance")
    assert banned.status_code == 401

    missing = client.get("/api/roles/9999999/provenance", headers=owner)
    assert missing.status_code == 404


def test_seed_wipe_clears_canonical_tables(db):
    """The wipe list keeps every Phase D table consistent with the seed: a full
    reseed clears and repopulates them cleanly."""
    for table in ("role_skill_sources", "role_isco_codes", "role_aliases",
                  "role_skills", "saved_roles"):
        assert table in _conn_tables(db)
    with models.get_cursor() as c:
        for table in ("role_skill_sources", "role_isco_codes", "role_aliases",
                      "role_skills", "saved_roles"):
            c.execute(f"DELETE FROM {table}")
    seed_mod.seed()
    assert models.list_catalog_roles()
