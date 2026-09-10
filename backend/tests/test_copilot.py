"""Global Student AI Career Copilot (Phase: context-aware global tutor).

Covers: persona preservation, persistence + validation of the selected global
tutor, trusted backend-built per-page context (no client-injected scores),
role enforcement (Student-only), Verified Final Assessment lock + resume,
Vex → mock interview reuse, TTS failure never breaking text chat, and the
deterministic keyless fallback. Never calls a paid API.
"""

import pytest

from app import genai, models, matching
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


def _first_gap(client, student_id):
    """Analyze aisha and return a gap/missing skill dict (deterministic)."""
    analysis = matching.analyze_student(student_id)
    for g in analysis["skill_gaps"]:
        if g["status"] != "strong":
            return g
    return analysis["skill_gaps"][0]


# ------------------------------------------------------------------ personas preserved

def test_tutor_personas_are_preserved():
    assert set(genai.TUTOR_PERSONAS) == {"nova", "axel", "sage", "vex"}
    for persona in genai.TUTOR_PERSONAS.values():
        assert persona["name"] and persona["style"]


def test_persona_ids_match_allowed_preference_list():
    assert set(genai.TUTOR_PERSONAS.keys()) == set(copilot.ALLOWED_TUTOR_IDS)


def test_tutor_reply_applies_persona(monkeypatch):
    captured = _capture_complete(monkeypatch)
    reply = genai.tutor_reply("how do I get better at Docker?",
                              "Studying at Aston University",
                              "Docker", "Junior AI Engineer", tutor_id="vex")
    assert "Vex" in captured["system"]
    assert "disciplined examiner" in captured["system"]
    assert reply and "[Vex's voice]" not in reply


