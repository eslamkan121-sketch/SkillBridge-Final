"""Smart Tutor Personas v2 — Phase 1: general intelligence + real persona identity.

Deterministic (keyless) coverage for:
- each persona's name identity, correct specialty and NO identity leakage across
  the four personas (system prompt and keyless reply both);
- general intelligence routing: science / programming / math questions are
  answered, and unrelated general knowledge is never forced into the student's
  target career;
- trust: personal skill claims, Verified Skills and assessment results are
  never invented, and target-role answers come ONLY from the trusted backend
  context that was passed in;
- persona switching: the selected tutor's identity wins in the system prompt.
- language: the identity question works in English and Arabic.

Never calls a paid API.
"""

import re

import pytest

from app import genai, copilot
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


CANONICAL = {
    "nova": {"name": "Nova", "role": "Explainer Tutor", "origin": "London, United Kingdom",
             "specialty": "Learn & Explain", "traits": ["Warm", "Patient", "Clear", "Supportive"]},
    "axel": {"name": "Axel", "role": "Practical Coach", "origin": "California, United States",
             "specialty": "Practice & Build", "traits": ["Energetic", "Practical", "Direct", "Action-focused"]},
    "sage": {"name": "Sage", "role": "Discussion Mentor", "origin": "Alexandria, Egypt",
             "specialty": "Discuss & Think", "traits": ["Calm", "Analytical", "Thoughtful", "Reflective"]},
    "vex": {"name": "Vex", "role": "Examiner", "origin": "Paris, France",
            "specialty": "Test & Interview", "traits": ["Precise", "Professional", "Challenging", "Sharp"]},
}


def _system_for(monkeypatch, tutor_id, message="What is your name?"):
    captured = _capture_complete(monkeypatch)
    reply = genai.tutor_reply(message, "Studying at Aston University", None, None,
                              tutor_id=tutor_id, mode="chat", language="en")
    return captured["system"], captured["user"], reply


# ------------------------------------------------------------------ identity: names, specialties, no leakage

@pytest.mark.parametrize("tutor_id", list(CANONICAL))
def test_persona_identity_block_and_no_leakage(monkeypatch, tutor_id):
    meta = CANONICAL[tutor_id]
    system, _, _ = _system_for(monkeypatch, tutor_id)
    assert f"You are {meta['name']}" in system
    assert meta["role"] in system
    assert meta["specialty"] in system
    assert meta["origin"] in system
    assert len(meta["traits"]) >= 2
    for trait in meta["traits"]:
        assert trait in system
    # No identity leakage: no other persona's name appears anywhere.
    for other in CANONICAL:
        if other != tutor_id:
            assert CANONICAL[other]["name"] not in system, \
                f"{meta['name']} prompt leaked {CANONICAL[other]['name']}"


def test_general_intelligence_rule_in_system(monkeypatch):
    system, _, _ = _system_for(monkeypatch, "nova")
    assert "general-knowledge tutor" in system
    assert "Never force" in system
    assert "never make you refuse" in system


def test_identity_fallback_is_first_person_and_persona_specific(monkeypatch):
    captured = _capture_complete(monkeypatch)
    nova = genai.tutor_reply("Who are you?", "ctx", None, None, tutor_id="nova", language="en")
    assert "Nova" in nova and "Learn & Explain" in nova and "AI career coach" in nova
    assert "I'm Nova" in nova
    assert captured["user"]  # sanitized scaffolding harness stays off the reply
    vex = genai.tutor_reply("What's your name?", "ctx", None, None, tutor_id="vex", language="en")
    assert "Vex" in vex and "Test & Interview" in vex
    assert "Nova" not in vex and "Sage" not in vex and "Axel" not in vex


def test_identity_block_never_claims_human_life(monkeypatch):
    system, _, _ = _system_for(monkeypatch, "sage")
    assert "never claim to be a real human" in system
    assert "origin is a character/profile attribute" in system


# ------------------------------------------------------------------ general intelligence routing

def test_science_question_is_allowed_and_not_bound_to_career(monkeypatch):
    captured = _capture_complete(monkeypatch)
    reply = genai.tutor_reply("Explain photosynthesis.", "ctx", None, "Cybersecurity Analyst",
                              tutor_id="nova", mode="chat", language="en")
    low = reply.lower()
    assert "photosynthesis" in low
    assert "cybersecurity" not in low
    assert "security analyst" not in low
    assert "never force" in captured["system"].lower()


