"""Learning Phase 3 — adaptive remediation after low Practice scores.

Remediation lives inside the existing lesson: a low Practice attempt (<70)
produces a Personalized Review with a NEW targeted example and a NEW follow-up
task. The follow-up answer is evaluated by the SAME Phase 2 Practice evaluator,
and the follow-up task itself is resolved server-side from the persisted source
attempt (never accepted from the frontend). Remediation never completes a topic,
never verifies a skill, and never changes Final Assessment or Mini Check state.
"""
import json

import pytest

from app import genai, lessons, models, practice
from tests.test_learning_practice import (
    _enc,
    _manual_context,
    _practice_url,
    _rich_practice_answer,
    _setup_lesson,
)


@pytest.fixture(autouse=True)
def _force_deterministic_fallback(monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)


@pytest.fixture()
def docker_skill(db):
    return models.get_skill_by_name("Docker")


def _low_evaluation():
    return {
        "score": 40,
        "status": "needs_review",
        "strengths": ["Submitted a concrete response"],
        "missing_points": ["Does not mention durable storage"],
        "feedback": "Basic coverage review: one gap remains.",
        "next_action": "Revise and resubmit with the missing concept.",
        "source": "fallback",
    }


def _ready_evaluation():
    return {
        "score": 85,
        "status": "ready",
        "strengths": ["Clear persistence reasoning"],
        "missing_points": [],
        "feedback": "Good applied answer — ready for the Mini Check.",
        "next_action": "Continue to the Mini Check when you feel ready.",
        "source": "fallback",
    }


def _submit(client, student_id, sk, comp, headers, **body):
    response = client.post(_practice_url(student_id, sk, comp), json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["attempt"]


def test_low_score_creates_remediation_and_persists(
        client, docker_skill, student_id, auth_headers, monkeypatch):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, headers, sk, student_id)
    monkeypatch.setattr(practice, "evaluate_practice", lambda ctx, ans: _low_evaluation())

    attempt = _submit(client, student_id, sk, item["competency"], headers,
                      answer="I would run the volume again.")

    remediation = attempt["remediation"]
    assert remediation is not None
    assert remediation["source"] == "fallback"
    assert remediation["focus_points"]
    assert remediation["explanation"]
    assert remediation["targeted_example"]
    assert remediation["follow_up_task"]
    assert remediation["practice_attempt_id"] == attempt["id"]

    history = client.get(_practice_url(student_id, sk, item["competency"]), headers=headers).json()
    assert history["latest"]["id"] == attempt["id"]
    assert history["latest"]["remediation"]["practice_attempt_id"] == attempt["id"]
    assert (history["latest"]["remediation"]["follow_up_task"]
            == remediation["follow_up_task"])


def test_high_score_does_not_create_remediation(
        client, docker_skill, student_id, auth_headers, monkeypatch):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, headers, sk, student_id)
    monkeypatch.setattr(practice, "evaluate_practice", lambda ctx, ans: _ready_evaluation())

    attempt = _submit(client, student_id, sk, item["competency"], headers,
                      answer=_rich_practice_answer())

    assert attempt["status"] == "ready"
    assert attempt["score"] == 85
    assert attempt["remediation"] is None


def test_hermetic_low_and_high_trigger_remediation():
    context = _manual_context()
    low = practice.evaluate_practice(context, "I would use Docker.")
    assert low["score"] < 70
    assert low["status"] == "needs_review"
    remediation = practice.generate_remediation(context, low, "I would use Docker.")
    assert remediation is not None
    assert remediation["source"] == "fallback"
    assert remediation["focus_points"]
    assert remediation["explanation"]
    assert remediation["targeted_example"]
    assert remediation["follow_up_task"]

    ready = practice.evaluate_practice(context, _rich_practice_answer())
    assert ready["score"] >= 70
    assert ready["status"] == "ready"
    assert practice.generate_remediation(context, ready, _rich_practice_answer()) is None


def test_follow_up_task_is_trusted_and_spoofing_is_ignored(
        client, docker_skill, student_id, auth_headers, monkeypatch):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, headers, sk, student_id)
    monkeypatch.setattr(practice, "evaluate_practice", lambda ctx, ans: _low_evaluation())

    source = _submit(client, student_id, sk, item["competency"], headers,
                     answer="I would run the volume again.")
    follow_up = source["remediation"]["follow_up_task"]

    spoofed = client.post(
        _practice_url(student_id, sk, item["competency"]),
        json={
            "answer": "I fixed the syntax gap.",
            "practice_task_source_attempt_id": source["id"],
            "follow_up_task": "SPOOFED FRONTEND TASK",
            "practice_task": {"source": "lesson", "questions": [{"question": "SPOOFED"}]},
            "score": 99,
        },
        headers=headers).json()["attempt"]

    assert spoofed["id"] != source["id"]
    assert spoofed["practice_task"]["source"] == "remediation"
    assert spoofed["practice_task"]["source_attempt_id"] == source["id"]
    task_question = spoofed["practice_task"]["questions"][0]["question"]
    assert task_question == follow_up
    assert task_question != "SPOOFED FRONTEND TASK"
    assert spoofed["answer"] == "I fixed the syntax gap."
    assert spoofed["score"] != 99

    history = client.get(_practice_url(student_id, sk, item["competency"]), headers=headers).json()
    assert history["count"] == 2
    assert history["latest"]["practice_task"]["source"] == "remediation"
    assert history["latest"]["practice_task"]["source_attempt_id"] == source["id"]
    assert history["latest"]["practice_task"]["questions"][0]["question"] == follow_up


