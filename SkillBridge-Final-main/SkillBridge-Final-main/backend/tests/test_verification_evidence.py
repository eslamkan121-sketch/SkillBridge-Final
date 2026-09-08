"""Evidence-backed skill verification view (hackathon hardening).

GET /api/students/{id}/skills/{skill_id}/verification must explain WHY a skill
is Verified from persisted rows: attempt history, per-competency breakdown from
the most recent competency-tagged attempt, integrity flags — no invented data.
"""
import pytest

from app import models, genai


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)


def _immcoq(comp, n):
    return {"question": f"{comp} q{n}", "type": "multiple_choice",
            "options": ["a", "b", "c"], "answer": "b", "explanation": "x", "competency": comp}


def _pass_docker(client, headers, student_id):
    skill = models.get_skill_by_name("Docker")
    from app import coverage as cov
    req = cov.required_slugs("Docker", "Intermediate")
    questions = [_immcoq(c, i) for i, c in enumerate(req)]
    r = client.post(f"/api/students/{student_id}/assessments", json={
        "skill_id": skill["id"], "questions": questions, "answers": ["b" for _ in questions],
        "total_seconds": 300, "tab_switches": 0, "free_text_answers": []}, headers=headers)
    assert r.status_code == 200 and r.json()["passed"] is True
    return skill


def test_verification_reports_evidence_after_pass(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    skill = _pass_docker(client, h, student_id)
    r = client.get(f"/api/students/{student_id}/skills/{skill['id']}/verification", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data["skill"]["name"] == "Docker"
    assert data["verified"] is True
    assert data["verified_level"] == "Intermediate"
    assert data["attempt_count"] >= 1
    assert data["source_attempt_id"] is not None
    assert data["competencies"], "expected a per-competency breakdown"
    assert all(c["passed"] for c in data["competencies"])
    assert all({"count", "correct", "score", "passed", "label", "competency"} <= set(c)
               for c in data["competencies"])


def test_verification_before_any_attempt_reports_unverified(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    skill = models.get_skill_by_name("Docker")
    r = client.get(f"/api/students/{student_id}/skills/{skill['id']}/verification", headers=h)
    data = r.json()
    assert data["verified"] is False
    assert data["attempt_count"] == 0
    assert data["competencies"] == []
    assert data["source_attempt_id"] is None


def test_verification_reports_flags_on_failed_attempt(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    skill = models.get_skill_by_name("Docker")
    from app import coverage as cov
    req = cov.required_slugs("Docker", "Intermediate")
    questions = [_immcoq(c, i) for i, c in enumerate(req)]
    # wrong answers + a timing anomaly -> flags, not passed
    r = client.post(f"/api/students/{student_id}/assessments", json={
        "skill_id": skill["id"], "questions": questions, "answers": ["a" for _ in questions],
        "total_seconds": 5, "tab_switches": 2, "free_text_answers": []}, headers=h)
    assert r.status_code == 200 and r.json()["passed"] is False
    data = client.get(f"/api/students/{student_id}/skills/{skill['id']}/verification", headers=h).json()
    assert data["verified"] is False
    labels = [f.get("code") for a in data["attempts"] for f in a["flags"]]
    assert "tab_switch" in labels and "timing_anomaly" in labels


def test_verification_access_control(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    skill = models.get_skill_by_name("Docker")
    url = f"/api/students/{student_id}/skills/{skill['id']}/verification"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=auth_headers("omar@student.edu")).status_code == 403
    assert client.get(url, headers=auth_headers("admin@univ.edu")).status_code == 403
    # a company may view evidence only for a student targeting its own role
    assert client.get(url, headers=auth_headers("hr@northstar.com")).status_code == 200
    assert client.get(url, headers=auth_headers("hr@signal.com")).status_code == 403
    assert client.get(f"/api/students/{student_id}/skills/999_999/verification",
                      headers=h).status_code == 404