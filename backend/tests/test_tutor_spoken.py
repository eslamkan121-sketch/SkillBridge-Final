"""Live-Mode spoken directive (Phase 4B.1 stability fix) — additive + opt-in.

The frontend Live voice surface sends ``spoken=true`` so replies are concise and
natural when read aloud. Normal chat turns never send it: the accepted persona
behavior in the standard chat path is byte-for-byte unchanged. These tests
prove:

- the directive is appended to the system prompt ONLY when spoken=true,
- the plain chat path carries NO spoken wording,
- the debug system-prompt endpoint reflects the flag,
- the /tutor route accepts the additive boolean and round-trips it.

Never calls a paid API.
"""

import os

import pytest

from app import genai, models
from app import copilot
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


def test_spoken_directive_only_when_requested(monkeypatch):
    captured = _capture_complete(monkeypatch)

    genai.tutor_reply(
        "What can you help me with?",
        tutor_id="nova",
        language="en",
        spoken=True,
    )
    assert "read aloud by a text-to-speech voice" in captured["system"]
    assert "1-3 short sentences" in captured["system"]
    assert "answer the requested question directly and first" in captured["system"]


def test_spoken_rule_allows_fuller_answer_on_explicit_request(monkeypatch):
    captured = _capture_complete(monkeypatch)

    genai.tutor_reply(
        "Please explain Docker step by step",
        tutor_id="nova",
        language="en",
        spoken=True,
    )
    # Simple questions stay at 1-3 sentences, but an EXPLICIT request for a
    # detailed / step-by-step explanation may get a fuller spoken answer —
    # the rule must never force arbitrary truncation.
    assert "fuller spoken answer is fine" in captured["system"]
    assert "do not pad it" in captured["system"]


def test_plain_chat_has_no_spoken_wording(monkeypatch):
    captured = _capture_complete(monkeypatch)

    genai.tutor_reply(
        "What's your name?",
        tutor_id="nova",
        language="en",
    )
    assert "read aloud by a text-to-speech voice" not in captured["system"]
    assert "1-3 short sentences" not in captured["system"]
    assert "fuller spoken answer is fine" not in captured["system"]


@pytest.mark.parametrize("tutor_id", ["nova", "axel", "sage", "vex"])
def test_spoken_directive_for_every_mentor(monkeypatch, tutor_id):
    captured = _capture_complete(monkeypatch)

    genai.tutor_reply(
        "What can you help me with?",
        tutor_id=tutor_id,
        language="en",
        spoken=True,
    )
    assert "read aloud by a text-to-speech voice" in captured["system"]


