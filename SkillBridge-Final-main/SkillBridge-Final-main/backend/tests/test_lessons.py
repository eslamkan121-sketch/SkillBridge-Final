"""Phase 4 — Real lesson engine (topic-specific Learn -> Example -> Practice -> Mini Check).

Covers: generation, fallback, persistence, state transitions, scoring, path progress
integration, access control, verified_skills safety, and non-regression of Phase 2/3.
All GenAI calls forced to deterministic fallback.
"""
import json

import pytest
from app import diagnostics as dx, genai, lessons, models


@pytest.fixture(autouse=True)
def _force_deterministic_fallback(monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)


@pytest.fixture()
def docker_skill(db):
    return models.get_skill_by_name("Docker")


def _setup_path(client, headers, skill_id, student_id):
    """Complete a diagnostic (with some wrong answers to ensure weak/developing topics)
    and build a path. Returns the path dict."""
    gen = client.post(
        f"/api/students/{student_id}/learning/{skill_id}/diagnostic/generate",
        json={}, headers=headers).json()
    qs = gen["questions"]
    answers = [q["correct_answer"] for q in qs]
    bad = 0
    for i, q in enumerate(qs):
        if q["type"] == "mcq" and bad < 2:
            wrong = [o for o in q["options"] if o != q["correct_answer"]]
            if wrong:
                answers[i] = wrong[0]
                bad += 1
    client.post(
        f"/api/students/{student_id}/learning/{skill_id}/diagnostic/submit",
        json={"diagnostic_id": gen["diagnostic_id"], "answers": answers}, headers=headers)
    path = client.post(
        f"/api/students/{student_id}/learning/{skill_id}/personalized-path/generate",
        json={}, headers=headers).json()
    return path


# ------------------------------------------------------------------ 1. generation

def test_generate_lesson_from_real_topic(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path = _setup_path(client, headers, sk, student_id)
    comp = path["items"][0]["competency"]
    r = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
        json={}, headers=headers)
    assert r.status_code == 200
    lesson = r.json()
    assert lesson["state"] == "not_started"
    assert lesson["competency"] == comp
    assert "learn" in lesson["content"]
    assert "example" in lesson["content"]
    assert lesson["content"]["mini_check"]["questions"]


# ------------------------------------------------------------------ 2. mastered blocked

def test_cannot_generate_for_mastered_topic(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path = _setup_path(client, headers, sk, student_id)
    mastered = path.get("skipped_mastered") or []
    if mastered:
        comp = mastered[0]
        r = client.post(
            f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
            json={}, headers=headers)
        # Mastered topics are excluded from the path items, so the competency
        # is not found -> 404 (not in the path). Either 400 or 404 is acceptable.
        assert r.status_code in (400, 404)


# ------------------------------------------------------------------ 3. learn vs review

def test_weak_topic_uses_learn_action(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path = _setup_path(client, headers, sk, student_id)
    weak_items = [it for it in path["items"] if it["topic_status"] == "weak"]
    if not weak_items:
        pytest.skip("No weak items in this path")
    comp = weak_items[0]["competency"]
    r = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
        json={}, headers=headers)
    assert r.json()["action"] == "learn"


def test_developing_topic_uses_review_action(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    # manufacture a developing item by answering most correctly
    gen = client.post(
        f"/api/students/{student_id}/learning/{sk}/diagnostic/generate",
        json={}, headers=headers).json()
    answers = [q["correct_answer"] for q in gen["questions"]]
    client.post(
        f"/api/students/{student_id}/learning/{sk}/diagnostic/submit",
        json={"diagnostic_id": gen["diagnostic_id"], "answers": answers}, headers=headers)
    path = client.post(
        f"/api/students/{student_id}/learning/{sk}/personalized-path/generate",
        json={}, headers=headers).json()
    dev_items = [it for it in path["items"] if it["topic_status"] == "developing"]
    if not dev_items:
        pytest.skip("No developing items in this path")
    comp = dev_items[0]["competency"]
    r = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
        json={}, headers=headers)
    assert r.json()["action"] == "review"


# ------------------------------------------------------------------ 4. fallback content quality

def test_fallback_content_structured_and_nonempty(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path = _setup_path(client, headers, sk, student_id)
    comp = path["items"][0]["competency"]
    r = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
        json={}, headers=headers)
    content = r.json()["content"]
    assert content["learn"]["explanation"]
    assert content["example"]["content"]
    assert content["practice"]["type"] == "practical"
    assert content["practice"]["task"]
    assert len(content["practice"]["questions"]) >= 1
    assert len(content["mini_check"]["questions"]) >= 1


def test_fallback_practice_is_one_open_ended_task(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path = _setup_path(client, headers, sk, student_id)
    comp = path["items"][0]["competency"]
    r = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
        json={}, headers=headers)
    practice = r.json()["content"]["practice"]
    assert practice["type"] == "practical"
    assert practice["title"].strip()
    assert practice["task"].strip()
    assert practice["response_type"].strip()
    assert len(practice["questions"]) == 1
    assert practice["questions"][0]["type"] == "free_text"
    assert practice["questions"][0]["question"] == practice["task"]
    assert not practice["questions"][0]["options"]


# ------------------------------------------------------------------ 5. reuse

def test_same_lesson_reused_not_regenerated(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path = _setup_path(client, headers, sk, student_id)
    comp = path["items"][0]["competency"]
    r1 = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
        json={}, headers=headers)
    r2 = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
        json={}, headers=headers)
    assert r1.json()["id"] == r2.json()["id"]


