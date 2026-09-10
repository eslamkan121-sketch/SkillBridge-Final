"""Manual GenAI-provider smoke tests (NVIDIA runtime fix).

These drive the REAL tutor endpoint with the exact uncached persona prompts for
the NVIDIA integration fix, and verify: substantive answers, NO offline
fallback, NO career hijack, Vex staying in chat (not becoming an interviewer),
the provider status reporting a real success, and per-persona latency.

They auto-skip when no provider key is configured, so the normal suite stays
byte-for-byte deterministic and 100% offline.

To run: export a provider key in your shell FIRST (the suite never reads .env)
and then run only this file with output on to see the latency timings:

    pytest tests/test_provider_smoke.py -s

Keys: OPENAI_API_KEY / ANTHROPIC_API_KEY / NVIDIA_API_KEY (or NVAPI_KEY /
NIM_API_KEY). Fallback priority: openai -> anthropic -> nvidia. Set
NIM_TIMEOUT_SECONDS in the shell if the default 60s is not enough for a
reasoning-class Nemotron model.
"""

import time

import pytest

from app import genai

pytestmark = pytest.mark.skipif(
    not genai.genai_enabled(),
    reason=("No GenAI provider configured. Export OPENAI_API_KEY, "
            "ANTHROPIC_API_KEY or NVIDIA_API_KEY to run this manual smoke suite."),
)

_OFFLINE_MARKERS = (
    "no genai provider",
    "no provider is connected",
    "won't make something up",
    "won't fake it",
    "won't improvise",
    "i will not bluff",
    "limited fallback",
    "temporarily unavailable",
    "practical skill you use to solve real problems",
    "acceptance start",
    "go deeper",
    # reasoning / chain-of-thought artifacts must never reach students
    "analyze user input",
    "thinking process",
    "mental rehearsal",
    "identify key elements",
    "determine topic",
    "student context provided",
    "the student context shows",
    "student context:",
    "反思考",
    "nemotron",
)


def _ask(client, student_id, headers, message, tutor_id, language="en"):
    started = time.time()
    r = client.post(
        f"/api/students/{student_id}/tutor",
        json={
            "message": message, "skill_id": None, "page": "dashboard",
            "competency": None, "job_title": None, "job_url": None,
            "tutor_id": tutor_id, "mode": "chat", "language": language,
        },
        headers=headers,
    )
    latency_ms = int((time.time() - started) * 1000)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["mode"] == "chat"  # persona selection, never an interview session
    print(f"[latency] persona={tutor_id!r} elapsed_ms={latency_ms} provider="
          f"{genai.provider_status()['last_active_provider']}")
    return payload["reply"], latency_ms


def _assert_no_markers(reply, extra=()):
    low = reply.lower()
    for marker in tuple(_OFFLINE_MARKERS) + tuple(extra):
        assert marker.lower() not in low, f"unexpected marker present: {marker!r}"


def _assert_real_answer(reply, expected):
    low = reply.lower()
    assert len(reply) > 80, reply
    _assert_no_markers(reply)
    assert expected in low, f"substantive topic missing {expected!r} in: {reply}"
    st = genai.provider_status()
    assert st["last_success"] is True, st
    assert st["last_active_provider"] == st["preferred_provider"], st


# ------------------------------------------------------------------ Phase 1C live regressions

def test_provider_phase1c_nova_volcano_not_career_hijacked(client, student_id, auth_headers):
    reply, _lat = _ask(client, student_id, auth_headers("aisha@student.edu"),
                       "Explain how volcanoes erupt to me like I'm a beginner.", "nova")
    low = reply.lower()
    assert "volcano" in low or "volcan" in low
    _assert_no_markers(reply, ("docker", "junior ai engineer", "readiness", "50%"))


