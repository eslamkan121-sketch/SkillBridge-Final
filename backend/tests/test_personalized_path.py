"""Phase 3 — Personalized learning path.

Covers path construction from a completed diagnostic (weak/developing included,
mastered skipped, deterministic ordering), reuse for the same diagnostic, new path
for a newer diagnostic, unanswered/no-diagnostic states, access control, and
non-regression of existing learning generation.
All GenAI calls are forced to the deterministic fallback (no API quota used).
"""
import pytest

from app import diagnostics as dx, genai, models, path_builder


@pytest.fixture(autouse=True)
def _force_deterministic_fallback(monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)


@pytest.fixture()
def docker_skill(db):
    return models.get_skill_by_name("Docker")


# ------------------------------------------------------------------ pure path builder

def _diag(topics):
    return {
        "completed_at": "2026-01-01 00:00:00",
        "topic_results": [
            {"competency": dx.competency_slug(comp), "label": comp, "score": score, "status": status}
            for comp, score, status in topics
        ],
    }


def _docker():
    return {"id": 5, "name": "Docker", "category": "DevOps"}


def test_path_builder_deterministic_ordering_match_spec():
    """The spec's worked example -> exactly Volumes, Networking, Dockerfile Review."""
    diag = _diag([
        ("Containers", 90, "mastered"),
        ("Images", 80, "mastered"),
        ("Dockerfile", 60, "developing"),
        ("Volumes", 20, "weak"),
        ("Networking", 30, "weak"),
    ])
    r = path_builder.build_personalized_path(_docker(), diag, "Intermediate")
    assert [p["title"] for p in r["path"]] == ["Volumes", "Networking", "Dockerfile Review"]
    assert [p["action"] for p in r["path"]] == ["learn", "learn", "review"]
    assert [p["order"] for p in r["path"]] == [1, 2, 3]
    assert set(r["skipped_mastered"]) == {"containers", "images"}


def test_path_builder_includes_weak_and_developing_skips_mastered():
    diag = _diag([
        ("Containers", 95, "mastered"),
        ("Volumes", 20, "weak"),
        ("Networking", 50, "developing"),
    ])
    r = path_builder.build_personalized_path(_docker(), diag)
    comps = [p["competency"] for p in r["path"]]
    assert comps == ["volumes", "networking"]  # mastered containers excluded
    assert "containers" in r["skipped_mastered"]
    # weak topics carry diagnostic_score and action labels
    volumes = next(p for p in r["path"] if p["competency"] == "volumes")
    assert volumes["action"] == "learn" and volumes["diagnostic_score"] == 20
    net = next(p for p in r["path"] if p["competency"] == "networking")
    assert net["action"] == "review" and net["diagnostic_score"] == 50


def test_path_builder_respects_prerequisites_within_status():
    """Within the same status, blueprint order wins over lower score."""
    diag = _diag([
        ("Dockerfile", 10, "weak"),   # earlier in blueprint order
        ("Volumes", 80, "weak"),      # higher score but later in order
    ])
    r = path_builder.build_personalized_path(_docker(), diag)
    # Dockerfile must come first (it is the prerequisite) despite the lower score
    assert [p["competency"] for p in r["path"]] == ["dockerfile", "volumes"]


def test_path_builder_adds_locked_milestones_after_topics():
    diag = _diag([("Volumes", 20, "weak")])
    r = path_builder.build_personalized_path(_docker(), diag)
    assert [s["stage"] for s in r["stages"]] == ["Practical Challenge", "Final Assessment"]
    assert all(s["state"] == "locked" for s in r["stages"])
    assert r["stages"][0]["order"] == 2


def test_path_builder_rejects_unanswered():
    diag = {"completed_at": None, "topic_results": [{"competency": "v", "label": "V", "score": 20, "status": "weak"}]}
    with pytest.raises(ValueError):
        path_builder.build_personalized_path(_docker(), diag)


# ------------------------------------------------------------------ persistence (fast, db fixture)

def test_path_persistence_across_database_read(db):
    student_id = 1  # aisha, guaranteed in seed
    skill = models.get_skill_by_name("Docker")
    diag = models.create_diagnostic(student_id, skill["id"], [])  # real id for FK
    items = [{"id": "v-1", "competency": "volumes", "title": "Volumes", "action": "learn", "order": 1, "state": "not_started"}]
    rows = models.create_personalized_path(student_id, skill["id"], diag["id"], "Intermediate", items, ["containers"], [])
    got = models.get_personalized_path(student_id, skill["id"])
    pub = models.public_personalized_path(got)
    assert pub["id"] == rows["id"]
    assert pub["diagnostic_id"] == diag["id"]
    assert pub["items"][0]["competency"] == "volumes"
    assert pub["skipped_mastered"] == ["containers"]


def test_path_state_applied_from_progress(db):
    student_id = 1
    skill = models.get_skill_by_name("Docker")
    diag = models.create_diagnostic(student_id, skill["id"], [])
    items = [{"id": "v-1", "competency": "volumes", "order": 1, "state": "not_started"}]
    models.create_personalized_path(student_id, skill["id"], diag["id"], "Intermediate", items, [], [])
    models.update_path_progress(student_id, skill["id"], ["v-1"])
    pub = models.public_personalized_path(models.get_personalized_path(student_id, skill["id"]))
    assert pub["items"][0]["state"] == "done"


