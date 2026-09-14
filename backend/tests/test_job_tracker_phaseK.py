"""Phase K — Saved Jobs and the private Application Tracker.

A student saves a currently-surfaced live-feed job (snapshot by fingerprint,
idempotent) into a private tracker and moves it through the ten-stage career
pipeline. Stage vocabulary is locked, transitions are validated and audited in
an append-only history table, notes are student-private, and records are only
destroyable while still 'saved' (everything else archives instead).
"""
import sqlite3

import pytest

from app import database, models

JOB_TPL = {
    "fingerprint": "fp-abc123",
    "title": "Junior AI Engineer",
    "company": "Northstar Labs",
    "url": "https://jobs.example.com/post/1",
    "apply_url": "https://jobs.example.com/apply/1",
    "location": "Cairo",
    "country": "EG",
    "provider": "adzuna",
    "source": "adzuna",
    "match_pct": 84.0,
    "work_type": "hybrid",
    "seniority": "junior",
    "listing_status": "live",
    "link_state": "unverified",
    "is_expired": False,
}


# ------------------------------------------------------------------ migration 0006

def _fresh_file_db(tmp_path, name="phasek.db"):
    conn = sqlite3.connect(str(tmp_path / name))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def test_migration_0006_on_fresh_db(tmp_path):
    conn = _fresh_file_db(tmp_path)
    database.set_db_for_test(conn)
    try:
        database.init_db()
        applied = [m["migration_id"] for m in database.applied_migrations()]
        # Later additive migrations may exist; this test owns the Phase K
        # tables, not the global migration tail.
        assert "0007_role_view_events" in applied
        assert applied[-1] == "0013_tutor_conversations"
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "student_job_tracker" in tables and "tracker_stage_history" in tables
        info = {r["name"] for r in conn.execute("PRAGMA table_info(student_job_tracker)")}
        assert {"student_id", "fingerprint", "stage", "note", "created_at",
                "updated_at", "is_expired"} <= info
        assert conn.execute("PRAGMA index_list('student_job_tracker')").fetchall()
        checks = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='student_job_tracker'"
        ).fetchone()["sql"]
        assert "archived_or_expired" in checks
    finally:
        database.set_db_for_test()
        conn.close()


