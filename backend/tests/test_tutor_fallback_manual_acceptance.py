"""Manual-acceptance regressions — target-role context gating in the tutor.

Reproduces the two October 2026 live Nova failures and locks the fixes:

  1. "Explain Docker volumes in a simple way." leaked the student's target role
     ("Clinical Research Assistant" came from the live student state, not from
     anything in the question) because the deterministic fallback built a career
     template for a GENERAL topic. GROUNDED topics must render role-free; a
     career-linked question is the ONLY case a fallback reply may name the role.
  2. "Give me another example of what you just explained." degraded to the
     generic limitation message. A deictic follow-up must resolve its topic from
     THIS mentor's conversation memory and produce a second, grounded example.
  3. The configured-but-unavailable NIM/NVIDIA path must show an honest
     "provider is connected but not answering" limitation -- never an invented
     career claim about the trusted role.

Also guards the PRECEDING WORK so this fix cannot regress it: Phase 1C general
context gating and Phase 2 per-mentor conversation-memory isolation.
"""

import pytest

from app import genai
import app.jobs as jobs_mod


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
    """Lock generation into the deterministic fallback and keep jobs offline."""
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    monkeypatch.setattr(jobs_mod, "_fetch_all", lambda *a, **k: [])
    jobs_mod.clear_job_cache()


def _capture_complete(monkeypatch):
    """Replace genai.complete with a recorder returning the deterministic fallback."""
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


CLINICAL = "Clinical Research Assistant"


# ------------------------------------------------------------------ #1 general, role-free

def test_general_docker_question_gets_no_target_role_in_prompt_or_reply(
        client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    captured = _capture_complete(monkeypatch)
    r = _chat(client, student_id, h, "Explain Docker volumes in a simple way.")

    user = captured["user"]
    assert "Context route: GENERAL" in user
    assert "Trusted SkillBridge context: omitted" in user
    assert "Trusted target role" not in user
    assert "Trusted current skill" not in user
    assert CLINICAL not in user

    reply = r["reply"]
    assert "volume" in reply.lower()
    assert CLINICAL not in reply
    assert "is a practical skill you use to solve real problems" not in reply


# ------------------------------------------------------------ #2 memory follow-up grounded

def test_memory_followup_resolves_docker_and_stays_role_free(
        client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _chat(client, student_id, h, "Explain Docker volumes in a simple way.")

    captured = _capture_complete(monkeypatch)
    r = _chat(client, student_id, h, "Give me another example of what you just explained.")

    user = captured["user"]
    assert "Conversation memory" in user
    assert "Explain Docker volumes in a simple way" in user
    assert CLINICAL not in user

    reply = r["reply"]
    assert "Two containers can share one volume" in reply
    assert "Another example" in reply
    assert CLINICAL not in reply
    assert "don't have a reliable answer" not in reply
    assert "isn't answering reliably" not in reply


# ---------------------------------------------------------- #3 follow-up stays GENERAL

def test_followup_turn_is_not_promoted_to_career(
        client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _chat(client, student_id, h, "Explain Docker volumes in a simple way.")

    captured = _capture_complete(monkeypatch)
    _chat(client, student_id, h, "Give me another example of what you just explained.")
    user = captured["user"]

    assert "Context route: GENERAL" in user
    assert "Trusted SkillBridge context: omitted for this standalone general turn." in user
    assert "Trusted target role" not in user
    assert "Trusted current skill" not in user
    assert CLINICAL not in user


# ------------------------------------------- #4 configured-but-unavailable fallback

def test_configured_but_unavailable_fallback_never_injects_target_role(
        client, student_id, auth_headers, monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: True)  # provider configured...
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})

    # ...but failing (complete resolves to the deterministic fallback): an
    # UNGROUNDED question gets the honest "connected but not answering" reply,
    # never a fabricated career claim.
    r = _chat(client, student_id, h, "Why do earthquakes happen?")
    assert "isn't answering reliably" in r["reply"]
    assert CLINICAL not in r["reply"]

    # A GROUNDED question stays grounded and role-free even in that state.
    r = _chat(client, student_id, h, "Explain Docker volumes.")
    assert "volume" in r["reply"].lower()
    assert CLINICAL not in r["reply"]


# --------------------------------------------- #5 role merely existing in state

def test_target_role_in_student_state_does_not_drive_general_replies(
        client, student_id, auth_headers, db, monkeypatch):
    row = db.execute("SELECT id FROM roles WHERE title=?", (CLINICAL,)).fetchone()
    assert row, "seed must provide the Clinical Research Assistant catalog role"
    db.execute("UPDATE students SET target_role_id=? WHERE id=?", (row["id"], student_id))
    db.commit()

    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})

    captured = _capture_complete(monkeypatch)
    r = _chat(client, student_id, h, "Explain Docker volumes in a simple way.")
    assert CLINICAL not in captured["user"]
    assert CLINICAL not in r["reply"]
    assert "volume" in r["reply"].lower()

    # The role only surfaces where it is legitimately asked for.
    r = _chat(client, student_id, h, "What is my target role according to SkillBridge?")
    assert CLINICAL in r["reply"]


