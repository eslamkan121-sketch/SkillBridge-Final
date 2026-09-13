"""Phase 5.5 Step 2 — Mock Interview merged into the Global Copilot.

The Copilot no longer deep-links away for an interview: interview mode runs
in the Copilot conversation using the exact same backend engine as the
standalone mock-interview (``api_interview``). These tests pin that engine's
backward compatibility so the merge never changes it:

- the standalone endpoint keeps accepting any tutor persona (including the
  non-recommended ones) and unknown tutor ids degrade to a neutral
  interviewer instead of erroring;
- turn validation (clamp 1..50), skill validation (404), oversized answers
  (400) and ownership (403) keep working;
- the Copilot interview-mode dispatch passes turns through the same engine
  and returning to chat afterwards still works.
Never calls a paid API.
"""

import pytest

from app import genai, models
import app.jobs as jobs_mod


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
    """Lock generation into the deterministic fallback and keep jobs offline."""
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    monkeypatch.setattr(jobs_mod, "_fetch_all", lambda *a, **k: [])
    jobs_mod.clear_job_cache()


def _capture_complete(monkeypatch):
    captured = {}

    def fake(system, user, fallback=None, **kw):
        captured["system"] = system
        captured["user"] = user
        return fallback

    monkeypatch.setattr(genai, "complete", fake)
    return captured


def _interview(client, student_id, headers, body=None):
    return client.post(f"/api/students/{student_id}/interview",
                       json={"message": "A type system prevents a whole class of bugs.",
                             "turn": 2, **(body or {})},
                       headers=headers)


# ------------------------------------------------------------------ standalone engine stays backward compatible

def test_standalone_interview_accepts_any_tutor_persona(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    for tutor in ("vex", "axel", "sage", "nova"):
        r = _interview(client, student_id, h, {"tutor": tutor})
        assert r.status_code == 200, (tutor, r.text)
        body = r.json()
        assert body["reply"] and body["turn"] == 3, (tutor, body)
    # the merge must not break the standalone engine even for an unfamiliar
    # tutor id: it degrades to a neutral interviewer rather than erroring
    r = _interview(client, student_id, h, {"tutor": "someone-else"})
    assert r.status_code == 200 and r.json()["reply"]


def test_deterministic_interview_fallbacks_reflect_all_four_tutors(monkeypatch):
    monkeypatch.setattr(genai, "OPENAI_KEY", None)
    monkeypatch.setattr(genai, "ANTHROPIC_KEY", None)
    monkeypatch.setattr(genai, "NIM_KEY", None)
    replies = {
        tutor: genai.interview_reply("", student_context="ctx", skill_name="Docker",
                                     target_role="DevOps", turn=1, tutor_id=tutor,
                                     language="en")
        for tutor in ("nova", "axel", "sage", "vex")
    }
    assert "gently" in replies["nova"].lower()
    assert "built" in replies["axel"].lower() or "run" in replies["axel"].lower()
    assert "tradeoff" in replies["sage"].lower() or "wrong choice" in replies["sage"].lower()
    assert "be specific" in replies["vex"].lower()
    assert len(set(replies.values())) == 4


def test_standalone_interview_next_turn_works(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    replies = []
    turn = 1
    for _ in range(3):
        r = client.post(f"/api/students/{student_id}/interview",
                        json={"message": f"my answer for turn {turn}", "turn": turn, "tutor": "vex"},
                        headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["turn"] == turn + 1
        assert body["reply"]
        replies.append(body["reply"])
        turn = body["turn"]
    assert len(set(replies)) >= 2  # the interviewer actually progresses


def test_standalone_interview_turn_validation_clamps(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    r = _interview(client, student_id, h, {"turn": 0})
    assert r.status_code == 200 and r.json()["turn"] == 2  # clamped up
    r = _interview(client, student_id, h, {"turn": 999})
    assert r.status_code == 200 and r.json()["turn"] == 51  # clamped to 50
    r = _interview(client, student_id, h, {"turn": "not-a-number"})
    assert r.status_code == 200 and r.json()["turn"] == 2  # falls back to 1


def test_standalone_interview_skill_not_found_is_404(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    r = _interview(client, student_id, h, {"skill_id": 999999})
    assert r.status_code == 404


def test_standalone_interview_answer_too_long_is_400(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    r = _interview(client, student_id, h, {"message": "x" * 4001})
    assert r.status_code == 400


def test_standalone_interview_ownership_and_roles(client, student_id, auth_headers):
    other = auth_headers("omar@student.edu")
    assert _interview(client, student_id, other).status_code == 403
    company = auth_headers("hr@northstar.com")
    assert _interview(client, student_id, company).status_code == 403
    assert _interview(client, student_id, {}).status_code in (401, 403)


# ------------------------------------------------------------------ Copilot interview-mode dispatch reuses the same engine

def test_copilot_interview_mode_uses_same_engine_and_persists(monkeypatch, client, student_id, auth_headers):
    captured = _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    r = client.post(f"/api/students/{student_id}/tutor",
                    json={"message": "What type system features matter most?",
                          "turn": 4, "mode": "interview", "tutor_id": "vex"},
                    headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "interview"
    assert "mock interview coach" in captured["system"]
    history = client.get(f"/api/students/{student_id}/tutor", headers=h).json()
    assert len(history) == 2  # interview-mode messages persist like any chat turn


def test_copilot_interview_with_non_recommended_tutor(client, student_id, auth_headers, monkeypatch):
    _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    client.put(f"/api/students/{student_id}/tutor/preference",
               json={"tutor_id": "axel", "mode": "interview"}, headers=h)
    r = client.post(f"/api/students/{student_id}/tutor",
                    json={"message": "What tradeoffs matter for my role?", "mode": "interview"},
                    headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "interview" and r.json()["tutor_id"] == "axel"


def test_return_to_chat_after_copilot_interview(client, student_id, auth_headers, monkeypatch):
    captured = _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    r = client.post(f"/api/students/{student_id}/tutor",
                    json={"message": "Walk me through an error-handling approach.", "mode": "interview"},
                    headers=h)
    assert r.status_code == 200 and r.json()["mode"] == "interview"
    # ending the interview just means going back to a normal mode; the engine
    # must accept the next chat turn normally and switch modes
    r = client.post(f"/api/students/{student_id}/tutor",
                    json={"message": "Great, back to helping me plan my week.", "mode": "chat"},
                    headers=h)
    assert r.status_code == 200 and r.json()["mode"] == "chat"
    assert "Working mode: CHAT." in captured["system"]


# ------------------------------------------------------------------ the Copilot lock still guards interview mode

def test_assessment_lock_still_blocks_copilot_interview(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")["id"]
    assert client.post(f"/api/students/{student_id}/assessments/session",
                       json={"skill_id": python,
                            "webcam_gate": {"passed": True, "checked_at": "2026-09-07T05:00:00Z", "meta": {"person_status": "one"}}}, headers=h).status_code == 200
    r = client.post(f"/api/students/{student_id}/tutor",
                    json={"message": "Interview me.", "mode": "interview"}, headers=h)
    assert r.status_code == 423
    assert _interview(client, student_id, h, {"tutor": "vex"}).status_code == 423
    assert client.post(f"/api/students/{student_id}/interview/tts",
                       json={"tutor": "vex", "text": "hello"}, headers=h).status_code == 423
    client.delete(f"/api/students/{student_id}/assessments/session", headers=h)
    assert client.post(f"/api/students/{student_id}/tutor",
                       json={"message": "Interview me.", "mode": "interview"}, headers=h).status_code == 200