def test_provider_phase1c_axel_recursion_exercise_not_career_hijacked(client, student_id, auth_headers):
    reply, _lat = _ask(client, student_id, auth_headers("aisha@student.edu"),
                       "Explain recursion, then give me one small practical exercise.", "axel")
    low = reply.lower()
    assert "recursion" in low and ("exercise" in low or "practice" in low)
    _assert_no_markers(reply, ("docker", "junior ai engineer", "readiness", "50%"))


def test_provider_phase1c_sage_interest_growth_not_skill_gap(client, student_id, auth_headers):
    reply, _lat = _ask(client, student_id, auth_headers("aisha@student.edu"),
                       "Why can raising interest rates slow economic growth?", "sage")
    low = reply.lower()
    assert "interest" in low and ("growth" in low or "econom" in low)
    _assert_no_markers(reply, ("docker", "junior ai engineer", "machine learning", "skill gap"))


def test_provider_phase1c_vex_https_question_stays_https(client, student_id, auth_headers):
    reply, _lat = _ask(client, student_id, auth_headers("aisha@student.edu"),
                       "Explain how HTTPS works, then ask me one technical question.", "vex")
    low = reply.lower()
    assert "https" in low and ("tls" in low or "certificate" in low or "encryption" in low)
    assert "?" in reply
    _assert_no_markers(reply, ("docker", "machine learning", "deployment"))


def test_provider_phase1c_arabic_personal_context_no_provider_identity(client, student_id, auth_headers):
    reply, _lat = _ask(client, student_id, auth_headers("aisha@student.edu"),
                       "أنا بتعلم إيه دلوقتي حسب SkillBridge؟", "nova", language="ar")
    assert genai._has_arabic(reply)
    assert "Docker" in reply or "docker" in reply.lower()
    _assert_no_markers(reply, ("nvidia", "openai", "claude", "gpt", "أنا نيموترون", "انا نيموترون"))


def test_provider_nova_earthquake(client, student_id, auth_headers):
    """Nova, uncached topic, real provider: 'Explain how earthquakes happen...'"""
    reply, _lat = _ask(client, student_id, auth_headers("aisha@student.edu"),
                       "Explain how earthquakes happen to me like I'm a beginner.", "nova")
    _assert_real_answer(reply, "earthquake")


def test_provider_axel_refrigerator(client, student_id, auth_headers):
    """Axel: 'Explain how a refrigerator works and give me a practical example.'"""
    reply, _lat = _ask(client, student_id, auth_headers("aisha@student.edu"),
                       "Explain how a refrigerator works and give me a practical example.", "axel")
    _assert_real_answer(reply, "refrigerator")


def test_provider_sage_interest_rates(client, student_id, auth_headers):
    """Sage: 'Why do central banks raise interest rates when inflation is high?'"""
    reply, _lat = _ask(client, student_id, auth_headers("aisha@student.edu"),
                       "Why do central banks raise interest rates when inflation is high?", "sage")
    low = reply.lower()
    assert "inflation" in low, reply
    assert "interest rate" in low or "rates" in low, reply
    for marker in _OFFLINE_MARKERS:
        assert marker not in low, f"offline/career/interview marker present: {marker!r}"
    assert len(reply) > 80, reply
    assert genai.provider_status()["last_success"] is True


def test_provider_vex_dna_chat_not_interview(client, student_id, auth_headers):
    """Vex in CHAT: 'Explain DNA replication clearly, then test me with one question.'"""
    reply, _lat = _ask(client, student_id, auth_headers("aisha@student.edu"),
                       "Explain DNA replication clearly, then test me with one question.", "vex")
    low = reply.lower()
    assert "dna" in low and ("replicat" in low or "replication" in low), reply
    for marker in _OFFLINE_MARKERS:
        assert marker not in low, f"offline/career/interview marker present: {marker!r}"
    assert "?" in reply  # Vex keeps its style: one short knowledge-check question
    assert "go deeper" not in low  # but must NOT become the interview engine
    assert len(reply) > 80, reply
    st = genai.provider_status()
    assert st["last_success"] is True, st
    assert st["last_active_provider"] == st["preferred_provider"], st