def test_bogus_or_remediation_free_follow_up_source_rejected(
        client, docker_skill, student_id, auth_headers, monkeypatch):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, headers, sk, student_id)
    url = _practice_url(student_id, sk, item["competency"])
    monkeypatch.setattr(practice, "evaluate_practice", lambda ctx, ans: _ready_evaluation())

    ready_attempt = _submit(client, student_id, sk, item["competency"], headers,
                            answer=_rich_practice_answer())
    assert ready_attempt["remediation"] is None
    no_task = client.post(
        url,
        json={"answer": "Still practising.", "practice_task_source_attempt_id": ready_attempt["id"]},
        headers=headers)
    assert no_task.status_code == 400
    assert "no follow-up task" in no_task.json()["detail"]

    bogus = client.post(
        url,
        json={"answer": "Still practising.", "practice_task_source_attempt_id": 999999},
        headers=headers)
    assert bogus.status_code == 404


def test_cross_student_follow_up_source_blocked(
        client, docker_skill, student_id, auth_headers, login, monkeypatch):
    sk = docker_skill["id"]
    omar_id = login("omar@student.edu")["student"]["id"]
    omar_headers = auth_headers("omar@student.edu")
    _, omar_item, _ = _setup_lesson(client, omar_headers, sk, omar_id)

    aisha_headers = auth_headers("aisha@student.edu")
    _, item, _ = _setup_lesson(client, aisha_headers, sk, student_id)
    monkeypatch.setattr(practice, "evaluate_practice", lambda ctx, ans: _low_evaluation())
    source = _submit(client, student_id, sk, item["competency"], aisha_headers,
                     answer="I would run the volume again.")

    response = client.post(
        _practice_url(omar_id, sk, omar_item["competency"]),
        json={"answer": "Hijack attempt.", "practice_task_source_attempt_id": source["id"]},
        headers=omar_headers)
    assert response.status_code == 404


def test_remediation_does_not_complete_topic_or_verify_skill(
        client, docker_skill, student_id, auth_headers, monkeypatch):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, headers, sk, student_id)
    before = {(v["name"], v["level"]) for v in models.get_student(student_id).get("verified_skills") or []}
    monkeypatch.setattr(practice, "evaluate_practice", lambda ctx, ans: _low_evaluation())
    url = _practice_url(student_id, sk, item["competency"])

    source = _submit(client, student_id, sk, item["competency"], headers, answer="Weak attempt 1.")
    client.post(
        url,
        json={"answer": "Follow-up answer.", "practice_task_source_attempt_id": source["id"]},
        headers=headers)

    lesson_after = client.get(
        f"/api/students/{student_id}/learning/{sk}/lessons/{_enc(item['competency'])}",
        headers=headers).json()
    path_after = client.get(
        f"/api/students/{student_id}/learning/{sk}/personalized-path",
        headers=headers).json()
    assert lesson_after["state"] != "completed"
    assert lesson_after["mini_check_result"] is None
    assert item["id"] not in (path_after.get("progress") or [])

    after = {(v["name"], v["level"]) for v in models.get_student(student_id).get("verified_skills") or []}
    assert before == after

    generation = client.post(
        f"/api/students/{student_id}/assessments/generate",
        json={"skill_id": sk, "num_questions": 3}, headers=headers)
    assert generation.status_code == 200