def test_migration_0006_upgrades_pre_0006_db_and_keeps_rows(tmp_path):
    conn = _fresh_file_db(tmp_path)
    database.set_db_for_test(conn)
    try:
        database.init_db()
        assert database.applied_migrations()[-1]["migration_id"] == "0013_tutor_conversations"
        counts_before = {r["name"]: conn.execute(f"SELECT COUNT(*) n FROM {r['name']}").fetchone()["n"]
                         for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

        # Simulate a pre-0006 DB: forget the 0006 + later ledger rows and drop
        # their tables (the 0007 recents table is additive on top of them).
        conn.execute("DELETE FROM schema_migrations WHERE migration_id IN ('0006_saved_jobs_tracker', '0007_role_view_events')")
        conn.execute("DROP TABLE tracker_stage_history")
        conn.execute("DROP TABLE student_job_tracker")
        conn.execute("DROP TABLE role_view_events")
        conn.commit()

        pending = database.run_migrations()
        assert pending == ["0006_saved_jobs_tracker", "0007_role_view_events"]

        # Every pre-existing table kept every row across the upgrade.
        counts_after = {r["name"]: conn.execute(f"SELECT COUNT(*) n FROM {r['name']}").fetchone()["n"]
                        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name, n in counts_before.items():
            assert counts_after.get(name) == n, name
    finally:
        database.set_db_for_test()
        conn.close()


# ------------------------------------------------------------------ stage vocabulary + transitions

def test_stage_vocabulary_is_exact():
    assert tuple(models.JOB_TRACKER_STAGES) == (
        "saved", "preparing", "applied", "screening", "interview", "offer",
        "hired", "rejected", "withdrawn", "archived_or_expired",
    )
    assert len(models.JOB_TRACKER_TRANSITIONS) == len(models.JOB_TRACKER_STAGES)


def test_transition_allows_and_blocks():
    rules = models.JOB_TRACKER_TRANSITIONS
    assert rules["saved"] == {"preparing", "applied", "archived_or_expired"}
    assert not ({"interview", "hired", "offer", "rejected", "withdrawn"} & rules["saved"])
    assert "hired" in rules["offer"]
    assert "saved" not in rules["applied"]
    assert "archived_or_expired" in rules["rejected"]
    assert "saved" in rules["withdrawn"]        # withdrawal can be reversed to prep again
    assert "saved" in rules["archived_or_expired"]  # an archived row can be reactivated
    assert "hired" not in rules["saved"]


# ------------------------------------------------------------------ model: snapshot + idempotency + expiry honesty

def test_save_snapshot_fidelity_and_idempotency(db):
    tracker_id, created = models.save_job_snapshot(1, JOB_TPL)
    assert created is True
    entry = models.get_tracker_entry(1, tracker_id)
    assert entry["stage"] == "saved"
    assert entry["match_pct"] == 84.0
    assert entry["listing_status"] == "live" and entry["link_state"] == "unverified"
    assert entry["company"] == "Northstar Labs" and entry["apply_url"].endswith("/apply/1")
    assert entry["created_at"] and entry["updated_at"]

    again_id, created2 = models.save_job_snapshot(1, JOB_TPL)
    assert again_id == tracker_id and created2 is False
    assert len(models.list_job_tracker(1)) == 1


def test_expired_and_dead_snapshots_preserved(db):
    dead = {**JOB_TPL, "fingerprint": "fp-dead-1", "listing_status": "link-unavailable",
            "link_state": "dead", "is_expired": True}
    tid, _ = models.save_job_snapshot(1, dead)
    entry = models.get_tracker_entry(1, tid)
    assert entry["listing_status"] == "link-unavailable"
    assert entry["link_state"] == "dead"
    assert entry["is_expired"] is True
    assert entry["stage"] == "saved"
    assert models.list_job_tracker(1)


def test_save_requires_fingerprint(db):
    with pytest.raises(models.TrackerError):
        models.save_job_snapshot(1, {**JOB_TPL, "fingerprint": ""})


def test_tracker_is_per_student(db):
    tid, _ = models.save_job_snapshot(1, JOB_TPL)
    assert models.get_tracker_entry(2, tid) is None
    assert models.list_job_tracker(2) == []
    assert models.list_job_tracker(1)[0]["id"] == tid


def test_transition_validation_and_audit(db):
    tid, _ = models.save_job_snapshot(1, JOB_TPL)
    models.update_tracker_entry(1, tid, stage="applied", note="sent resume")
    models.update_tracker_entry(1, tid, stage="interview", note="call Tue", interview_date="2026-10-01")
    entry = models.get_tracker_entry(1, tid)
    assert entry["stage"] == "interview"
    assert entry["note"] == "call Tue"
    assert entry["interview_date"] == "2026-10-01"
    stages = [h["stage"] for h in entry["history"]]
    assert stages == ["saved", "applied", "interview"]
    assert entry["history"][1]["changed_from"] == "saved"
    assert entry["history"][2]["changed_from"] == "applied"

    with pytest.raises(models.TrackerError) as ei:
        models.update_tracker_entry(1, tid, stage="hired")
    assert ei.value.code == 409

    with pytest.raises(models.TrackerError) as ei:
        models.update_tracker_entry(1, tid, stage="not-a-stage")
    assert ei.value.code == 400

    with pytest.raises(models.TrackerError):
        models.update_tracker_entry(1, tid, stage="applied", interview_date="not-a-date")


def test_same_stage_patch_is_a_noop_without_history(db):
    tid, _ = models.save_job_snapshot(1, JOB_TPL)
    models.update_tracker_entry(1, tid, stage="saved", note="edited note")
    entry = models.get_tracker_entry(1, tid)
    assert entry["note"] == "edited note"
    assert len(entry["history"]) == 1  # only the initial 'saved' audit row


def test_archive_keeps_record_and_reactivation_allowed(db):
    tid, _ = models.save_job_snapshot(1, JOB_TPL)
    models.update_tracker_entry(1, tid, stage="applied")
    models.archive_tracker_entry(1, tid)
    entry = models.get_tracker_entry(1, tid)
    assert entry["stage"] == "archived_or_expired"
    assert entry["history"][-1]["stage"] == "archived_or_expired"
    entry = models.update_tracker_entry(1, tid, stage="preparing")
    assert entry["stage"] == "preparing"


def test_delete_saved_only(db):
    tid, _ = models.save_job_snapshot(1, JOB_TPL)
    assert models.delete_saved_only(1, tid) is True
    assert models.list_job_tracker(1) == []

    tid2, _ = models.save_job_snapshot(1, {**JOB_TPL, "fingerprint": "fp-keep"})
    models.update_tracker_entry(1, tid2, stage="applied")
    with pytest.raises(models.TrackerError) as ei:
        models.delete_saved_only(1, tid2)
    assert ei.value.code == 409
    assert models.get_tracker_entry(1, tid2)["stage"] == "applied"


# ------------------------------------------------------------------ endpoints (monkeypatch the live feed)

def _fake_feed_job(skills, role, country, location, requisites, market, fingerprint, limit=10):
    if fingerprint == "fp-missing":
        return None
    return {**JOB_TPL, "fingerprint": fingerprint or JOB_TPL["fingerprint"]}


@pytest.fixture()
def mock_feed(monkeypatch, client):
    monkeypatch.setattr("app.main.jobs.locate_feed_job", _fake_feed_job)
    monkeypatch.setattr("app.main.jobs.peek_feed_job",
                        lambda *a, **k: None)
    yield client


def test_save_list_get_via_endpoint(mock_feed, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    r = mock_feed.post(f"/api/students/{student_id}/jobs/saved",
                       json={"fingerprint": "fp-abc123"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True and body["item"]["stage"] == "saved"
    tid = body["tracker_id"]

    r2 = mock_feed.post(f"/api/students/{student_id}/jobs/saved",
                        json={"fingerprint": "fp-abc123"}, headers=h)
    assert r2.status_code == 200 and r2.json()["tracker_id"] == tid and r2.json()["created"] is False

    r = mock_feed.get(f"/api/students/{student_id}/jobs/tracker", headers=h)
    assert r.status_code == 200
    assert r.json()["counts"]["saved"] == 1
    assert any(i["fingerprint"] == "fp-abc123" for i in r.json()["items"])

    r = mock_feed.get(f"/api/students/{student_id}/jobs/tracker/{tid}", headers=h)
    assert r.status_code == 200
    assert r.json()["title"] == "Junior AI Engineer"


def test_save_unknown_fingerprint_404(mock_feed, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    r = mock_feed.post(f"/api/students/{student_id}/jobs/saved",
                       json={"fingerprint": "fp-missing"}, headers=h)
    assert r.status_code == 404
    assert mock_feed.get(f"/api/students/{student_id}/jobs/tracker", headers=h).json()["items"] == []


def test_save_requires_fingerprint_param(mock_feed, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    r = mock_feed.post(f"/api/students/{student_id}/jobs/saved", json={}, headers=h)
    assert r.status_code == 400


def test_tracker_endpoints_student_private(mock_feed, student_id, auth_headers):
    aisha = auth_headers("aisha@student.edu")
    mock_feed.post(f"/api/students/{student_id}/jobs/saved",
                   json={"fingerprint": "fp-abc123"}, headers=aisha)

    omar = auth_headers("omar@student.edu")
    r = mock_feed.get(f"/api/students/{student_id}/jobs/tracker", headers=omar)
    assert r.status_code == 403

    company = auth_headers("hr@northstar.com")
    r = mock_feed.get(f"/api/students/{student_id}/jobs/tracker", headers=company)
    assert r.status_code == 403

    r = mock_feed.get(f"/api/students/{student_id}/jobs/tracker")
    assert r.status_code == 401


def test_patch_transitions_and_audit_via_endpoint(mock_feed, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    tid = mock_feed.post(f"/api/students/{student_id}/jobs/saved",
                         json={"fingerprint": "fp-abc123"}, headers=h).json()["tracker_id"]

    r = mock_feed.patch(f"/api/students/{student_id}/jobs/tracker/{tid}",
                        json={"stage": "applied", "note": "sent portfolio", "application_deadline": "2026-10-15"},
                        headers=h)
    assert r.status_code == 200, r.text
    entry = r.json()
    assert entry["stage"] == "applied" and entry["note"] == "sent portfolio"
    assert entry["application_deadline"] == "2026-10-15"

    r = mock_feed.patch(f"/api/students/{student_id}/jobs/tracker/{tid}",
                        json={"stage": "applied"}, headers=h)
    assert r.status_code == 200
    assert len([x for x in r.json()["history"] if x["stage"] == "applied"]) == 1

    r = mock_feed.patch(f"/api/students/{student_id}/jobs/tracker/{tid}",
                        json={"stage": "hired"}, headers=h)
    assert r.status_code == 409

    r = mock_feed.patch(f"/api/students/{student_id}/jobs/tracker/{tid}",
                        json={"stage": "does-not-exist"}, headers=h)
    assert r.status_code == 400

    r = mock_feed.patch(f"/api/students/{student_id}/jobs/tracker/{tid}",
                        json={"interview_date": "wont-parse"}, headers=h)
    assert r.status_code == 400

    r = mock_feed.patch(f"/api/students/{student_id}/jobs/tracker/999999",
                        json={"note": "x"}, headers=h)
    assert r.status_code == 404


def test_delete_saved_only_via_endpoint(mock_feed, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    tid = mock_feed.post(f"/api/students/{student_id}/jobs/saved",
                         json={"fingerprint": "fp-abc123"}, headers=h).json()["tracker_id"]
    r = mock_feed.delete(f"/api/students/{student_id}/jobs/tracker/{tid}", headers=h)
    assert r.status_code == 200 and r.json()["deleted"] is True

    tid2 = mock_feed.post(f"/api/students/{student_id}/jobs/saved",
                          json={"fingerprint": "fp-keep"}, headers=h).json()["tracker_id"]
    mock_feed.patch(f"/api/students/{student_id}/jobs/tracker/{tid2}",
                    json={"stage": "applied"}, headers=h)
    r = mock_feed.delete(f"/api/students/{student_id}/jobs/tracker/{tid2}", headers=h)
    assert r.status_code == 409
    assert mock_feed.get(f"/api/students/{student_id}/jobs/tracker/{tid2}", headers=h).status_code == 200
