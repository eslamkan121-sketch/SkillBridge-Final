"""Learning Phase 2 — evaluated Practice step.

Practice is feedback-only: it persists attempts and readiness guidance, but Mini
Check remains the only personalized-path completion mechanism.
"""
import json
from urllib.parse import quote

import pytest

from app import genai, lessons, models, practice


@pytest.fixture(autouse=True)
def _force_deterministic_fallback(monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)


@pytest.fixture()
def docker_skill(db):
    return models.get_skill_by_name("Docker")


def _enc(value):
    return quote(value, safe="")


def _setup_path(client, headers, skill_id, student_id):
    for _ in range(3):
        gen = client.post(
            f"/api/students/{student_id}/learning/{skill_id}/diagnostic/generate",
            json={}, headers=headers).json()
        answers = [q["correct_answer"] for q in gen["questions"]]
        misses = 0
        for i, q in enumerate(gen["questions"]):
            if misses >= 3:
                break
            if q["type"] == "mcq":
                wrong = [o for o in q["options"] if o != q["correct_answer"]]
                if not wrong:
                    continue
                answers[i] = wrong[0]
            else:
                answers[i] = "not sure yet"
            misses += 1
        client.post(
            f"/api/students/{student_id}/learning/{skill_id}/diagnostic/submit",
            json={"diagnostic_id": gen["diagnostic_id"], "answers": answers},
            headers=headers)
        path = client.post(
            f"/api/students/{student_id}/learning/{skill_id}/personalized-path/generate",
            json={}, headers=headers).json()
        if path.get("items"):
            return path
    raise AssertionError("Expected diagnostic to produce at least one learning topic")


def _setup_lesson(client, headers, skill_id, student_id):
    path = _setup_path(client, headers, skill_id, student_id)
    item = path["items"][0]
    comp = item["competency"]
    response = client.post(
        f"/api/students/{student_id}/learning/{skill_id}/lessons/{_enc(comp)}/generate",
        json={}, headers=headers)
    assert response.status_code == 200, response.text
    return path, item, response.json()


def _rich_practice_answer():
    return (
        "I would explain the container storage choice, then use a named volume or "
        "bind mount so data persists beyond the container lifecycle. I would show "
        "the docker volume create step, mount it into the container, verify the "
        "host directory or volume contents, and call out the tradeoff between "
        "portable Docker-managed persistence and direct host-file access."
    )


def _practice_url(student_id, skill_id, competency):
    return f"/api/students/{student_id}/learning/{skill_id}/lessons/{_enc(competency)}/practice"


def test_submit_practice_persists_latest_attempt(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, headers, sk, student_id)

    response = client.post(
        _practice_url(student_id, sk, item["competency"]),
        json={"answer": _rich_practice_answer()}, headers=headers)

    assert response.status_code == 200, response.text
    attempt = response.json()["attempt"]
    assert attempt["answer"].startswith("I would explain")
    assert attempt["source"] == "fallback"
    assert attempt["status"] in ("ready", "needs_review")

    history = client.get(_practice_url(student_id, sk, item["competency"]), headers=headers)
    assert history.status_code == 200
    assert history.json()["latest"]["id"] == attempt["id"]
    assert history.json()["count"] == 1


def test_practice_retry_creates_second_attempt(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, headers, sk, student_id)
    url = _practice_url(student_id, sk, item["competency"])

    first = client.post(url, json={"answer": "I would use Docker."}, headers=headers).json()["attempt"]
    second = client.post(url, json={"answer": _rich_practice_answer()}, headers=headers).json()["attempt"]
    history = client.get(url, headers=headers).json()

    assert second["id"] != first["id"]
    assert history["count"] == 2
    assert history["latest"]["id"] == second["id"]


def test_empty_practice_answer_rejected(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, headers, sk, student_id)

    response = client.post(
        _practice_url(student_id, sk, item["competency"]),
        json={"answer": "   "}, headers=headers)

    assert response.status_code == 400


def test_non_owner_cannot_submit_or_read_practice(client, docker_skill, student_id, auth_headers):
    owner_headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, owner_headers, sk, student_id)
    other_headers = auth_headers("omar@student.edu")
    url = _practice_url(student_id, sk, item["competency"])

    assert client.get(url, headers=other_headers).status_code == 403
    assert client.post(url, json={"answer": "Trying anyway."}, headers=other_headers).status_code == 403


def test_ai_practice_response_is_parsed_and_threshold_controls_status(
        client, docker_skill, student_id, auth_headers, monkeypatch):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, headers, sk, student_id)
    monkeypatch.setattr(genai, "genai_enabled", lambda: True)

    def fake_complete(system, user, max_tokens=None, timeout=None):
        assert "Learning Practice evaluator" in system
        assert "Submitted practice answer" in user
        return json.dumps({
            "score": 82,
            "status": "needs_review",
            "strengths": ["Clear persistence reasoning"],
            "missing_points": ["Mention one validation step"],
            "feedback": "Good applied answer with one small gap.",
            "next_action": "Take the Mini Check.",
            "source": "ai",
        })

    monkeypatch.setattr(genai, "complete", fake_complete)

    response = client.post(
        _practice_url(student_id, sk, item["competency"]),
        json={"answer": _rich_practice_answer()}, headers=headers)

    attempt = response.json()["attempt"]
    assert attempt["source"] == "ai"
    assert attempt["score"] == 82
    assert attempt["status"] == "ready"
    assert attempt["feedback"] == "Good applied answer with one small gap."