def test_ai_remediation_json_is_parsed(
        client, docker_skill, student_id, auth_headers, monkeypatch):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, headers, sk, student_id)
    monkeypatch.setattr(genai, "genai_enabled", lambda: True)

    def fake_complete(system, user, max_tokens=None, timeout=None):
        if "Learning Practice evaluator" in system:
            return json.dumps({
                "score": 45, "status": "needs_review",
                "strengths": ["Started a response"], "missing_points": ["Syntax"],
                "feedback": "Gaps remain.", "next_action": "Revise.",
                "source": "ai",
            })
        if "adaptive Learning remediation writer" in system:
            assert "latest_practice_attempt" in user
            return json.dumps({
                "focus_points": ["Syntax"],
                "explanation": "Compose syntax controls the container graph.",
                "targeted_example": "Declare services under the services key.",
                "follow_up_task": "Fix the compose file so the app starts.",
                "source": "ai",
            })
        raise AssertionError(f"Unexpected genai call: {system[:60]}")

    monkeypatch.setattr(genai, "complete", fake_complete)

    attempt = _submit(client, student_id, sk, item["competency"], headers,
                      answer="I would rewrite the compose file.")
    assert attempt["score"] == 45
    assert attempt["source"] == "ai"
    assert attempt["remediation"]["source"] == "ai"
    assert attempt["remediation"]["focus_points"] == ["Syntax"]
    assert attempt["remediation"]["follow_up_task"] == "Fix the compose file so the app starts."


def test_remediation_targeted_example_code_is_fenced_on_response(
        client, docker_skill, student_id, auth_headers, monkeypatch):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, headers, sk, student_id)
    code_example = (
        "import torch\n"
        "import torch.nn as nn\n\n"
        "class NetWithAct(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.layers = nn.Sequential(nn.Linear(4, 2), nn.ReLU())\n\n"
        "model = NetWithAct()\n"
        "print(model)"
    )
    monkeypatch.setattr(practice, "evaluate_practice", lambda ctx, ans: _low_evaluation())
    monkeypatch.setattr(practice, "generate_remediation", lambda ctx, result, answer: {
        "focus_points": ["activation layers"],
        "explanation": "Use activations between linear layers.",
        "targeted_example": code_example,
        "follow_up_task": "Add an activation to the model.",
        "source": "ai",
    })

    attempt = _submit(client, student_id, sk, item["competency"], headers,
                      answer="I would add a layer.")
    served = attempt["remediation"]["targeted_example"]

    assert served.startswith("```\n")
    assert served.endswith("\n```")
    assert "\nimport torch.nn as nn\n" in served
    assert "\n    def __init__(self):\n" in served
    assert "\nmodel = NetWithAct()\n" in served

    history = client.get(_practice_url(student_id, sk, item["competency"]),
                         headers=headers).json()
    assert history["latest"]["remediation"]["targeted_example"] == served


def test_remediation_prose_targeted_example_stays_prose():
    prose = {
        "focus_points": ["stakeholder context"],
        "explanation": "Focus the retry.",
        "targeted_example": (
            "In a workplace scenario, identify who needs the update, explain the "
            "tradeoff, and confirm the next action."),
        "follow_up_task": "Write the update.",
        "source": "fallback",
    }

    normalized = lessons.normalize_remediation_review(prose)

    assert normalized["targeted_example"] == prose["targeted_example"]
    assert not normalized["targeted_example"].startswith("```")


def test_bad_ai_remediation_json_uses_labelled_fallback(
        client, docker_skill, student_id, auth_headers, monkeypatch):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, headers, sk, student_id)
    monkeypatch.setattr(genai, "genai_enabled", lambda: True)

    def fake_complete(system, user, max_tokens=None, timeout=None):
        if "Learning Practice evaluator" in system:
            return json.dumps({
                "score": 45, "status": "needs_review",
                "strengths": ["Start"], "missing_points": ["Syntax"],
                "feedback": "Gaps remain.", "next_action": "Revise.",
                "source": "ai",
            })
        return "this is not valid json at all"

    monkeypatch.setattr(genai, "complete", fake_complete)

    attempt = _submit(client, student_id, sk, item["competency"], headers,
                      answer="I would rewrite the compose file.")
    remediation = attempt["remediation"]
    assert remediation["source"] == "fallback"
    assert "AI remediation is unavailable" in remediation["explanation"]
    assert remediation["focus_points"]

    history = client.get(_practice_url(student_id, sk, item["competency"]), headers=headers).json()
    assert history["latest"]["remediation"]["source"] == "fallback"


def test_ai_remediation_error_uses_labelled_fallback(
        client, docker_skill, student_id, auth_headers, monkeypatch):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    _, item, _ = _setup_lesson(client, headers, sk, student_id)
    monkeypatch.setattr(genai, "genai_enabled", lambda: True)

    def fake_complete(system, user, max_tokens=None, timeout=None):
        if "Learning Practice evaluator" in system:
            return json.dumps({
                "score": 45, "status": "needs_review",
                "strengths": ["Start"], "missing_points": ["Syntax"],
                "feedback": "Gaps remain.", "next_action": "Revise.",
                "source": "ai",
            })
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(genai, "complete", fake_complete)

    attempt = _submit(client, student_id, sk, item["competency"], headers,
                      answer="I would rewrite the compose file.")
    assert attempt["remediation"]["source"] == "fallback"
    assert "AI remediation is unavailable" in attempt["remediation"]["explanation"]


