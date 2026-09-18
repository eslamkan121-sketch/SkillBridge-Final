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

from app import genai, knowledge_base, models, path_builder


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


def test_refreshed_path_keeps_scores_attached_to_their_competency(client, student_id, auth_headers):
    """A stale path can have older values, but a refreshed path may never swap them."""
    headers = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")
    topic_ids = ["python_functions", "python_error_handling"]

    def complete_with_scores(functions, errors):
        diag = models.create_diagnostic(student_id, python["id"], [])
        topics = [
            {"competency": "python_functions", "label": "Python Functions", "score": functions,
             "status": "weak", "correct": 0, "total": 3},
            {"competency": "python_error_handling", "label": "Python Error Handling", "score": errors,
             "status": "weak", "correct": 0, "total": 3},
        ]
        return models.complete_diagnostic(diag["id"], [], (functions + errors) / 2,
                                          {"overall_score": (functions + errors) / 2, "topics": topics,
                                           "weak_topics": topic_ids, "strong_topics": []})

    older = complete_with_scores(0.0, 33.3)
    old_path = path_builder.build_personalized_path(python, models.public_diagnostic(older), "Intermediate")
    models.create_personalized_path(student_id, python["id"], older["id"], "Intermediate",
                                    old_path["path"], old_path["skipped_mastered"], old_path["stages"])
    newer = complete_with_scores(33.3, 0.0)

    stale = client.get(f"/api/students/{student_id}/learning/{python['id']}/personalized-path", headers=headers).json()
    assert stale["stale"] is True
    assert stale["diagnostic_id"] == older["id"]
    assert stale["latest_diagnostic_id"] == newer["id"]

    refreshed = client.post(f"/api/students/{student_id}/learning/{python['id']}/personalized-path/generate",
                            json={}, headers=headers).json()
    assert refreshed["diagnostic_id"] == newer["id"] and refreshed["stale"] is False
    assert {item["competency"]: item["diagnostic_score"] for item in refreshed["items"]} == {
        "python_functions": 33.3, "python_error_handling": 0.0,
    }


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


def test_path_availability_states_are_unambiguous_for_learning_navigation(
        client, student_id, auth_headers):
    """The frontend can distinguish every Continue Learning destination.

    A current path is safe to open; a newer *completed* diagnostic makes that
    path stale; a newer unanswered diagnostic does neither; and an absent path
    explicitly asks for a diagnostic.  These data states are skill-generic and
    deliberately exercise the public API rather than a Python-only UI branch.
    """
    headers = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")
    endpoint = f"/api/students/{student_id}/learning/{python['id']}/personalized-path"

    # No existing path: the UI must offer diagnostic/path generation, not a lesson.
    absent = client.get(endpoint, headers=headers).json()
    assert absent == {"diagnostic_required": True, "path": None}

    completed = _completed_diagnostic(
        student_id, python, ["python_functions", "python_error_handling"])
    models.create_personalized_path(
        student_id, python["id"], completed["id"], "Intermediate",
        _make_items("python_functions", "python_error_handling"), [], [])

    # Current active path: first incomplete topic is available to open.
    current = client.get(endpoint, headers=headers).json()
    assert current["stale"] is False
    assert current["diagnostic_id"] == completed["id"]
    assert current["progress"] == []
    assert current["items"][0]["competency"] == "python_functions"

    # A newly opened but incomplete diagnostic must not hide a current path.
    incomplete = models.create_diagnostic(student_id, python["id"], [])
    assert incomplete["id"] > completed["id"]
    still_current = client.get(endpoint, headers=headers).json()
    assert still_current["stale"] is False
    assert still_current["diagnostic_id"] == completed["id"]

    # Only newer completed evidence makes the existing path stale and refreshable.
    newer_completed = _completed_diagnostic(
        student_id, python, ["python_functions", "python_error_handling"])
    stale = client.get(endpoint, headers=headers).json()
    assert newer_completed["id"] > incomplete["id"]
    assert stale["stale"] is True
    assert stale["diagnostic_id"] == completed["id"]
    assert stale["latest_diagnostic_id"] == newer_completed["id"]


def test_lesson_creation_is_idempotent_for_overlapping_generate_requests(student_id):
    """A duplicate generate request returns the one lesson instead of a 500."""
    python = models.get_skill_by_name("Python")
    diagnostic = _completed_diagnostic(student_id, python, ["python_functions"])
    path = models.create_personalized_path(
        student_id, python["id"], diagnostic["id"], "Intermediate",
        _make_items("python_functions"), [], [])
    first = models.create_lesson(
        student_id, python["id"], path["id"], "python_functions",
        "Python > python_functions", "learn", {"learn": {}})
    duplicate = models.create_lesson(
        student_id, python["id"], path["id"], "python_functions",
        "Python > python_functions", "learn", {"learn": {}})
    assert duplicate["id"] == first["id"]
    assert models.get_lesson(student_id, path["id"], "python_functions")["id"] == first["id"]
