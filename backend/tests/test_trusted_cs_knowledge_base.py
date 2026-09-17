"""Phase 1 contracts for the curated CS knowledge-base vertical slice."""
from urllib.parse import quote

from app import genai, knowledge_base, lessons, models, skill_blueprint as sb


def test_python_functions_is_a_trusted_canonical_blueprint_topic():
    assert sb.source_for("Python") == "trusted"
    assert sb.required_competencies("Python", "Beginner", "Advanced") == ["Python Functions", "Python Error Handling"]
    topic = knowledge_base.complete_lesson("Python", "Python Functions")
    assert topic and topic["status"] == "complete"
    assert topic["prerequisites"]
    assert "roadmap" in topic["roadmap_rationale"].lower()


def test_planned_topics_are_not_served_as_complete_content():
    assert knowledge_base.PLANNED_TOPICS[("sql", "joins")]["status"] == "planned"
    assert knowledge_base.PLANNED_TOPICS[("machine learning", "evaluation basics")]["content"] is None
    assert knowledge_base.complete_lesson("SQL", "Joins") is None


def test_python_functions_content_has_bilingual_explanation_and_validated_checks():
    content = lessons.generate_lesson("Python", "Python Functions", "learn")
    assert content["canonical"]["source"] == "trusted_cs_knowledge_base"
    assert "بالعربية" in content["learn"]["explanation"]
    assert len(content["mini_check"]["questions"]) == 3
    assert all(q["correct_answer"] and q["misconception_hint"] for q in content["mini_check"]["questions"])
    answers = [q["correct_answer"] for q in content["mini_check"]["questions"]]
    assert lessons.score_mini_check(content["mini_check"]["questions"], answers) == (3, 3, True)


def test_python_error_handling_is_reviewed_and_its_check_matches_its_objective():
    topic = knowledge_base.complete_lesson("Python", "Python Error Handling")
    assert topic and topic["status"] == "complete"
    assert topic["prerequisites"][0]["competency"] == "Python Functions"
    content = lessons.generate_lesson("Python", "Python Error Handling", "learn")
    assert content["canonical"]["source"] == "trusted_cs_knowledge_base"
    assert "try" in content["example"]["content"] and "except ValueError" in content["example"]["content"]
    assert "Walk through a realistic" not in content["example"]["content"]
    assert all(q["competency"] == "Python Error Handling" for q in content["mini_check"]["questions"])
    answers = [q["correct_answer"] for q in content["mini_check"]["questions"]]
    assert lessons.score_mini_check(content["mini_check"]["questions"], answers) == (3, 3, True)


def test_error_handling_slug_and_reviewed_arabic_display_fields_are_served():
    # A path stores its competency as a slug.  That must still select the
    # trusted lesson instead of re-exposing older generic generated prose.
    content = lessons.generate_lesson("Python", "python_error_handling", "learn")
    assert "def parse_age(text):" in content["example"]["content"]
    arabic = content["locales"]["ar"]
    assert "الاستثناء" in arabic["learn"]["explanation"]
    assert "parse_score(text)" in arabic["practice"]["task"]


def test_python_functions_example_and_practical_solution_pass_multiple_inputs():
    content = lessons.generate_lesson("Python", "Python Functions", "learn")
    namespace = {}
    exec(content["example"]["content"], namespace)
    assert namespace["delivery_total"](4, 1) == 5

    namespace = {}
    exec("def celsius_to_fahrenheit(celsius):\n    return (celsius * 9 / 5) + 32\n", namespace)
    for case in content["practice"]["automated_tests"]:
        assert namespace["celsius_to_fahrenheit"](*case["input"]) == case["expected"]


def test_canonical_lesson_is_returned_even_when_llm_is_enabled(monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: True)
    monkeypatch.setattr(genai, "complete", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM must not run")))
    content = lessons.generate_lesson("Python", "Python Functions", "learn")
    assert content["canonical"]["source"] == "trusted_cs_knowledge_base"


def test_mini_check_and_practice_do_not_verify_python_skill(client, student_id, auth_headers, monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    headers = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")
    diagnostic = client.post(f"/api/students/{student_id}/learning/{python['id']}/diagnostic/generate", json={}, headers=headers).json()
    submitted = client.post(
        f"/api/students/{student_id}/learning/{python['id']}/diagnostic/submit",
        json={"diagnostic_id": diagnostic["diagnostic_id"], "answers": ["not sure"] * len(diagnostic["questions"])},
        headers=headers,
    )
    assert submitted.status_code == 200, submitted.text
    path = client.post(f"/api/students/{student_id}/learning/{python['id']}/personalized-path/generate", json={}, headers=headers).json()
    item = next(i for i in path["items"] if i["competency"] == "python_functions")
    url = f"/api/students/{student_id}/learning/{python['id']}/lessons/{quote(item['competency'], safe='') }"
    lesson = client.post(url + "/generate", json={}, headers=headers)
    assert lesson.status_code == 200, lesson.text
    before = {s["name"] for s in models.get_student(student_id)["verified_skills"]}
    practice = client.post(
        url + "/practice",
        json={"answer": "def celsius_to_fahrenheit(celsius):\n    return (celsius * 9 / 5) + 32\n\nI use return so the caller can test and reuse the value."},
        headers=headers,
    )
    assert practice.status_code == 200, practice.text
    assert {s["name"] for s in models.get_student(student_id)["verified_skills"]} == before
    mini = lesson.json()["content"]["mini_check"]["questions"]
    result = client.post(url + "/mini-check", json={"answers": [q["correct_answer"] for q in mini]}, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["lesson"]["state"] == "completed"
    after = {s["name"] for s in models.get_student(student_id)["verified_skills"]}
    assert after == before