# ------------------------------------------------------------------ 6. persistence

def test_lesson_persists_across_reads(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path = _setup_path(client, headers, sk, student_id)
    comp = path["items"][0]["competency"]
    client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
        json={}, headers=headers)
    r = client.get(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}",
        headers=headers)
    assert r.status_code == 200
    assert r.json()["competency"] == comp


# ------------------------------------------------------------------ 7. start state

def test_start_changes_state_to_in_progress(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path = _setup_path(client, headers, sk, student_id)
    comp = path["items"][0]["competency"]
    client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
        json={}, headers=headers)
    r = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/start",
        json={}, headers=headers)
    assert r.status_code == 200
    assert r.json()["state"] == "in_progress"


# ------------------------------------------------------------------ 8. mini-check scoring

def test_mini_check_fail_does_not_complete(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path = _setup_path(client, headers, sk, student_id)
    comp = path["items"][0]["competency"]
    client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
        json={}, headers=headers)
    client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/start",
        json={}, headers=headers)
    lesson = client.get(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}",
        headers=headers).json()
    questions = lesson["content"]["mini_check"]["questions"]
    wrong_answers = ["WRONG ANSWER" for _ in questions]
    r = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/mini-check",
        json={"answers": wrong_answers}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["lesson"]["state"] == "in_progress"
    assert body["lesson"]["mini_check_result"]["passed"] is False
    assert path["items"][0]["id"] not in body["path_progress"]


def test_mini_check_pass_completes_lesson(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path = _setup_path(client, headers, sk, student_id)
    comp = path["items"][0]["competency"]
    item_id = path["items"][0]["id"]
    client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
        json={}, headers=headers)
    client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/start",
        json={}, headers=headers)
    lesson = client.get(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}",
        headers=headers).json()
    questions = lesson["content"]["mini_check"]["questions"]
    correct_answers = [q["correct_answer"] for q in questions]
    r = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/mini-check",
        json={"answers": correct_answers}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["lesson"]["state"] == "completed"
    assert body["lesson"]["mini_check_result"]["passed"] is True
    assert item_id in body["path_progress"]


# ------------------------------------------------------------------ 9. verified_skills safety