def test_programming_question_is_allowed(monkeypatch):
    reply = genai.tutor_reply("What is SQL injection?", "ctx", None, "Lawyer",
                              tutor_id="vex", mode="chat", language="en")
    low = reply.lower()
    assert "sql" in low and "injection" in low
    assert "lawyer" not in low


def test_math_question_is_allowed(monkeypatch):
    reply = genai.tutor_reply("Explain Newton's second law.", "ctx", None, "Graphic Designer",
                              tutor_id="sage", mode="chat", language="en")
    low = reply.lower()
    assert "force" in low and "acceleration" in low
    assert "graphic" not in low


def test_direct_arithmetic_is_answered_not_quized(monkeypatch):
    """B2: 'what is 2+2?' must return the number itself, deterministically —
    never a counter-question (the persona-guided 'optional knowledge check'
    used to turn it into 'What is 3 + 3?')."""
    reply = genai.tutor_reply("what is 2+2?", "ctx", None, "Cybersecurity Analyst",
                              tutor_id="vex", mode="chat", language="en")
    assert "2 + 2 = 4." in reply
    arabic = genai.tutor_reply("كام 2+2؟", "ctx", None, None,
                               tutor_id="nova", mode="chat", language="ar")
    assert "2 + 2 = 4." in arabic
    # non-arithmetic questions still flow through the normal path untouched
    baked = genai.tutor_reply("What is Docker?", "ctx", None, "Cybersecurity Analyst",
                              tutor_id="vex", mode="chat", language="en")
    assert "2 + 2" not in baked and "docker" in baked.lower()


def test_general_knowledge_not_forced_into_target_career_across_personas(monkeypatch):
    for tutor_id in CANONICAL:
        reply = genai.tutor_reply("What is Docker?", "ctx", None, "Cybersecurity Analyst",
                                  tutor_id=tutor_id, mode="chat", language="en")
        low = reply.lower()
        assert "docker" in low
        assert "cybersecurity" not in low and "analyst" not in low


def test_general_topic_stays_out_of_skill_gap_topic(monkeypatch):
    # Even with a skill gap present, an unrelated general question must not
    # be hijacked into that skill's content.
    reply = genai.tutor_reply("Teach me linear algebra.", "ctx", "Penetration Testing",
                              "Cyber Security Analyst", tutor_id="nova", mode="chat", language="en")
    low = reply.lower()
    assert "linear algebra" in low or "matrix" in low or "matrices" in low
    assert "penetration testing" not in low.split("\n\n", 1)[0]


def test_general_context_gate_omits_student_snapshot(monkeypatch):
    captured = _capture_complete(monkeypatch)
    context = (
        "Dashboard context:\n"
        "University: Aston University\n"
        "Target career: Junior AI Engineer\n"
        "Career readiness: 50% match to the target role\n"
        "- Docker: you have it but below the required level\n"
        "Recommended next step: work on 'Docker' next, then 'Machine Learning'."
    )
    reply = genai.tutor_reply(
        "Explain how volcanoes erupt to me like I'm a beginner.",
        context,
        "Docker",
        "Junior AI Engineer",
        tutor_id="nova",
        mode="chat",
        language="en",
    )
    assert "volcano" not in reply.lower()  # keyless fallback stays honest for unmapped topics
    assert "Context route: GENERAL" in captured["user"]
    assert "Trusted SkillBridge context: omitted" in captured["user"]
    assert "Junior AI Engineer" not in captured["user"]
    assert "Docker" not in captured["user"]
    assert "Career readiness" not in captured["user"]
    assert "No private SkillBridge profile snapshot" in captured["system"]


def test_identity_context_gate_omits_student_snapshot(monkeypatch):
    captured = _capture_complete(monkeypatch)
    reply = genai.tutor_reply(
        "Who are you?",
        "Dashboard context:\nTarget career: Junior AI Engineer\nRecommended next step: work on 'Docker' next.",
        "Docker",
        "Junior AI Engineer",
        tutor_id="vex",
        mode="chat",
        language="en",
    )
    assert "Vex" in reply
    assert "Context route: IDENTITY" in captured["user"]
    assert "Junior AI Engineer" not in captured["user"]
    assert "Docker" not in captured["user"]


