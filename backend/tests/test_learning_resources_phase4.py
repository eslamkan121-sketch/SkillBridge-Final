"""Learning Phase 4 resources for personalized topic lessons."""
import json
from urllib.parse import quote

import pytest

from app import genai, lessons, models, practice, resources
from tests.test_learning_practice import _rich_practice_answer, _setup_lesson


@pytest.fixture(autouse=True)
def _force_deterministic_fallback(monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)


def _enc(value):
    return quote(value, safe="")


def _urls(items):
    return [r["url"] for r in items]


def test_personalized_topic_receives_relevant_resources():
    res = resources.recommend_lesson_resources(
        "Pandas", "Data", "pandas_filtering", "Intermediate", "Data Analyst",
        live_check=False)

    assert 2 <= len(res) <= 4
    assert "https://pandas.pydata.org/docs/user_guide/indexing.html" in _urls(res)
    assert all("python.org/3/tutorial" not in r["url"] for r in res)
    assert all(r["reason"] and r["type_label"] for r in res)


def test_resources_use_real_curated_safe_urls():
    res = resources.recommend_lesson_resources(
        "Docker", "DevOps", "Volumes", "Intermediate", "Junior AI Engineer",
        live_check=False)

    assert _urls(res)[0] == "https://docs.docker.com/engine/storage/volumes/"
    assert all(resources.is_safe_public_url(r["url"]) for r in res)
    assert all(r["source_kind"] in ("curated", "curated_fallback") for r in res)


def test_fundamental_topics_prefer_official_curated_sources():
    pandas = resources.recommend_lesson_resources(
        "Pandas", "Data", "pandas_fundamentals", "Beginner",
        "Machine Learning Engineer", live_check=False)
    docker = resources.recommend_lesson_resources(
        "Docker", "DevOps", "containers", "Beginner",
        "Machine Learning Engineer", live_check=False)

    assert len(pandas) >= 3
    assert len(docker) >= 3
    assert all(r["source_kind"] == "curated" for r in pandas[:3])
    assert all(r["source_kind"] == "curated" for r in docker[:3])
    assert all("pandas.pydata.org" in r["url"] for r in pandas[:3])
    assert all("docs.docker.com" in r["url"] for r in docker[:3])


def test_ai_cannot_inject_arbitrary_lesson_resource_url(monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: True)

    def fake_complete(*args, **kwargs):
        return json.dumps({
            "learn": {"title": "Filtering", "explanation": "Use masks.", "key_ideas": [],
                      "key_terms": {}},
            "example": {"title": "Example", "type": "code", "content": "df[df.x > 1]",
                        "explanation": "The mask filters rows."},
            "practice": {"type": "practical", "title": "Practice", "task": "Filter rows.",
                         "response_type": "code", "competency": "pandas_filtering"},
            "mini_check": {"questions": []},
            "resources": [
                {"title": "Invented", "url": "https://ai-made-this-up.example/not-real",
                 "type": "article"},
            ],
        })

    monkeypatch.setattr(genai, "complete", fake_complete)
    content = lessons.generate_lesson(
        "Pandas", "pandas_filtering", "learn", required_level="Intermediate",
        target_role="Data Analyst", skill_category="Data")

    assert content["resources"]
    assert "ai-made-this-up.example" not in " ".join(_urls(content["resources"]))
    assert "pandas.pydata.org" in " ".join(_urls(content["resources"]))


def test_malformed_url_rejected_before_checking():
    bad = [
        "not a url",
        "ftp://example.com/resource",
        "https://exa mple.com/path",
        "http://[::1",
    ]
    assert all(not resources.is_safe_public_url(url) for url in bad)

    annotated = resources.annotate_resources([
        {"title": "Bad", "url": "not a url", "type": "doc"},
    ])
    assert annotated[0]["available"] is False


def test_unsafe_private_url_rejected_before_checking():
    bad = [
        "http://localhost:8000/secret",
        "http://127.0.0.1/admin",
        "http://10.0.0.4/resource",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://service.internal/resource",
    ]
    assert all(not resources.is_safe_public_url(url) for url in bad)
    assert resources._resource_availability("http://127.0.0.1/admin") is False


def test_external_link_check_failure_does_not_break_lesson(monkeypatch):
    def explode(_items):
        raise RuntimeError("network checker down")

    monkeypatch.setattr(resources, "annotate_resources", explode)
    res = resources.recommend_lesson_resources(
        "Docker", "DevOps", "Networking", "Intermediate", "Junior AI Engineer")

    assert res
    assert all(r["status"] == "Status unknown" for r in res)
    assert "docs.docker.com" in " ".join(_urls(res))