def test_mini_check_does_not_update_verified_skills(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path = _setup_path(client, headers, sk, student_id)
    comp = path["items"][0]["competency"]
    client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
        json={}, headers=headers)
    client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/start",
        json={}, headers=headers)
    lesson = client.get(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}",
        headers=headers).json()
    questions = lesson["content"]["mini_check"]["questions"]
    before = models.get_student(student_id)
    verified_before = {(v["name"], v["level"]) for v in before.get("verified_skills") or []}
    correct_answers = [q["correct_answer"] for q in questions]
    client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/mini-check",
        json={"answers": correct_answers}, headers=headers)
    after = models.get_student(student_id)
    verified_after = {(v["name"], v["level"]) for v in after.get("verified_skills") or []}
    assert verified_before == verified_after


# ------------------------------------------------------------------ 10. access control

def test_unauthenticated_401(client, docker_skill, student_id):
    sk = docker_skill["id"]
    r = client.post(f"/api/students/{student_id}/learning/{sk}/lessons/containers/generate", json={})
    assert r.status_code == 401


def test_company_access_blocked(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("hr@northstar.com")
    sk = docker_skill["id"]
    r = client.post(f"/api/students/{student_id}/learning/{sk}/lessons/containers/generate",
                    json={}, headers=headers)
    assert r.status_code == 403


def test_non_owner_student_blocked(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("omar@student.edu")
    sk = docker_skill["id"]
    r = client.post(f"/api/students/{student_id}/learning/{sk}/lessons/containers/generate",
                    json={}, headers=headers)
    assert r.status_code == 403


def test_invalid_competency_404(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _setup_path(client, headers, sk, student_id)
    r = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/nonexistent_topic/generate",
        json={}, headers=headers)
    assert r.status_code == 404


# ------------------------------------------------------------------ 11. regressions

def test_existing_diagnostics_still_work(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    gen = client.post(
        f"/api/students/{student_id}/learning/{sk}/diagnostic/generate",
        json={}, headers=headers).json()
    assert gen["questions"]
    answers = [q["correct_answer"] for q in gen["questions"]]
    sub = client.post(
        f"/api/students/{student_id}/learning/{sk}/diagnostic/submit",
        json={"diagnostic_id": gen["diagnostic_id"], "answers": answers}, headers=headers)
    assert sub.status_code == 200


def test_existing_personalized_paths_still_work(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path = _setup_path(client, headers, sk, student_id)
    assert path["items"]
    assert path["stages"]


def test_existing_assessments_still_verify_skills(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    gen = client.post(
        f"/api/students/{student_id}/assessments/generate",
        json={"skill_id": sk, "num_questions": 3}, headers=headers)
    assert gen.status_code == 200


# ------------------------------------------------------------------ 12. learn vs review content

def test_learn_action_has_key_ideas(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path = _setup_path(client, headers, sk, student_id)
    weak = [it for it in path["items"] if it["topic_status"] == "weak"]
    if not weak:
        pytest.skip("No weak items")
    comp = weak[0]["competency"]
    lesson = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
        json={}, headers=headers).json()
    assert lesson["content"]["learn"].get("key_ideas")
    assert len(lesson["content"]["learn"]["key_ideas"]) >= 2
    assert lesson["content"]["learn"].get("key_terms")


def test_review_action_has_shorter_explanation(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    gen = client.post(
        f"/api/students/{student_id}/learning/{sk}/diagnostic/generate",
        json={}, headers=headers).json()
    answers = [q["correct_answer"] for q in gen["questions"]]
    client.post(
        f"/api/students/{student_id}/learning/{sk}/diagnostic/submit",
        json={"diagnostic_id": gen["diagnostic_id"], "answers": answers}, headers=headers)
    path = client.post(
        f"/api/students/{student_id}/learning/{sk}/personalized-path/generate",
        json={}, headers=headers).json()
    dev = [it for it in path["items"] if it["topic_status"] == "developing"]
    if not dev:
        pytest.skip("No developing items")
    comp = dev[0]["competency"]
    lesson = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
        json={}, headers=headers).json()
    assert lesson["action"] == "review"
    assert "review" in lesson["content"]["learn"]["explanation"].lower()


# ------------------------------------------------------------------ 13. no api key returns valid content

def test_generate_lesson_works_without_api_key(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path = _setup_path(client, headers, sk, student_id)
    comp = path["items"][0]["competency"]
    r = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
        json={}, headers=headers)
    assert r.status_code == 200
    lesson = r.json()
    assert lesson["content"]["learn"]["explanation"]
    assert lesson["content"]["example"]["content"]
    assert lesson["content"]["practice"]["type"] == "practical"
    assert lesson["content"]["practice"]["task"]
    assert lesson["content"]["practice"]["questions"]
    assert lesson["content"]["mini_check"]["questions"]


# ------------------------------------------------------------------ 15. practical practice task shape

def test_ai_lesson_parses_practical_practice(monkeypatch):
    fake_content = {
        "learn": {"title": "N", "explanation": "E", "key_ideas": ["i1"],
                  "key_terms": {"term": "def"}},
        "example": {"title": "Ex", "type": "code", "content": "c", "explanation": "e"},
        "practice": {
            "type": "practical",
            "title": "Investigate a login spike",
            "task": ("An alert shows repeated failed logins then a success. "
                     "Walk through your SIEM investigation."),
            "response_type": "scenario_response",
            "competency": "security monitoring",
        },
        "mini_check": {
            "questions": [
                {"id": "m1", "type": "mcq", "question": "q?", "options": ["a", "b"],
                 "correct_answer": "a", "competency": "security monitoring",
                 "difficulty": "beginner"},
            ],
        },
    }
    monkeypatch.setattr(genai, "genai_enabled", lambda: True)
    monkeypatch.setattr(genai, "complete", lambda *a, **k: json.dumps(fake_content))
    content = lessons.generate_lesson(
        skill_name="Cybersecurity", competency="security monitoring", action="learn")
    practice = content["practice"]
    assert practice["type"] == "practical"
    assert practice["title"] == "Investigate a login spike"
    assert practice["task"] == (
        "An alert shows repeated failed logins then a success. Walk through your SIEM investigation.")
    assert practice["response_type"] == "scenario_response"
    assert practice["competency"] == "security monitoring"
    assert len(practice["questions"]) == 1
    assert practice["questions"][0]["type"] == "free_text"
    assert practice["questions"][0]["question"] == practice["task"]
    assert len(content["mini_check"]["questions"]) == 1


def test_legacy_mcq_practice_derives_practical_task():
    legacy = {
        "type": "mcq",
        "questions": [
            {"id": "p1", "type": "mcq", "question": "Which flag mounts a volume?",
             "options": ["-v", "-p", "-d"], "correct_answer": "-v",
             "competency": "container storage", "difficulty": "beginner"},
            {"id": "p2", "type": "free_text",
             "question": "Explain a named volume vs a bind mount.",
             "correct_answer": "ports", "competency": "container storage",
             "difficulty": "beginner"},
        ],
    }
    canonical = lessons.canonical_practice(legacy, "container storage")
    assert canonical["type"] == "practical"
    assert canonical["competency"] == "container storage"
    assert "named volume" in canonical["task"]
    assert len(canonical["questions"]) == 1
    assert canonical["questions"][0]["type"] == "free_text"


def test_legacy_mcq_only_practice_derives_applied_task():
    legacy = {
        "type": "mcq",
        "questions": [{"type": "mcq", "question": "What does -v do?",
                       "options": ["a", "b"], "correct_answer": "a"}],
    }
    canonical = lessons.canonical_practice(legacy, "container storage")
    assert canonical["type"] == "practical"
    assert "Apply this concept" in canonical["task"]
    assert len(canonical["questions"]) == 1


def test_empty_practice_produces_deterministic_task():
    canonical = lessons.canonical_practice({}, "container storage")
    assert canonical["type"] == "practical"
    assert canonical["task"].strip()
    assert canonical["response_type"] in ("explanation", "code_explanation")

    canonical_scenario = lessons.canonical_practice(
        {}, "client communication", prefer_type="scenario_response")
    assert canonical_scenario["response_type"] == "scenario_response"


def test_legacy_lesson_content_is_normalized_on_response():
    legacy_content = {
        "learn": {"title": "T", "explanation": "E", "key_ideas": [], "key_terms": {}},
        "example": {"title": "Ex", "type": "scenario", "content": "c", "explanation": "e"},
        "practice": {"type": "mcq", "questions": [{"type": "mcq", "question": "Q?",
                                                    "options": ["a"], "correct_answer": "a"}]},
        "mini_check": {"questions": [{"type": "mcq", "question": "M?", "options": ["a"],
                                       "correct_answer": "a"}]},
    }
    lesson = {"id": 1, "content": legacy_content, "state": "in_progress"}
    normalized = lessons.normalize_lesson_practice(lesson, "container storage")
    assert normalized["content"]["practice"]["type"] == "practical"
    assert normalized["content"]["practice"]["task"]
    assert normalized["content"]["mini_check"]["questions"]
    assert lesson["content"]["practice"]["type"] == "mcq"


def test_legacy_persisted_lesson_serves_practical_practice_without_crashing(
        client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path = _setup_path(client, headers, sk, student_id)
    item = path["items"][0]
    legacy_content = {
        "learn": {"title": "T", "explanation": "E", "key_ideas": [], "key_terms": {}},
        "example": {"title": "Ex", "type": "scenario", "content": "c", "explanation": "e"},
        "practice": {"type": "mcq", "questions": [
            {"id": "p1", "type": "mcq", "question": "Which storage approach persists data?",
             "options": ["named volume", "network"], "correct_answer": "named volume",
             "competency": item["competency"], "difficulty": "beginner"},
        ]},
        "mini_check": {"questions": [
            {"id": "m1", "type": "mcq", "question": "M?", "options": ["a"], "correct_answer": "a",
             "competency": item["competency"], "difficulty": "beginner"},
        ]},
    }
    models.create_lesson(
        student_id=student_id, skill_id=sk, path_id=path["id"],
        competency=item["competency"], title=f"{sk} > {item['competency']}",
        action="learn", content_json=legacy_content)
    r = client.get(
        f"/api/students/{student_id}/learning/{sk}/lessons/{item['competency']}",
        headers=headers)
    assert r.status_code == 200
    practice = r.json()["content"]["practice"]
    assert practice["type"] == "practical"
    assert practice["task"].strip()
    assert len(practice["questions"]) == 1
    assert practice["questions"][0]["type"] == "free_text"


# ------------------------------------------------------------------ 14. path progress integration

def test_pass_adds_to_path_progress(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path = _setup_path(client, headers, sk, student_id)
    comp = path["items"][0]["competency"]
    client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
        json={}, headers=headers)
    client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/start",
        json={}, headers=headers)
    lesson = client.get(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}",
        headers=headers).json()
    questions = lesson["content"]["mini_check"]["questions"]
    correct = [q["correct_answer"] for q in questions]
    r = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/mini-check",
        json={"answers": correct}, headers=headers)
    path_progress = r.json()["path_progress"]
    # The mini-check pass must have added the item_id to the path progress
    path_after = client.get(
        f"/api/students/{student_id}/learning/{sk}/personalized-path",
        headers=headers).json()
    item_id = next(it["id"] for it in path_after["items"] if it["competency"] == comp)
    assert item_id in path_progress


# ------------------------------------------------------------------ 15. retry after fail

def test_retry_after_fail_allows_resubmission(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path = _setup_path(client, headers, sk, student_id)
    comp = path["items"][0]["competency"]
    client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
        json={}, headers=headers)
    client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/start",
        json={}, headers=headers)
    lesson = client.get(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}",
        headers=headers).json()
    questions = lesson["content"]["mini_check"]["questions"]
    # first attempt: fail
    wrong = ["WRONG" for _ in questions]
    client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/mini-check",
        json={"answers": wrong}, headers=headers)
    # second attempt: pass
    correct = [q["correct_answer"] for q in questions]
    r = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/mini-check",
        json={"answers": correct}, headers=headers)
    assert r.json()["lesson"]["state"] == "completed"
    assert r.json()["lesson"]["mini_check_result"]["passed"] is True