def test_general_education_question_classifies_general_under_learning_page():
    context = (
        "Learning context:\n"
        "Skill focus: Active Directory (cybersecurity)\n"
        "Latest diagnostic score: 40/100 (needs work)."
    )
    # a standalone educational question must stay GENERAL even when the page
    # banner routes toward the current learning context
    assert genai._classify_tutor_turn(
        "Explain why dinosaurs became extinct.",
        skill_name="Active Directory",
        target_role="Cybersecurity Analyst",
        student_context=context,
    ) == "GENERAL"


def test_general_context_omits_role_learning_state_and_gaps():
    targeted = (
        "Trusted SkillBridge context route: CURRENT_LEARNING\n"
        "Trusted current skill: Active Directory\n"
        "Trusted target role: Cybersecurity Analyst\n"
        "Trusted SkillBridge context:\n"
        "Latest diagnostic score: 40/100 (needs work)."
    )
    out = genai._context_for_intent("GENERAL", targeted, "Active Directory", "Cybersecurity Analyst")
    assert "Active Directory" not in out
    assert "Cybersecurity Analyst" not in out
    assert "40/100" not in out
    assert "omitted for this standalone general turn" in out


def test_explain_dinosaurs_from_learning_page_gets_no_student_snapshot(monkeypatch):
    captured = _capture_complete(monkeypatch)
    context = (
        "Learning context:\n"
        "Skill focus: Active Directory (cybersecurity)\n"
        "Latest diagnostic score: 40/100 (needs work)."
    )
    genai.tutor_reply(
        "Explain why dinosaurs became extinct.",
        context,
        "Active Directory",
        "Cybersecurity Analyst",
        tutor_id="nova",
        mode="chat",
        language="en",
    )
    assert "Context route: GENERAL" in captured["user"]
    assert "Trusted SkillBridge context: omitted" in captured["user"]
    assert "Active Directory" not in captured["user"]
    assert "Cybersecurity Analyst" not in captured["user"]
    assert "40/100" not in captured["user"]


def test_personal_context_gate_preserves_trusted_skillbridge_state(monkeypatch):
    captured = _capture_complete(monkeypatch)
    context = (
        "Dashboard context:\n"
        "Target career: Junior AI Engineer\n"
        "Recommended next step: work on 'Docker' next, then 'Machine Learning'."
    )
    reply = genai.tutor_reply(
        "What am I learning right now according to SkillBridge?",
        context,
        None,
        "Junior AI Engineer",
        tutor_id="nova",
        mode="chat",
        language="en",
    )
    assert "Docker" in reply
    assert "Context route: CURRENT_LEARNING" in captured["user"]
    assert "Junior AI Engineer" in captured["user"]
    assert "Docker" in captured["user"]


def test_vex_explain_then_question_prompt_stays_on_user_topic(monkeypatch):
    captured = _capture_complete(monkeypatch)
    genai.tutor_reply(
        "Explain how HTTPS works, then ask me one technical question.",
        "Dashboard context:\nRecommended next step: work on 'Docker' next.",
        "Docker",
        "Junior AI Engineer",
        tutor_id="vex",
        mode="chat",
        language="en",
    )
    assert "Context route: GENERAL" in captured["user"]
    assert "HTTPS" in captured["user"]
    assert "Docker" not in captured["user"]
    assert "test question must be about the topic" in captured["user"]


def test_requested_followup_question_is_added_when_provider_omits_it(monkeypatch):
    captured = {}

    def fake_complete(system, user, fallback=None, **kw):
        captured["system"] = system
        captured["user"] = user
        return "HTTPS uses TLS to encrypt HTTP traffic and verify the server identity."

    monkeypatch.setattr(genai, "complete", fake_complete)
    reply = genai.tutor_reply(
        "Explain how HTTPS works, then ask me one technical question.",
        "Dashboard context:\nRecommended next step: work on 'Docker' next.",
        "Docker",
        "Junior AI Engineer",
        tutor_id="vex",
        mode="chat",
        language="en",
    )
    assert "Quick check on HTTPS" in reply
    assert "certificate" in reply
    assert "Docker" not in reply
    assert "Docker" not in captured["user"]


