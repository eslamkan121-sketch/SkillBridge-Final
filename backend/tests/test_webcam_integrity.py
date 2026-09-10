"""Webcam integrity MVP: metadata-only camera events for Final Assessments."""
import pytest

from app import integrity, models


def _headers(auth_headers):
    return auth_headers("aisha@student.edu")


def _docker_id():
    return models.get_skill_by_name("Docker")["id"]


def _camera_event(event_type="multiple_people", incident_id="cam-incident-1", **extra):
    return {
        "event_type": event_type,
        "duration_ms": extra.pop("duration_ms", 9000),
        "occurred_at": extra.pop("occurred_at", "2026-09-07T05:00:00Z"),
        "severity": extra.pop("severity", "warning"),
        "incident_id": incident_id,
        **extra,
    }


def _question(answer="a"):
    return [{
        "question": "Which option is correct?",
        "type": "multiple_choice",
        "options": ["a", "b", "c"],
        "answer": answer,
        "explanation": "a is correct",
    }]


def _hard_event(event_type="browser_hidden", incident_id="hard-incident-1", **extra):
    return {
        "event_type": event_type,
        "duration_ms": extra.pop("duration_ms", 0),
        "occurred_at": extra.pop("occurred_at", "2026-09-07T05:00:00Z"),
        "severity": extra.pop("severity", "high"),
        "incident_id": incident_id,
        **extra,
    }


def test_camera_event_validation_allows_metadata_only():
    event = integrity.validate_camera_integrity_event(_camera_event("camera_subject_missing"))
    assert event["event_type"] == "camera_subject_missing"
    assert event["duration_ms"] == 9000
    assert "image" not in event and "video" not in event
    flags = integrity.camera_events_to_flags([event])
    assert flags[0]["code"] == "camera_subject_missing"
    assert flags[0]["source"] == "camera"


@pytest.mark.parametrize("forbidden_key", [
    "frame", "image", "video", "blob", "base64", "embedding",
])
def test_camera_event_validation_rejects_media_payloads(forbidden_key):
    try:
        integrity.validate_camera_integrity_event({
            **_camera_event("multiple_people"),
            forbidden_key: "data:image/png;base64,not-allowed",
        })
        assert False, f"raw media payload should be rejected for {forbidden_key}"
    except ValueError as exc:
        assert "raw image" in str(exc)


def test_camera_integrity_event_is_token_bound_and_deduped(client, student_id, auth_headers):
    h = _headers(auth_headers)
    skill_id = _docker_id()
    token = "camera-token-1"
    started = client.post(f"/api/students/{student_id}/assessments/session",
                          json={"skill_id": skill_id, "external_token": token,
                              "webcam_gate": {"passed": True, "checked_at": "2026-09-07T05:00:00Z", "meta": {"person_status": "one", "camera_status": "working"}}}, headers=h)
    assert started.status_code == 200
    body = {**_camera_event("multiple_people"), "skill_id": skill_id, "external_token": token}
    first = client.post(f"/api/students/{student_id}/assessments/integrity-events",
                        json=body, headers=h)
    assert first.status_code == 200, first.text
    assert first.json()["accepted"] is True
    second = client.post(f"/api/students/{student_id}/assessments/integrity-events",
                         json=body, headers=h)
    assert second.status_code == 200, second.text
    assert second.json()["accepted"] is False
    assert second.json()["events_count"] == 1
    assert len(models.list_active_assessment_events(student_id, skill_id, token)) == 1


def test_attention_away_is_soft_metadata_event(client, student_id, auth_headers):
    h = _headers(auth_headers)
    skill_id = _docker_id()
    token = "attention-soft-token"
    client.post(f"/api/students/{student_id}/assessments/session",
                json={"skill_id": skill_id, "external_token": token,
                              "webcam_gate": {"passed": True, "checked_at": "2026-09-07T05:00:00Z", "meta": {"person_status": "one", "camera_status": "working"}}}, headers=h)
    body = {**_camera_event("attention_away", duration_ms=14000, confidence=0.72),
            "skill_id": skill_id, "external_token": token}
    event = client.post(f"/api/students/{student_id}/assessments/integrity-events",
                        json=body, headers=h)
    assert event.status_code == 200, event.text
    submit = client.post(f"/api/students/{student_id}/assessments", json={
        "skill_id": skill_id,
        "questions": _question(),
        "answers": ["a"],
        "total_seconds": 120,
        "tab_switches": 0,
        "free_text_answers": [],
        "external_token": token,
    }, headers=h)
    data = submit.json()
    assert data["passed"] is True
    assert data["integrity_status"] == "review_recommended"
    assert any(f["code"] == "attention_away" for f in data["flags"])


