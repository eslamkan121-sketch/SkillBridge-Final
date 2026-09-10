"""Unified Tutor Modes (Phase 5.5 Step 1): the Global Copilot runs in
chat / practice / discuss / interview modes with per-tutor defaults,
persistence through the tutor-preference architecture, backend validation,
and a Verified Final Assessment lock that covers every mode — including the
standalone mock-interview engine. Never calls a paid API.
"""

import pytest

from app import genai, models
from app import copilot
import app.jobs as jobs_mod


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
    """Lock generation into the deterministic fallback and keep jobs offline."""
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    monkeypatch.setattr(jobs_mod, "_fetch_all", lambda *a, **k: [])
    jobs_mod._cache.update({"at": 0.0, "key": "", "data": None})


def _capture_complete(monkeypatch):
    """Replace genai.complete with a recorder returning the deterministic fallback."""
    captured = {}

    def fake(system, user, fallback=None, **kw):
        captured["system"] = system
        captured["user"] = user
        return fallback

    monkeypatch.setattr(genai, "complete", fake)
    return captured


def _tutor(client, student_id, headers, body=None):
    return client.post(f"/api/students/{student_id}/tutor",
                       json={"message": "What should I do next?", **(body or {})},
                       headers=headers)


def _set_pref(client, student_id, headers, body):
    return client.put(f"/api/students/{student_id}/tutor/preference", json=body, headers=headers)


# ------------------------------------------------------------------ mode validation

def test_all_modes_are_known_and_have_defaults():
    assert copilot.MODES == ("chat", "practice", "discuss", "interview")
    # Vex defaults to chat: selecting a persona must not imply an interview
    # session. Explicit Interview mode is opt-in and stays fully supported.
    assert copilot.TUTOR_DEFAULT_MODES == {
        "nova": "chat", "axel": "practice", "sage": "discuss", "vex": "chat",
    }


def test_tutor_route_accepts_every_valid_mode(client, student_id, auth_headers, monkeypatch):
    _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    for mode in copilot.MODES:
        r = _tutor(client, student_id, h, {"mode": mode})
        assert r.status_code == 200, (mode, r.text)
        assert r.json()["mode"] == mode


