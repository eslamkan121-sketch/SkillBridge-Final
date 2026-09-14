"""Phase E Slice 2 — migration 0004 + dry-run plan engine (offline).

Same guarantee as Slice 1: everything resolves through the FixtureTransport.
The only row writes here are the *test arranging* its own managed state via
models.import_esco_role + a manual imprint stamp; the plan engine itself
(plan_refresh / preview) is asserted to never mutate role data.
"""

import os
import sqlite3

import pytest

from app import database, esco_import, models

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "esco")

URI_1 = "http://data.europa.eu/esco/occupation/174b1a5b-f93b-4d5e-b2b2-c6a2a5c9d001"
URI_2 = "http://data.europa.eu/esco/occupation/286c2b6c-a04c-5e6f-c3c3-d7b3b6dae112"
URI_3 = "http://data.europa.eu/esco/occupation/397d3c7d-b15d-6f70-d4d4-e8c4c7ebf223"
URI_4 = "http://data.europa.eu/esco/occupation/4a8e4d8e-c26e-7081-e5e5-f9d5d8fc4344"
URI_5 = "http://data.europa.eu/esco/occupation/5b9f5e9f-d37f-8192-f6f6-0ae6e90d5455"

MIGRATION_0004 = "0004_esco_import"
MIGRATION_0005 = "0005_company_role_mapping"


def _fixture():
    return esco_import.FixtureTransport(FIXTURES)


def _v120_fetch(uri, lang="en"):
    return _fixture().fetch_occupation(uri, language=lang, version="1.2.0")


def _v121_fetch(uri):
    return _fixture().fetch_occupation(uri, language="en", version="1.2.1")


def _search_full(version="1.2.0", lang="en", query="data engineer"):
    """Search stubs upgraded to full resource records, exactly as preview does."""
    fixture = _fixture()
    stubs = list(fixture.iter_search(query, language=lang, version=version))
    return esco_import.enrich_occupations(fixture, stubs, lang, version)


def _import_managed(uri, *, version="1.2.0", lang="en"):
    """Import an occupation then stamp it as a *managed* row (imprint present,
    imported_at == updated_at) exactly as a real apply would leave it."""
    occ = _fixture().fetch_occupation(uri, language=lang, version=version)
    role = models.import_esco_role(occ.uri, occ.title, occ.essential, occ.optional)
    imprint = esco_import.occupation_imprint(occ)
    now = models._now()
    with database.get_cursor() as conn:
        conn.execute(
            "UPDATE roles SET import_imprint=?, imported_at=?, updated_at=?, "
            "source_version=?, source_language=? WHERE id=?",
            (imprint, now, now, version, lang, role["id"]))
    return role, occ


def _role_counts():
    def count(table):
        with database.get_cursor() as conn:
            return conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
    return {t: count(t) for t in ("roles", "role_skills", "role_aliases",
                                  "role_isco_codes", "role_skill_sources")}


# ------------------------------------------------------------------ migration 0004


def test_migration_0004_on_fresh_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "e.db"))
    conn.row_factory = sqlite3.Row
    database.set_db_for_test(conn)
    try:
        database.init_db()
        applied = [m["migration_id"] for m in database.applied_migrations()]
        assert applied[-1] == "0013_tutor_conversations"
        role_cols = {r["name"] for r in conn.execute("PRAGMA table_info(roles)")}
        assert {"source_language", "import_imprint"} <= role_cols
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"esco_import_runs", "esco_import_changes"} <= tables
        run_cols = {r["name"] for r in conn.execute("PRAGMA table_info(esco_import_runs)")}
        assert {"mode", "status", "version", "language", "triggered_by_user_id",
                "previewed_run_id", "started_at", "finished_at", "error", "stats_json"} <= run_cols
        assert database.run_migrations() == []
    finally:
        database.set_db_for_test()
        conn.close()