def test_camera_events_cannot_be_submitted_for_another_student(client, student_id, auth_headers):
    aisha = _headers(auth_headers)
    omar = auth_headers("omar@student.edu")
    skill_id = _docker_id()
    token = "camera-token-owner"
    client.post(f"/api/students/{student_id}/assessments/session",
                json={"skill_id": skill_id, "external_token": token,
                              "webcam_gate": {"passed": True, "checked_at": "2026-09-07T05:00:00Z", "meta": {"person_status": "one"}}}, headers=aisha)
    r = client.post(f"/api/students/{student_id}/assessments/integrity-events",
                    json={**_camera_event("camera_disabled"), "skill_id": skill_id, "external_token": token},
                    headers=omar)
    assert r.status_code == 403


def test_camera_events_reject_wrong_session_token(client, student_id, auth_headers):
    h = _headers(auth_headers)
    skill_id = _docker_id()
    client.post(f"/api/students/{student_id}/assessments/session",
                json={"skill_id": skill_id, "external_token": "real-token",
                              "webcam_gate": {"passed": True, "checked_at": "2026-09-07T05:00:00Z", "meta": {"person_status": "one"}}}, headers=h)
    r = client.post(f"/api/students/{student_id}/assessments/integrity-events",
                    json={**_camera_event("camera_disabled"), "skill_id": skill_id,
                          "external_token": "wrong-token"},
                    headers=h)
    assert r.status_code == 403


def test_finalized_attempt_rejects_late_camera_events(client, student_id, auth_headers):
    h = _headers(auth_headers)
    skill_id = _docker_id()
    token = "camera-finalized-token"
    client.post(f"/api/students/{student_id}/assessments/session",
                json={"skill_id": skill_id, "external_token": token,
                              "webcam_gate": {"passed": True, "checked_at": "2026-09-07T05:00:00Z", "meta": {"person_status": "one", "camera_status": "working"}}}, headers=h)
    submit = client.post(f"/api/students/{student_id}/assessments", json={
        "skill_id": skill_id,
        "questions": _question(),
        "answers": ["a"],
        "total_seconds": 120,
        "tab_switches": 0,
        "free_text_answers": [],
        "external_token": token,
    }, headers=h)
    assert submit.status_code == 200, submit.text
    late = client.post(f"/api/students/{student_id}/assessments/integrity-events",
                       json={**_camera_event("camera_disabled"), "skill_id": skill_id,
                             "external_token": token},
                       headers=h)
    assert late.status_code == 409


def test_hard_camera_flags_block_verification_and_require_review(client, student_id, auth_headers):
    h = _headers(auth_headers)
    skill_id = _docker_id()
    token = "camera-hard-review"
    client.post(f"/api/students/{student_id}/assessments/session",
                json={"skill_id": skill_id, "external_token": token,
                              "webcam_gate": {"passed": True, "checked_at": "2026-09-07T05:00:00Z", "meta": {"person_status": "one", "camera_status": "working"}}}, headers=h)
    r = client.post(f"/api/students/{student_id}/assessments/integrity-events",
                    json={**_camera_event("multiple_people", severity="high"),
                          "skill_id": skill_id, "external_token": token},
                    headers=h)
    assert r.status_code == 200, r.text
    submit = client.post(f"/api/students/{student_id}/assessments", json={
        "skill_id": skill_id,
        "questions": _question(),
        "answers": ["a"],
        "total_seconds": 120,
        "tab_switches": 0,
        "free_text_answers": [],
        "external_token": token,
    }, headers=h)
    data = submit.json()
    assert data["score"] == 100.0
    assert data["passed"] is False
    assert data["integrity_status"] == "review_required"
    assert any(f["code"] == "multiple_people" and f["source"] == "camera" for f in data["flags"])


def test_camera_event_alone_never_creates_verified_skill(client, student_id, auth_headers):
    h = _headers(auth_headers)
    skill = models.create_skill("Camera Only Skill", "General")
    token = "camera-no-verify"
    client.post(f"/api/students/{student_id}/assessments/session",
                json={"skill_id": skill["id"], "external_token": token,
                              "webcam_gate": {"passed": True, "checked_at": "2026-09-07T05:00:00Z", "meta": {"person_status": "one"}}}, headers=h)
    client.post(f"/api/students/{student_id}/assessments/integrity-events",
                json={**_camera_event("camera_subject_missing", duration_ms=12000),
                      "skill_id": skill["id"], "external_token": token},
                headers=h)
    submit = client.post(f"/api/students/{student_id}/assessments", json={
        "skill_id": skill["id"],
        "questions": _question(answer="a"),
        "answers": ["b"],
        "total_seconds": 120,
        "tab_switches": 0,
        "free_text_answers": [],
        "external_token": token,
    }, headers=h)
    assert submit.status_code == 200, submit.text
    assert submit.json()["passed"] is False
    assert "Camera Only Skill" not in {v["name"] for v in models.get_student(student_id)["verified_skills"]}


