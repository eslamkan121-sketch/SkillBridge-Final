"""Contracts for the single complete SQL Queries & Filtering learning topic."""
from urllib.parse import quote

import pytest

from app import genai, knowledge_base, lessons, models, practice


SQL_ANSWER = """SELECT name, email
FROM customers
WHERE city = 'Cairo'
  AND status = 'active';

The city condition keeps Cairo customers, and the status condition keeps active customers."""


@pytest.fixture(autouse=True)
def offline_reviewer(monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)


def _url(student_id, skill_id):
    return f"/api/students/{student_id}/learning/{skill_id}/lessons/{quote('sql_queries_filtering', safe='')}"


def _make_sql_path(client, student_id, headers, sql):
    generated = client.post(
        f"/api/students/{student_id}/learning/{sql['id']}/diagnostic/generate",
        json={}, headers=headers)
    assert generated.status_code == 200, generated.text
    diagnostic = generated.json()
    submitted = client.post(
        f"/api/students/{student_id}/learning/{sql['id']}/diagnostic/submit",
        json={"diagnostic_id": diagnostic["diagnostic_id"], "answers": ["not this" for _ in diagnostic["questions"]]},
        headers=headers)
    assert submitted.status_code == 200, submitted.text
    path = client.post(
        f"/api/students/{student_id}/learning/{sql['id']}/personalized-path/generate",
        json={}, headers=headers)
    assert path.status_code == 200, path.text
    return diagnostic, path.json()


def test_sql_queries_filtering_is_the_only_complete_sql_lesson_with_bilingual_content():
    topic = knowledge_base.complete_lesson("SQL", "sql_queries_filtering")
    assert topic and topic["status"] == "complete"
    assert knowledge_base.complete_lesson("SQL", "Joins") is None
    assert "SELECT name, email" in topic["example"]["content"]
    assert "WHERE city = 'Cairo'" in topic["example"]["content"]
    assert len(topic["learn"]["grounding_sources"]) == 2
    assert "SkillBridge does not provide a SQL database" in topic["learn"]["version_note"]

    content = lessons.generate_lesson("SQL", "Queries & filtering", "learn")
    assert content["canonical"]["source"] == "trusted_cs_knowledge_base"
    assert "استعلامات SQL" in content["locales"]["ar"]["learn"]["title"]
    assert content["practice"]["language"] == "sql"
    assert "does not connect to a database" in content["practice"]["evaluation_note"]
    answers = [question["correct_answer"] for question in content["mini_check"]["questions"]]
    assert lessons.score_mini_check(content["mini_check"]["questions"], answers) == (3, 3, True)


def test_sql_static_review_never_executes_and_requires_the_requested_read_only_shape():
    lesson = {"content": lessons.generate_lesson("SQL", "Queries & filtering", "learn")}
    good = practice.sql_queries_filtering_static_check(lesson, SQL_ANSWER)
    assert good["kind"] == "sql_text"
    assert good["status"] == "looks_structurally_sound"
    assert "did not connect to a database or execute" in good["note"]

    unsafe = practice.sql_queries_filtering_static_check(
        lesson, "DELETE FROM customers WHERE city = 'Cairo';")
    assert unsafe["status"] == "needs_fix"
    assert any("read-only SELECT" in check for check in unsafe["checks"])


def test_sql_diagnostic_practice_mini_check_persist_without_verifying_skill(client, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sql = models.get_skill_by_name("SQL")
    before = {(row["name"], row["level"]) for row in models.get_student(student_id).get("verified_skills") or []}
    diagnostic, path = _make_sql_path(client, student_id, headers, sql)

    assert len(diagnostic["questions"]) == 3
    assert {question["competency"] for question in diagnostic["questions"]} == {"sql_queries_filtering"}
    assert all(
        "select" in f"{question['question']} {question['correct_answer']}".lower()
        or "where" in f"{question['question']} {question['correct_answer']}".lower()
        for question in diagnostic["questions"]
    )
    assert [item["competency"] for item in path["items"]] == ["sql_queries_filtering"]

    base = _url(student_id, sql["id"])
    lesson_response = client.post(base + "/generate", json={}, headers=headers)
    assert lesson_response.status_code == 200, lesson_response.text
    lesson = lesson_response.json()
    first = client.post(base + "/practice", json={"answer": SQL_ANSWER}, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["attempt"]["practice_task"]["static_check"]["status"] == "looks_structurally_sound"
    assert first.json()["attempt"]["practice_task"]["static_check"]["kind"] == "sql_text"
    cached = client.post(base + "/practice", json={"answer": SQL_ANSWER}, headers=headers)
    assert cached.status_code == 200, cached.text
    assert cached.json()["reused"] is True
    changed = client.post(base + "/practice", json={"answer": SQL_ANSWER + "\n-- reviewed"}, headers=headers)
    assert changed.status_code == 200, changed.text
    assert changed.json().get("reused") is not True

    questions = lesson["content"]["mini_check"]["questions"]
    completed = client.post(base + "/mini-check", json={"answers": [q["correct_answer"] for q in questions]}, headers=headers)
    assert completed.status_code == 200, completed.text
    assert completed.json()["lesson"]["state"] == "completed"
    persisted = client.get(
        f"/api/students/{student_id}/learning/{sql['id']}/personalized-path", headers=headers).json()
    assert path["items"][0]["id"] in persisted["progress"]
    assert {(row["name"], row["level"]) for row in models.get_student(student_id).get("verified_skills") or []} == before