def _remediation_context():
    ctx = json.loads(json.dumps(_manual_context()))
    learn = ctx["lesson"]["learn"]
    learn["key_ideas"] = [
        "Persist data with a named volume or a bind mount.",
    ]
    learn["key_terms"] = {
        "named volume": "Docker-managed storage for persistent data.",
        "bind mount": "A host directory mounted into a container.",
        "compose syntax": "YAML rules that make the compose file valid.",
    }
    ctx["lesson"]["example"] = {
        "title": "Deploying the service",
        "type": "command",
        "content": "Run the pipeline and verify the output.",
        "explanation": "A successful deploy signals the fix.",
    }
    ctx["lesson"]["practice"] = {
        "type": "practice",
        "questions": [{
            "id": "p1", "type": "free_text",
            "question": "Explain container storage choices.",
            "correct_answer": "Use a named volume for persistence and bind mounts for host access.",
            "competency": "container storage",
            "difficulty": "intermediate",
        }],
    }
    return ctx


def test_remaining_gaps_drive_next_remediation():
    context = _remediation_context()

    answer_one = "I am not sure yet what to do here."
    first = practice.evaluate_practice(context, answer_one)
    assert first["score"] < 70
    remediation_one = practice.generate_remediation(context, first, answer_one)
    assert remediation_one is not None
    assert remediation_one["source"] == "fallback"

    answer_two = "Persist container storage data with a named volume plus a bind mount for host files."
    improved = practice.evaluate_practice(context, answer_two)
    assert improved["score"] < 70
    assert improved["status"] == "needs_review"
    remediation_two = practice.generate_remediation(context, improved, answer_two)
    assert remediation_two is not None

    focus_one = " | ".join(remediation_one["focus_points"]).lower()
    assert "named volume" in focus_one
    assert "bind mount" in focus_one

    focus_two = " | ".join(remediation_two["focus_points"]).lower()
    assert "compose syntax" in focus_two
    assert "named volume" not in focus_two
    assert "bind mount" not in focus_two
    assert "container storage" not in focus_two


def test_fallback_remediation_is_explicitly_labelled():
    context = _remediation_context()
    answer = "I am not sure yet what to do here."
    low = practice.evaluate_practice(context, answer)
    remediation = practice.generate_remediation(context, low, answer)

    assert remediation["source"] == "fallback"
    assert "AI remediation is unavailable" in remediation["explanation"]
    assert all(k in remediation for k in (
        "focus_points", "explanation", "targeted_example", "follow_up_task"))


def test_tokenizer_normalizes_surrounding_punctuation():
    baseline = practice._tokens("volume mount container persistence")
    for variant in (
        "volume. mount, container? \"persistence\"",
        "volume, mount. container! persistence;",
        "(volume) [mount] {container} 'persistence'",
        "volume... mount: container? persistence!",
    ):
        assert practice._tokens(variant) == baseline, variant


def test_tokenizer_preserves_technical_syntax():
    tokens = practice._tokens(
        "docker-compose read-only --mount /dev/sda1 --name=web --read-only."
    )
    assert "docker-compose" in tokens
    assert "read-only" in tokens
    assert "mount" in tokens
    assert "name" in tokens


def test_sentence_final_concept_word_matches_bare_token():
    context = _remediation_context()
    with_period = "The compose file must have valid syntax and yaml."
    bare = "The compose file must have valid syntax and yaml"

    punctuated = practice.evaluate_practice(context, with_period)
    plain = practice.evaluate_practice(context, bare)
    assert punctuated["score"] == plain["score"]
    assert punctuated["strengths"] == plain["strengths"]
    assert punctuated["missing_points"] == plain["missing_points"]
    assert any("compose syntax" in text for text in punctuated["strengths"])


def test_punctuation_does_not_change_concept_coverage():
    context = _remediation_context()
    base = "Use a named volume for persistence and a bind mount for host access"
    styled = "Use a named volume for persistence, and a bind mount for host access!"

    first = practice.evaluate_practice(context, base)
    second = practice.evaluate_practice(context, styled)
    assert first["score"] == second["score"]
    assert first["strengths"] == second["strengths"]
    assert first["missing_points"] == second["missing_points"]


def test_trailing_period_on_concept_word_keeps_coverage():
    context = _remediation_context()
    something = "I would use a named volume and a bind mount."
    bare = "I would use a named volume and a bind mount"

    with_period = practice.evaluate_practice(context, something)
    plain = practice.evaluate_practice(context, bare)
    assert with_period["score"] == plain["score"]
    assert with_period["score"] >= 50
    strengths = " | ".join(with_period["strengths"]).lower()
    assert "named volume" in strengths
    assert "bind mount" in strengths