def test_tutor_route_rejects_invalid_mode(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    for bad in ("", "bogus", "practicee", 123):
        r = _tutor(client, student_id, h, {"mode": bad})
        assert r.status_code == 400, (bad, r.text)
        assert "mode" in r.json()["detail"].lower()
    # mode is normalized like the persona (strip + lowercase), not typo-tolerant
    r = _tutor(client, student_id, h, {"mode": "  DISCUSS "})
    assert r.status_code == 200 and r.json()["mode"] == "discuss"
    # nothing persisted for a bad mode, and chat still works afterwards
    assert _tutor(client, student_id, h, {"mode": "chat"}).status_code == 200


def test_preference_rejects_invalid_mode(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    for bad in ("nope", "AXEL", "", 7, None):
        r = _set_pref(client, student_id, h, {"mode": bad})
        assert r.status_code == 400, (bad, r.text)
    assert models.get_tutor_preference(student_id) is None
    assert models.get_tutor_mode(student_id) is None


def test_preference_requires_at_least_one_field(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    assert _set_pref(client, student_id, h, {}).status_code == 400


# ------------------------------------------------------------------ per-tutor defaults

def test_default_mode_follows_tutor_selection(client, student_id, auth_headers, monkeypatch):
    _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    for tutor, default in copilot.TUTOR_DEFAULT_MODES.items():
        assert _set_pref(client, student_id, h, {"tutor_id": tutor}).status_code == 200
        got = client.get(f"/api/students/{student_id}/tutor/preference", headers=h).json()
        assert got["tutor_id"] == tutor and got["mode"] == default, (tutor, got)
        r = _tutor(client, student_id, h)
        assert r.json()["mode"] == default, (tutor, r.json())


def test_default_mode_is_chat_without_preference(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    got = client.get(f"/api/students/{student_id}/tutor/preference", headers=h).json()
    assert got == {"tutor_id": "nova", "mode": "chat", "language": "auto"}
    assert _tutor(client, student_id, h).json()["mode"] == "chat"


# ------------------------------------------------------------------ switching + persistence

def test_mode_switch_persists_and_is_independent_of_tutor(client, student_id, auth_headers, monkeypatch):
    _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    # switch mode only; tutor persona must be untouched
    assert _set_pref(client, student_id, h, {"mode": "discuss"}).status_code == 200
    got = client.get(f"/api/students/{student_id}/tutor/preference", headers=h).json()
    assert got["tutor_id"] == "nova" and got["mode"] == "discuss"
    # persists across chat requests until changed
    assert _tutor(client, student_id, h).json()["mode"] == "discuss"
    # switching tutor with an explicit mode (as the UI does) lands on that mode
    _set_pref(client, student_id, h, {"tutor_id": "vex", "mode": "interview"})
    got = client.get(f"/api/students/{student_id}/tutor/preference", headers=h).json()
    assert got["tutor_id"] == "vex" and got["mode"] == "interview"
    # a tutor-only update keeps the stored mode
    _set_pref(client, student_id, h, {"tutor_id": "sage"})
    got = client.get(f"/api/students/{student_id}/tutor/preference", headers=h).json()
    assert got["tutor_id"] == "sage" and got["mode"] == "interview"
    # combined update works in a single call
    assert _set_pref(client, student_id, h,
                     {"tutor_id": "sage", "mode": "practice"}).json() == {"tutor_id": "sage", "mode": "practice", "language": "auto"}
    assert models.get_tutor_mode(student_id) == "practice"


def test_mode_is_isolated_per_student(db, auth_headers, client):
    h = auth_headers("aisha@student.edu")
    sid = models.get_student_by_user(models.get_user_by_email("aisha@student.edu")["id"])["id"]
    other = models.get_student_by_user(models.get_user_by_email("omar@student.edu")["id"])["id"]
    client.put(f"/api/students/{sid}/tutor/preference", json={"mode": "practice"}, headers=h)
    assert models.get_tutor_mode(sid) == "practice"
    assert models.get_tutor_mode(other) is None


# ------------------------------------------------------------------ mode drives behavior

def test_chat_mode_applies_chat_instruction(monkeypatch, client, student_id, auth_headers):
    captured = _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    assert _tutor(client, student_id, h, {"mode": "chat"}).status_code == 200
    assert "Working mode: CHAT." in captured["system"]


def test_practice_mode_applies_practice_instruction(monkeypatch, client, student_id, auth_headers):
    captured = _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    assert _tutor(client, student_id, h, {"mode": "practice"}).status_code == 200
    assert "Working mode: PRACTICE." in captured["system"]


def test_discuss_mode_applies_discuss_instruction(monkeypatch, client, student_id, auth_headers):
    captured = _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    assert _tutor(client, student_id, h, {"mode": "discuss"}).status_code == 200
    assert "Working mode: DISCUSS." in captured["system"]


def test_interview_mode_reuses_interview_engine(monkeypatch, client, student_id, auth_headers):
    captured = _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    r = _tutor(client, student_id, h, {"mode": "interview"})
    assert r.status_code == 200 and r.json()["mode"] == "interview"
    assert "mock interview coach" in captured["system"]
    # the interview-mode message is persisted like any other tutor message
    history = client.get(f"/api/students/{student_id}/tutor", headers=h).json()
    assert len(history) == 2  # user message + assistant reply


# ------------------------------------------------------------------ assessment lock covers ALL modes

def test_assessment_lock_blocks_every_mode(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")["id"]
    assert client.post(f"/api/students/{student_id}/assessments/session",
                       json={"skill_id": python,
                       "webcam_gate": {"passed": True, "checked_at": "2026-09-07T05:00:00Z", "meta": {"person_status": "one"}}}, headers=h).status_code == 200
    for mode in copilot.MODES:
        r = _tutor(client, student_id, h, {"mode": mode})
        assert r.status_code == 423, (mode, r.text)
    # the standalone interview engine must not bypass the lock either
    r = client.post(f"/api/students/{student_id}/interview",
                    json={"message": "", "turn": 1, "tutor": "vex"}, headers=h)
    assert r.status_code == 423
    r = client.post(f"/api/students/{student_id}/interview/tts",
                    json={"tutor": "vex", "text": "hello"}, headers=h)
    assert r.status_code == 423
    client.delete(f"/api/students/{student_id}/assessments/session", headers=h)
    assert _tutor(client, student_id, h, {"mode": "interview"}).status_code == 200


# ------------------------------------------------------------------ regressions from Phase 5 behavior

def test_phase5_preference_and_chat_still_work(client, student_id, auth_headers, monkeypatch):
    _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    assert _set_pref(client, student_id, h, {"tutor_id": "axel"}).json()["tutor_id"] == "axel"
    assert _tutor(client, student_id, h).status_code == 200
    # unknown tutor still rejected even when a valid mode is attached
    r = _set_pref(client, student_id, h, {"tutor_id": "sarah", "mode": "chat"})
    assert r.status_code == 400
    assert models.get_tutor_preference(student_id) == "axel"