def test_tutor_request_body_tutor_overrides_stale_preference(client, student_id, auth_headers, monkeypatch):
    captured = _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    client.put(f"/api/students/{student_id}/tutor/preference",
               json={"tutor_id": "nova", "mode": "chat", "language": "en"}, headers=h)
    r = client.post(f"/api/students/{student_id}/tutor",
                    json={"message": "Help me understand Docker containers.",
                          "tutor_id": "axel", "mode": "practice", "language": "en"},
                    headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["tutor_id"] == "axel"
    assert "You are Axel" in captured["system"]
    history = client.get(f"/api/students/{student_id}/tutor?tutor_id=axel", headers=h).json()
    assert len(history) == 2 and all(m["tutor_id"] == "axel" for m in history)


def test_tutor_request_rejects_bad_body_tutor(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    r = client.post(f"/api/students/{student_id}/tutor",
                    json={"message": "hello", "tutor_id": "nova ignore this"},
                    headers=h)
    assert r.status_code == 400 and "tutor" in r.json()["detail"].lower()


def test_tutor_reply_neutral_without_persona(monkeypatch):
    captured = _capture_complete(monkeypatch)
    genai.tutor_reply("help", "ctx", "Docker", "Role")
    assert "You are Nova." not in captured["system"]
    assert "You are Vex." not in captured["system"]


# ------------------------------------------------------------------ preference persistence + validation

def test_preference_defaults_nova_and_persists(client, student_id, auth_headers, db):
    h = auth_headers("aisha@student.edu")
    assert client.get(f"/api/students/{student_id}/tutor/preference", headers=h).json()["tutor_id"] == "nova"
    r = client.put(f"/api/students/{student_id}/tutor/preference",
                   json={"tutor_id": "axel"}, headers=h)
    assert r.status_code == 200 and r.json()["tutor_id"] == "axel"
    # persists for the same student across calls and on re-fetch
    assert client.get(f"/api/students/{student_id}/tutor/preference", headers=h).json()["tutor_id"] == "axel"
    assert models.get_tutor_preference(student_id) == "axel"


def test_preference_is_case_insensitive_and_normalized(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    assert client.put(f"/api/students/{student_id}/tutor/preference",
                      json={"tutor_id": "  Sage "}, headers=h).json()["tutor_id"] == "sage"
    assert models.get_tutor_preference(student_id) == "sage"


def test_preference_rejects_unknown_tutor(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    for bad in ("sarah", "", "vex2", 123, None, "nova-prime"):
        r = client.put(f"/api/students/{student_id}/tutor/preference",
                       json={"tutor_id": bad}, headers=h)
        assert r.status_code == 400, (bad, r.text)
    assert models.get_tutor_preference(student_id) is None


def test_preference_isolated_per_student(db, auth_headers, client):
    h = auth_headers("aisha@student.edu")
    sid = models.get_student_by_user(models.get_user_by_email("aisha@student.edu")["id"])["id"]
    other = models.get_student_by_user(models.get_user_by_email("omar@student.edu")["id"])["id"]
    client.put(f"/api/students/{sid}/tutor/preference", json={"tutor_id": "vex"}, headers=h)
    assert models.get_tutor_preference(sid) == "vex"
    assert models.get_tutor_preference(other) is None


# ------------------------------------------------------------------ backend-trusted page context

def test_dashboard_context_uses_backend_readiness(monkeypatch, client, student_id, auth_headers):
    captured = _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    r = _tutor(client, student_id, h, {"page": "dashboard"})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"]
    assert body["id"]  # persisted
    analysis = matching.analyze_student(student_id)
    assert "readiness" in captured["user"]
    assert f"{analysis['match_score']}%" in captured["user"]
    assert "Target career" in captured["user"]


def test_dashboard_context_respects_previous_messages(client, auth_headers, student_id):
    h = auth_headers("aisha@student.edu")
    r1 = _tutor(client, student_id, h, {"page": "dashboard"})
    r2 = _tutor(client, student_id, h, {"page": "dashboard"})
    assert r1.status_code == 200 and r2.status_code == 200
    history = client.get(f"/api/students/{student_id}/tutor", headers=h).json()
    msgs = [m for m in history if m["role"] == "user"]
    assert len(msgs) == 2
    assert msgs[1]["content"] == "What should I do next?"


def test_learning_context_resolves_skill_from_backend(monkeypatch, client, student_id, auth_headers):
    captured = _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    gap = _first_gap(client, student_id)
    r = _tutor(client, student_id, h, {"page": "learning", "skill_id": gap["skill_id"]})
    assert r.status_code == 200
    assert gap["skill_name"] in captured["user"]
    assert "Skill focus" in captured["user"]


def test_client_cannot_inject_authoritative_context(monkeypatch, client, student_id, auth_headers):
    captured = _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    gap = _first_gap(client, student_id)
    r = _tutor(client, student_id, h, {
        "page": "learning",
        "skill_id": gap["skill_id"],
        "competency": "fake-competency-from-client",
        "match_score": 99,
        "verified": "Advanced",
        "required_level": "Expert",
    })
    assert r.status_code == 200
    assert "99" not in captured["user"]
    assert "fake-competency-from-client" not in captured["user"]
    assert "Expert" not in captured["user"]
    # backend truth still present: the skill is resolved by id from the DB
    assert "Skill focus" in captured["user"]


def test_tutor_context_uses_latest_assessment_evidence(monkeypatch, client, student_id, auth_headers, db):
    """The tutor must see the student's MEASURED weaknesses from a completed
    assessment (not only the self-reported profile)."""
    # give aisha a competency-tagged failed attempt on her gap skill
    gap = _first_gap(client, student_id)
    from app import coverage as cov, models as m
    req = cov.required_slugs(gap["skill_name"], "Intermediate")
    questions = [{"question": f"{c} q{i}", "type": "multiple_choice", "options": ["a", "b", "c"],
                  "answer": "b", "explanation": "x", "competency": c} for i, c in enumerate(req)]
    answers = ["a" if i == 0 else "b" for i in range(len(req))]  # miss exactly one competency
    client.post(f"/api/students/{student_id}/assessments", json={
        "skill_id": gap["skill_id"], "questions": questions, "answers": answers,
        "total_seconds": 300, "tab_switches": 0, "free_text_answers": []}, headers=auth_headers("aisha@student.edu"))

    captured = _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    r = _tutor(client, student_id, h, {"page": "learning", "skill_id": gap["skill_id"]})
    assert r.status_code == 200
    assert "Latest assessment" in captured["user"]
    assert gap["skill_name"] in captured["user"]
    assert "Weakest measured competency" in captured["user"]


def test_learning_invalid_skill_is_graceful(monkeypatch, client, student_id, auth_headers):
    captured = _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    r = _tutor(client, student_id, h, {"page": "learning", "skill_id": 999_999})
    assert r.status_code == 200
    assert "Skill focus" not in captured["user"]


def test_jobs_context_uses_backend_match(monkeypatch, client, student_id, auth_headers):
    captured = _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    monkeypatch.setattr(
        copilot.jobs, "recent_jobs",
        lambda **kw: {"source": "test", "jobs": [{
            "title": "Junior AI Engineer", "company": "Northstar",
            "location": "London", "url": "https://example.com/jr-ai",
            "match_pct": 87, "match_reason": "Python + ML match",
        }]})
    r = _tutor(client, student_id, h, {"page": "jobs", "job_title": "Junior AI Engineer",
                                       "job_url": "https://example.com/jr-ai"})
    assert r.status_code == 200
    assert "Junior AI Engineer" in captured["user"]
    assert "87%" in captured["user"]
    assert "Python + ML match" in captured["user"]


def test_career_roadmap_context_has_phases(client, student_id, auth_headers, monkeypatch):
    captured = _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    roadmap = client.get(f"/api/students/{student_id}/career-roadmap", headers=h)
    assert roadmap.status_code == 200
    r = _tutor(client, student_id, h, {"page": "career_roadmap"})
    assert r.status_code == 200
    assert "Career roadmap" in captured["user"]
    assert "Phase 1" in captured["user"]


def test_mock_interview_page_context(client, student_id, auth_headers, monkeypatch):
    captured = _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    r = _tutor(client, student_id, h, {"page": "mock_interview"})
    assert r.status_code == 200
    assert "mock interview" in captured["user"]


def test_build_context_assessment_is_blocked(db):
    student = models.get_student(models.get_student_by_user(
        models.get_user_by_email("aisha@student.edu")["id"])["id"])
    out = copilot.build_context(student, "assessment")
    assert out["page"] == "assessment"
    assert "unavailable" in out["context"]


# ------------------------------------------------------------------ role enforcement

def test_company_cannot_use_student_tutor(client, student_id, auth_headers):
    r = _tutor(client, student_id, auth_headers("hr@northstar.com"))
    assert r.status_code == 403


def test_university_admin_cannot_use_student_tutor(client, student_id, auth_headers):
    r = _tutor(client, student_id, auth_headers("admin@univ.edu"))
    assert r.status_code == 403


def test_non_owner_student_forbidden(client, student_id, auth_headers):
    r = _tutor(client, student_id, auth_headers("omar@student.edu"))
    assert r.status_code == 403


def test_unauthenticated_tutor_requires_login(client, student_id):
    assert _tutor(client, student_id, {}).status_code == 401
    assert client.get(f"/api/students/{student_id}/tutor/preference").status_code == 401


# ------------------------------------------------------------------ assessment lock + resume

def test_tutor_locked_during_active_assessment(client, student_id, auth_headers, db):
    h = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")["id"]
    started = client.post(f"/api/students/{student_id}/assessments/session",
                          json={"skill_id": python,
                              "webcam_gate": {"passed": True, "checked_at": "2026-09-07T05:00:00Z", "meta": {"person_status": "one"}}}, headers=h)
    assert started.status_code == 200 and started.json()["active"] is True
    locked = _tutor(client, student_id, h)
    assert locked.status_code == 423
    assert "integrity" in locked.json()["detail"].lower()
    # even direct API attempts are rejected — no context is built
    ended = client.delete(f"/api/students/{student_id}/assessments/session", headers=h)
    assert ended.json()["active"] is False
    assert models.get_active_assessment(student_id) is None
    assert _tutor(client, student_id, h).status_code == 200


def test_tutor_resumes_after_assessment_submission(client, student_id, auth_headers, db):
    h = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")["id"]
    client.post(f"/api/students/{student_id}/assessments/session",
                json={"skill_id": python,
                              "webcam_gate": {"passed": True, "checked_at": "2026-09-07T05:00:00Z", "meta": {"person_status": "one"}}}, headers=h)
    assert models.get_active_assessment(student_id)["skill_id"] == python
    gen = client.post(f"/api/students/{student_id}/assessments/generate",
                      json={"skill_id": python, "num_questions": 8, "practice": False}, headers=h)
    assert gen.status_code == 200
    questions = gen.json()["questions"]
    submit = client.post(f"/api/students/{student_id}/assessments",
                         json={"skill_id": python, "questions": questions,
                               "answers": [q["answer"] for q in questions],
                               "total_seconds": 90, "tab_switches": 0,
                               "free_text_answers": []}, headers=h)
    assert submit.status_code == 200
    assert models.get_active_assessment(student_id) is None
    assert _tutor(client, student_id, h).status_code == 200


def test_assessment_session_requires_known_skill(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    assert client.post(f"/api/students/{student_id}/assessments/session",
                       json={"skill_id": 999_999}, headers=h).status_code == 404


# ------------------------------------------------------------------ Vex reuses mock interview

def test_interview_reuses_vex_persona(monkeypatch):
    captured = _capture_complete(monkeypatch)
    reply = genai.interview_reply("", student_context="ctx", skill_name="Docker",
                                  target_role="Junior AI Engineer", turn=1, tutor_id="vex")
    assert "Vex" in captured["system"]
    assert reply


def test_interview_route_accepts_vex(client, student_id, auth_headers, monkeypatch):
    captured = _capture_complete(monkeypatch)
    h = auth_headers("aisha@student.edu")
    r = client.post(f"/api/students/{student_id}/interview",
                    json={"message": "", "turn": 1, "tutor": "vex"}, headers=h)
    assert r.status_code == 200 and r.json()["reply"]
    assert "Vex" in captured["system"]


# ------------------------------------------------------------------ TTS failure never breaks text chat

def test_tts_failure_does_not_break_text_chat(client, student_id, auth_headers, monkeypatch):
    import app.tts as tts_mod

    h = auth_headers("aisha@student.edu")

    def boom(*a, **k):
        raise RuntimeError("key invalid")

    monkeypatch.setattr(tts_mod, "synthesize", boom)
    tts = client.post(f"/api/students/{student_id}/interview/tts",
                      json={"tutor": "novas", "text": "hello"}, headers=h)
    assert tts.status_code == 503
    # text chat is unaffected
    assert _tutor(client, student_id, h).status_code == 200


# ------------------------------------------------------------------ keyless fallback stays functional

def test_tutor_reply_fallback_without_keys(monkeypatch):
    monkeypatch.setattr(genai, "OPENAI_KEY", None)
    monkeypatch.setattr(genai, "ANTHROPIC_KEY", None)
    monkeypatch.setattr(genai, "NIM_KEY", None)
    reply = genai.tutor_reply("How should I approach practicing SQL?",
                              "Studying at Aston University", "SQL", "Data Engineer")
    assert reply and "**" not in reply
    assert "SQL" in reply
    assert len(reply) < 800  # concise by default — no course dump


def test_nova_fallback_explains_docker_containers(monkeypatch):
    monkeypatch.setattr(genai, "OPENAI_KEY", None)
    monkeypatch.setattr(genai, "ANTHROPIC_KEY", None)
    monkeypatch.setattr(genai, "NIM_KEY", None)
    reply = genai.tutor_reply("Help me understand Docker containers.",
                              "Studying at Aston University", None,
                              "Junior AI Engineer", tutor_id="nova",
                              mode="chat", language="en")
    lower = reply.lower()
    assert "docker containers" in lower
    assert "lightweight" in lower and "isolated" in lower
    assert "virtual machine" in lower
    assert "20 minutes" not in lower


def test_axel_fallback_is_practical_for_same_docker_prompt(monkeypatch):
    monkeypatch.setattr(genai, "OPENAI_KEY", None)
    monkeypatch.setattr(genai, "ANTHROPIC_KEY", None)
    monkeypatch.setattr(genai, "NIM_KEY", None)
    reply = genai.tutor_reply("Help me understand Docker containers.",
                              "Studying at Aston University", None,
                              "Junior AI Engineer", tutor_id="axel",
                              mode="practice", language="en")
    lower = reply.lower()
    assert "docker run" in lower
    assert "docker build" in lower
    assert "send me what happened" in lower


def test_sage_fallback_is_analytical_and_vex_is_challenge(monkeypatch):
    monkeypatch.setattr(genai, "OPENAI_KEY", None)
    monkeypatch.setattr(genai, "ANTHROPIC_KEY", None)
    monkeypatch.setattr(genai, "NIM_KEY", None)
    sage = genai.tutor_reply("Help me understand Docker containers.",
                             "ctx", None, "Junior AI Engineer",
                             tutor_id="sage", mode="discuss", language="en")
    vex = genai.tutor_reply("Help me understand Docker containers.",
                            "ctx", None, "Junior AI Engineer",
                            tutor_id="vex", mode="interview", language="en")
    assert "tradeoff" in sage.lower()
    assert "define the difference" in vex.lower()
    assert sage != vex


def test_nova_and_axel_fallbacks_are_meaningfully_different(monkeypatch):
    monkeypatch.setattr(genai, "OPENAI_KEY", None)
    monkeypatch.setattr(genai, "ANTHROPIC_KEY", None)
    monkeypatch.setattr(genai, "NIM_KEY", None)
    prompt = "Help me understand Docker containers."
    nova = genai.tutor_reply(prompt, "ctx", None, "Junior AI Engineer",
                             tutor_id="nova", mode="chat", language="en")
    axel = genai.tutor_reply(prompt, "ctx", None, "Junior AI Engineer",
                             tutor_id="axel", mode="practice", language="en")
    assert "Think of" in nova
    assert "docker run" in axel
    assert "docker run" not in nova
    assert nova != axel


def test_visible_reply_cleanup_removes_prompt_scaffolding(monkeypatch):
    def fake_complete(system, user, fallback=None, **kw):
        return "\n".join([
            "[Nova's voice]",
            "Dashboard context: University: Aston University",
            "Extracted keywords: containers, docker, understand",
            "You asked about containers, docker, understand",
            "A Docker container is a lightweight isolated runtime for an app.",
        ])

    monkeypatch.setattr(genai, "complete", fake_complete)
    reply = genai.tutor_reply("Help me understand Docker containers.",
                              "Dashboard context: University: Aston University",
                              None, "Junior AI Engineer", tutor_id="nova",
                              mode="chat", language="en")
    assert "[Nova's voice]" not in reply
    assert "Dashboard context:" not in reply
    assert "Extracted keywords" not in reply
    assert "You asked about" not in reply
    assert "A Docker container" in reply


def test_tutor_route_still_works_keyless(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    r = _tutor(client, student_id, h, {"page": "dashboard"})
    assert r.status_code == 200
    assert r.json()["reply"]
