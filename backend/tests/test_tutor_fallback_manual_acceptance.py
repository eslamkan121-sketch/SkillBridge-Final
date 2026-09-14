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

import re

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
        or "isn't one i can answer reliably" in r["reply"].lower()
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
    assert "outside what I can handle reliably offline" in r["reply"].lower() or \
        "won't fake it" in r["reply"].lower()

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


# ------------------------------------------------- grounded-knowledge definition

_GROUNDED_KNOWN = "Docker"

_UNKNOWN_TOPIC = "Why do earthquakes happen?"

_NO_PROVIDER_AR_NOVA = "مزوّد الذكاء الاصطناعي مش بيرد بشكل موثوق دلوقتي"
_UNAVAILABLE_AR_NOVA = "السؤال ده مش بيرد معايا بشكل موثوق دلوقتي"


# -------------------------------------- #9-#10 provider-failure UX (honest, short)

def test_provider_failure_fallback_is_short_honest_and_neutral_en(
        client, student_id, auth_headers, monkeypatch):
    """A configured-but-failing provider must yield a SHORT, honest, role-free
    limitation — never a fabricated career claim, never a random-topic menu."""
    monkeypatch.setattr(genai, "genai_enabled", lambda: True)  # configured...
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})

    r = _chat(client, student_id, h, _UNKNOWN_TOPIC)
    reply = r["reply"]
    assert "isn't answering reliably" in reply.lower()
    assert len(reply) < 250
    assert CLINICAL not in reply
    assert "is a practical skill you use to solve real problems" not in reply
    low = reply.lower()
    for banned in ("photosynthesis", "newton", "the sky is blue", "genai", "provider configured"):
        assert banned not in low
    assert not re.search(r"\n\s*\d+[.)]", reply)  # no numbered menu


def test_provider_failure_fallback_is_short_honest_and_neutral_ar(
        client, student_id, auth_headers, monkeypatch):
    """Same provider-failure contract in Arabic: the limitation is real Arabic,
    short, honest and neutral — and never leaks the English target role."""
    monkeypatch.setattr(genai, "genai_enabled", lambda: True)  # configured...
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})

    r = _chat(client, student_id, h, _UNKNOWN_TOPIC,
              body={"language": "ar", "mode": "chat"})
    reply = r["reply"]
    assert genai._has_arabic(reply)
    assert "مش بيرد معايا بشكل موثوق" in reply
    assert len(reply) < 250
    assert CLINICAL not in reply
    assert "is a practical skill you use to solve real problems" not in reply


def test_no_provider_fallback_is_short_honest_and_never_a_topic_menu(
        client, student_id, auth_headers, monkeypatch):
    """The offline (no provider at all) limitation is just as short/neutral and
    the student is never handed a menu of unrelated fallback topics."""
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})

    r = _chat(client, student_id, h, _UNKNOWN_TOPIC)
    reply = r["reply"]
    assert (
        "don't have a reliable answer" in reply.lower()
        or "isn't one i can answer reliably" in reply.lower()
    )
    assert len(reply) < 250
    assert CLINICAL not in reply
    low = reply.lower()
    for banned in ("photosynthesis", "newton", "the sky is blue", "want to try"):
        assert banned not in low
    assert not re.search(r"\n\s*\d+[.)]", reply)


# ------------------------------------------------- media-placeholder hygiene

def test_standalone_svg_placeholder_line_is_removed():
    """A whole-line '**svg**' stub is dropped from the visible reply (regression
    guard for the original standalone case)."""
    assert genai._clean_visible_reply("**svg**", persona_id="nova") == ""
    assert genai._clean_visible_reply("Good question.\n\n**svg**", persona_id="nova") == "Good question."
    assert genai._clean_visible_reply("[svg]", persona_id="nova") == ""
    assert genai._clean_visible_reply("<svg>", persona_id="nova") == ""


def test_inline_svg_placeholder_after_prose_is_removed(monkeypatch):
    """A diagram stub the provider appends AFTER real prose ('...explanation.
    **svg**') must be stripped so it cannot render as a visible artifact."""
    monkeypatch.setattr(genai, "complete", lambda system, user, fallback=None, **kw:
                        "Useful explanation here. **svg**")
    reply = genai.tutor_reply(
        "Explain Docker volumes.",
        "Dashboard context:\nTarget career: Junior AI Engineer",
        "Docker", "Junior AI Engineer",
        tutor_id="nova", mode="chat", language="en",
    )
    assert reply == "Useful explanation here."