# ------------------------------------------------------------ #6 trusted career works

def test_trusted_career_questions_still_get_career_context(
        client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})

    captured = _capture_complete(monkeypatch)
    r = _chat(client, student_id, h, "What is my target role according to SkillBridge?")
    user = captured["user"]
    assert "Context route: CAREER" in user
    assert "Trusted target role" in user
    assert "Junior AI Engineer" in user
    assert "Junior AI Engineer" in r["reply"]

    # A question that explicitly ties the topic to the career may reference the
    # trusted role in a fallback reply -- via the honest role-connector, with a
    # grounded explanation of the topic itself.
    captured = _capture_complete(monkeypatch)
    r = _chat(client, student_id, h, "Show me how Docker applies to my career.")
    assert "Context route: CAREER" in captured["user"]
    assert "Template" not in captured["user"] or "trusted" in captured["user"]
    assert "Docker" in r["reply"]
    assert "Junior AI Engineer" in r["reply"]
    assert "is a practical skill you use to solve real problems" not in r["reply"]


# ------------------------------------------------------------ #7 Phase 1C gating intact

def test_phase1c_general_route_gating_intact(
        client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _chat(client, student_id, h, "Explain Docker volumes.")
    _chat(client, student_id, h, "Thanks, that helps.")

    captured = _capture_complete(monkeypatch)
    r = _chat(client, student_id, h, "Why do earthquakes happen?")
    user = captured["user"]

    assert "Context route: GENERAL" in user
    assert "Trusted SkillBridge context: omitted for this standalone general turn." in user
    assert "Trusted target role" not in user
    assert "Trusted current skill" not in user
    # The thread memory is NOT attached to a standalone general turn: memory is
    # exactly where a prior career/role exchange could hand the target role to
    # the model for a closing CTA, so non-follow-up general turns omit it.
    assert "Conversation memory" not in user
    assert CLINICAL not in r["reply"]
    # Ungrounded topic -> honest limitation, not a fabricated career template.
    assert (
        "don't have a reliable answer" in r["reply"].lower()
        or "isn't one I can answer reliably" in r["reply"].lower()
    )
    assert "is a practical skill you use to solve real problems" not in r["reply"]


# ------------------------------------------------------------ #8 Phase 2 isolation intact

def test_phase2_mentor_isolation_intact_with_fallback(
        client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _chat(client, student_id, h, "I am confused about Docker volumes.")
    # Nova's second turn carries the Docker memory block.
    captured = _capture_complete(monkeypatch)
    r = _chat(client, student_id, h, "Give me another example of what you just explained.")
    assert "Conversation memory" in captured["user"]
    assert "Two containers can share one volume" in r["reply"]

    # Switch to Axel: a fresh thread must carry no Nova memory block, no Nova
    # thread text, and no target-role leakage. The deictic follow-up has no
    # memory and no skill to resolve, so it honestly degrades to the limitation
    # reply. (Docker may still appear from the TRUSTED snapshot -- the student's
    # own gap analysis -- which is legitimate state, not a thread leak.)
    _set_pref(client, student_id, h, {"tutor_id": "axel"})
    captured = _capture_complete(monkeypatch)
    r = _chat(client, student_id, h, "Give me another example of what you just explained.")
    user = captured["user"]
    assert "Conversation memory" not in user
    assert "I am confused about Docker volumes" not in user
    assert CLINICAL not in user
    assert "don't have a reliable answer" in r["reply"].lower() or \
        "isn't answering reliably" in r["reply"] or \
        "explain reliably offline" in r["reply"].lower()

    # Axel's own grounded topics are still answerable offline, role-free.
    r = _chat(client, student_id, h, "Explain SQL injection.")
    assert CLINICAL not in r["reply"]
    assert "SQL" in r["reply"]

    # Switching back to Nova restores Nova's own memory: the same deictic
    # follow-up now resolves to the earlier Docker topic.
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    captured = _capture_complete(monkeypatch)
    r = _chat(client, student_id, h, "Give me another example of what you just explained.")
    assert "Conversation memory" in captured["user"]
    assert "Two containers can share one volume" in r["reply"]
    assert CLINICAL not in r["reply"]