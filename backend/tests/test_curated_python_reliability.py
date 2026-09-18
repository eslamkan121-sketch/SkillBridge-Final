"""End-to-end contracts for the curated Python topics."""
from urllib.parse import quote

import pytest

from app import genai, models


@pytest.fixture(autouse=True)
def offline_reviewer(monkeypatch):
    """Use the explicitly labelled local evaluator for deterministic journeys."""
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)


def _url(student_id, skill_id, competency):
    return f"/api/students/{student_id}/learning/{skill_id}/lessons/{quote(competency, safe='')}"


def _answers_for_all_gaps(questions):
    return [next(option for option in q["options"] if option != q["correct_answer"])
            for q in questions]


def _make_path(client, student_id, headers, python):
    generated = client.post(
        f"/api/students/{student_id}/learning/{python['id']}/diagnostic/generate",
        json={}, headers=headers).json()
    completed = client.post(
        f"/api/students/{student_id}/learning/{python['id']}/diagnostic/submit",
        json={"diagnostic_id": generated["diagnostic_id"], "answers": _answers_for_all_gaps(generated["questions"])},
        headers=headers)
    assert completed.status_code == 200, completed.text
    path = client.post(
        f"/api/students/{student_id}/learning/{python['id']}/personalized-path/generate",
        json={}, headers=headers).json()
    return generated, path


def test_curated_python_diagnostic_is_exactly_tagged_and_path_is_prerequisite_ordered(
        client, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")
    generated, path = _make_path(client, student_id, headers, python)

    assert len(generated["questions"]) == 6
    assert {q["competency"] for q in generated["questions"]} == {"python_functions", "python_error_handling"}
    functions_text = " ".join(f"{q['question']} {q['correct_answer']}" for q in generated["questions"] if q["competency"] == "python_functions").lower()
    errors_text = " ".join(f"{q['question']} {q['correct_answer']}" for q in generated["questions"] if q["competency"] == "python_error_handling").lower()
    assert "return" in functions_text and "parameter" in functions_text
    assert "valueerror" in errors_text and "try" in errors_text
    assert [item["competency"] for item in path["items"]] == ["python_functions", "python_error_handling"]


def test_both_curated_python_topics_complete_without_verifying_skill_and_cache_exact_answer(
        client, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")
    before = {(s["name"], s["level"]) for s in models.get_student(student_id).get("verified_skills") or []}
    _, path = _make_path(client, student_id, headers, python)
    answers = {
        "python_functions": "def celsius_to_fahrenheit(celsius):\n    return (celsius * 9 / 5) + 32\n\nreturn lets the caller reuse and test the converted value.",
        "python_error_handling": "def parse_score(text):\n    try:\n        return int(text)\n    except ValueError:\n        return None\n\nA bare except could hide an unrelated programming bug.",
    }
    for item in path["items"]:
        base = _url(student_id, python["id"], item["competency"])
        lesson = client.post(base + "/generate", json={}, headers=headers)
        assert lesson.status_code == 200, lesson.text
        content = lesson.json()["content"]
        assert content["canonical"]["source"] == "trusted_cs_knowledge_base"
        assert len(content["locales"]["ar"]["mini_check"]["questions"]) == 3
        first = client.post(base + "/practice", json={"answer": answers[item["competency"]]}, headers=headers)
        assert first.status_code == 200, first.text
        assert first.json()["attempt"]["practice_task"]["static_check"]["status"] == "looks_structurally_sound"
        cached = client.post(base + "/practice", json={"answer": answers[item["competency"]]}, headers=headers)
        assert cached.status_code == 200, cached.text
        assert cached.json()["reused"] is True
        assert cached.json()["attempt"]["id"] == first.json()["attempt"]["id"]
        changed = client.post(base + "/practice", json={"answer": answers[item["competency"]] + "\nI checked one more case."}, headers=headers)
        assert changed.status_code == 200, changed.text
        assert changed.json().get("reused") is not True
        questions = content["mini_check"]["questions"]
        passed = client.post(base + "/mini-check", json={"answers": [q["correct_answer"] for q in questions]}, headers=headers)
        assert passed.status_code == 200, passed.text
        assert passed.json()["lesson"]["state"] == "completed"

    persisted = client.get(f"/api/students/{student_id}/learning/{python['id']}/personalized-path", headers=headers).json()
    assert {item["id"] for item in path["items"]}.issubset(set(persisted["progress"]))
    assert {(s["name"], s["level"]) for s in models.get_student(student_id).get("verified_skills") or []} == before


def test_live_provider_failure_returns_retryable_error_and_persists_no_grade(
        client, student_id, auth_headers, monkeypatch):
    headers = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")
    _, path = _make_path(client, student_id, headers, python)
    base = _url(student_id, python["id"], path["items"][0]["competency"])
    client.post(base + "/generate", json={}, headers=headers)
    monkeypatch.setattr(genai, "genai_enabled", lambda: True)
    monkeypatch.setattr(genai, "complete", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("provider down")))
    failed = client.post(base + "/practice", json={"answer": "A changed answer that requires a live review."}, headers=headers)
    assert failed.status_code == 503
    assert "retry" in failed.json()["detail"].lower()
    assert client.get(base + "/practice", headers=headers).json()["count"] == 0


def test_unanswered_newer_diagnostic_does_not_hide_latest_completed_path(
        client, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")
    completed, original_path = _make_path(client, student_id, headers, python)
    incomplete = client.post(
        f"/api/students/{student_id}/learning/{python['id']}/diagnostic/generate", json={}, headers=headers).json()
    assert incomplete["diagnostic_id"] > completed["diagnostic_id"]
    rebuilt = client.post(
        f"/api/students/{student_id}/learning/{python['id']}/personalized-path/generate", json={}, headers=headers)
    assert rebuilt.status_code == 200, rebuilt.text
    payload = rebuilt.json()
    assert payload["diagnostic_id"] == completed["diagnostic_id"]
    assert payload["id"] == original_path["id"]
