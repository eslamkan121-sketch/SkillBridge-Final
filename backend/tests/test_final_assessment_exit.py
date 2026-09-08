"""Step 4.5 FINAL CORRECTION — assessment exit finalization.

The dedicated verified-assessment experience finalizes immediately when the
student leaves (navigate, close, refresh, route-leave): every unanswered
question is scored as zero, the active-assessment lock clears so the Tutor
unlocks right away, the finalize call is idempotent per attempt token, and a
crashed/stale client session can never leave the lock open forever.
"""
import sqlite3

import pytest

from app import models

DOCKER = "Docker"


def _gen_questions(client, student_id, headers, skill_id=None, num=10):
    if skill_id is None:
        skill_id = models.get_skill_by_name(DOCKER)["id"]
    r = client.post(f"/api/students/{student_id}/assessments/generate",
                    json={"skill_id": skill_id, "num_questions": num}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["questions"]


def _finalize(client, student_id, questions, answers, ext_token=None, h=None, **extra):
    body = {"skill_id": models.get_skill_by_name(DOCKER)["id"],
            "questions": questions, "answers": answers,
            "total_seconds": extra.get("total_seconds", 300),
            "tab_switches": extra.get("tab_switches", 0),
            "free_text_answers": extra.get("free_text_answers") or []}
    if ext_token:
        body["external_token"] = ext_token
    return client.post(f"/api/students/{student_id}/assessments/finalize",
                       json=body, headers=h)


# ------------------------------------------------------------------ auth / access

def test_finalize_requires_auth(client, student_id):
    r = _finalize(client, student_id, [], [])
    assert r.status_code == 401


def test_finalize_forbids_non_owner(client, student_id, auth_headers):
    h = auth_headers("hr@northstar.com")
    r = _finalize(client, student_id, [], [], h=h)
    assert r.status_code in (401, 403)


def test_finalize_forbids_other_student(client, student_id, auth_headers):
    h = auth_headers("omar@student.edu")
    r = _finalize(client, student_id, [], [], h=h)
    assert r.status_code in (401, 403)


# ------------------------------------------------------------------ grading

def test_finalize_grades_only_answered_questions(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    questions = _gen_questions(client, student_id, h)
    r = _finalize(client, student_id, questions, [q["answer"] for q in questions[:3]], h=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["score"] == 30.0  # 3 of 10 answered correctly
    assert data["unanswered"] == 7
    assert data["ended"] == "exit"


def test_finalize_empty_attempt_scores_zero(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    questions = _gen_questions(client, student_id, h)
    r = _finalize(client, student_id, questions, [], h=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["score"] == 0.0
    assert data["unanswered"] == len(questions)
    assert data["passed"] is False


def test_finalize_marks_exited_flag(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    questions = _gen_questions(client, student_id, h)
    data = _finalize(client, student_id, questions, [], h=h).json()
    codes = [f["code"] for f in data["flags"]]
    assert "assessment_exited" in codes


def test_finalize_full_correct_pass(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    questions = _gen_questions(client, student_id, h)
    data = _finalize(client, student_id, questions, [q["answer"] for q in questions], h=h).json()
    assert data["score"] == 100.0
    assert data["unanswered"] == 0
    assert data["passed"] is True


def test_finalize_pass_updates_verified_skill(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    before = {v["name"] for v in models.get_student(student_id)["verified_skills"]}
    questions = _gen_questions(client, student_id, h)
    data = _finalize(client, student_id, questions, [q["answer"] for q in questions], h=h).json()
    assert data["passed"] is True
    after = {v["name"] for v in models.get_student(student_id)["verified_skills"]}
    assert DOCKER in after - before


# ------------------------------------------------------------------ idempotency / lock

def test_finalize_is_idempotent_per_token(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    questions = _gen_questions(client, student_id, h)
    before = len(models.list_assessment_attempts(student_id))
    token = "exit-token-abc"
    first = _finalize(client, student_id, questions, [q["answer"] for q in questions[:4]],
                      ext_token=token, h=h)
    assert first.status_code == 200
    second = _finalize(client, student_id, questions, [q["answer"] for q in questions[:4]],
                       ext_token=token, h=h)
    assert second.status_code == 200
    assert second.json()["already"] is True
    assert second.json()["score"] == first.json()["score"]
    assert second.json()["unanswered"] == first.json()["unanswered"]
    assert len(models.list_assessment_attempts(student_id)) == before + 1


def test_finalize_duplicate_events_do_not_double_submit(client, student_id, auth_headers):
    """route-leave + pagehide + beacon firing for the same attempt = ONE row."""
    h = auth_headers("aisha@student.edu")
    questions = _gen_questions(client, student_id, h)
    token = "dup-events-777"
    answers = [q["answer"] for q in questions]
    for _ in range(3):
        r = _finalize(client, student_id, questions, answers, ext_token=token, h=h)
        assert r.status_code == 200
    rows = [a for a in models.list_assessment_attempts(student_id)
            if a.get("external_token") == token]
    assert len(rows) == 1
    assert bool(rows[0]["passed"]) is True


def test_finalize_without_token_creates_one_attempt_per_call(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    questions = _gen_questions(client, student_id, h)
    before = len(models.list_assessment_attempts(student_id))
    _finalize(client, student_id, questions, [], h=h)
    _finalize(client, student_id, questions, [], h=h)
    assert len(models.list_assessment_attempts(student_id)) == before + 2


def test_submit_then_finalize_same_token_is_idempotent(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    docker = models.get_skill_by_name(DOCKER)["id"]
    questions = _gen_questions(client, student_id, h)
    token = "submit-then-exit-42"
    answers = [q["answer"] for q in questions]
    submit = client.post(f"/api/students/{student_id}/assessments", json={
        "skill_id": docker, "questions": questions, "answers": answers,
        "total_seconds": 300, "tab_switches": 0, "free_text_answers": [], "external_token": token,
    }, headers=h)
    assert submit.status_code == 200, submit.text
    assert submit.json()["passed"] is True
    exit_ = _finalize(client, student_id, questions, answers, ext_token=token, h=h)
    assert exit_.status_code == 200
    assert exit_.json()["already"] is True
    assert exit_.json()["score"] == submit.json()["score"]
    rows = [a for a in models.list_assessment_attempts(student_id)
            if a.get("external_token") == token]
    assert len(rows) == 1


def test_finalize_releases_active_assessment_lock(client, student_id, auth_headers, db):
    h = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")["id"]
    started = client.post(f"/api/students/{student_id}/assessments/session",
                          json={"skill_id": python}, headers=h)
    assert started.status_code == 200 and started.json()["active"] is True
    questions = _gen_questions(client, student_id, h)
    r = _finalize(client, student_id, questions, [], h=h)
    assert r.status_code == 200
    assert models.get_active_assessment(student_id) is None
    tutor = client.post(f"/api/students/{student_id}/tutor",
                        json={"message": "hello", "tutor_id": "nova"}, headers=h)
    assert tutor.status_code == 200


# ------------------------------------------------------------------ beacon body-token auth

def test_finalize_accepts_body_token_for_beacon(client, student_id, login):
    """sendBeacon cannot set headers, so the session token may ride in the body."""
    payload = login("aisha@student.edu")
    token = payload["token"]
    h = {"Authorization": f"Bearer {token}"}
    questions = _gen_questions(client, student_id, h)
    body = {"skill_id": models.get_skill_by_name(DOCKER)["id"],
            "questions": questions, "answers": [],
            "total_seconds": 120, "tab_switches": 0, "free_text_answers": [],
            "auth_token": token, "external_token": "beacon-attempt-1"}
    r = client.post(f"/api/students/{student_id}/assessments/finalize", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["unanswered"] == len(questions)


def test_finalize_rejects_bogus_body_token(client, student_id):
    body = {"skill_id": models.get_skill_by_name(DOCKER)["id"],
            "questions": [], "answers": [], "auth_token": "not-a-real-session-token"}
    r = client.post(f"/api/students/{student_id}/assessments/finalize", json=body)
    assert r.status_code == 401


# ------------------------------------------------------------------ stale-lock protection

def test_stale_active_assessment_lock_clears_after_ttl(client, student_id, db, auth_headers):
    docker = models.get_skill_by_name(DOCKER)["id"]
    old = db.execute(
        "INSERT INTO active_assessments (student_id, skill_id, started_at)"
        " VALUES (?, ?, datetime('now', '-4 hours'))",
        (student_id, docker))
    db.commit()
    assert old.rowcount == 1
    assert models.get_active_assessment(student_id) is None
    fresh = db.execute(
        "INSERT INTO active_assessments (student_id, skill_id, started_at)"
        " VALUES (?, ?, datetime('now'))",
        (student_id, docker))
    db.commit()
    assert models.get_active_assessment(student_id) is not None
    db.execute("DELETE FROM active_assessments WHERE student_id=?", (student_id,))
    db.commit()
    h = auth_headers("aisha@student.edu")
    started = client.post(f"/api/students/{student_id}/assessments/session",
                          json={"skill_id": docker}, headers=h)
    assert started.status_code == 200
    db.execute("UPDATE active_assessments SET started_at=datetime('now', '-4 hours')"
               " WHERE student_id=?", (student_id,))
    db.commit()
    tutor = client.post(f"/api/students/{student_id}/tutor",
                        json={"message": "hello", "tutor_id": "nova"}, headers=h)
    assert tutor.status_code == 200


# ------------------------------------------------------------------ no readiness gate

def test_assessment_does_not_require_readiness_gate(client, student_id, auth_headers):
    """The old 'complete N required topics first' gate is gone: a student can
    generate, submit and even exit-finalize a verified assessment without any
    learning-path prerequisite being satisfied."""
    h = auth_headers("aisha@student.edu")
    status = client.get(f"/api/students/{student_id}/learning/"
                        f"{models.get_skill_by_name(DOCKER)['id']}/final-assessment/status",
                        headers=h)
    assert status.status_code == 200
    gen = client.post(f"/api/students/{student_id}/assessments/generate",
                      json={"skill_id": models.get_skill_by_name(DOCKER)["id"],
                            "num_questions": 8}, headers=h)
    assert gen.status_code == 200
    questions = gen.json()["questions"]
    submit = client.post(f"/api/students/{student_id}/assessments", json={
        "skill_id": models.get_skill_by_name(DOCKER)["id"], "questions": questions,
        "answers": [q["answer"] for q in questions], "total_seconds": 300,
        "tab_switches": 0, "free_text_answers": [], "external_token": "no-gate-token",
    }, headers=h)
    assert submit.status_code == 200
    assert submit.json()["passed"] is True