def test_migration_0004_upgrades_pre_0004_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "old-e.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    database.set_db_for_test(conn)
    try:
        pre = [m for m in database.MIGRATIONS
               if m["id"] not in (MIGRATION_0004, MIGRATION_0005, "0006_saved_jobs_tracker", "0007_role_view_events", "0008_job_link_reports", "0009_copilot_config", "0010_copilot_onboarding", "0011_mentor_keys", "0012_tutor_memory", "0013_tutor_conversations")]
        database.run_migrations(conn=conn, migrations=pre)
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "esco_import_runs" not in tables
        pending = database.run_migrations()
        assert pending == [MIGRATION_0004, MIGRATION_0005, "0006_saved_jobs_tracker", "0007_role_view_events", "0008_job_link_reports", "0009_copilot_config", "0010_copilot_onboarding", "0011_mentor_keys", "0012_tutor_memory", "0013_tutor_conversations"]
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "esco_import_runs" in tables
    finally:
        database.set_db_for_test()
        conn.close()


# ------------------------------------------------------------------ imprint


def test_imprint_is_deterministic_and_sensitive():
    occ = _v120_fetch(URI_1)
    assert esco_import.occupation_imprint(occ) == esco_import.occupation_imprint(occ)
    changed = esco_import.EscoOccupation(
        uri=occ.uri, title=occ.title, alt_titles=occ.alt_titles,
        hidden_titles=occ.hidden_titles, code=occ.code, description=occ.description,
        essential=("entirely different skill",), optional=occ.optional,
        parent_uri=occ.parent_uri, language=occ.language)
    assert esco_import.occupation_imprint(changed) != esco_import.occupation_imprint(occ)


# ------------------------------------------------------------------ plan on empty DB


def test_plan_on_empty_db_lists_new_occupations_as_adds(db):
    occs = _search_full(version="1.2.0")
    changes, stats = esco_import.plan_refresh(occs, version="1.2.0", language="en")
    assert stats["add"] == 3
    assert all(c.action == "add" and c.role_id is None for c in changes)
    assert {c.uri for c in changes} == {URI_1, URI_2, URI_3}


# ------------------------------------------------------------------ dry-run preview


def test_preview_persists_run_and_never_mutates_roles(db):
    before = _role_counts()
    out = esco_import.preview(_fixture(), version="1.2.0", language="en",
                              query="data engineer", triggered_by_user_id=1)
    assert out["status"] == "succeeded"
    assert out["stats"]["add"] == 3
    assert out["version"] == "1.2.0"
    run = esco_import.get_import_run(out["run_id"])
    assert run["mode"] == "dry_run"
    assert run["status"] == "succeeded"
    assert run["version"] == "1.2.0"
    assert run["language"] == "en"
    assert run["triggered_by_user_id"] == 1
    rows = esco_import.get_run_changes(out["run_id"])
    assert len(rows) == 3
    assert {r["action"] for r in rows} == {"add"}
    assert _role_counts() == before


def test_preview_by_uri_fetches_resources(db):
    out = esco_import.preview(_fixture(), version="1.2.0", language="en",
                              uris=[URI_1, URI_2])
    assert out["status"] == "succeeded"
    assert {c["uri"] for c in out["changes"]} == {URI_1, URI_2}
    assert all(c["action"] == "add" for c in out["changes"])


def test_preview_records_failed_run_on_transport_error(db):
    class _Boom:
        def iter_search(self, *a, **kw):
            raise esco_import.EscoUnavailableError("esco unavailable in test")

    out = esco_import.preview(_Boom(), version="1.2.0", language="en", query="data")
    assert out["status"] == "failed"
    run = esco_import.get_import_run(out["run_id"])
    assert run["status"] == "failed"
    assert "unavailable" in run["error"]


# ------------------------------------------------------------------ repeat / changed upstream / deprecation / conflict


def test_refresh_of_unchanged_managed_set_is_all_noop(db):
    _import_managed(URI_1)
    occs = _search_full(version="1.2.0")
    changes, stats = esco_import.plan_refresh(occs, version="1.2.0", language="en")
    by_uri = {c.uri: c for c in changes}
    assert by_uri[URI_1].action == "noop"
    assert stats["noop"] == 1
    assert stats["add"] == 2  # occ-2, occ-3 not yet managed