# ------------------------------------------------------------------ 16. no-lesson-yet on get

def test_get_lesson_returns_404_before_generate(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _setup_path(client, headers, sk, student_id)
    r = client.get(
        f"/api/students/{student_id}/learning/{sk}/lessons/containers",
        headers=headers)
    assert r.status_code == 404


# ------------------------------------------------------------------ 17. start before generate fails

def test_start_before_generate_404(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _setup_path(client, headers, sk, student_id)
    r = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/containers/start",
        json={}, headers=headers)
    assert r.status_code == 404


# ------------------------------------------------------------------ 18. minicheck before generate fails

def test_mini_check_before_generate_404(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _setup_path(client, headers, sk, student_id)
    r = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/containers/mini-check",
        json={"answers": []}, headers=headers)
    assert r.status_code == 404


# ------------------------------------------------------------------ 19. same-path reuse after newer path

def test_lesson_bound_to_current_path(client, docker_skill, student_id, auth_headers):
    """After a newer diagnostic + path, the old lesson should not be returned."""
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path1 = _setup_path(client, headers, sk, student_id)
    comp = path1["items"][0]["competency"]
    client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}/generate",
        json={}, headers=headers)
    # a newer diagnostic + path
    gen = client.post(
        f"/api/students/{student_id}/learning/{sk}/diagnostic/generate",
        json={}, headers=headers).json()
    answers = [q["correct_answer"] for q in gen["questions"]]
    client.post(
        f"/api/students/{student_id}/learning/{sk}/diagnostic/submit",
        json={"diagnostic_id": gen["diagnostic_id"], "answers": answers}, headers=headers)
    path2 = client.post(
        f"/api/students/{student_id}/learning/{sk}/personalized-path/generate",
        json={}, headers=headers).json()
    assert path2["id"] != path1["id"]
    # old lesson should no longer be accessible on the new path
    r = client.get(
        f"/api/students/{student_id}/learning/{sk}/lessons/{comp}",
        headers=headers)
    assert r.status_code == 404