def test_vex_explain_dns_then_quiz_stays_general_under_learning_banner(monkeypatch):
    """Pins the live FAIL 2 shape: on the Learning page (Active Directory focus)
    Vex in chat mode explaining DNS keeps the turn GENERAL — no profile/current
    skill snapshot leaks, the DNA topic is kept, and the quiz must be about the
    topic the student named (never the reversed 'explain DNS to me')."""
    captured = _capture_complete(monkeypatch)
    context = (
        "Learning context:\n"
        "Skill focus: Active Directory (cybersecurity)\n"
        "Latest diagnostic score: 40/100 (needs work)."
    )
    assert genai._classify_tutor_turn(
        "Explain DNS, then ask me one question about what you just explained.",
        skill_name="Active Directory",
        target_role="Cybersecurity Analyst",
        student_context=context,
    ) == "GENERAL"
    genai.tutor_reply(
        "Explain DNS, then ask me one question about what you just explained.",
        context,
        "Active Directory",
        "Cybersecurity Analyst",
        tutor_id="vex",
        mode="chat",
        language="en",
    )
    assert "Context route: GENERAL" in captured["user"]
    assert "Active Directory" not in captured["user"]
    assert "40/100" not in captured["user"]
    assert "DNS" in captured["user"]
    assert "test question must be about the topic" in captured["user"]


# ------------------------------------------------------------------ trust: no invented personal data

def test_personal_skill_claim_is_not_invented(monkeypatch):
    capt = _capture_complete(monkeypatch)
    reply = genai.tutor_reply("Am I good at penetration testing?", "ctx", None,
                              "Cybersecurity Analyst", tutor_id="vex", mode="chat", language="en")
    low = reply.lower()
    assert "evidence" in low or "fabricate" in low or "won't" in low
    assert not re.search(r"\b(score|grade|level)\b\s*[:\=]?\s*\d", low)
    # The system prompt must tell the model not to invent student data.
    assert "Never invent" in capt["system"]


def test_verified_skill_is_not_invented(monkeypatch):
    capt = _capture_complete(monkeypatch)
    genai.tutor_reply("Am I good at SQL?", "ctx", "SQL", "Data Engineer",
                      tutor_id="nova", mode="chat", language="en")
    assert "Verified Skills" in capt["system"]
    assert "assessment results" in capt["system"]


def test_target_role_comes_from_backend_context(monkeypatch):
    captured = _capture_complete(monkeypatch)
    with_role = genai.tutor_reply("What is my target role?", "ctx", None,
                                  "Cybersecurity Analyst", tutor_id="nova", mode="chat", language="en")
    assert "Cybersecurity Analyst" in with_role
    assert "target role: cybersecurity analyst" in captured["user"].lower()
    without_role = genai.tutor_reply("What is my target role?", "ctx", "Docker", None,
                                 tutor_id="nova", mode="chat", language="en")
    assert "Cybersecurity" not in without_role
    assert "Docker" in without_role  # trusted skill focus is used; the role is not invented
    neither = genai.tutor_reply("What is my target role?", "ctx", None, None,
                                tutor_id="nova", mode="chat", language="en")
    assert "won't invent" in neither.lower()


def test_grade_not_in_backend_is_not_fabricated(monkeypatch):
    reply = genai.tutor_reply("What grade did I get in my university exam?", "ctx",
                              None, None, tutor_id="sage", mode="chat", language="en")
    low = reply.lower()
    assert not re.search(r"\bfirst\b|\b[A-F]\b|\b\d+\s*/\s*\d+\b", low)
    assert "evidence" in low or "won't" in low or "guess" in low


# ------------------------------------------------------------------ persona switching