@pytest.mark.parametrize("event_type,duration_ms", [
    ("phone_detected", 5200),
    ("multiple_people", 8200),
])
def test_hard_camera_finalize_never_creates_verified_skill(
        client, student_id, auth_headers, event_type, duration_ms):
    h = _headers(auth_headers)
    skill = models.create_skill(f"{event_type} Hard Stop Skill", "General")
    token = f"{event_type}-hard-finalize-no-verify"
    client.post(f"/api/students/{student_id}/assessments/session",
                json={"skill_id": skill["id"], "external_token": token,
                              "webcam_gate": {"passed": True, "checked_at": "2026-09-07T05:00:00Z", "meta": {"person_status": "one"}}}, headers=h)
    r = client.post(f"/api/students/{student_id}/assessments/finalize", json={
        "skill_id": skill["id"],
        "questions": _question(answer="a"),
        "answers": ["a"],
        "total_seconds": 120,
        "tab_switches": 0,
        "free_text_answers": [],
        "external_token": token,
        "termination_event": _hard_event(event_type, duration_ms=duration_ms),
    }, headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ended"] == "integrity_violation"
    assert data["integrity_status"] == "review_required"
    assert data["passed"] is False
    assert skill["name"] not in {v["name"] for v in models.get_student(student_id)["verified_skills"]}


def test_hard_browser_termination_finalize_is_idempotent(client, student_id, auth_headers):
    h = _headers(auth_headers)
    skill_id = _docker_id()
    token = "browser-hidden-hard-stop"
    client.post(f"/api/students/{student_id}/assessments/session",
                json={"skill_id": skill_id, "external_token": token,
                              "webcam_gate": {"passed": True, "checked_at": "2026-09-07T05:00:00Z", "meta": {"person_status": "one", "camera_status": "working"}}}, headers=h)
    body = {
        "skill_id": skill_id,
        "questions": _question(),
        "answers": ["a"],
        "total_seconds": 120,
        "tab_switches": 0,
        "free_text_answers": [],
        "external_token": token,
        "termination_event": _hard_event("browser_hidden"),
    }
    first = client.post(f"/api/students/{student_id}/assessments/finalize",
                        json=body, headers=h)
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["ended"] == "integrity_violation"
    assert data["termination_reason"] == "The assessment browser tab was hidden."
    assert data["integrity_status"] == "review_required"
    assert data["passed"] is False
    second = client.post(f"/api/students/{student_id}/assessments/finalize",
                         json=body, headers=h)
    assert second.status_code == 200, second.text
    assert second.json()["already"] is True
    rows = [a for a in models.list_assessment_attempts(student_id)
            if a.get("external_token") == token]
    assert len(rows) == 1


def test_soft_attention_cannot_be_used_as_termination_event(client, student_id, auth_headers):
    h = _headers(auth_headers)
    skill_id = _docker_id()
    token = "attention-not-hard"
    client.post(f"/api/students/{student_id}/assessments/session",
                json={"skill_id": skill_id, "external_token": token,
                              "webcam_gate": {"passed": True, "checked_at": "2026-09-07T05:00:00Z", "meta": {"person_status": "one", "camera_status": "working"}}}, headers=h)
    r = client.post(f"/api/students/{student_id}/assessments/finalize", json={
        "skill_id": skill_id,
        "questions": _question(),
        "answers": [],
        "total_seconds": 120,
        "tab_switches": 0,
        "free_text_answers": [],
        "external_token": token,
        "termination_event": _camera_event("attention_away", duration_ms=15000),
    }, headers=h)
    assert r.status_code == 400


def test_finalized_attempt_token_cannot_start_again(client, student_id, auth_headers):
    h = _headers(auth_headers)
    skill_id = _docker_id()
    token = "no-resume-token"
    client.post(f"/api/students/{student_id}/assessments/session",
                json={"skill_id": skill_id, "external_token": token,
                              "webcam_gate": {"passed": True, "checked_at": "2026-09-07T05:00:00Z", "meta": {"person_status": "one", "camera_status": "working"}}}, headers=h)
    done = client.post(f"/api/students/{student_id}/assessments/finalize", json={
        "skill_id": skill_id,
        "questions": _question(),
        "answers": [],
        "total_seconds": 120,
        "tab_switches": 0,
        "free_text_answers": [],
        "external_token": token,
        "termination_event": _hard_event("camera_disabled"),
    }, headers=h)
    assert done.status_code == 200, done.text
    again = client.post(f"/api/students/{student_id}/assessments/session",
                        json={"skill_id": skill_id, "external_token": token,
                              "webcam_gate": {"passed": True, "checked_at": "2026-09-07T05:00:00Z", "meta": {"person_status": "one", "camera_status": "working"}}}, headers=h)
    assert again.status_code == 409


def test_blank_answers_are_unanswered_and_score_zero_after_hard_finalize(client, student_id, auth_headers):
    h = _headers(auth_headers)
    skill_id = _docker_id()
    token = "blank-answer-hard-stop"
    questions = _question() + [{
        "question": "Second?",
        "type": "multiple_choice",
        "options": ["a", "b", "c"],
        "answer": "b",
        "explanation": "b is correct",
    }, {
        "question": "Third?",
        "type": "multiple_choice",
        "options": ["a", "b", "c"],
        "answer": "c",
        "explanation": "c is correct",
    }]
    client.post(f"/api/students/{student_id}/assessments/session",
                json={"skill_id": skill_id, "external_token": token,
                              "webcam_gate": {"passed": True, "checked_at": "2026-09-07T05:00:00Z", "meta": {"person_status": "one", "camera_status": "working"}}}, headers=h)
    r = client.post(f"/api/students/{student_id}/assessments/finalize", json={
        "skill_id": skill_id,
        "questions": questions,
        "answers": ["a", "", ""],
        "total_seconds": 120,
        "tab_switches": 0,
        "free_text_answers": [],
        "external_token": token,
        "termination_event": _hard_event("camera_subject_missing", duration_ms=11000),
    }, headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["score"] == 33.3
    assert data["unanswered"] == 2
    assert data["ended"] == "integrity_violation"


# ------------------------------------------------------------------ gate


def test_session_start_requires_webcam_gate(client, student_id, auth_headers):
    """The pre-assessment camera gate is enforced server-side: no attestation,
    no session. This is what makes the gate more than a client-side UI affordance.
    """
    h = _headers(auth_headers)
    skill_id = _docker_id()
    no_gate = client.post(f"/api/students/{student_id}/assessments/session",
                          json={"skill_id": skill_id}, headers=h)
    assert no_gate.status_code == 400
    assert "camera integrity gate" in no_gate.json()["detail"].lower()
    assert models.get_active_assessment(student_id) is None

    false_gate = client.post(f"/api/students/{student_id}/assessments/session",
                             json={"skill_id": skill_id, "webcam_gate": {"passed": False}}, headers=h)
    assert false_gate.status_code == 400
    assert models.get_active_assessment(student_id) is None


def test_valid_gate_starts_session_and_persists_metadata(client, student_id, auth_headers):
    h = _headers(auth_headers)
    skill_id = _docker_id()
    r = client.post(f"/api/students/{student_id}/assessments/session",
                    json={"skill_id": skill_id, "external_token": "gated-token-1",
                          "webcam_gate": {
                              "passed": True,
                              "checked_at": "2026-09-07T05:00:00Z",
                              "meta": {"person_status": "one", "camera_status": "working",
                                       "camera_count": 2}}},
                    headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["webcam_gate"] == {"required": True, "passed": True}
    active = models.get_active_assessment(student_id)
    assert active["webcam_gate_passed"] == 1
    assert active["webcam_gate_checked_at"] == "2026-09-07T05:00:00Z"
    meta = __import__("json").loads(active["webcam_gate_meta"])
    assert meta.get("person_status") == "one"
    assert meta.get("camera_count") == 2


def test_gate_metadata_is_sanitised_to_primitive_values(client, student_id, auth_headers):
    """Only small primitive metadata survives storage: media blobs and oversized
    fields are dropped so the gate never becomes a covert upload channel."""
    h = _headers(auth_headers)
    skill_id = _docker_id()
    r = client.post(f"/api/students/{student_id}/assessments/session",
                    json={"skill_id": skill_id,
                          "webcam_gate": {
                              "passed": True,
                              "checked_at": "2026-09-07T05:00:00Z",
                              "meta": {"person_status": "one",
                                       "frame": "data:image/png;base64,AAAA",
                                       "huge": "x" * 500,
                                       "nested": {"not": "allowed"}}}},
                    headers=h)
    assert r.status_code == 200
    active = models.get_active_assessment(student_id)
    meta = __import__("json").loads(active["webcam_gate_meta"])
    assert meta.get("person_status") == "one"
    assert "frame" not in meta and "huge" not in meta and "nested" not in meta
