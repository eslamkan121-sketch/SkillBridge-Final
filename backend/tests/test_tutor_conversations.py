"""Step 4.5 — Separate tutor conversations, New Chat, chat TTS, assessment gate.

Covers: each tutor owning its own thread (storage + history filtering), legacy
pre-separation rows staying readable by any tutor, New Chat clearing ONLY the
current tutor's conversation (never another tutor's, never the preference /
mode / language), interview-mode messages being persisted under the tutor who
runs them, chat TTS sharing the ElevenLabs pipeline with the same integrity
lock and proper errors, and the Final Assessment gate reading readiness from
topic mastery + path progress — never from the Career Roadmap. Never calls a
paid API.
"""

import pytest

from app import genai, models
import app.jobs as jobs_mod
import app.tts as tts_mod


@pytest.fixture()
def docker_skill(db):
    return models.get_skill_by_name("Docker")


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    monkeypatch.setattr(jobs_mod, "_fetch_all", lambda *a, **k: [])
    jobs_mod.clear_job_cache()


def _set_pref(client, student_id, headers, body):
    return client.put(f"/api/students/{student_id}/tutor/preference",
                      json=body, headers=headers)


def _tutor(client, student_id, headers, body=None):
    return client.post(f"/api/students/{student_id}/tutor",
                       json={"message": "What should I do next?", **(body or {})},
                       headers=headers)


def _history(client, student_id, headers, tutor_id=None):
    url = f"/api/students/{student_id}/tutor"
    if tutor_id:
        url += f"?tutor_id={tutor_id}"
    return client.get(url, headers=headers).json()


# ------------------------------------------------------------------ each tutor owns its thread

def test_messages_are_stored_under_the_current_tutor(client, student_id, auth_headers, db):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "axel"})
    r = _tutor(client, student_id, h)
    assert r.status_code == 200 and r.json()["tutor_id"] == "axel"
    rows = db.execute("SELECT tutor_id, role FROM tutor_messages "
                      "WHERE student_id=? ORDER BY id", (student_id,)).fetchall()
    assert rows, "messages must be persisted"
    assert all(row["tutor_id"] == "axel" for row in rows)
    assert {row["role"] for row in rows} == {"user", "assistant"}


def test_history_is_scoped_per_tutor(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "sage"})
    _tutor(client, student_id, h)
    _set_pref(client, student_id, h, {"tutor_id": "axel"})
    _tutor(client, student_id, h)
    _tutor(client, student_id, h)

    sage = _history(client, student_id, h, "sage")
    axel = _history(client, student_id, h, "axel")
    nova = _history(client, student_id, h, "nova")
    vex = _history(client, student_id, h, "vex")

    assert len(sage) == 2 and all(m["tutor_id"] == "sage" for m in sage)
    assert len(axel) == 4 and all(m["tutor_id"] == "axel" for m in axel)
    assert nova == [] and vex == []


def test_legacy_rows_without_owner_stay_readable_by_any_tutor(client, student_id, auth_headers, db):
    h = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")["id"]
    models.add_tutor_message(student_id, None, python, "user", "pre-separation message")
    for tutor in ("nova", "axel", "sage", "vex"):
        history = _history(client, student_id, h, tutor)
        assert any(m["content"] == "pre-separation message" for m in history), tutor


def test_legacy_rows_are_cleared_by_new_chat(client, student_id, auth_headers, db):
    h = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")["id"]
    models.add_tutor_message(student_id, None, python, "user", "pre-separation message")
    r = client.request("DELETE", f"/api/students/{student_id}/tutor",
                       json={"tutor_id": "nova"}, headers=h)
    assert r.status_code == 200 and r.json()["cleared"] is True
    assert _history(client, student_id, h, "nova") == []


# ------------------------------------------------------------------ New Chat clears only the current tutor