def test_selected_tutor_identity_wins_in_system_prompt(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    client.put(f"/api/students/{student_id}/tutor/preference",
               json={"tutor_id": "sage", "mode": "chat", "language": "en"}, headers=h)
    captured = _capture_complete(monkeypatch)
    r = client.post(f"/api/students/{student_id}/tutor",
                    json={"message": "What's your name?", "tutor_id": "vex",
                          "mode": "chat", "language": "en"}, headers=h)
    assert r.status_code == 200, r.text
    system = captured["system"]
    assert "You are Vex" in system
    assert "You are Sage" not in system
    assert "You are Nova" not in system
    assert "Nova" not in system and "Axel" not in system
    assert "Vex" in r.json()["reply"] and "Nova" not in r.json()["reply"]


def test_stored_preference_persona_identity_still_wins_without_body(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    client.put(f"/api/students/{student_id}/tutor/preference",
               json={"tutor_id": "axel", "mode": "practice", "language": "en"}, headers=h)
    captured = _capture_complete(monkeypatch)
    r = client.post(f"/api/students/{student_id}/tutor",
                    json={"message": "Who are you?", "mode": "practice", "language": "en"}, headers=h)
    assert r.status_code == 200, r.text
    system = captured["system"]
    assert "You are Axel" in system
    assert "You are Vex" not in system and "You are Sage" not in system and "You are Nova" not in system


def test_persona_ids_still_align_with_allowed_list():
    assert set(genai.TUTOR_PERSONAS) == set(copilot.ALLOWED_TUTOR_IDS)
    for tid, meta in CANONICAL.items():
        persona = genai.TUTOR_PERSONAS[tid]
        assert persona["name"] == meta["name"]
        assert persona["role"] == meta["role"]
        assert persona["origin"] == meta["origin"]
        assert persona["specialty"] == meta["specialty"]
        assert persona["traits"] == meta["traits"]
        assert persona["best_at"]
        assert persona["behavior"]
        assert persona["style"]


# ------------------------------------------------------------------ language

def test_arabic_identity_question_works(monkeypatch):
    captured = _capture_complete(monkeypatch)
    reply = genai.tutor_reply("انت مين؟", "ctx", None, None,
                              tutor_id="sage", mode="chat", language="ar")
    assert genai._has_arabic(reply)
    assert "Sage" in reply and "Discuss & Think" in reply


def test_english_identity_question_works(monkeypatch):
    captured = _capture_complete(monkeypatch)
    reply = genai.tutor_reply("What's your name?", "ctx", None, None,
                              tutor_id="nova", mode="chat", language="en")
    assert "Nova" in reply and "Learn & Explain" in reply


def test_arabic_general_knowledge_is_not_career_bound(monkeypatch):
    reply = genai.tutor_reply("اشرح البناء الضوئي.", "ctx", None, "محلل أمن سيبراني",
                              tutor_id="nova", mode="chat", language="ar")
    assert genai._has_arabic(reply)
    assert "أمن سيبراني" not in reply


def test_arabic_trust_is_not_invented(monkeypatch):
    reply = genai.tutor_reply("هل أنا كويس في اختبار الاختراق؟", "ctx", None,
                              "Cybersecurity Analyst", tutor_id="vex", mode="chat", language="ar")
    assert genai._has_arabic(reply)
    assert "مختلق" in reply or "دليل" in reply


# ------------------------------------------------------------------ Phase 1 runtime acceptance
#
# These go through the SAME FastAPI endpoint the browser hits
# (POST /api/students/{id}/tutor) so a stale fallback can never hide behind a
# helper-level unit test. Deterministic: the autouse fixture disables GenAI,
# so the endpoint returns the persona-aware fallback path end to end.


def _send(client, student_id, headers, message, tutor_id, mode="chat", language="en",
          page="dashboard", skill_id=None, competency=None, monkeypatch=None):
    if monkeypatch is not None:
        _capture_complete(monkeypatch)
    return client.post(f"/api/students/{student_id}/tutor",
                       json={"message": message, "skill_id": skill_id, "page": page,
                             "competency": competency, "job_title": None, "job_url": None,
                             "tutor_id": tutor_id, "mode": mode, "language": language},
                       headers=headers)


def test_endpoint_nova_identity_browser_exact(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    r = _send(client, student_id, h, "What's your name and what are you best at?",
              "nova", language="en", monkeypatch=monkeypatch)
    assert r.status_code == 200, r.text
    reply = r.json()["reply"]
    assert "Nova" in reply and "Learn & Explain" in reply
    assert "practical skill" not in reply


def test_endpoint_axel_docker_beginner(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    r = _send(client, student_id, h, "Explain Docker to me. I am a beginner.",
              "axel", language="en", monkeypatch=monkeypatch)
    assert r.status_code == 200, r.text
    reply = r.json()["reply"].lower()
    assert "docker" in reply
    assert "container" in reply
    assert "practical skill" not in reply


def test_endpoint_sage_sky_blue(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    r = _send(client, student_id, h, "Why is the sky blue?", "sage",
              language="en", monkeypatch=monkeypatch)
    assert r.status_code == 200, r.text
    reply = r.json()["reply"].lower()
    assert "scatter" in reply
    assert "practical skill" not in reply
    assert "your target role" not in reply


def test_endpoint_vex_newton_then_check(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    r = _send(client, student_id, h,
              "Explain Newton's second law, then test me with one question.",
              "vex", language="en", monkeypatch=monkeypatch)
    assert r.status_code == 200, r.text
    reply = r.json()["reply"]
    assert "f = ma" in reply.lower()
    assert "?" in reply  # the one short knowledge check is present
    assert "practical skill" not in reply


def test_endpoint_arabic_nova_identity(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    r = _send(client, student_id, h, "اسمك إيه وإنت بتساعدني في إيه؟",
              "nova", language="ar", monkeypatch=monkeypatch)
    assert r.status_code == 200, r.text
    reply = r.json()["reply"]
    assert genai._has_arabic(reply)
    assert "Nova" in reply and "Learn & Explain" in reply
    assert "مختلق" not in reply


def test_endpoint_identity_wins_over_page_context(client, student_id, auth_headers, monkeypatch):
    """Passive page context ('learning', Docker-everywhere) must not hijack identity."""
    h = auth_headers("aisha@student.edu")
    cap = _capture_complete(monkeypatch)
    r = _send(client, student_id, h, "What's your name?", "nova", mode="discuss",
              page="learning", skill_id=None, competency="Docker", monkeypatch=None)
    assert r.status_code == 200, r.text
    reply = r.json()["reply"]
    assert "Nova" in reply
    assert "Docker" not in reply
    assert "docker" not in reply.lower()
    assert "practical skill" not in reply
    assert "context:" in cap["user"]


def test_endpoint_general_question_wins_over_page_context(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    r = _send(client, student_id, h, "Why is the sky blue?", "nova", mode="practice",
              page="learning", competency="Docker", monkeypatch=monkeypatch)
    assert r.status_code == 200, r.text
    reply = r.json()["reply"].lower()
    assert "scatter" in reply
    assert "docker" not in reply
    assert "practical skill" not in reply


def test_endpoint_profile_question_uses_trusted_context(client, student_id, auth_headers, monkeypatch):
    """'What am I learning right now?' must map to the trusted skill context, not invent."""
    from app import models
    skills = models.list_skills()
    assert skills
    skill = skills[0]
    h = auth_headers("aisha@student.edu")
    r = _send(client, student_id, h, "What am I learning right now?", "nova",
              page="learning", skill_id=skill["id"], monkeypatch=monkeypatch)
    assert r.status_code == 200, r.text
    reply = r.json()["reply"]
    assert skill["name"].lower() in reply.lower() or "skill focus" in reply.lower() \
        or "target role" in reply.lower()


# ------------------------------------------------------------------ unmapped general knowledge

def test_sky_blue_is_a_science_answer(monkeypatch):
    reply = genai.tutor_reply("Why is the sky blue?", "ctx", None, "Junior AI Engineer",
                              tutor_id="sage", mode="chat", language="en")
    low = reply.lower()
    assert "scatter" in low
    assert "practical skill" not in low and "Junior AI Engineer" not in low


def test_penetration_testing_is_explained(monkeypatch):
    reply = genai.tutor_reply("What is penetration testing?", "ctx", None, "Junior AI Engineer",
                              tutor_id="nova", mode="chat", language="en")
    low = reply.lower()
    assert "penetration testing" in low or "pentest" in low
    assert "practical skill" not in low


def test_arabic_sky_blue_answer(monkeypatch):
    reply = genai.tutor_reply("ليه السماء زرقا؟", "ctx", None, None,
                              tutor_id="nova", mode="chat", language="ar")
    low = reply.lower()
    assert genai._has_arabic(reply)
    assert "التشتت" in reply
    assert "مهارة عملية" not in reply


def test_unmapped_general_gets_honest_limitation(monkeypatch):
    reply = genai.tutor_reply("Why is the ocean salty?", "ctx", None, "Junior AI Engineer",
                              tutor_id="nova", mode="chat", language="en")
    low = reply.lower()
    assert "practical skill" not in low
    assert "junior ai engineer" not in low
    assert "won't" in low or "make something up" in low


def test_unmapped_general_arabic_limitation(monkeypatch):
    reply = genai.tutor_reply("ليه البحر مالح؟", "ctx", None, None,
                              tutor_id="sage", mode="chat", language="ar")
    assert genai._has_arabic(reply)
    assert "مختلق" not in reply
    assert "مهارة عملية" not in reply
    assert "GenAI" in reply


# ------------------------------------------------------------------ Phase 1B: Vex persona vs mode separation
#
# Selecting the Vex persona must NOT enter the mock-interview session. The
# persona and the working mode are independent: Vex + ordinary chat answers
# identity/Docker/science like a chat tutor; the interview probe ("Acceptable
# start. Now go deeper...") appears ONLY in an explicit Interview mode/session.

def test_vex_chat_prompt_is_not_the_interview_engine(monkeypatch):
    """Vex in chat mode assembles a chat prompt, never an interviewer prompt."""
    cap = _capture_complete(monkeypatch)
    genai.tutor_reply("Explain Docker to me. I am a beginner.", "ctx", "Docker",
                      "Junior AI Engineer", tutor_id="vex", mode="chat", language="en")
    system = cap["system"]
    assert "Examiner" in system
    assert "Do not turn every normal question into a formal test" in system
    assert "Student's latest answer" not in system
    assert "Respond as the interviewer" not in system


def test_explicit_interview_session_is_a_distinct_prompt(monkeypatch):
    """The same Vex persona inside an interview session uses the interviewer path."""
    cap = _capture_complete(monkeypatch)
    genai.interview_reply("I built a small Docker compose setup", "ctx", "Docker",
                          "Junior AI Engineer", turn=2, tutor_id="vex", language="en")
    assert "Interviewer identity: Vex" in cap["system"]
    assert "Respond as the interviewer" in cap["user"]
    assert "Student's latest answer" in cap["user"]


def test_endpoint_vex_identity_via_chat(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    r = _send(client, student_id, h, "What's your name and what is your specialty?",
              "vex", mode="chat", language="en", monkeypatch=monkeypatch)
    assert r.status_code == 200, r.text
    reply = r.json()["reply"]
    assert "Vex" in reply and "Examiner" in reply
    assert "Acceptable start" not in reply
    assert "go deeper" not in reply.lower()


def test_endpoint_vex_docker_explains_not_interviews(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    r = _send(client, student_id, h, "Explain Docker to me. I am a beginner.",
              "vex", mode="chat", language="en", monkeypatch=monkeypatch)
    assert r.status_code == 200, r.text
    reply = r.json()["reply"].lower()
    assert "docker" in reply and "container" in reply
    assert "acceptable start" not in reply
    assert "go deeper" not in reply
    assert "practical skill" not in reply


def test_endpoint_vex_sky_blue_explains_science(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    r = _send(client, student_id, h, "Why is the sky blue?",
              "vex", mode="chat", language="en", monkeypatch=monkeypatch)
    assert r.status_code == 200, r.text
    reply = r.json()["reply"].lower()
    assert "scatter" in reply
    assert "acceptable start" not in reply
    assert "job" not in reply


def test_endpoint_vex_explicit_interview_preserved(client, student_id, auth_headers, monkeypatch):
    """Vex in an EXPLICIT interview session keeps interviewing (no chat answer)."""
    h = auth_headers("aisha@student.edu")
    r = _send(client, student_id, h, "Why is the sky blue?", "vex",
              mode="interview", language="en", monkeypatch=monkeypatch)
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "interview"
    reply = r.json()["reply"]
    assert "go deeper" in reply.lower() or "?" in reply
    assert "scatter" not in reply.lower()  # the interview treats the message as an answer


def test_endpoint_vex_persona_and_mode_are_independent(client, student_id, auth_headers, monkeypatch):
    """Same student, same Vex persona: chat mode answers; interview mode interviews."""
    h = auth_headers("aisha@student.edu")
    chat = _send(client, student_id, h, "Why is the sky blue?", "vex",
                 mode="chat", language="en", monkeypatch=monkeypatch)
    assert chat.status_code == 200, chat.text
    assert "scatter" in chat.json()["reply"].lower()
    assert "go deeper" not in chat.json()["reply"].lower()
    iv = _send(client, student_id, h, "Why is the sky blue?", "vex",
               mode="interview", language="en", monkeypatch=monkeypatch)
    assert iv.status_code == 200, iv.text
    assert "scatter" not in iv.json()["reply"].lower()
    assert "go deeper" in iv.json()["reply"].lower()


# ------------------------------------------------------------------ greeting + identity determinism (Phase 1 retest)

def test_pure_greeting_is_the_personas_own_greeting(monkeypatch):
    """A bare 'hello' gets the persona's deterministic greeting — never the
    model's meta-commentary ('You said hello...') or a topic/assessment offer."""
    reply = genai.tutor_reply("hello", "ctx", None, "Cybersecurity Analyst",
                              tutor_id="vex", mode="chat", language="en")
    assert reply == genai._GREETING_EN["vex"]
    for banned in ("you said", "this is", "as this", "acknowledge", "would you like",
                   "assessment", "knowledge check", "topic you wish"):
        assert banned not in reply.lower()
    arabic = genai.tutor_reply("مرحبا", "ctx", None, "Cybersecurity Analyst",
                               tutor_id="sage", mode="chat", language="ar")
    assert arabic == genai._GREETING_AR["sage"]
    assert "حسب" not in arabic  # never a profile/assessment redirect


def test_greeting_stays_scoped_to_single_tokens(monkeypatch):
    """'hello there' is not a pure greeting — it keeps the normal provider path."""
    reply = genai.tutor_reply("hello there", "ctx", None, "Cybersecurity Analyst",
                              tutor_id="nova", mode="chat", language="en")
    assert reply != genai._GREETING_EN["nova"]


def test_identity_reply_ends_on_canonical_identity_no_assessment_offer(monkeypatch):
    """An identity question always ends on the canonical persona identity — never
    a trailing knowledge-check, topic offer, or assessment nudge."""
    reply = genai.tutor_reply("Who are you?", "ctx", None, "Cybersecurity Analyst",
                              tutor_id="vex", mode="chat", language="en")
    assert reply == genai._identity_fallback("vex", "en")
    assert "Vex" in reply and "Examiner" in reply
    for banned in ("would you like", "assessment", "knowledge check", "optional",
                   "topic you wish", "as this is"):
        assert banned not in reply.lower()
    ar = genai.tutor_reply("مين انت؟", "ctx", None, "Cybersecurity Analyst",
                           tutor_id="vex", mode="chat", language="ar")
    assert ar == genai._identity_fallback("vex", "ar")


def test_arabic_trusted_skills_block_dedupes_and_keeps_names_verbatim():
    """The Arabic trusted block: fully-Arabic counts (never 'skill مطلوب'),
    verbatim English skill names (never a fumbled calque), no duplicates."""
    ctx = (
        "University: Cairo University\n"
        "Target career: Cybersecurity Analyst\n"
        "Career readiness: 62.5% match to the target role\n"
        "Required-skill status: 12 required skills (7 below requirement).\n"
        "- Active Directory: you do not have it yet\n"
        "- Communication: you already meet the requirement [Verified]\n"
        "- Threat Detection: you already meet the requirement\n"
        "- Threat Detection: you already meet the requirement\n"
        "- Security Monitoring: you do not have it yet\n"
        "Recommended next step: work on 'Active Directory' next.\n"
    )
    block = genai._arabic_trusted_skills_block(ctx, "Cybersecurity Analyst")
    assert "Threat Detection" in block
    assert block.count("Threat Detection") == 1  # deduped
    assert block.count("Security Monitoring") == 1
    assert "Security Monitoring" in block  # verbatim English, never calque
    assert "الاحتجاز" not in block and "detention" not in block
    assert "12 مهارة مطلوبة" in block
    assert "7" in block
    assert "skill مطلوب" not in block and "skill" not in block.lower()
    assert "متقنة تماماً" in block
    assert "(موثّقة)" in block  # Verified marker present
    assert "لسه محتاج تكتسبها" in block


def test_arabic_profile_turn_injects_trusted_block_and_keeps_fallback(monkeypatch):
    """The real Arabic personal-claim turn receives the trusted Arabic block in
    the user prompt (source data for the provider) while the deterministic
    fallback still answers from the trusted English context."""
    cap = _capture_complete(monkeypatch)
    ctx = (
        "Target career: Cybersecurity Analyst\n"
        "Career readiness: 62% match to the target role\n"
        "Required-skill status: 12 required skills (7 below requirement).\n"
        "- Active Directory: you do not have it yet\n"
        "- Security Monitoring: you do not have it yet\n"
        "- Threat Detection: you already meet the requirement\n"
    )
    reply = genai.tutor_reply("هل أكون جاهز للدور ده حسب SkillBridge؟", ctx,
                              "Threat Detection", "Cybersecurity Analyst",
                              tutor_id="nova", mode="chat", language="ar")
    user = cap["user"]
    assert "Trusted Arabic SkillBridge summary" in user
    assert "12 مهارة مطلوبة" in user
    assert "Security Monitoring" in user
    assert "- Threat Detection: متقنة تماماً" in user
    assert "Security Monitoring: لسه محتاج تكتسبها" in user
    assert "حسب بروفايلك في SkillBridge" in reply  # deterministic fallback answer
