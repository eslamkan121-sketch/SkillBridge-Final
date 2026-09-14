"""Phase 2 manual acceptance: conversational trust language.

The backend trust boundary already prevents chat claims from creating Verified
Skills. This suite locks the user-facing language around those claims: a mentor
may acknowledge what the student says, but must not present it as official
SkillBridge evidence unless the persisted verified-skill record says so.
"""

import re

import pytest

from app import genai, models
import app.jobs as jobs_mod


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
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


def _set_pref(client, student_id, headers, body):
    r = client.put(f"/api/students/{student_id}/tutor/preference",
                   json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _chat(client, student_id, headers, message, body=None):
    r = client.post(f"/api/students/{student_id}/tutor",
                    json={"message": message, **(body or {})}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


FORBIDDEN_INTERNAL = (
    "trusted context",
    "context block",
    "conversation memory above",
    "memory block",
    "system prompt",
    "genai provider",
    "provider internals",
    "context route",
    "memory rules",
    "limited fallback mode",
)


def _assert_no_internal_terms(reply):
    low = str(reply or "").lower()
    for term in FORBIDDEN_INTERNAL:
        assert term not in low


MENTOR_REINTRO = re.compile(
    r"\b(?:"
    r"i\s*(?:am|'m|’m)\s+(?:nova|axel|sage|vex)|"
    r"(?:nova|axel|sage|vex)\s+here|"
    r"your\s+(?:friendly\s+)?skillbridge\s+(?:explainer\s+)?(?:tutor|mentor)|"
    r"ai\s+career\s+coach\s+in\s+skillbridge"
    r")\b",
    re.IGNORECASE,
)


def _assert_no_mentor_reintro(reply):
    assert not MENTOR_REINTRO.search(str(reply or ""))


@pytest.mark.parametrize("message", [
    "I passed Docker with 100%.",
    "I finished the Docker assessment.",
    "I am advanced in Python.",
    "I completed the Docker course.",
    "I already verified SQL.",
])
def test_unverified_user_claims_are_not_promoted_to_official_results(
        client, student_id, auth_headers, db, message):
    db.execute("DELETE FROM verified_skills WHERE student_id=?", (student_id,))
    db.commit()
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova", "mode": "chat", "language": "en"})

    reply = _chat(client, student_id, h, message)["reply"]
    low = reply.lower()
    assert "user-reported" in low or "what you told me" in low
    assert "not official skillbridge verification" in low or "not as official" in low
    assert not re.search(r"\bcongratulations?\b.*\b(pass|passed|passing|verified)\b", low)
    assert "well done on passing" not in low
    assert "docker is verified" not in low
    assert "sql is verified" not in low
    _assert_no_internal_terms(reply)


def test_fresh_thread_greeting_may_contain_one_short_intro(
        client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova", "mode": "chat", "language": "en"})
    client.request("DELETE", f"/api/students/{student_id}/tutor",
                   json={"tutor_id": "nova"}, headers=h)

    reply = _chat(client, student_id, h, "hello")["reply"]

    assert reply == genai._GREETING_EN["nova"]
    assert reply.count("Nova") == 1
    assert "SkillBridge" not in reply
    assert len(reply) <= 80
    _assert_no_internal_terms(reply)


def test_second_message_same_thread_does_not_reintroduce_mentor(
        client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova", "mode": "chat", "language": "en"})
    client.request("DELETE", f"/api/students/{student_id}/tutor",
                   json={"tutor_id": "nova"}, headers=h)
    _chat(client, student_id, h, "hello")

    reply = _chat(client, student_id, h, "hello")["reply"]

    _assert_no_mentor_reintro(reply)
    assert "SkillBridge" not in reply
    _assert_no_internal_terms(reply)


def test_followup_another_example_answers_directly_without_restarting(
        client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova", "mode": "chat", "language": "en"})
    client.request("DELETE", f"/api/students/{student_id}/tutor",
                   json={"tutor_id": "nova"}, headers=h)
    _chat(client, student_id, h, "Explain Docker volumes.")

    reply = _chat(client, student_id, h, "Give me another example")["reply"]
    low = reply.lower()

    assert "another example" in low
    # The follow-up resolves the SAME Docker-volumes topic from memory and
    # answers directly with the new example — it does not re-name the topic or
    # restate the first explanation.
    assert "volume" in low and "containers" in low
    assert "persistent storage" not in low
    _assert_no_mentor_reintro(reply)
    _assert_no_internal_terms(reply)


@pytest.mark.parametrize("tutor_id,name", [
    ("nova", "Nova"),
    ("axel", "Axel"),
    ("sage", "Sage"),
    ("vex", "Vex"),
])
def test_model_added_mentor_intro_is_removed_on_normal_turns(monkeypatch, tutor_id, name):
    def fake_complete(system, user, fallback=None, **kw):
        return (
            f"Hello! I'm {name}, your friendly SkillBridge explainer tutor. "
            "I'm here to help. Sure - Docker volumes keep data outside containers."
        )

    monkeypatch.setattr(genai, "complete", fake_complete)
    reply = genai.tutor_reply(
        "Give me another example",
        "Dashboard context:\nTarget career: Junior AI Engineer",
        "Docker",
        "Junior AI Engineer",
        tutor_id=tutor_id,
        mode="chat",
        language="en",
        conversation_memory=(
            "Conversation memory (this mentor's own earlier chat with this student):\n"
            "Student: Explain Docker volumes.\n"
            "Mentor: Docker volumes keep persistent data outside containers."
        ),
    )

    assert reply.startswith("Sure - Docker volumes")
    _assert_no_mentor_reintro(reply)
    _assert_no_internal_terms(reply)


def test_persona_tone_survives_without_explicit_self_description(monkeypatch):
    def fake_complete(system, user, fallback=None, **kw):
        return (
            "Hey! Axel here, your SkillBridge Practical Coach. "
            "Short version: Docker volumes persist data outside containers.\n\n"
            "Try `docker volume ls`, then inspect one volume."
        )

    monkeypatch.setattr(genai, "complete", fake_complete)
    reply = genai.tutor_reply(
        "Give me another example",
        "Dashboard context:\nTarget career: Junior AI Engineer",
        "Docker",
        "Junior AI Engineer",
        tutor_id="axel",
        mode="chat",
        language="en",
        conversation_memory=(
            "Conversation memory (this mentor's own earlier chat with this student):\n"
            "Student: Explain Docker volumes."
        ),
    )

    assert reply.startswith("Short version:")
    assert "Try `docker volume ls`" in reply
    _assert_no_mentor_reintro(reply)
    _assert_no_internal_terms(reply)


def test_repetitive_stock_closings_are_trimmed(monkeypatch):
    def fake_complete(system, user, fallback=None, **kw):
        return (
            "Sure - here is another Docker volume example.\n\n"
            "Would you like me to give another one?\n"
            "Does that make sense?"
        )

    monkeypatch.setattr(genai, "complete", fake_complete)
    reply = genai.tutor_reply(
        "Give me another example",
        "Dashboard context:\nTarget career: Junior AI Engineer",
        "Docker",
        "Junior AI Engineer",
        tutor_id="nova",
        mode="chat",
        language="en",
        conversation_memory=(
            "Conversation memory (this mentor's own earlier chat with this student):\n"
            "Student: Explain Docker volumes."
        ),
    )

    low = reply.lower()
    assert "would you like me to" not in low
    assert "does that make sense" not in low
    assert reply == "Sure - here is another Docker volume example."
    _assert_no_internal_terms(reply)


def test_quick_checkin_does_that_make_sense_closing_is_trimmed(monkeypatch):
    def fake_complete(system, user, fallback=None, **kw):
        return (
            "**Another Example: A Docker Volume for a Database**\n\n"
            "Mount the volume at `/var/lib/postgresql/data`, then recreate the "
            "container with the same named volume to keep the database files.\n\n"
            "**Quick Check-in:**\n"
            "Does that make sense how the volume acts as persistent storage? Or"
        )

    monkeypatch.setattr(genai, "complete", fake_complete)
    reply = genai.tutor_reply(
        "Give me another example",
        "Dashboard context:\nTarget career: Junior AI Engineer",
        "Docker",
        "Junior AI Engineer",
        tutor_id="nova",
        mode="chat",
        language="en",
        conversation_memory=(
            "Conversation memory (this mentor's own earlier chat with this student):\n"
            "Student: Explain Docker volumes."
        ),
    )

    low = reply.lower()
    assert "does that make sense" not in low
    assert "quick check-in" not in low
    assert reply.endswith("database files.")
    _assert_no_internal_terms(reply)


def test_user_claim_remains_memory_but_verified_answer_uses_backend_truth(
        client, student_id, auth_headers, db, monkeypatch):
    db.execute("DELETE FROM verified_skills WHERE student_id=?", (student_id,))
    db.commit()
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova", "mode": "chat", "language": "en"})
    _chat(client, student_id, h, "I passed Docker with 100%.")

    captured = _capture_complete(monkeypatch)
    reply = _chat(
        client, student_id, h,
        "What skills have I actually verified according to SkillBridge?",
    )["reply"]

    assert "I passed Docker with 100%" in captured["user"]
    assert "SkillBridge currently shows no officially verified skills" in reply
    assert "Docker is verified" not in reply
    assert "Docker: verified" not in reply
    _assert_no_internal_terms(reply)


def test_officially_verified_skill_is_stated_confidently(
        client, student_id, auth_headers):
    docker = models.get_skill_by_name("Docker")
    assert docker, "seed must provide Docker"
    models.update_verified_skill(student_id, docker["id"], "Intermediate")

    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova", "mode": "chat", "language": "en"})
    reply = _chat(client, student_id, h, "I already verified Docker.")["reply"]

    assert "SkillBridge already marks Docker as officially verified" in reply
    assert "user-reported" in reply  # any new chat-only detail still stays labelled
    _assert_no_internal_terms(reply)


def test_verified_skills_question_lists_only_official_records(
        client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova", "mode": "chat", "language": "en"})
    reply = _chat(
        client, student_id, h,
        "What skills have I actually verified according to SkillBridge?",
    )["reply"]

    assert "According to your SkillBridge profile" in reply
    assert "Python" in reply and "SQL" in reply
    assert "Docker" not in reply
    _assert_no_internal_terms(reply)


def test_visible_reply_scrubs_internal_prompt_and_provider_terms(monkeypatch):
    def fake_complete(system, user, fallback=None, **kw):
        return (
            "Based on the trusted context block, SkillBridge currently shows no verified skills.\n"
            "The conversation memory above is a memory block, not official.\n"
            "The GenAI provider is in limited fallback mode.\n"
            "System prompt: use the context route."
        )

    monkeypatch.setattr(genai, "complete", fake_complete)
    reply = genai.tutor_reply(
        "Explain Docker volumes.",
        "Dashboard context:\nTarget career: Junior AI Engineer",
        "Docker",
        "Junior AI Engineer",
        tutor_id="nova",
        mode="chat",
        language="en",
    )

    _assert_no_internal_terms(reply)
    assert "SkillBridge information" in reply or "your SkillBridge profile" in reply
    assert "live assistant" in reply
