"""Phase N — Jobs Board safety and job-link-report contracts."""
import sqlite3

from app import database, models


JOB = {
    "fingerprint": "phase-n-job-1",
    "title": "Junior Data Analyst",
    "company": "Example Labs",
    "url": "https://jobs.example.test/listing/1",
    "apply_url": "https://jobs.example.test/apply/1",
    "provider": "ExampleProvider",
}


def test_migration_0008_creates_private_idempotent_link_reports(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "phase-n.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    database.set_db_for_test(conn)
    try:
        database.init_db()
        assert database.applied_migrations()[-1]["migration_id"] == "0013_tutor_conversations"
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(job_link_reports)")}
        assert {"student_id", "fingerprint", "url", "reported_at"} <= columns
        unique_indexes = [row for row in conn.execute("PRAGMA index_list(job_link_reports)") if row["unique"]]
        assert unique_indexes
    finally:
        database.set_db_for_test()
        conn.close()


def _feed_job(skills, role, country, location, requisites, market, fingerprint, limit=10):
    if fingerprint == "not-in-feed":
        return None
    return {**JOB, "fingerprint": fingerprint}


def test_link_report_is_idempotent_and_does_not_change_tracker(db):
    report_id, created = models.report_job_link(1, JOB)
    assert created is True
    again_id, created_again = models.report_job_link(1, JOB)
    assert (again_id, created_again) == (report_id, False)

    rows = models.list_job_link_reports(1)
    assert len(rows) == 1
    assert rows[0]["url"] == JOB["apply_url"]
    assert models.list_job_tracker(1) == []
    assert models.list_job_link_reports(2) == []


def test_report_endpoint_is_student_private_and_idempotent(client, student_id, auth_headers, monkeypatch):
    monkeypatch.setattr("app.main.jobs.locate_feed_job", _feed_job)
    aisha = auth_headers("aisha@student.edu")

    first = client.post(
        f"/api/students/{student_id}/jobs/recent/phase-n-job-1/report-dead-link",
        json={"market": "EG"}, headers=aisha)
    assert first.status_code == 200, first.text
    assert first.json()["created"] is True

    second = client.post(
        f"/api/students/{student_id}/jobs/recent/phase-n-job-1/report-dead-link",
        json={"market": "EG"}, headers=aisha)
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["report_id"] == first.json()["report_id"]

    listed = client.get(f"/api/students/{student_id}/jobs/link-reports", headers=aisha)
    assert listed.status_code == 200
    assert [r["fingerprint"] for r in listed.json()["reports"]] == ["phase-n-job-1"]

    omar = auth_headers("omar@student.edu")
    assert client.get(f"/api/students/{student_id}/jobs/link-reports", headers=omar).status_code == 403
    assert client.post(
        f"/api/students/{student_id}/jobs/recent/phase-n-job-1/report-dead-link", json={}, headers=omar
    ).status_code == 403


def test_report_unknown_job_is_an_honest_404(client, student_id, auth_headers, monkeypatch):
    monkeypatch.setattr("app.main.jobs.locate_feed_job", _feed_job)
    response = client.post(
        f"/api/students/{student_id}/jobs/recent/not-in-feed/report-dead-link",
        json={}, headers=auth_headers("aisha@student.edu"))
    assert response.status_code == 404