def test_spoken_turn_persists_reply(client, auth_headers, student_id, monkeypatch):
    _capture_complete(monkeypatch)
    cid = client.post(
        f"/api/students/{student_id}/tutor/conversations",
        headers=auth_headers("aisha@student.edu"),
        json={"tutor_id": "vex", "title": "spoken-mode"},
    ).json()["conversation"]["id"]

    res = client.post(
        f"/api/students/{student_id}/tutor",
        headers=auth_headers("aisha@student.edu"),
        json={
            "message": "Explain Docker volumes",
            "page": "dashboard",
            "tutor_id": "vex",
            "mode": "chat",
            "language": "en",
            "conversation_id": cid,
            "spoken": True,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["tutor_id"] == "vex"
    assert body["conversation_id"] == cid
    assert isinstance(body["reply"], str) and body["reply"].strip()

    rows = models.list_tutor_messages(student_id, tutor_id="vex", conversation_id=cid)
    assert any(r.get("role") == "assistant" and str(r.get("content") or "").strip()
               for r in rows)


def test_debug_system_prompt_reflects_spoken(client, monkeypatch):
    monkeypatch.setenv("SKILLBRIDGE_ENABLE_DEBUG", "1")
    res = client.get(
        "/api/debug/tutor-system",
        params={"message": "What's your name?", "tutor_id": "sage",
                "mode": "chat", "language": "en", "spoken": "true"},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["spoken"] is True
    assert "read aloud by a text-to-speech voice" in payload["system"]
    assert payload["mirror_rule"]

    res2 = client.get(
        "/api/debug/tutor-system",
        params={"message": "What's your name?", "tutor_id": "sage",
                "mode": "chat", "language": "en"},
    )
    payload2 = res2.json()
    assert payload2["spoken"] is False
    assert "read aloud by a text-to-speech voice" not in payload2["system"]


# ---------------------------------------------------------------------------
# Phase 4C.1 (r2, latency return): LIVE turn budget, fast-model override, and
# provider-free spoken identity. All deterministic / monkeypatched — never a
# paid API.

@pytest.mark.parametrize("tutor_id,expected_key", [
    ("nova", "nova"), ("axel", "axel"), ("sage", "sage"), ("vex", "vex"),
])
def test_spoken_identity_is_short_and_provider_free(monkeypatch, tutor_id, expected_key):
    captured = _capture_complete(monkeypatch)

    out = genai.tutor_reply("What's your name?", tutor_id=tutor_id,
                            language="en", spoken=True)
    assert not captured  # provider never consulted: deterministic, instant
    assert out == genai._SPOKEN_IDENTITY_EN[expected_key]
    assert len(out) < 120


@pytest.mark.parametrize("tutor_id,expected_key", [
    ("nova", "nova"), ("axel", "axel"), ("sage", "sage"), ("vex", "vex"),
])
def test_spoken_identity_arabic_short(monkeypatch, tutor_id, expected_key):
    captured = _capture_complete(monkeypatch)

    out = genai.tutor_reply("اسمك ايه؟", tutor_id=tutor_id, language="ar",
                            spoken=True)
    assert not captured
    assert out == genai._SPOKEN_IDENTITY_AR[expected_key]


def test_spoken_identity_accepts_variants(monkeypatch):
    for q in ("Who are you?", "Tell me about yourself", "your name?",
              "مين انت", "قولي اسمك"):
        captured = _capture_complete(monkeypatch)
        out = genai.tutor_reply(q, tutor_id="nova", language="en", spoken=True)
        assert not captured
        assert out == genai._SPOKEN_IDENTITY_EN["nova"]


def test_chat_identity_keeps_full_profile(monkeypatch):
    _capture_complete(monkeypatch)
    out = genai.tutor_reply("What's your name?", tutor_id="sage", language="en")
    assert out == genai._identity_fallback("sage", "en")
    assert "I'm Sage, your AI career coach in SkillBridge." in out


def test_spoken_simple_turn_uses_small_budget_and_live_timeout(monkeypatch):
    captured = {}

    def fake(system, user, fallback=None, max_tokens=None, timeout=None,
             model=None, **kw):
        captured["max_tokens"] = max_tokens
        captured["timeout"] = timeout
        captured["model"] = model
        return fallback

    monkeypatch.setattr(genai, "complete", fake)
    genai.tutor_reply("Explain Docker volumes", tutor_id="nova",
                      language="en", spoken=True)
    assert captured["max_tokens"] == genai._SPOKEN_MAX_TOKENS
    assert captured["timeout"] == genai._SPOKEN_TIMEOUT_SECONDS
    assert captured["model"] is None  # LIVE_NIM_MODEL unset by default


def test_spoken_step_by_step_keeps_full_budget(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        genai, "complete",
        lambda system, user, fallback=None, max_tokens=None, timeout=None,
               model=None, **kw: captured.update(max_tokens=max_tokens,
                                                 timeout=timeout, model=model)
        or fallback,
    )
    genai.tutor_reply("Explain Docker step by step", tutor_id="nova",
                      language="en", spoken=True)
    assert captured["max_tokens"] is None  # explicit fuller answer allowed
    assert captured["timeout"] == genai._SPOKEN_TIMEOUT_SECONDS


def test_spoken_uses_live_fast_model_when_configured(monkeypatch):
    monkeypatch.setenv("LIVE_NIM_MODEL", "google/gemma-3-4b-it")
    captured = {}
    monkeypatch.setattr(
        genai, "complete",
        lambda system, user, fallback=None, max_tokens=None, timeout=None,
               model=None, **kw: captured.update(model=model) or fallback,
    )
    genai.tutor_reply("Explain Docker volumes", tutor_id="nova",
                      language="en", spoken=True)
    assert captured["model"] == "google/gemma-3-4b-it"


def test_plain_chat_never_uses_live_budget_or_model(monkeypatch):
    monkeypatch.setenv("LIVE_NIM_MODEL", "google/gemma-3-4b-it")
    captured = {}
    monkeypatch.setattr(
        genai, "complete",
        lambda system, user, fallback=None, max_tokens=None, timeout=None,
               model=None, **kw: captured.update(max_tokens=max_tokens,
                                                 timeout=timeout, model=model)
        or fallback,
    )
    genai.tutor_reply("Explain Docker volumes", tutor_id="nova", language="en")
    assert captured["max_tokens"] is None
    assert captured["timeout"] is None
    assert captured["model"] is None


def test_live_fast_model_falls_back_to_main_model(monkeypatch):
    calls = []

    def fake_nim(system, user, retries=1, max_tokens=1024, timeout=None,
                 model=None):
        calls.append((max_tokens, model))
        if model:
            raise RuntimeError("fast model failed")
        return "ok main model"

    monkeypatch.setattr(genai, "NIM_KEY", "test-key")
    monkeypatch.setattr(genai, "_call_nim", fake_nim)
    out = genai.complete("s", "u", max_tokens=200, timeout=30, model="fast")
    assert out == "ok main model"
    assert len(calls) == 2
    assert calls[0] == (200, "fast")
    assert calls[1] == (200, None)  # fallback uses the configured NIM_MODEL


def test_live_fast_model_value_never_hardcoded(monkeypatch):
    assert genai._live_fast_model() is None  # unset -> default model
    monkeypatch.setenv("LIVE_NIM_MODEL", "  ")
    assert genai._live_fast_model() is None  # blank -> default model
    monkeypatch.delenv("LIVE_NIM_MODEL", raising=False)
    assert genai._live_fast_model() is None