def test_new_chat_keeps_other_tutors_conversations(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _tutor(client, student_id, h)
    _set_pref(client, student_id, h, {"tutor_id": "vex"})
    _tutor(client, student_id, h)
    _tutor(client, student_id, h)

    r = client.request("DELETE", f"/api/students/{student_id}/tutor",
                       json={"tutor_id": "nova"}, headers=h)
    assert r.status_code == 200
    assert _history(client, student_id, h, "nova") == []
    assert len(_history(client, student_id, h, "vex")) == 4
    # switching back to nova shows a fresh empty thread
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    npm = client.get(f"/api/students/{student_id}/tutor/preference", headers=h).json()
    assert npm["tutor_id"] == "nova"


def test_new_chat_uses_preferred_tutor_when_body_absent(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "sage"})
    _tutor(client, student_id, h)
    r = client.delete(f"/api/students/{student_id}/tutor", headers=h)
    assert r.status_code == 200 and r.json()["tutor_id"] == "sage"
    assert _history(client, student_id, h, "sage") == []


def test_new_chat_keeps_preference_mode_and_language(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "vex", "mode": "interview", "language": "ar"})
    _tutor(client, student_id, h, {"turn": 1})
    client.request("DELETE", f"/api/students/{student_id}/tutor", json={"tutor_id": "vex"}, headers=h)
    got = client.get(f"/api/students/{student_id}/tutor/preference", headers=h).json()
    assert got == {"tutor_id": "vex", "mode": "interview", "language": "ar"}