def test_generic_fallback_resources_are_honestly_represented():
    res = resources.recommend_lesson_resources(
        "Quantum Knitting", "Other", "quantum_knitting_fundamentals",
        "Beginner", "Textile Engineer", live_check=False)

    assert res
    assert all(r["source_kind"] == "curated_fallback" for r in res)
    assert all(r["status"] == "Unavailable" for r in res)
    assert all(r["unavailable"] is True for r in res)
    assert all(not r["url"] for r in res)
    assert any("Quantum Knitting" in r["title"] for r in res)


def test_resource_relevance_differs_by_topic():
    pandas = resources.recommend_lesson_resources(
        "Pandas", "Data", "pandas_filtering", "Intermediate", "Data Analyst",
        live_check=False)
    docker = resources.recommend_lesson_resources(
        "Docker", "DevOps", "Networking", "Intermediate", "Junior AI Engineer",
        live_check=False)

    assert set(_urls(pandas)).isdisjoint(set(_urls(docker)))
    assert any("pandas.pydata.org" in url for url in _urls(pandas))
    assert any("docs.docker.com/engine/network" in url for url in _urls(docker))


def test_beginner_and_advanced_resource_selection_can_differ():
    beginner = resources.recommend_lesson_resources(
        "Docker", "DevOps", "Containers", "Beginner", "Junior AI Engineer",
        live_check=False)
    advanced = resources.recommend_lesson_resources(
        "Docker", "DevOps", "Multi-stage builds", "Advanced", "Junior AI Engineer",
        live_check=False)

    assert _urls(beginner)[0] != _urls(advanced)[0]
    assert "what-is-a-container" in _urls(beginner)[0]
    assert "multi-stage" in _urls(advanced)[0]


def test_role_signal_can_lift_ai_engineer_statistics_resources():
    res = resources.recommend_lesson_resources(
        "Statistics", "Data", "statistics_fundamentals", "Intermediate",
        "Junior AI Engineer", live_check=False)

    urls = _urls(res)
    assert "https://scikit-learn.org/stable/modules/model_evaluation.html" in urls
    assert any("machine-learning/crash-course" in url for url in urls)


def test_lesson_endpoint_renders_resources_without_changing_practice_or_mini_check(
        client, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = models.get_skill_by_name("Docker")["id"]
    _, item, lesson = _setup_lesson(client, headers, sk, student_id)

    assert lesson["content"]["resources"]
    assert lesson["content"]["practice"]["type"] == "practical"
    assert lesson["content"]["mini_check"]["questions"]

    url = f"/api/students/{student_id}/learning/{sk}/lessons/{_enc(item['competency'])}/practice"
    practice_response = client.post(
        url, json={"answer": _rich_practice_answer()}, headers=headers)
    assert practice_response.status_code == 200
    assert practice_response.json()["attempt"]["source"] in ("ai", "fallback")

    questions = lesson["content"]["mini_check"]["questions"]
    mini = client.post(
        f"/api/students/{student_id}/learning/{sk}/lessons/{_enc(item['competency'])}/mini-check",
        json={"answers": [q["correct_answer"] for q in questions]}, headers=headers)
    assert mini.status_code == 200
    assert mini.json()["lesson"]["mini_check_result"]["passed"] is True


def test_practice_remediation_stays_green_with_lesson_resources():
    context = {
        "skill": {"id": 1, "name": "Docker"},
        "target_role": {"id": 1, "title": "Junior AI Engineer"},
        "required_level": "Intermediate",
        "topic": {"competency": "Volumes", "title": "Docker > Volumes"},
        "diagnostic": {"topic_status": "weak", "diagnostic_score": 20},
        "lesson": {
            "learn": {"title": "Volumes", "explanation": "Persist data.",
                      "key_ideas": ["Use named volumes for persistence."],
                      "key_terms": {"volume": "Docker-managed storage."}},
            "example": {"title": "Volume example", "type": "command",
                        "content": "docker volume create app-data",
                        "explanation": "The volume outlives containers."},
            "practice": {"source": "lesson", "questions": [{
                "id": "p1", "type": "free_text", "question": "Explain volumes.",
                "correct_answer": "", "competency": "Volumes"}]},
            "resources": resources.recommend_lesson_resources(
                "Docker", "DevOps", "Volumes", "Intermediate",
                "Junior AI Engineer", live_check=False),
        },
        "previous_attempts": [],
    }
    result = practice.evaluate_practice(context, "I would use Docker.")
    remediation = practice.generate_remediation(context, result, "I would use Docker.")

    assert result["status"] == "needs_review"
    assert remediation
    assert remediation["follow_up_task"]


def test_final_assessment_remains_accessible_with_lesson_resources(
        client, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = models.get_skill_by_name("Docker")["id"]
    _setup_lesson(client, headers, sk, student_id)

    response = client.post(
        f"/api/students/{student_id}/assessments/generate",
        json={"skill_id": sk, "num_questions": 3}, headers=headers)

    assert response.status_code == 200
    assert response.json()["questions"]
