"""Path↔diagnostic currency + legacy-topic recovery + prerequisite order.

Covers the roadmap-consistency contract:
- a path belongs to exactly one diagnostic (personalized_paths.diagnostic_id);
- a newer COMPLETED diagnostic makes the stored path stale and requires
  regenerating (or explicitly refreshing) it before it is taught again;
- legacy topic identifiers that the trusted knowledge base cannot resolve are
  surfaced explicitly (never silently skipped) with a recovery action;
- declared prerequisites (Python Functions before Python Error Handling) are
  respected even when path order is degenerate.

No test here fabricates scores, completes lessons, or touches verified_skills.
"""
from urllib.parse import quote

from app import genai, knowledge_base, models


def _make_items(*slugs, status="weak"):
    items = []
    for i, slug in enumerate(slugs, start=1):
        items.append({
            "id": f"{slug}-{i}",
            "competency": slug,
            "title": slug.replace("_", " "),
            "topic_status": status,
            "diagnostic_score": 0.0,
            "action": "learn",
            "order": i,
            "estimated_minutes": 30,
            "state": "not_started",
        })
    return items


def _completed_diagnostic(student_id, python, topic_slugs):
    """Create and complete a diagnostic row directly (in-memory DB)."""
    questions = [{"idn": i, "competency": slug, "type": "mcq",
                  "question": f"q{i}", "options": ["a", "b"], "correct_answer": "a"}
                 for i, slug in enumerate(topic_slugs)]
    diag = models.create_diagnostic(student_id, python["id"], questions)
    topics = [{"competency": slug, "label": slug.replace("_", " "),
               "score": 0.0, "status": "weak", "correct": 0, "total": 1}
              for slug in topic_slugs]
    result = {"overall_score": 0.0, "topics": topics,
              "weak_topics": list(topic_slugs), "strong_topics": []}
    return models.complete_diagnostic(diag["id"], [], 0.0, result)


def _auth_headers(client, email="aisha@student.edu"):
    payload = client.post("/api/auth/login",
                          json={"email": email, "password": "demo1234"}).json()
    return {"Authorization": f"Bearer {payload['token']}"}


