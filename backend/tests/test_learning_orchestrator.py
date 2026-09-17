"""Phase 2: state-driven learning-agent contracts."""
from urllib.parse import quote

from app import genai, learning_orchestrator as agent, models


def _prepare_python(client, student_id, headers):
    skill = models.get_skill_by_name("Python")
    diagnostic = client.post(f"/api/students/{student_id}/learning/{skill['id']}/diagnostic/generate", json={}, headers=headers).json()
    submitted = client.post(
        f"/api/students/{student_id}/learning/{skill['id']}/diagnostic/submit",
        json={"diagnostic_id": diagnostic["diagnostic_id"], "answers": ["not sure"] * len(diagnostic["questions"])}, headers=headers)
    assert submitted.status_code == 200, submitted.text
    path = client.post(f"/api/students/{student_id}/learning/{skill['id']}/personalized-path/generate", json={}, headers=headers).json()
    item = next(row for row in path["items"] if row["competency"] == "python_functions")
    url = f"/api/students/{student_id}/learning/{skill['id']}/lessons/{quote(item['competency'], safe='')}"
    lesson = client.post(url + "/generate", json={}, headers=headers)
    assert lesson.status_code == 200, lesson.text
    raw_path = models.get_personalized_path(student_id, skill["id"])
    raw_lesson = models.get_lesson(student_id, raw_path["id"], item["competency"])
    return skill, raw_path, item, raw_lesson


def _attempt(student_id, skill, path, lesson, score, status, answer, missing):
    return models.create_practice_attempt(student_id, skill["id"], path["id"], lesson["id"], lesson["competency"], answer,
        {"score": score, "status": status, "strengths": [], "missing_points": missing,
         "feedback": "Stored evaluator result", "next_action": "Retry", "source": "fallback"})