def test_upstream_change_is_detected_not_conflict(db):
    role, _ = _import_managed(URI_1)
    occs = _search_full(version="1.2.1")
    changes, stats = esco_import.plan_refresh(occs, version="1.2.1", language="en")
    by_uri = {c.uri: c for c in changes}
    assert by_uri[URI_1].action == "change"          # occ-1 retitled + new skill (v1.2.1)
    assert by_uri[URI_1].role_id == role["id"]
    assert stats["change"] == 1


def test_local_edit_gates_upstream_change_as_conflict(db):
    role, _ = _import_managed(URI_1)
    later = "2099-01-01 00:00:00"
    with database.get_cursor() as conn:
        conn.execute("UPDATE roles SET updated_at=? WHERE id=?", (later, role["id"]))
    occs = _search_full(version="1.2.1")
    changes, stats = esco_import.plan_refresh(occs, version="1.2.1", language="en")
    by_uri = {c.uri: c for c in changes}
    assert by_uri[URI_1].action == "conflict"
    assert by_uri[URI_1].role_id == role["id"]
    assert stats["conflict"] == 1
    assert stats.get("change", 0) == 0


def test_removed_occupation_with_unique_successor_is_superseded(db):
    _import_managed(URI_2)  # "Big data specialist" at v1.2.0
    occs = _search_full(version="1.2.1")
    changes, stats = esco_import.plan_refresh(occs, version="1.2.1", language="en")
    by_uri = {c.uri: c for c in changes}
    sup = by_uri[URI_2]
    assert sup.action == "supersede"
    assert sup.detail["successor_uri"] == URI_5
    assert sup.detail["successor_title"] == "Big data specialist"
    assert stats["supersede"] == 1


def test_removed_occupation_without_successor_is_deprecated(db):
    _import_managed(URI_3)  # "Data scientist" only exists at v1.2.0
    occs = _search_full(version="1.2.1")
    changes, stats = esco_import.plan_refresh(occs, version="1.2.1", language="en")
    by_uri = {c.uri: c for c in changes}
    assert by_uri[URI_3].action == "deprecate"
    assert stats["deprecate"] == 1


def test_previously_deprecated_rows_are_left_alone(db):
    role, _ = _import_managed(URI_3)
    with database.get_cursor() as conn:
        conn.execute("UPDATE roles SET canonical_status='deprecated' WHERE id=?",
                     (role["id"],))
    occs = _search_full(version="1.2.1")
    changes, stats = esco_import.plan_refresh(occs, version="1.2.1", language="en")
    assert URI_3 not in {c.uri for c in changes}
    assert stats.get("deprecate", 0) == 0


def test_unmanaged_existing_row_is_reported_but_never_removed(db):
    occ = _v120_fetch(URI_3)
    models.import_esco_role(occ.uri, occ.title, occ.essential, occ.optional)  # no imprint
    occs = _search_full(version="1.2.0")
    changes, stats = esco_import.plan_refresh(occs, version="1.2.0", language="en")
    by_uri = {c.uri: c for c in changes}
    assert URI_3 in by_uri and by_uri[URI_3].action == "unmanaged"
    assert stats["unmanaged"] == 1
    assert stats.get("deprecate", 0) == 0
    # deprecation only ever applies to managed rows, so the unmanaged row's
    # canonical_status remains the honest default.
    with database.get_cursor() as conn:
        st = conn.execute("SELECT canonical_status FROM roles WHERE external_id=?",
                          (URI_3,)).fetchone()["canonical_status"]
    assert st == "active"


def test_full_v120_to_v121_refresh_plan(db):
    _import_managed(URI_1)
    _import_managed(URI_2)
    _import_managed(URI_3)
    before = _role_counts()
    occs = _search_full(version="1.2.1")
    changes, stats = esco_import.plan_refresh(occs, version="1.2.1", language="en")
    actions = {c.uri: c.action for c in changes}
    assert actions[URI_1] == "change"
    assert actions[URI_2] == "supersede"
    assert actions[URI_3] == "deprecate"
    assert actions[URI_4] == "add"
    assert actions[URI_5] == "add"
    assert stats["change"] == 1 and stats["supersede"] == 1
    assert stats["deprecate"] == 1 and stats["add"] == 2
    assert _role_counts() == before
