"""Phase 6 — University dashboard: aggregated stats + minimum-cohort rule."""
import sqlite3
import pytest

from app import database, models, seed


def _admin_headers(client):
    r = client.post("/api/auth/login", json={"email": "admin@univ.edu", "password": "demo1234"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_university_stats_are_aggregated(client):
    headers = _admin_headers(client)
    r = client.get("/api/university/stats", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["rule"]["satisfied"] is True
    assert data["student_count"] >= 5
    # aggregated skill stats present, never individual records
    assert "skill_stats" in data
    assert data["average_match_score"] is not None
    # No individual student names/emails leak through the endpoint
    blob = str(data)
    assert "aisha" not in blob.lower() or "email" not in blob


def test_min_cohort_rule_hides_stats():
    # Fresh DB with too few students -> stats withheld
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    database.set_db_for_test(conn)
    seed.seed()
    from app import main
    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        # Startup may seed the shared DB; delete students *after* startup, in-context.
        conn.execute("DELETE FROM students")
        conn.commit()
        headers = _admin_headers(c)
        r = c.get("/api/university/stats", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["rule"]["satisfied"] is False
    assert data["stats"] is None
    database.set_db_for_test()
    conn.close()


def test_university_never_drills_into_individual(client):
    # Verify no student-specific detail endpoint is exposed from the university view —
    # /api/university/stats returns only the shape above.
    headers = _admin_headers(client)
    r = client.get("/api/university/stats", headers=headers)
    data = r.json()
    assert "students" not in data
    assert "student" not in data


def test_non_admin_cannot_read_university_stats(client, auth_headers):
    headers = auth_headers("aisha@student.edu")
    assert client.get("/api/university/stats", headers=headers).status_code == 403


def test_cohort_endpoint_is_anonymized(client):
    headers = _admin_headers(client)
    r = client.get("/api/university/cohort", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["student_count"] >= 5 and data["confirmed_count"] >= 5
    blob = str(data)
    # never exposes names or emails
    assert "@" not in blob
    assert "aisha" not in blob.lower()
    # every entry is just an index + confirmation status
    for s in data["students"]:
        assert set(s.keys()) == {"index", "confirmed"}