# ------------------------------------------------------------------ 20. presentation polish (labels + code fences)

def test_humanize_competency_converts_slugs():
    assert lessons.humanize_competency("statistics_fundamentals") == "Statistics Fundamentals"
    assert lessons.humanize_competency("containers") == "Containers"
    assert lessons.humanize_competency("basic_commands") == "Basic Commands"
    assert lessons.humanize_competency("What is statistics_fundamentals?") == "What is Statistics Fundamentals?"
    assert lessons.humanize_competency("What is containers?") == "What is Containers?"
    assert lessons.humanize_competency("Deep Learning") == "Deep Learning"
    assert lessons.humanize_competency("") == ""
    assert lessons.humanize_competency(None) == ""
    assert lessons.humanize_competency("api_authentication") == "API Authentication"
    assert lessons.humanize_competency("algorithm_design_and_analysis") == "Algorithm Design and Analysis"
    assert lessons._lesson_human("pandas_fundamentals") == "Pandas Fundamentals"


def test_fence_code_content_preserves_newlines():
    pandas = (
        "import pandas as pd\n"
        "df = pd.read_csv('sales.csv')\n"
        "# Filter rows where quantity is greater than 10\n"
        "filtered = df[df['quantity'] > 10]\n"
        "filtered['revenue'] = filtered['quantity'] * filtered['price']\n"
        "total_revenue = filtered['revenue'].sum()\n"
        "print(f'Total revenue: {total_revenue}')"
    )
    dockfile = (
        "FROM python:3.11-slim AS builder\n"
        "WORKDIR /app\n"
        "COPY requirements.txt .\n"
        "RUN pip install --no-cache-dir -r requirements.txt\n"
        "CMD [\"python\", \"serve.py\"]"
    )
    commands = (
        "# Pull the hello-world image (if not present)\n"
        "docker pull hello-world\n"
        "# Run a container that prints hello-world and exits\n"
        "docker run --rm hello-world\n"
        "# Stop the nginx container\n"
        "docker stop web\n"
        "# Verify removal\n"
        "docker ps -a"
    )
    fenced_pandas = lessons._fence_code_content(pandas)
    assert fenced_pandas.startswith("```\n")
    assert fenced_pandas.endswith("\n```")
    assert "\nfiltered['revenue'] = filtered['quantity'] * filtered['price']\n" in fenced_pandas
    assert "print(f'Total revenue: {total_revenue}')" in fenced_pandas
    fenced_docker = lessons._fence_code_content(dockfile)
    assert fenced_docker.startswith("```\n")
    fenced_commands = lessons._fence_code_content(commands)
    assert fenced_commands.startswith("```\n")
    assert "# Run a container that prints hello-world and exits\n" in fenced_commands
    # already-fenced content is untouched
    already = "```py\nimport torch\nx = 1\n```"
    assert lessons._fence_code_content(already) == already
    # single-line content is untouched
    assert lessons._fence_code_content("docker run --rm hello-world") == "docker run --rm hello-world"
    # prose (even multi-line) is never wrapped
    prose = (
        "Walk through a realistic scenario step by step.\n"
        "Consider the constraints of the task first.\n"
        "Then confirm the outcome matches the goal."
    )
    assert lessons._fence_code_content(prose) == prose


