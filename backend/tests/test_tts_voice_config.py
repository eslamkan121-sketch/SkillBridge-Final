"""Mentor voice configuration + TTS reliability (Phase 4C.1).

Covers, WITHOUT calling ElevenLabs (a monkeypatched httpx.post substitutes the
provider):

- every mentor resolves its OWN voice configuration entry,
- the public status payloads are safe booleans only (never IDs or keys),
- unknown tutors and unconfigured mentors raise a SPECIFIC error that names
  the affected mentor while leaving the other three untouched,
- one synthesis per (tutor, text) with in-process caching (no duplicate work),
- a configured mentor still synthesizes even when a SIBLING mentor is missing,
  so one unavailable voice can never break the others.
"""

import pytest

from app import tts


def _patch_voices(monkeypatch, voices):
    monkeypatch.setattr(tts, "TUTOR_VOICES", voices)
    monkeypatch.setattr(tts, "ELEVENLABS_API_KEY", "test-key")


def _patch_httpx(monkeypatch, audio=b"ID3testaudio"):
    def fake_post(url, **kw):
        assert "api.elevenlabs.io" in url
        class _Resp:
            status_code = 200
            headers = {"content-type": "audio/mpeg"}
            content = audio
        return _Resp()

    monkeypatch.setattr(tts.httpx, "post", fake_post)
    return audio


def test_all_four_mentors_have_a_voice_config_entry(monkeypatch):
    _patch_voices(monkeypatch, {
        "nova": "voice-nova", "axel": "voice-axel",
        "sage": "voice-sage", "vex": "voice-vex",
    })
    status = tts.tutor_voice_status()
    assert set(status) == {"nova", "axel", "sage", "vex"}
    assert all(status[m] for m in ("nova", "axel", "sage", "vex"))


def test_config_status_exposes_booleans_only(monkeypatch):
    _patch_voices(monkeypatch, {
        "nova": "voice-nova", "axel": "voice-axel",
        "sage": "voice-sage", "vex": "voice-vex",
    })
    payload = tts.config_status()
    assert payload["available"] is True
    assert payload["api_key_loaded"] is True
    assert payload["tts_configured"] is True
    assert set(payload["tutor_voices_loaded"]) == {"nova", "axel", "sage", "vex"}
    # Booleans only: voice IDs and the API key must never leak into the payload.
    assert all(isinstance(v, bool) for v in payload["tutor_voices_loaded"].values())
    assert "voice-nova" not in str(payload)
    assert "test-key" not in str(payload)


def test_unknown_tutor_raises_specific_error(monkeypatch):
    _patch_voices(monkeypatch, {"nova": "voice-nova"})
    with pytest.raises(ValueError) as exc:
        tts.synthesize("siri", "hello")
    assert "siri" in str(exc.value)


def test_unconfigured_mentor_reports_the_specific_mentor(monkeypatch):
    # sage has a voice entry but NO id -> only sage must fail, and the error
    # must name sage so operators can see exactly which mentor is broken.
    _patch_voices(monkeypatch, {
        "nova": "voice-nova", "axel": "voice-axel",
        "sage": "", "vex": "voice-vex",
    })
    with pytest.raises(RuntimeError) as exc:
        tts.synthesize("sage", "مرحبا")
    assert "sage" in str(exc.value)


def test_one_missing_mentor_does_not_break_the_other_three(monkeypatch):
    _patch_httpx(monkeypatch)
    _patch_voices(monkeypatch, {
        "nova": "voice-nova", "axel": "voice-axel",
        "sage": "", "vex": "voice-vex",
    })
    assert tts.tutor_voice_status()["sage"] is False
    for mentor in ("nova", "axel", "vex"):
        audio = tts.synthesize(mentor, f"hello from {mentor}")
        assert audio == b"ID3testaudio"


def test_synthesis_is_cached_per_tutor_text(monkeypatch):
    _patch_httpx(monkeypatch)
    fake_post = tts.httpx.post
    calls = []

    def counting_post(url, **kw):
        calls.append(url)
        return fake_post(url, **kw)

    monkeypatch.setattr(tts.httpx, "post", counting_post)
    _patch_voices(monkeypatch, {"nova": "voice-nova"})

    tts._CACHE.clear()
    first = tts.synthesize("nova", "repeat me")
    second = tts.synthesize("nova", "repeat me")
    assert first == second
    assert len(calls) == 1, "second identical request must hit the cache (one TTS per unique line)"


def test_empty_text_is_rejected_without_a_provider_call(monkeypatch):
    _patch_voices(monkeypatch, {"nova": "voice-nova"})
    with pytest.raises(ValueError):
        tts.synthesize("nova", "   ")