def test_malformed_ai_response_uses_labelled_fallback(
        client, docker_skill, student_id, auth_headers, monkeypatch):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, headers, sk, student_id)
    monkeypatch.setattr(genai, "genai_enabled", lambda: True)
    monkeypatch.setattr(genai, "complete", lambda *args, **kwargs: "not json")

    response = client.post(
        _practice_url(student_id, sk, item["competency"]),
        json={"answer": _rich_practice_answer()}, headers=headers)

    attempt = response.json()["attempt"]
    assert attempt["source"] == "fallback"
    assert "basic automated concept-coverage review" in attempt["feedback"]


def test_ai_exception_uses_labelled_fallback(
        client, docker_skill, student_id, auth_headers, monkeypatch):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, headers, sk, student_id)
    monkeypatch.setattr(genai, "genai_enabled", lambda: True)

    def failing_complete(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(genai, "complete", failing_complete)

    response = client.post(
        _practice_url(student_id, sk, item["competency"]),
        json={"answer": _rich_practice_answer()}, headers=headers)

    assert response.json()["attempt"]["source"] == "fallback"


def test_fallback_scores_under_70_as_needs_review():
    context = _manual_context()
    result = practice.evaluate_practice(context, "I would use Docker.")

    assert result["source"] == "fallback"
    assert result["score"] < 70
    assert result["status"] == "needs_review"


def test_fallback_scores_70_or_higher_as_ready():
    context = _manual_context()
    result = practice.evaluate_practice(context, _rich_practice_answer())

    assert result["source"] == "fallback"
    assert result["score"] >= 70
    assert result["status"] == "ready"


def _manual_context():
    return {
        "skill": {"id": 1, "name": "Docker"},
        "target_role": {"id": 1, "title": "Backend Developer"},
        "required_level": "Intermediate",
        "topic": {"competency": "container storage", "title": "Docker > container storage"},
        "diagnostic": {"topic_status": "weak", "diagnostic_score": 40},
        "lesson": {
            "learn": {
                "title": "Container storage",
                "explanation": "Containers need durable storage outside their lifecycle.",
                "key_ideas": [
                    "Persist data outside the container lifecycle.",
                    "Use docker volume create for Docker-managed persistence.",
                    "Use a bind mount for direct host directory access.",
                ],
                "key_terms": {
                    "named volume": "Docker-managed storage for persistent data.",
                    "bind mount": "A host directory mounted into a container.",
                },
            },
            "example": {
                "title": "Container storage in practice",
                "type": "command",
                "content": "Create a named volume, mount it, then verify the data.",
                "explanation": "The volume keeps data after the container is replaced.",
            },
            "practice": {
                "type": "practice",
                "questions": [{
                    "id": "p1",
                    "type": "free_text",
                    "question": "Explain when to use a named volume versus a bind mount.",
                    "correct_answer": "Use a named volume for portable persistence and a bind mount for direct host file access.",
                    "competency": "container storage",
                    "difficulty": "intermediate",
                }],
            },
            "mini_check_result": None,
        },
        "previous_attempts": [],
    }


def test_practice_does_not_complete_topic_or_mini_check(
        client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path, item, lesson = _setup_lesson(client, headers, sk, student_id)
    url = _practice_url(student_id, sk, item["competency"])

    response = client.post(url, json={"answer": _rich_practice_answer()}, headers=headers)
    assert response.status_code == 200

    lesson_after = client.get(
        f"/api/students/{student_id}/learning/{sk}/lessons/{_enc(item['competency'])}",
        headers=headers).json()
    path_after = client.get(
        f"/api/students/{student_id}/learning/{sk}/personalized-path",
        headers=headers).json()
    assert lesson_after["state"] == lesson["state"]
    assert lesson_after["mini_check_result"] is None
    assert item["id"] not in (path_after.get("progress") or [])
    assert item["id"] not in (path.get("progress") or [])


def test_practice_does_not_update_verified_skills(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, headers, sk, student_id)
    before = {(v["name"], v["level"]) for v in models.get_student(student_id).get("verified_skills") or []}

    client.post(
        _practice_url(student_id, sk, item["competency"]),
        json={"answer": _rich_practice_answer()}, headers=headers)

    after = {(v["name"], v["level"]) for v in models.get_student(student_id).get("verified_skills") or []}
    assert before == after


def test_practice_does_not_change_active_assessment_state(
        client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, headers, sk, student_id)
    models.start_active_assessment(student_id, sk)
    before = models.get_active_assessment(student_id)

    response = client.post(
        _practice_url(student_id, sk, item["competency"]),
        json={"answer": _rich_practice_answer()}, headers=headers)

    after = models.get_active_assessment(student_id)
    models.clear_active_assessment(student_id)
    assert response.status_code == 200
    assert before["skill_id"] == after["skill_id"] == sk


def test_mini_check_still_controls_completion_after_practice(
        client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, headers, sk, student_id)
    comp = item["competency"]
    lesson_url = f"/api/students/{student_id}/learning/{sk}/lessons/{_enc(comp)}"
    client.post(f"{lesson_url}/start", json={}, headers=headers)
    client.post(_practice_url(student_id, sk, comp),
                json={"answer": _rich_practice_answer()}, headers=headers)
    lesson = client.get(lesson_url, headers=headers).json()
    questions = lesson["content"]["mini_check"]["questions"]

    failed = client.post(
        f"{lesson_url}/mini-check",
        json={"answers": ["WRONG" for _ in questions]}, headers=headers).json()
    assert failed["lesson"]["state"] == "in_progress"
    assert failed["lesson"]["mini_check_result"]["passed"] is False
    assert item["id"] not in failed["path_progress"]

    passed = client.post(
        f"{lesson_url}/mini-check",
        json={"answers": [q["correct_answer"] for q in questions]}, headers=headers).json()
    assert passed["lesson"]["state"] == "completed"
    assert passed["lesson"]["mini_check_result"]["passed"] is True
    assert item["id"] in passed["path_progress"]


def test_final_assessment_generation_remains_accessible_before_learning_completion(
        client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _setup_lesson(client, headers, sk, student_id)

    response = client.post(
        f"/api/students/{student_id}/assessments/generate",
        json={"skill_id": sk, "num_questions": 3}, headers=headers)

    assert response.status_code == 200
    assert response.json()["questions"]


def test_practical_task_flows_through_existing_evaluator():
    context = json.loads(json.dumps(_manual_context()))
    context["lesson"]["practice"] = lessons.canonical_practice(None, "container storage")
    result = practice.evaluate_practice(context, _rich_practice_answer())
    assert result["source"] == "fallback"
    assert isinstance(result["score"], int)
    assert isinstance(result["missing_points"], list)
    assert isinstance(result["strengths"], list)


def test_legacy_mcq_practice_still_evaluates_without_crash():
    context = json.loads(json.dumps(_manual_context()))
    context["lesson"]["practice"] = {
        "type": "mcq",
        "questions": [
            {"id": "p1", "type": "mcq", "question": "Which approach persists data?",
             "options": ["named volume", "network"], "correct_answer": "named volume",
             "competency": "container storage", "difficulty": "beginner"},
        ],
    }
    result = practice.evaluate_practice(context, _rich_practice_answer())
    assert result["source"] == "fallback"
    assert isinstance(result["score"], int)


def test_generated_lesson_serves_single_practical_task(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path, item, lesson = _setup_lesson(client, headers, sk, student_id)
    practice_block = lesson["content"]["practice"]
    assert practice_block["type"] == "practical"
    assert practice_block["task"].strip()
    assert len(practice_block["questions"]) == 1
    assert practice_block["questions"][0]["type"] == "free_text"

    url = _practice_url(student_id, sk, item["competency"])
    response = client.post(url, json={"answer": _rich_practice_answer()}, headers=headers)
    assert response.status_code == 200
    assert response.json()["attempt"]["source"] in ("fallback", "ai")


def test_frontend_practice_submit_contract_is_not_405(client, docker_skill, student_id, auth_headers):
    """Reproduce the exact LearningPage submit request (frontend/src/lib/api.ts

    lessonSubmitPractice) byte-for-byte: POST, encodeURIComponent(competency),
    Authorization Bearer, Content-Type application/json, body {"answer": ...}.

    A 405 here means the backend route table no longer exposes the Phase 2
    Practice POST route (regression observed as `Method Not Allowed` in the
    browser when a stale server without the practice routes was running).
    """
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path, item, lesson = _setup_lesson(client, headers, sk, student_id)
    competency = item["competency"]

    api_ts_url = f"/api/students/{student_id}/learning/{sk}/lessons/{_enc(competency)}/practice"
    assert " " not in api_ts_url
    answer = "I would use statistics to look at the average and decide if the result is good."
    response = client.post(
        api_ts_url,
        headers={"Content-Type": "application/json", **headers},
        json={"answer": answer},
    )

    assert response.status_code == 200, (
        f"practice submit must not 405; got {response.status_code}: {response.text[:200]}")
    payload = response.json()
    attempt = payload["attempt"]
    assert attempt["competency"] == competency
    assert attempt["answer"] == answer
    assert isinstance(attempt["score"], (int, float))
    assert attempt["source"] in ("ai", "fallback")
    assert "strengths" in attempt and "missing_points" in attempt
    assert payload["attempts_count"] >= 1
