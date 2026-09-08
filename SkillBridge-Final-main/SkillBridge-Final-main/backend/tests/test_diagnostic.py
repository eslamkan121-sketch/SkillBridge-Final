"""Phase 2 — Topic-level learning diagnostic.

Covers generation (blueprint-aware, competency-tagged), deterministic per-topic
scoring, weak-topic extraction, persistence, latest retrieval, unauthenticated
access, invalid skills, skills without a blueprint, and a GenAI-free fallback.
All GenAI calls are forced to the deterministic fallback so tests never consume
(and never depend on) a real API key.
"""
import pytest

from app import diagnostics, genai, models


@pytest.fixture(autouse=True)
def _force_deterministic_fallback(monkeypatch):
    """Guarantee no real GenAI call ever happens in these tests."""
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)


@pytest.fixture()
def docker_skill(db):
    return models.get_skill_by_name("Docker")


@pytest.fixture()
def tensorflow_skill(db):
    return models.get_skill_by_name("TensorFlow")


@pytest.fixture()
def aisha_id(client):
    return client.post("/api/auth/login", json={
        "email": "aisha@student.edu", "password": "demo1234"}).json()["student"]["id"]


def _generate(client, student_id, skill_id, headers):
    return client.post(
        f"/api/students/{student_id}/learning/{skill_id}/diagnostic/generate",
        json={}, headers=headers)


# ------------------------------------------------------------------ generation

def test_generate_diagnostic_every_question_has_competency(client, docker_skill, aisha_id,
                                                           auth_headers):
    headers = auth_headers("aisha@student.edu")
    r = _generate(client, aisha_id, docker_skill["id"], headers)
    assert r.status_code == 200, r.text
    body = r.json()
    qs = body["questions"]
    assert 5 <= len(qs) <= 9
    assert body["diagnostic_id"]
    assert body["topics"]
    for q in qs:
        assert q["competency"], q  # machine-readable tag on EVERY question
        assert q["type"] in ("mcq", "free_text")
        assert q["difficulty"] in ("beginner", "intermediate", "advanced")


def test_no_blueprint_skill_still_generates(client, tensorflow_skill, aisha_id, auth_headers):
    assert models.get_skill_by_name("TensorFlow")  # exists but has no closed blueprint
    headers = auth_headers("aisha@student.edu")
    r = _generate(client, aisha_id, tensorflow_skill["id"], headers)
    assert r.status_code == 200, r.text
    qs = r.json()["questions"]
    assert 5 <= len(qs) <= 9
    assert all(q["competency"] for q in qs)


def test_deterministic_fallback_valid(db, docker_skill):
    """Without an API key, generation still yields a structured, tagged, usable diagnostic."""
    comps = diagnostics.resolve_topics(docker_skill["name"])
    qs = genai.generate_diagnostic(docker_skill["name"], comps, "AI Engineer")
    assert 5 <= len(qs) <= 9
    for q in qs:
        assert q["id"] and q["question"] and q["competency"]
        if q["type"] == "mcq":
            assert q["options"] and q["correct_answer"]
        else:
            assert q["correct_answer"]


def test_generate_diagnostic_llm_path_no_crash(monkeypatch, client, docker_skill, aisha_id,
                                               auth_headers):
    """The real-provider branch (genai_enabled True) must also return 200.

    Regression guard: the LLM branch referenced `dx` before importing it, so any
    enabled provider raised NameError -> 500. All other tests force the
    deterministic fallback, which is why this path was never exercised.
    """
    import json

    comps = diagnostics.resolve_topics(docker_skill["name"])
    slugs = [diagnostics.competency_slug(c) for c in comps]
    payload = json.dumps([
        {"question": f"Comp {i} question?", "type": "mcq" if i % 2 == 0 else "free_text",
         "options": ["a", "b", "c", "d"] if i % 2 == 0 else [],
         "correct_answer": "a", "competency": slugs[i % len(slugs)],
         "difficulty": "beginner"} for i in range(7)])
    monkeypatch.setattr(genai, "genai_enabled", lambda: True)
    monkeypatch.setattr(genai, "complete", lambda *a, **k: payload)
    headers = auth_headers("aisha@student.edu")
    r = _generate(client, aisha_id, docker_skill["id"], headers)
    assert r.status_code == 200, r.text
    assert 5 <= len(r.json()["questions"]) <= 9
    assert all(q["competency"] for q in r.json()["questions"])


# ------------------------------------------------------------------ deterministic scoring

def test_topic_status_thresholds():
    assert diagnostics.topic_status(90) == "mastered"
    assert diagnostics.topic_status(75) == "mastered"
    assert diagnostics.topic_status(74) == "developing"
    assert diagnostics.topic_status(40) == "developing"
    assert diagnostics.topic_status(39) == "weak"
    assert diagnostics.topic_status(0) == "weak"