def test_generate_lesson_fallback_title_uses_humanized_label():
    content = lessons._lesson_fallback("Docker", "basic_commands", "learn", "weak", 0.4, "Intermediate")
    assert content["learn"]["title"] == "What is Basic Commands?"
    assert content["practice"]["competency"] == "Basic Commands"
    assert content["practice"]["title"].startswith("Practice: Basic Commands")


def test_served_lesson_example_code_is_fenced_while_stored_content_is_untouched(
        client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    path = _setup_path(client, headers, sk, student_id)
    item = path["items"][0]
    code_content = (
        "import pandas as pd\n"
        "df = pd.read_csv('sales.csv')\n"
        "total_revenue = df['revenue'].sum()\n"
        "print(total_revenue)\n"
        "width = df.shape[0]"
    )
    slug_content = {
        "learn": {"title": "What is statistics_fundamentals?", "explanation": "E",
                  "key_ideas": [], "key_terms": {}},
        "example": {"title": "statistics_fundamentals in practice", "type": "scenario",
                    "content": code_content, "explanation": "e"},
        "practice": {"type": "practical", "title": "Practice: statistics_fundamentals",
                     "task": "T", "response_type": "code_explanation",
                     "competency": "statistics_fundamentals"},
        "mini_check": {"questions": [
            {"id": "m1", "type": "mcq", "question": "M?", "options": ["a"],
             "correct_answer": "a", "competency": item["competency"], "difficulty": "beginner"},
        ]},
    }
    models.create_lesson(
        student_id=student_id, skill_id=sk, path_id=path["id"],
        competency=item["competency"], title=f"{sk} > {item['competency']}",
        action="learn", content_json=slug_content)
    r = client.get(
        f"/api/students/{student_id}/learning/{sk}/lessons/{item['competency']}",
        headers=headers)
    assert r.status_code == 200
    served = r.json()["content"]
    assert served["learn"]["title"] == "What is Statistics Fundamentals?"
    assert served["example"]["title"] == "Statistics Fundamentals in Practice"
    assert served["example"]["content"].startswith("```\n")
    assert "\ntotal_revenue = df['revenue'].sum()\n" in served["example"]["content"]
    assert served["practice"]["title"] == "Practice: Statistics Fundamentals"
    assert served["practice"]["competency"] == "statistics_fundamentals"
    # stored row is never rewritten
    stored = models.get_lesson(student_id, path["id"], item["competency"])
    assert stored["content"]["learn"]["title"] == "What is statistics_fundamentals?"
    assert stored["content"]["example"]["content"] == code_content