# ------------------------------------------------------------------ endpoint flow (client, slow)

def test_full_flow_reuse_and_newer_diagnostic(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]

    # no diagnostic yet
    g = client.get(f"/api/students/{student_id}/learning/{sk}/personalized-path", headers=headers).json()
    assert g.get("diagnostic_required") is True and g.get("path") is None

    # complete a diagnostic (ensure at least one weak/developing topic)
    for attempt in range(2):
        gen = client.post(
            f"/api/students/{student_id}/learning/{sk}/diagnostic/generate", json={}, headers=headers).json()
        qs = gen["questions"]
        answers = [q["correct_answer"] for q in qs if q]
        # make first two MCQs wrong to manufacture weakness
        bad = 0
        for i, q in enumerate(qs):
            if q["type"] == "mcq" and bad < 2:
                wrong = [o for o in q["options"] if o != q["correct_answer"]]
                if wrong:
                    answers[i] = wrong[0]
                    bad += 1
        sub = client.post(
            f"/api/students/{student_id}/learning/{sk}/diagnostic/submit",
            json={"diagnostic_id": gen["diagnostic_id"], "answers": answers}, headers=headers)
        assert sub.status_code == 200
    latest = client.get(
        f"/api/students/{student_id}/learning/{sk}/diagnostic/latest", headers=headers).json()
    assert latest["completed_at"]

    # build path from the completed diagnostic
    p = client.post(
        f"/api/students/{student_id}/learning/{sk}/personalized-path/generate", json={}, headers=headers).json()
    assert p["diagnostic_id"] == latest["id"]
    assert p["required_level"] in ("Beginner", "Intermediate", "Advanced")
    assert p["items"]  # weak/developing topics present, mastered excluded
    statuses = {t["topic_status"] for t in p["items"]}
    assert statuses <= {"weak", "developing"}
    assert p["stages"]  # locked milestones present
    assert isinstance(p["skipped_mastered"], list)

    # same diagnostic -> reused, not regenerated
    p2 = client.post(
        f"/api/students/{student_id}/learning/{sk}/personalized-path/generate", json={}, headers=headers).json()
    assert p2["id"] == p["id"]

    # a NEWER completed diagnostic produces a NEW path
    gen = client.post(
        f"/api/students/{student_id}/learning/{sk}/diagnostic/generate", json={}, headers=headers).json()
    qs = gen["questions"]
    answers2 = [q["correct_answer"] for q in qs]
    client.post(
        f"/api/students/{student_id}/learning/{sk}/diagnostic/submit",
        json={"diagnostic_id": gen["diagnostic_id"], "answers": answers2}, headers=headers)
    newer = client.get(
        f"/api/students/{student_id}/learning/{sk}/diagnostic/latest", headers=headers).json()
    assert newer["id"] != latest["id"]
    p3 = client.post(
        f"/api/students/{student_id}/learning/{sk}/personalized-path/generate", json={}, headers=headers).json()
    assert p3["id"] != p["id"]
    assert p3["diagnostic_id"] == newer["id"]


def test_no_completed_diagnostic_returns_required_state(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    r = client.post(
        f"/api/students/{student_id}/learning/{sk}/personalized-path/generate", json={}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body.get("diagnostic_required") is True


def test_unanswered_diagnostic_rejected(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    client.post(f"/api/students/{student_id}/learning/{sk}/diagnostic/generate", json={}, headers=headers)
    r = client.post(
        f"/api/students/{student_id}/learning/{sk}/personalized-path/generate", json={}, headers=headers)
    assert r.status_code == 200
    assert r.json().get("diagnostic_required") is True


def test_invalid_skill_404(client, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    r = client.post(
        f"/api/students/{student_id}/learning/999999/personalized-path/generate",
        json={}, headers=headers)
    assert r.status_code == 404


def test_unauthenticated_401(client, student_id, docker_skill):
    r = client.get(f"/api/students/{student_id}/learning/{docker_skill['id']}/personalized-path")
    assert r.status_code == 401


def test_company_access_blocked(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("hr@northstar.com")
    r = client.post(
        f"/api/students/{student_id}/learning/{docker_skill['id']}/personalized-path/generate",
        json={}, headers=headers)
    assert r.status_code == 403


def test_non_owner_student_blocked(client, docker_skill, student_id):
    omar = client.post("/api/auth/login", json={"email": "omar@student.edu", "password": "demo1234"}).json()
    headers = {"Authorization": f"Bearer {omar['token']}"}
    r = client.get(f"/api/students/{student_id}/learning/{docker_skill['id']}/personalized-path", headers=headers)
    assert r.status_code == 403


def test_existing_learning_generation_still_works(client, docker_skill, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    r = client.post(
        f"/api/students/{student_id}/learning/generate",
        json={"skill_id": docker_skill["id"]}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["skill_id"] == docker_skill["id"]
    assert body["explanation"] and body["practice_exercise"] and body["mini_project"]