def test_new_chat_rejects_unknown_tutor(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    r = client.request("DELETE", f"/api/students/{student_id}/tutor",
                      json={"tutor_id": "sarah"}, headers=h)
    assert r.status_code == 400 and "tutor" in r.json()["detail"].lower()


def test_history_rejects_unknown_tutor(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    assert client.get(f"/api/students/{student_id}/tutor?tutor_id=vex2",
                      headers=h).status_code == 400


def test_history_and_new_chat_require_student_ownership(client, student_id):
    r = client.get(f"/api/students/{student_id}/tutor?tutor_id=nova")
    assert r.status_code == 401
    assert client.request("DELETE", f"/api/students/{student_id}/tutor",
                         json={"tutor_id": "nova"}).status_code == 401


def test_history_and_new_chat_block_non_owners(client, student_id, auth_headers):
    h = auth_headers("omar@student.edu")
    assert client.get(f"/api/students/{student_id}/tutor?tutor_id=nova",
                      headers=h).status_code == 403
    assert client.request("DELETE", f"/api/students/{student_id}/tutor",
                         json={"tutor_id": "nova"}, headers=h).status_code == 403
    h2 = auth_headers("hr@northstar.com")
    assert client.get(f"/api/students/{student_id}/tutor?tutor_id=nova",
                      headers=h2).status_code == 403


# ------------------------------------------------------------------ interview-mode messages stay with the tutor

def test_interview_messages_persist_under_the_running_tutor(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    # Interview is opt-in per request: the stored preference keeps the tutor, and
    # the message must carry an explicit "interview" mode to enter that engine.
    _set_pref(client, student_id, h, {"tutor_id": "vex"})
    r = _tutor(client, student_id, h, {"turn": 1, "mode": "interview"})
    assert r.status_code == 200 and r.json()["mode"] == "interview"
    vex = _history(client, student_id, h, "vex")
    assert len(vex) == 2
    assert all(m["tutor_id"] == "vex" for m in vex)
    assert _history(client, student_id, h, "nova") == []


# ------------------------------------------------------------------ chat TTS (same pipeline, same lock)

def _fake_audio(*a, **k):
    return b"ID3\x00\x00FAKEAUDIO"


def test_tutor_tts_returns_audio(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    monkeypatch.setattr(tts_mod, "synthesize", _fake_audio)
    r = client.post(f"/api/students/{student_id}/tutor/tts",
                    json={"tutor": "nova", "text": "Hello, let's unpack Docker."}, headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/mpeg")
    assert b"FAKEAUDIO" in r.content


def test_tutor_tts_maps_all_four_tutors_to_their_own_voice(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200
        content = b"ID3\x00\x00MP3"
        headers = {"content-type": "audio/mpeg"}

        def raise_for_status(self):
            return None

    def fake_post(url, headers=None, json=None, timeout=None, verify=None):
        calls.append((url, headers, json, timeout, verify))
        return FakeResponse()

    voices = {
        "nova": "voice-nova",
        "axel": "voice-axel",
        "sage": "voice-sage",
        "vex": "voice-vex",
    }
    monkeypatch.setattr(tts_mod, "ELEVENLABS_API_KEY", "loaded-test-key")
    monkeypatch.setattr(tts_mod, "TUTOR_VOICES", voices.copy())
    monkeypatch.setattr(tts_mod.httpx, "post", fake_post)
    tts_mod._CACHE.clear()

    for tutor, voice_id in voices.items():
        audio = tts_mod.synthesize(tutor, f"hello from {tutor}")
        assert audio == b"ID3\x00\x00MP3"
        assert calls[-1][0].endswith(f"/{voice_id}")
        assert calls[-1][1]["xi-api-key"] == "loaded-test-key"
        assert calls[-1][4] is not False


def test_interview_voice_status_hides_secret_voice_ids(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    monkeypatch.setattr(tts_mod, "ELEVENLABS_API_KEY", "loaded-test-key")
    monkeypatch.setattr(tts_mod, "TUTOR_VOICES", {
        "nova": "voice-nova", "axel": "voice-axel", "sage": "voice-sage", "vex": "voice-vex",
    })
    r = client.get(f"/api/students/{student_id}/interview/voice", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "available": True,
        "api_key_loaded": True,
        "tutor_voices_loaded": {"nova": True, "axel": True, "sage": True, "vex": True},
        "tts_configured": True,
    }
    assert "voice-nova" not in r.text and "loaded-test-key" not in r.text


def test_tts_missing_config_status_is_safe(monkeypatch):
    monkeypatch.setattr(tts_mod, "ELEVENLABS_API_KEY", "")
    monkeypatch.setattr(tts_mod, "TUTOR_VOICES", {
        "nova": "", "axel": "voice-axel", "sage": "", "vex": "voice-vex",
    })
    assert tts_mod.config_status() == {
        "available": False,
        "api_key_loaded": False,
        "tutor_voices_loaded": {"nova": False, "axel": True, "sage": False, "vex": True},
        "tts_configured": False,
    }


def test_tutor_tts_rejects_unknown_tutor(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    r = client.post(f"/api/students/{student_id}/tutor/tts",
                    json={"tutor": "not-a-tutor", "text": "hi"}, headers=h)
    assert r.status_code == 400


def test_tutor_tts_503_on_pipeline_failure(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")

    def boom(*a, **k):
        raise RuntimeError("quota exhausted")

    monkeypatch.setattr(tts_mod, "synthesize", boom)
    r = client.post(f"/api/students/{student_id}/tutor/tts",
                    json={"tutor": "sage", "text": "hi"}, headers=h)
    assert r.status_code == 503
    # audio failure never breaks the next text reply
    assert _tutor(client, student_id, h).status_code == 200


def test_tutor_tts_rejects_empty_or_non_audio_upstream_response(monkeypatch):
    class FakeResponse:
        status_code = 200
        content = b""
        headers = {"content-type": "audio/mpeg"}

        def raise_for_status(self):
            return None

    monkeypatch.setattr(tts_mod, "ELEVENLABS_API_KEY", "loaded-test-key")
    monkeypatch.setattr(tts_mod, "TUTOR_VOICES", {
        "nova": "voice-nova", "axel": "voice-axel", "sage": "voice-sage", "vex": "voice-vex",
    })
    monkeypatch.setattr(tts_mod.httpx, "post", lambda *a, **k: FakeResponse())
    tts_mod._CACHE.clear()
    with pytest.raises(RuntimeError, match="empty audio"):
        tts_mod.synthesize("nova", "hello")

    FakeResponse.content = b'{"error":"not audio"}'
    FakeResponse.headers = {"content-type": "application/json"}
    with pytest.raises(RuntimeError, match="non-audio"):
        tts_mod.synthesize("nova", "hello again")


def test_tutor_tts_converts_httpx_connection_errors_to_safe_503(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    monkeypatch.setattr(tts_mod, "ELEVENLABS_API_KEY", "loaded-test-key")
    monkeypatch.setattr(tts_mod, "TUTOR_VOICES", {
        "nova": "voice-nova", "axel": "voice-axel", "sage": "voice-sage", "vex": "voice-vex",
    })
    monkeypatch.setattr(tts_mod.httpx, "post",
                        lambda *a, **k: (_ for _ in ()).throw(tts_mod.httpx.ConnectError("TLS failed")))
    tts_mod._CACHE.clear()
    r = client.post(f"/api/students/{student_id}/tutor/tts",
                    json={"tutor": "nova", "text": "hello"}, headers=h)
    assert r.status_code == 503
    assert "ConnectError" in r.json()["detail"]
    assert "loaded-test-key" not in r.text and "voice-nova" not in r.text


def test_tutor_tts_locked_during_active_assessment(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")["id"]
    client.post(f"/api/students/{student_id}/assessments/session",
                json={"skill_id": python,
                "webcam_gate": {"passed": True, "checked_at": "2026-09-07T05:00:00Z", "meta": {"person_status": "one"}}}, headers=h)
    tts = client.post(f"/api/students/{student_id}/tutor/tts",
                      json={"tutor": "nova", "text": "hello"}, headers=h)
    assert tts.status_code == 423 and "integrity" in tts.json()["detail"].lower()
    client.delete(f"/api/students/{student_id}/assessments/session", headers=h)
    client.post(f"/api/students/{student_id}/tutor/tts",
                json={"tutor": "nova", "text": "hello"}, headers=h).status_code in (200, 503)


# ------------------------------------------------------------------ assessment gate vs. career roadmap

def test_final_assessment_status_never_exposes_roadmap(client, docker_skill, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    body = client.get(f"/api/students/{student_id}/learning/{sk}/final-assessment/status",
                      headers=h).json()
    assert body["has_blueprint"] is True
    assert "readiness" in body and "missing" in body["readiness"]
    # the gate is the readiness payload — no roadmap steps/done fields anywhere
    assert "roadmap" not in body
    assert "steps" not in body and "done" not in body


def test_readiness_is_achievable_without_any_personalized_path(client, docker_skill, student_id, auth_headers):
    """Mastering every diagnostic topic unlocks the gate even with zero path rows —
    proving the gate never depends on the Career Roadmap."""
    h = auth_headers("aisha@student.edu")
    sk = docker_skill["id"]
    gen = client.post(f"/api/students/{student_id}/learning/{sk}/diagnostic/generate",
                      json={}, headers=h).json()
    answers = [q["correct_answer"] for q in gen["questions"]]
    client.post(f"/api/students/{student_id}/learning/{sk}/diagnostic/submit",
                json={"diagnostic_id": gen["diagnostic_id"], "answers": answers}, headers=h)
    status = client.get(f"/api/students/{student_id}/learning/{sk}/final-assessment/status",
                        headers=h).json()
    assert status["readiness"]["missing"] == []
    assert status["readiness"]["ready"] is True
    assert models.get_personalized_path(student_id, sk) is None


def test_readiness_counts_only_topic_mastery_and_path_progress():
    """Unit-level: the readiness function takes no roadmap input at all."""
    from app import coverage as cov
    req = cov.required_slugs("Docker", "Intermediate")
    topics = [{"competency": c, "status": "mastered"} for c in req]
    r = cov.final_assessment_ready("Docker", "Intermediate", topics, [], [], [])
    assert r["ready"] is True and r["missing"] == []
    r2 = cov.final_assessment_ready("Docker", "Intermediate", [], [], [], [])
    assert r2["ready"] is False