def test_appended_svg_variants_are_stripped():
    for stub in ("**svg**", "*svg*", "[svg]", "[svg.fig]", "<svg>", "<svg/>",
                 "![svg](chart.svg)", "svg placeholder", "diagram; **svg**"):
        reply = genai._clean_visible_reply(f"Here is the idea. {stub}", persona_id="nova")
        assert reply == "Here is the idea.", (stub, reply)
    # Chained stubs and a stub on a non-final line are handled too.
    assert genai._clean_visible_reply(
        "First part. **svg**\nSecond part. [svg]", persona_id="nova"
    ) == "First part.\nSecond part."


def test_legitimate_svg_prose_is_never_altered():
    """Explaining the SVG format itself (uppercase 'SVG' in prose) must survive
    untouched — the guard only removes the lowercase artifact token form."""
    for text in (
        "What is an SVG image?",
        "An SVG diagram is vector-based and scales without losing quality.",
        "It renders best as an **SVG**.",
        "Use SVG for crisp icons on any screen.",
    ):
        assert genai._clean_visible_reply(text, persona_id="nova") == text, text
    # 'SVG' inside a sentence mid-line is not at the end, so it always survives.
    assert "**SVG**" in genai._clean_visible_reply(
        "It renders best as an **SVG** you can resize freely.", persona_id="nova"
    )


# ------------------------------- #11-#12 follow-up directness (no repeated CTA)

def test_consecutive_followup_does_not_repeat_previous_turn_closing(
        client, student_id, auth_headers):
    """A genuine follow-up must not repeat the identical automatic closing
    question ('Want to see how bind mounts differ...') from the immediately
    previous mentor reply, and must not restate the full first explanation."""
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})

    first = _chat(client, student_id, h, "Explain Docker volumes in a simple way.")["reply"]
    second = _chat(client, student_id, h, "Give me another example of what you just explained.")["reply"]

    closing = "Want to see how bind mounts differ"
    assert closing in first  # turn 1 carries its own automatic closing question
    assert closing not in second  # turn 2 never re-emits the identical closing
    assert "A Docker volume is persistent storage" in first
    assert "A Docker volume is persistent storage" not in second  # no restatement
    assert "safe-deposit box" not in second  # the original analogy is not repeated either
    assert "Two containers can share one volume" in second  # the NEW example is delivered


def test_another_example_answer_is_direct_and_short(
        client, student_id, auth_headers):
    """'Give me another example...' is answered DIRECTLY with the second example
    — a short turn, not a rebuilt version of the original explanation."""
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _chat(client, student_id, h, "Explain Docker volumes in a simple way.")

    second = _chat(client, student_id, h, "Give me another example of what you just explained.")["reply"]

    assert second.startswith("Another example:")
    assert "persistent storage" not in second
    assert len(second) < 250
    assert CLINICAL not in second
    assert "is a practical skill you use to solve real problems" not in second


# ------------------- #13 Arabic no-provider wording (Issue 2 polish)

def test_arabic_no_provider_fallback_has_no_assistant_referral_or_offline_claim(
        client, student_id, auth_headers):
    """The offline Arabic limitation must not tell the student to 'connect me to
    the direct assistant' (no such user-facing concept exists), must never claim
    the mentor itself is offline, and must stay a short, honest, neutral
    provider-availability statement — no random topics, no career context."""
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})

    reply = _chat(client, student_id, h, _UNKNOWN_TOPIC,
                  body={"language": "ar", "mode": "chat"})["reply"]

    assert genai._has_arabic(reply)
    assert "المساعد المباشر" not in reply
    assert "غير متصل" not in reply  # never claims the mentor itself is offline
    assert "بيرد بشكل موثوق" in reply  # a plain provider-availability statement
    assert len(reply) < 250
    assert CLINICAL not in reply
    low = reply.lower()
    for banned in ("photosynthesis", "newton", "the sky is blue"):
        assert banned not in low
    assert not re.search(r"\n\s*\d+[.)]", reply)  # no numbered menu