def test_agent_selects_only_actual_trusted_gap_and_exposes_evidence(client, student_id, auth_headers, monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    h = auth_headers("aisha@student.edu")
    skill, _, item, _ = _prepare_python(client, student_id, h)
    decision = client.get(f"/api/students/{student_id}/learning/{skill['id']}/orchestrator/next", headers=h)
    assert decision.status_code == 200, decision.text
    body = decision.json()
    assert body["topic_id"] == item["competency"]
    assert body["action_type"] == agent.PRACTICE
    assert any(e["kind"] == "diagnostic" for e in body["evidence"])


def test_wrong_then_repeated_prerequisite_errors_change_action_and_persist(client, student_id, auth_headers, monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    h = auth_headers("aisha@student.edu")
    skill, path, _, lesson = _prepare_python(client, student_id, h)
    _attempt(student_id, skill, path, lesson, 20, "needs_review", "I would print the number instead of returning it.", ["Explain return behavior"])
    first = agent.observe_and_decide(student_id, skill)
    assert first["action_type"] == agent.GIVE_HINT
    assert any(e["kind"] == "hint" for e in first["evidence"])
    _attempt(student_id, skill, path, lesson, 30, "needs_review", "My parameter and return are still confused.", ["Use the parameter in the calculation"])
    second = agent.observe_and_decide(student_id, skill)
    assert second["action_type"] == agent.REVIEW_PREREQUISITE
    assert "2 needs-review attempts" in second["decision_reason"] or "Repeated" in second["decision_reason"]
    assert agent.observe_and_decide(student_id, skill)["action_type"] == agent.REVIEW_PREREQUISITE


def test_corrected_real_result_offers_mini_check_then_advances_without_verifying(client, student_id, auth_headers, monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    h = auth_headers("aisha@student.edu")
    skill, path, item, lesson = _prepare_python(client, student_id, h)
    _attempt(student_id, skill, path, lesson, 92, "ready", "return (celsius * 9 / 5) + 32", [])
    assert agent.observe_and_decide(student_id, skill)["action_type"] == agent.MINI_CHECK
    before = {row["name"] for row in models.get_student(student_id)["verified_skills"]}
    models.update_lesson_state(student_id, path["id"], item["competency"], "completed", {"passed": True, "score": 1.0})
    advanced = agent.observe_and_decide(student_id, skill)
    assert advanced["action_type"] == agent.ADVANCE
    assert item["id"] in models.public_personalized_path(models.get_personalized_path(student_id, skill["id"]))["progress"]
    assert {row["name"] for row in models.get_student(student_id)["verified_skills"]} == before


def test_missing_or_contradictory_state_requests_reassessment_without_claiming_mastery(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    skill = models.get_skill_by_name("Python")
    r = client.get(f"/api/students/{student_id}/learning/{skill['id']}/orchestrator/next", headers=h)
    assert r.status_code == 200
    assert r.json()["action_type"] == agent.REQUEST_REASSESSMENT
    assert "cannot be selected" in r.json()["decision_reason"]


def test_orchestrator_endpoint_always_returns_json_not_spa_html(client, student_id, auth_headers):
    """Route-registration regression: an old server used to send index.html."""
    skill = models.get_skill_by_name("Python")
    url = f"/api/students/{student_id}/learning/{skill['id']}/orchestrator/next"

    unauthenticated = client.get(url)
    assert unauthenticated.status_code in (401, 403)
    assert unauthenticated.headers["content-type"].startswith("application/json")
    assert not unauthenticated.text.lstrip().lower().startswith("<!doctype")

    authenticated = client.get(url, headers=auth_headers("aisha@student.edu"))
    assert authenticated.status_code == 200, authenticated.text
    assert authenticated.headers["content-type"].startswith("application/json")
    assert isinstance(authenticated.json(), dict)


def test_real_api_journey_persists_practice_mini_check_and_next_action(client, student_id, auth_headers, monkeypatch):
    """Acceptance flow: all state is created through the public learning APIs."""
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    h = auth_headers("aisha@student.edu")
    skill, _, item, _ = _prepare_python(client, student_id, h)
    base = f"/api/students/{student_id}/learning/{skill['id']}/lessons/{quote(item['competency'], safe='')}"
    bad = client.post(base + "/practice", json={"answer": "def celsius_to_fahrenheit(celsius):\n    print(celsius)"}, headers=h)
    assert bad.status_code == 200, bad.text
    assert bad.json()["attempt"]["practice_task"]["static_check"]["status"] == "needs_fix"
    hint = client.get(f"/api/students/{student_id}/learning/{skill['id']}/orchestrator/next", headers=h).json()
    assert hint["action_type"] == agent.GIVE_HINT
    good = client.post(base + "/practice", json={"answer": """def celsius_to_fahrenheit(celsius):
    return (celsius * 9 / 5) + 32

I return the result so other code can reuse and test it rather than only printing it."""}, headers=h)
    assert good.status_code == 200, good.text
    assert good.json()["attempt"]["practice_task"]["static_check"]["status"] == "looks_structurally_sound"
    # The established prose reviewer can be inconclusive.  The agent may use
    # the persisted, non-executing AST evidence to offer a Mini Check without
    # altering that review score/status or claiming a runtime test passed.
    assert good.json()["attempt"]["status"] == "needs_review"
    next_action = client.get(f"/api/students/{student_id}/learning/{skill['id']}/orchestrator/next", headers=h).json()
    assert next_action["action_type"] == agent.MINI_CHECK
    assert any(item["kind"] == "static_check" for item in next_action["evidence"])
    lesson = client.get(base, headers=h).json()
    mini = lesson["content"]["mini_check"]["questions"]
    checked = client.post(base + "/mini-check", json={"answers": [q["correct_answer"] for q in mini]}, headers=h)
    assert checked.status_code == 200, checked.text
    assert checked.json()["lesson"]["state"] == "completed"
    after_refresh = client.get(f"/api/students/{student_id}/learning/{skill['id']}/orchestrator/next", headers=h).json()
    # Functions is complete, so the persisted prerequisite-aware path now
    # recommends the next curated topic rather than pretending the whole skill
    # advanced.
    assert after_refresh["action_type"] == agent.EXPLAIN
    assert after_refresh["topic_id"] == "python_error_handling"