def test_score_topics_weak_extraction():
    qs = [
        {"competency": "a", "type": "mcq"},
        {"competency": "a", "type": "mcq"},
        {"competency": "b", "type": "mcq"},
        {"competency": "b", "type": "mcq"},
        {"competency": "b", "type": "free_text"},
        {"competency": "c", "type": "mcq"},
    ]
    # a: 1/2 (50 developing); b: mcq wrong, wrong, ft correct => 1/3 (33 weak); c: 0/1 weak
    flags = [True, False, False, False, True, False]
    res = diagnostics.score_topics(qs, [""] * len(qs), lambda i, q, a: flags[i])
    by = {t["competency"]: t for t in res["topics"]}
    assert by["a"]["status"] == "developing"
    assert by["b"]["status"] == "weak"
    assert by["c"]["status"] == "weak"
    assert set(res["weak_topics"]) == {"b", "c"}
    assert res["strong_topics"] == []
    assert isinstance(res["overall_score"], (int, float))


def test_score_topics_mastered_when_all_correct():
    qs = [
        {"competency": "a", "type": "mcq"},
        {"competency": "a", "type": "mcq"},
        {"competency": "b", "type": "free_text"},
    ]
    res = diagnostics.score_topics(qs, ["x", "y", "z"], lambda i, q, a: True)
    by = {t["competency"]: t for t in res["topics"]}
    assert all(by[k]["status"] == "mastered" for k in ("a", "b"))
    assert set(res["weak_topics"]) == set()
    assert set(res["strong_topics"]) == {"a", "b"}


# ------------------------------------------------------------------ submit / persistence

def test_submit_diagnostic_scores_and_persists(client, docker_skill, aisha_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    gen = _generate(client, aisha_id, docker_skill["id"], headers).json()
    diag_id = gen["diagnostic_id"]
    qs = gen["questions"]
    answers = []
    for q in qs:
        if q["type"] == "mcq":
            wrong = [o for o in q["options"] if o != q["correct_answer"]]
            answers.append(wrong[0] if wrong else q["options"][0])
        else:
            answers.append("")
    r = client.post(
        f"/api/students/{aisha_id}/learning/{docker_skill['id']}/diagnostic/submit",
        json={"diagnostic_id": diag_id, "answers": answers}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["completed_at"]
    assert isinstance(body["score"], (int, float))
    assert isinstance(body["topic_results"], list) and body["topic_results"]
    assert body["completed_at"]
    # persisted: latest now returns the completed diagnostic
    latest = client.get(
        f"/api/students/{aisha_id}/learning/{docker_skill['id']}/diagnostic/latest",
        headers=headers).json()
    assert latest["id"] == diag_id
    assert latest["completed_at"]


def test_submit_diagnostic_all_correct_mastered(client, docker_skill, aisha_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    gen = _generate(client, aisha_id, docker_skill["id"], headers).json()
    qs = gen["questions"]
    answers = [q["correct_answer"] for q in qs]
    r = client.post(
        f"/api/students/{aisha_id}/learning/{docker_skill['id']}/diagnostic/submit",
        json={"diagnostic_id": gen["diagnostic_id"], "answers": answers}, headers=headers)
    assert r.status_code == 200, r.text
    topics = r.json()["topic_results"]
    assert topics  # every competency scored as mastered
    for t in topics:
        assert t["status"] == "mastered", t


def test_submit_unknown_diagnostic_404(client, docker_skill, aisha_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    r = client.post(
        f"/api/students/{aisha_id}/learning/{docker_skill['id']}/diagnostic/submit",
        json={"diagnostic_id": 999999, "answers": []}, headers=headers)
    assert r.status_code == 404


def test_latest_none_returns_404(client, docker_skill, aisha_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    r = client.get(
        f"/api/students/{aisha_id}/learning/{docker_skill['id']}/diagnostic/latest",
        headers=headers)
    assert r.status_code == 404


# ------------------------------------------------------------------ access control / validation

def test_diagnostic_requires_auth(client, docker_skill, aisha_id):
    r = client.post(
        f"/api/students/{aisha_id}/learning/{docker_skill['id']}/diagnostic/generate",
        json={})
    assert r.status_code == 401


def test_diagnostic_invalid_skill_404(client, aisha_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    r = client.post(f"/api/students/{aisha_id}/learning/999999/diagnostic/generate",
                    json={}, headers=headers)
    assert r.status_code == 404


def test_diagnostic_company_forbidden(client, docker_skill, aisha_id, auth_headers):
    headers = auth_headers("hr@northstar.com")
    r = client.post(
        f"/api/students/{aisha_id}/learning/{docker_skill['id']}/diagnostic/generate",
        json={}, headers=headers)
    assert r.status_code == 403


def test_diagnostic_non_owner_forbidden(client, docker_skill, aisha_id, auth_headers):
    # omar is a different student; log in as omar and try to access aisha's diagnostic
    omar = client.post("/api/auth/login", json={
        "email": "omar@student.edu", "password": "demo1234"}).json()
    headers = {"Authorization": f"Bearer {omar['token']}"}
    r = client.post(
        f"/api/students/{aisha_id}/learning/{docker_skill['id']}/diagnostic/generate",
        json={}, headers=headers)
    assert r.status_code == 403
