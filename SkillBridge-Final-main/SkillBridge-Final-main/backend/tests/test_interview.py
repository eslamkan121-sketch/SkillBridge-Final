from app import genai


def test_interview_reply_fallback_is_contextual(monkeypatch):
    monkeypatch.setattr(genai, "OPENAI_KEY", None)
    monkeypatch.setattr(genai, "ANTHROPIC_KEY", None)
    monkeypatch.setattr(genai, "NIM_KEY", None)

    reply = genai.interview_reply(
        "",
        "Independent learner; current profile: Python (Beginner)",
        "Python",
        "Junior AI Engineer",
        1,
    )

    assert "Python" in reply
    assert "Junior AI Engineer" in reply


def test_interview_route_student_success(client, student_id, auth_headers, monkeypatch):
    monkeypatch.setattr(genai, "OPENAI_KEY", None)
    monkeypatch.setattr(genai, "ANTHROPIC_KEY", None)
    monkeypatch.setattr(genai, "NIM_KEY", None)
    headers = auth_headers("aisha@student.edu")

    res = client.post(
        f"/api/students/{student_id}/interview",
        json={"message": "I built a small Dockerized API.", "turn": 2},
        headers=headers,
    )

    assert res.status_code == 200, res.text
    data = res.json()
    assert data["turn"] == 3
    assert data["reply"].strip()


def test_interview_rejects_non_owner_student(client, student_id, auth_headers):
    headers = auth_headers("omar@student.edu")

    res = client.post(
        f"/api/students/{student_id}/interview",
        json={"message": "Start", "turn": 1},
        headers=headers,
    )

    assert res.status_code == 403


def test_interview_rejects_company_access(client, student_id, auth_headers):
    headers = auth_headers("hr@northstar.com")

    res = client.post(
        f"/api/students/{student_id}/interview",
        json={"message": "Start", "turn": 1},
        headers=headers,
    )

    assert res.status_code == 403


def test_interview_rejects_unknown_skill(client, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")

    res = client.post(
        f"/api/students/{student_id}/interview",
        json={"message": "Start", "turn": 1, "skill_id": 999999},
        headers=headers,
    )

    assert res.status_code == 404
