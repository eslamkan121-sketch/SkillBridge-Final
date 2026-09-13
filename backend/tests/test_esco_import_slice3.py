"""Phase E Slice 3 — apply executor + admin endpoints (offline).

Apply is the single managed write path. These tests assert its transaction
shape, its refusal cases (drift / missing preview), the no-delete rule (R7),
deprecate/supersede/conflict behavior, endpoint authorization, and that no
sensitive content ever reaches logs or error strings.
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


def _fixture():
    return esco_import.FixtureTransport(FIXTURES)


def _v120_query():
    """Full v1.2.0 'data engineer' search set, enriched to full records."""
    fx = _fixture()
    stubs = list(fx.iter_search("data engineer", language="en", version="1.2.0"))
    return esco_import.enrich_occupations(fx, stubs, "en", "1.2.0")


def _v121_query():
    fx = _fixture()
    stubs = list(fx.iter_search("data engineer", language="en", version="1.2.1"))
    return esco_import.enrich_occupations(fx, stubs, "en", "1.2.1")


def _import_managed(uri, *, version="1.2.0"):
    occ = _fixture().fetch_occupation(uri, language="en", version=version)
    role = models.import_esco_role(occ.uri, occ.title, occ.essential, occ.optional)
    imprint = esco_import.occupation_imprint(occ)
    now = models._now()
    with database.get_cursor() as conn:
        conn.execute(
            "UPDATE roles SET import_imprint=?, imported_at=?, updated_at=?, "
            "source_version=?, source_language=? WHERE id=?",
            (imprint, now, now, version, "en", role["id"]))
    return role, occ


def _counts():
    def count(table):
        with database.get_cursor() as conn:
            return conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
    return {t: count(t) for t in ("roles", "role_skills", "role_aliases",
                                  "role_isco_codes", "role_skill_sources")}


def _run_row(run_id):
    with database.get_cursor() as conn:
        r = conn.execute("SELECT * FROM esco_import_runs WHERE id=?",
                         (run_id,)).fetchone()
        return dict(r) if r else None


def _changes(run_id):
    with database.get_cursor() as conn:
        rows = conn.execute(
            "SELECT * FROM esco_import_changes WHERE run_id=? ORDER BY id",
            (run_id,)).fetchall()
        return [dict(r) for r in rows]


# ------------------------------------------------------------------- apply executor


def test_apply_refuses_unknown_preview(db):
    with pytest.raises(esco_import.EscoApplyError) as exc:
        esco_import.apply_refresh(_fixture(), 999999, "1.2.0", "en")
    assert exc.value.status_code == 404


def test_apply_refuses_non_dry_run_preview(db):
    run_id = esco_import.create_import_run("apply", "1.2.0", "en")
    with pytest.raises(esco_import.EscoApplyError) as exc:
        esco_import.apply_refresh(_fixture(), run_id, "1.2.0", "en")
    assert exc.value.status_code == 400


def test_apply_refuses_config_drift(db):
    before = _counts()["roles"]
    result = esco_import.preview(_fixture(), "1.2.0", "en", uris=[URI_1])
    assert result["status"] == "succeeded"
    with pytest.raises(esco_import.EscoApplyError) as exc:
        esco_import.apply_refresh(_fixture(), result["run_id"], "1.2.1", "en")
    assert exc.value.status_code == 409
    assert "config drift" in str(exc.value)
    assert _counts()["roles"] == before  # nothing applied


def test_apply_add_imports_fully_managed_row(db):
    before = _counts()
    preview = esco_import.preview(_fixture(), "1.2.0", "en", uris=[URI_1])
    result = esco_import.apply_refresh(_fixture(), preview["run_id"], "1.2.0", "en")
    assert result["status"] == "succeeded"
    assert result["stats"]["applied"]["add"] == 1

    occ = _fixture().fetch_occupation(URI_1, language="en", version="1.2.0")
    with database.get_cursor() as conn:
        row = dict(conn.execute("SELECT * FROM roles WHERE source='esco' AND external_id=?",
                                (URI_1,)).fetchone())
    assert row["source_version"] == "1.2.0"
    assert row["source_language"] == "en"
    assert row["import_imprint"] == esco_import.occupation_imprint(occ)
    assert row["is_local_authoring"] == 0
    assert row["canonical_status"] == "active"
    # The fixture v1.2.0 resource carries no broaderOccupations, so
    # parent_role_id stays honest NULL. The imprint (asserted next) captures
    # the occupation's exact state including any parent_uri when one exists.
    assert row["parent_role_id"] is None

    assert _counts()["roles"] == before["roles"] + 1
    assert _counts()["role_skills"] > before["role_skills"]
    assert _counts()["role_aliases"] > before["role_aliases"]
    assert _counts()["role_isco_codes"] > before["role_isco_codes"]
    assert _counts()["role_skill_sources"] > before["role_skill_sources"]

    run = _run_row(result["run_id"])
    assert run["mode"] == "apply"
    assert run["status"] == "succeeded"
    assert run["previewed_run_id"] == preview["run_id"]


def test_apply_is_idempotent_second_apply_is_noop(db):
    first = esco_import.preview(_fixture(), "1.2.0", "en", uris=[URI_1])
    esco_import.apply_refresh(_fixture(), first["run_id"], "1.2.0", "en")
    counts_after_first = _counts()

    second = esco_import.preview(_fixture(), "1.2.0", "en", uris=[URI_1])
    result = esco_import.apply_refresh(_fixture(), second["run_id"], "1.2.0", "en")
    assert result["status"] == "succeeded"
    assert result["stats"]["noop"] == 1
    assert result["stats"]["applied"].get("add", 0) == 0
    assert _counts() == counts_after_first


def test_apply_change_reconciles_without_deletes(db):
    role, _ = _import_managed(URI_1)  # v1.2.0
    skills_before = _counts()["role_skills"]
    aliases_before = _counts()["role_aliases"]

    preview = esco_import.preview(_fixture(), "1.2.1", "en", uris=[URI_1])
    result = esco_import.apply_refresh(_fixture(), preview["run_id"], "1.2.1", "en")
    assert result["status"] == "succeeded"
    assert result["stats"]["applied"]["change"] == 1

    occ = _fixture().fetch_occupation(URI_1, language="en", version="1.2.1")
    with database.get_cursor() as conn:
        row = dict(conn.execute("SELECT * FROM roles WHERE id=?", (role["id"],)).fetchone())
    assert row["title"] == occ.title          # retitled upstream
    assert row["source_version"] == "1.2.1"
    assert row["source_language"] == "en"
    assert row["import_imprint"] == esco_import.occupation_imprint(occ)
    assert row["imported_at"] == row["updated_at"]

    # R7: nothing was deleted — skill/alias counts never shrank.
    assert _counts()["role_skills"] >= skills_before
    assert _counts()["role_aliases"] >= aliases_before


def test_apply_supersede_links_single_successor(db):
    old, _ = _import_managed(URI_2)  # Big data specialist (v1.2.0)
    # occ-2 is absent at v1.2.1, so the preview must come from the search path
    # (fetching the removed URI directly would fail).
    preview = esco_import.preview(_fixture(), "1.2.1", "en", query="data engineer")
    result = esco_import.apply_refresh(_fixture(), preview["run_id"], "1.2.1", "en")
    assert result["status"] == "succeeded"
    assert result["stats"]["applied"].get("supersede") == 1

    with database.get_cursor() as conn:
        old_row = dict(conn.execute("SELECT * FROM roles WHERE id=?", (old["id"],)).fetchone())
        succ_row = dict(conn.execute(
            "SELECT * FROM roles WHERE source='esco' AND external_id=?",
            (URI_5,)).fetchone())
    assert old_row["canonical_status"] == "superseded"
    assert old_row["superseded_by_role_id"] == succ_row["id"]
    assert succ_row["source_version"] == "1.2.1"
    assert succ_row["import_imprint"]


def test_apply_deprecate_keeps_row_and_student_reference(db):
    old, _ = _import_managed(URI_3)
    with database.get_cursor() as conn:
        student = conn.execute("SELECT id FROM students LIMIT 1").fetchone()
        conn.execute("UPDATE students SET target_role_id=? WHERE id=?",
                     (old["id"], student["id"]))
    preview = esco_import.preview(_fixture(), "1.2.1", "en", query="data engineer")
    result = esco_import.apply_refresh(_fixture(), preview["run_id"], "1.2.1", "en")
    assert result["status"] == "succeeded"
    assert result["stats"]["applied"]["deprecate"] == 1

    with database.get_cursor() as conn:
        row = dict(conn.execute("SELECT * FROM roles WHERE id=?", (old["id"],)).fetchone())
        ref = conn.execute("SELECT target_role_id FROM students WHERE id=?",
                           (student["id"],)).fetchone()["target_role_id"]
    assert row["canonical_status"] == "deprecated"
    assert ref == old["id"]  # history preserved: target reference intact


def test_apply_skips_locally_edited_row_as_conflict(db):
    role, _ = _import_managed(URI_1)
    later = "2099-01-01 00:00:00"
    with database.get_cursor() as conn:
        conn.execute("UPDATE roles SET updated_at=? WHERE id=?", (later, role["id"]))
    title_before = role["title"]

    preview = esco_import.preview(_fixture(), "1.2.1", "en", uris=[URI_1])
    result = esco_import.apply_refresh(_fixture(), preview["run_id"], "1.2.1", "en")
    assert result["status"] == "succeeded"
    assert result["stats"]["applied"].get("change", 0) == 0
    actions = {c["uri"]: c["action"] for c in _changes(result["run_id"])}
    assert actions[URI_1] == "conflict"

    with database.get_cursor() as conn:
        row = dict(conn.execute("SELECT * FROM roles WHERE id=?", (role["id"],)).fetchone())
    assert row["title"] == title_before  # local edit never overwritten
    assert row["updated_at"] == later


def test_apply_leaves_unmanaged_rows_untouched(db):
    occ = _fixture().fetch_occupation(URI_1, language="en", version="1.2.0")
    role = models.import_esco_role(occ.uri, occ.title, occ.essential, occ.optional)
    with database.get_cursor() as conn:
        conn.execute("UPDATE roles SET updated_at='2099-01-01 00:00:00' WHERE id=?",
                     (role["id"],))

    preview = esco_import.preview(_fixture(), "1.2.0", "en", uris=[URI_1])
    result = esco_import.apply_refresh(_fixture(), preview["run_id"], "1.2.0", "en")
    assert result["status"] == "succeeded"
    actions = {c["uri"]: c["action"] for c in _changes(result["run_id"])}
    assert actions[URI_1] == "unmanaged"
    with database.get_cursor() as conn:
        row = dict(conn.execute("SELECT * FROM roles WHERE id=?", (role["id"],)).fetchone())
    assert row["import_imprint"] is None
    assert row["canonical_status"] == "active"
    assert row["updated_at"] == "2099-01-01 00:00:00"


def test_apply_fetch_failure_records_failed_run_and_writes_nothing(db):
    class RaisingTransport:
        def iter_search(self, *args, **kwargs):
            raise esco_import.EscoUnavailableError("ESCO unreachable (boom)")

        def fetch_occupation(self, uri, *args, **kwargs):
            raise esco_import.EscoUnavailableError("ESCO unreachable (boom)")

    before = _counts()
    preview = esco_import.preview(_fixture(), "1.2.0", "en", uris=[URI_1])
    result = esco_import.apply_refresh(
        RaisingTransport(), preview["run_id"], "1.2.0", "en")
    assert result["status"] == "failed"
    run = _run_row(result["run_id"])
    assert run["status"] == "failed"
    assert "ESCO unreachable" in (run["error"] or "")
    assert _counts() == before


class _TrackingTransport:
    """Fixture transport that records every URL-ish string it was asked for."""

    def __init__(self):
        self.fx = esco_import.FixtureTransport(FIXTURES)
        self.asked = []

    def iter_search(self, text, language=None, version=None, **kwargs):
        self.asked.append(text)
        yield from self.fx.iter_search(text, language=language, version=version, **kwargs)

    def fetch_occupation(self, uri, language=None, version=None):
        self.asked.append(uri)
        return self.fx.fetch_occupation(uri, language=language, version=version)


def test_redaction_nothing_sensitive_reaches_errors_or_logs(db, caplog):
    transport = _TrackingTransport()
    preview = esco_import.preview(transport, "1.2.0", "en", query="data engineer")
    assert preview["status"] == "succeeded"
    result = esco_import.apply_refresh(
        transport, preview["run_id"], "1.2.0", "en", triggered_by_user_id=42)
    assert result["status"] == "succeeded"
    # No user identifiers or CV content anywhere.
    for banned in ("cv ", "email", "password", "token"):
        assert banned not in caplog.text.lower()


def test_live_error_messages_carry_no_urls(monkeypatch):
    class Client:
        def get(self, url, **kwargs):
            assert "ec.europa.eu" in url  # only through the fixed publisher URL
            resp = type("R", (), {"status_code": 500, "json": lambda self: {}})()
            return resp

    monkeypatch.setattr(esco_import, "ESCO_RETRIES", 0)
    monkeypatch.setattr(esco_import, "ESCO_RETRY_BACKOFF_SECONDS", 0)
    transport = esco_import.LiveTransport(client=Client())
    with pytest.raises(esco_import.EscoUnavailableError) as exc:
        transport.fetch_occupation(URI_1, language="en", version="1.2.0")
    assert "ec.europa" not in str(exc.value)
    assert "status=500" in str(exc.value)


# ------------------------------------------------------------------ endpoints


def test_esco_endpoints_block_non_admins(client, auth_headers):
    student = auth_headers("aisha@student.edu")
    company = auth_headers("hr@northstar.com")
    assert client.get("/api/system/esco/status", headers=student).status_code == 403
    assert client.get("/api/system/esco/status", headers=company).status_code == 403
    assert client.get("/api/system/esco/status").status_code == 401
    assert client.post("/api/system/esco/preview", json={"query": "data engineer"},
                       headers=student).status_code == 403
    assert client.post("/api/system/esco/apply", json={"preview_run_id": 1},
                       headers=company).status_code == 403


def test_esco_status_endpoint_is_offline_and_honest(client, db, auth_headers):
    admin = auth_headers("admin@univ.edu")
    r = client.get("/api/system/esco/status", headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body["configured"]["version"] == "1.2.0"
    assert body["configured"]["language"] == "en"
    assert "esco_market_cache_age_seconds" in body
    assert body["roles"]["total_esco"] >= 0
    assert "managed_by_status" in body["roles"]
    assert body["last_run"] is None


def test_esco_preview_endpoint_persists_dry_run(client, db, auth_headers, monkeypatch):
    monkeypatch.setattr(esco_import, "build_default_transport", _fixture)
    admin = auth_headers("admin@univ.edu")
    before = _counts()["roles"]
    r = client.post("/api/system/esco/preview", json={"query": "data engineer"},
                    headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["version"] == "1.2.0"
    run = _run_row(body["run_id"])
    assert run["mode"] == "dry_run"
    assert run["status"] == "succeeded"
    assert _counts()["roles"] == before  # preview never mutates roles


def test_esco_apply_endpoint_roundtrip(client, db, auth_headers, monkeypatch):
    monkeypatch.setattr(esco_import, "build_default_transport", _fixture)
    admin = auth_headers("admin@univ.edu")
    preview = client.post("/api/system/esco/preview",
                          json={"query": "data engineer"}, headers=admin).json()
    assert preview["status"] == "succeeded"

    r = client.post("/api/system/esco/apply",
                    json={"preview_run_id": preview["run_id"]}, headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["previewed_run_id"] == preview["run_id"]
    with database.get_cursor() as conn:
        added = conn.execute(
            "SELECT COUNT(*) AS c FROM roles WHERE source='esco' AND import_imprint IS NOT NULL"
        ).fetchone()["c"]
    assert added >= 1


def test_esco_apply_endpoint_refuses_drift(client, db, auth_headers, monkeypatch):
    monkeypatch.setattr(esco_import, "build_default_transport", _fixture)
    admin = auth_headers("admin@univ.edu")
    preview = client.post("/api/system/esco/preview",
                          json={"query": "data engineer"}, headers=admin).json()
    monkeypatch.setattr(esco_import, "configured_version", lambda: "1.2.1")
    r = client.post("/api/system/esco/apply",
                    json={"preview_run_id": preview["run_id"]}, headers=admin)
    assert r.status_code == 409
    assert "config drift" in r.json()["detail"]