def test_new_path_is_current_and_canonical_and_older_path_goes_stale(client, student_id, auth_headers, monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    headers = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")

    # Diagnostic A (all wrong) -> path is current and canonical.
    a = client.post(f"/api/students/{student_id}/learning/{python['id']}/diagnostic/generate", json={}, headers=headers).json()
    a_res = client.post(
        f"/api/students/{student_id}/learning/{python['id']}/diagnostic/submit",
        json={"diagnostic_id": a["diagnostic_id"], "answers": ["not sure"] * len(a["questions"])}, headers=headers).json()
    assert a_res["id"] == a["diagnostic_id"]
    path1 = client.post(f"/api/students/{student_id}/learning/{python['id']}/personalized-path/generate", json={}, headers=headers).json()
    # Canonical identifier resolution, first two topics already respected.
    assert [p["competency"] for p in path1["items"]][:2] == ["python_functions", "python_error_handling"]
    assert path1["stale"] is False
    assert path1["latest_diagnostic_id"] == a_res["id"]

    # Diagnostic B is a NEWER completed diagnostic -> stored path is stale.
    b = client.post(f"/api/students/{student_id}/learning/{python['id']}/diagnostic/generate", json={}, headers=headers).json()
    b_res = client.post(
        f"/api/students/{student_id}/learning/{python['id']}/diagnostic/submit",
        json={"diagnostic_id": b["diagnostic_id"], "answers": ["not sure"] * len(b["questions"])}, headers=headers).json()
    assert b_res["id"] > a_res["id"]

    before_skills = {s["name"] for s in models.get_student(student_id)["verified_skills"]}
    decision = client.get(f"/api/students/{student_id}/learning/{python['id']}/orchestrator/next", headers=headers).json()
    assert decision["action_type"] == "REQUEST_REASSESSMENT"
    assert any(f"#{a_res['id']}" in e["detail"] and f"#{b_res['id']}" in e["detail"]
               for e in decision["evidence"] if e["kind"] == "diagnostic")
    assert "Regenerate the learning path" in decision["next_step"]

    for _ in range(3):
        assert {s["name"] for s in models.get_student(student_id)["verified_skills"]} == before_skills

    stale_path = client.get(f"/api/students/{student_id}/learning/{python['id']}/personalized-path", headers=headers).json()
    assert stale_path["stale"] is True
    assert stale_path["latest_diagnostic_id"] == b_res["id"]

    # Explicit refresh: regenerating from the latest diagnostic yields a current path.
    refreshed = client.post(f"/api/students/{student_id}/learning/{python['id']}/personalized-path/generate", json={}, headers=headers).json()
    assert refreshed["stale"] is False
    assert refreshed["diagnostic_id"] == b_res["id"]


def test_legacy_function_design_identifier_is_surfaced_not_silently_skipped(client, student_id, auth_headers, monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    headers = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")

    # A completed diagnostic whose topic set mixes canonical + legacy identifiers,
    # with a matching (non-stale) persisted path that carries the legacy topic.
    diag = _completed_diagnostic(student_id, python,
                                 ["python_functions", "python_error_handling", "function_design"])
    items = _make_items("python_functions", "python_error_handling", "function_design")
    models.create_personalized_path(student_id, python["id"], diag["id"], "Intermediate",
                                    items, [], [])
    assert models.public_diagnostic(models.get_latest_completed_diagnostic(student_id, python["id"]))["id"] == diag["id"]

    path = client.get(f"/api/students/{student_id}/learning/{python['id']}/personalized-path", headers=headers).json()
    assert path["stale"] is False

    before = {s["name"] for s in models.get_student(student_id)["verified_skills"]}
    decision = client.get(f"/api/students/{student_id}/learning/{python['id']}/orchestrator/next", headers=headers).json()
    assert decision["action_type"] == "REQUEST_REASSESSMENT"
    curriculum = next(e["detail"] for e in decision["evidence"] if e["kind"] == "curriculum")
    assert "function_design" in curriculum
    assert "Regenerate the path" in decision["next_step"] or "reassess" in decision["next_step"]
    assert {s["name"] for s in models.get_student(student_id)["verified_skills"]} == before

    # The agent never invents content for the legacy identifier.
    assert knowledge_base.complete_lesson("Python", "function_design".replace("_", " ")) is None


def test_prerequisite_guard_reviews_python_functions_before_error_handling(client, student_id, auth_headers, monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    headers = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")

    # Current path (diagnostic matches) but degenerate order: Error Handling is
    # listed first even though it declares Python Functions as its prerequisite.
    diag = _completed_diagnostic(student_id, python,
                                 ["python_error_handling", "python_functions"])
    items = _make_items("python_error_handling", "python_functions")
    models.create_personalized_path(student_id, python["id"], diag["id"], "Intermediate",
                                    items, [], [])
    decision = client.get(f"/api/students/{student_id}/learning/{python['id']}/orchestrator/next", headers=headers).json()
    assert decision["action_type"] == "REVIEW_PREREQUISITE"
    assert decision["topic_id"] == "python_functions"
    assert "Python Functions" in decision["decision_reason"]
    assert decision["next_step"].startswith("Complete the prerequisite topic")


def test_stale_path_never_teaches_nor_claims_progress(client, student_id, auth_headers, monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    headers = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")
    skill_id = python["id"]
    base = f"/api/students/{student_id}/learning/{skill_id}"

    older = _completed_diagnostic(student_id, python, ["python_functions", "python_error_handling"])
    models.create_personalized_path(student_id, skill_id, older["id"], "Intermediate",
                                    _make_items("python_functions", "python_error_handling"), [], [])
    newer = _completed_diagnostic(student_id, python, ["python_functions", "python_error_handling"])

    url = f"{base}/lessons/{quote('python_functions', safe='')}"
    lesson = client.post(url + "/generate", json={}, headers=headers)
    assert lesson.status_code == 200, lesson.text

    decision = client.get(f"{base}/orchestrator/next", headers=headers).json()
    assert decision["action_type"] == "REQUEST_REASSESSMENT"
    assert any(e["kind"] == "path" and "stale" in e["detail"] for e in decision["evidence"])

    # No progress was written by the agent for the stale path.
    path = models.get_personalized_path(student_id, skill_id)
    assert (models.public_personalized_path(path)["progress"] or []) == []