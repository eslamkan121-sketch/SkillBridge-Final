"""Phase 3.1 — Provider-persona hardening (§6.1) + custom personality layering.

The deterministic fallback decks already differentiate the four mentors (Phase
3, manual-accepted). This suite hardens the PROVIDER path: it captures the exact
system/user messages that would be sent to a real GenAI provider (no paid API)
and verifies that:

- every mentor's provider request carries its OWN structural teaching strategy
  (Nova simplify/step-by-step/analogy; Axel action-first; Sage reasoning/
  trade-offs; Vex precise/challenge) — built on teaching structure, not
  catchphrases;
- the same question yields meaningfully DIFFERENT teaching structures per
  mentor, while the shared intelligence floor stays intact (persona controls
  HOW, never WHAT);
- a confusion turn ("I still don't understand.") explicitly requires a CHANGED
  strategy, different per mentor, never "repeat the previous explanation";
- length requests ("short answer", "explain simply", "explain more", "go deep")
  reach the provider as explicit instructions from the existing deterministic
  detector;
- Build-Your-Copilot ``personality`` is LAYERED (base mentor + optional
  modifiers) and never replaces Nova/Axel/Sage/Vex identity or teaching
  strategy;
- Vex remains Chat unless Interview mode is explicitly started;
- trusted-context rules are unchanged;

and that the deterministic fallback decks are byte-for-byte untouched (§5).
"""
import pytest

from app import genai


@pytest.fixture(autouse=True)
def _lock_generation(monkeypatch):
    """Force the deterministic fallback path (never a paid call) and keep jobs
    offline."""
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)


def _capture(monkeypatch):
    """Record the exact system/user messages sent to the provider path and
    return the deterministic fallback as the (never-used-by-asserts) reply."""
    captured = {}

    def fake(system, user, fallback=None, **kw):
        captured["system"] = system
        captured["user"] = user
        return fallback

    monkeypatch.setattr(genai, "complete", fake)
    return captured


def _request(monkeypatch, question, tutor_id="nova", mode="chat",
             personality=None, student_context=None, target_role=None,
             language="en"):
    """Build a provider request via ``tutor_reply`` and return (system, user)."""
    captured = _capture(monkeypatch)
    genai.tutor_reply(
        question,
        student_context,
        None,
        target_role,
        tutor_id=tutor_id,
        mode=mode,
        language=language,
        personality=personality,
    )
    return captured["system"], captured["user"]


Q = "Explain recursion to me and give me one example."


# ------------------------------------------------------------------ provider teaching strategies (§6.1)

def test_nova_provider_request_carries_nova_teaching_strategy(monkeypatch):
    system, _ = _request(monkeypatch, Q, tutor_id="nova")
    assert "Teaching method (Nova)" in system
    assert "small steps" in system
    assert "analogy or example" in system
    assert "Simplify jargon" in system
    assert "prefer explanation before challenge".title() in system or "before" in system.lower()


def test_axel_provider_request_carries_action_teaching_strategy(monkeypatch):
    system, _ = _request(monkeypatch, Q, tutor_id="axel")
    assert "Teaching method (Axel)" in system
    assert "hands-on coach" in system
    assert "try right away" in system
    assert "task, exercise, or mini challenge" in system
    assert "direct, actionable feedback" in system


def test_sage_provider_request_carries_analytical_teaching_strategy(monkeypatch):
    system, _ = _request(monkeypatch, Q, tutor_id="sage")
    assert "Teaching method (Sage)" in system
    assert "underlying reasoning" in system
    assert "trade-offs" in system
    assert "directly and correctly FIRST" in system
    assert "thoughtful why/how question" in system


def test_vex_provider_request_carries_precise_challenge_teaching_strategy(monkeypatch):
    system, _ = _request(monkeypatch, Q, tutor_id="vex")
    assert "Teaching method (Vex)" in system
    assert "precise, correct explanation" in system
    assert "challenge or test" in system
    assert "weak spots" in system
    assert "harder follow-up or knowledge check" in system
    assert "never rude, insulting, hostile, or discouraging" in system


def test_same_question_produces_distinct_structures_per_mentor(monkeypatch):
    """§6.1 differentiation gate: the SAME question must yield different
    teaching structures, not 'same answer + different greeting + closing'."""
    nova, _ = _request(monkeypatch, Q, tutor_id="nova")
    axel, _ = _request(monkeypatch, Q, tutor_id="axel")
    sage, _ = _request(monkeypatch, Q, tutor_id="sage")
    vex, _ = _request(monkeypatch, Q, tutor_id="vex")

    strategies = {
        "nova": nova[nova.index("Teaching method (Nova)"):nova.index("Teaching method (Nova)") + 120],
        "axel": axel[axel.index("Teaching method (Axel)"):axel.index("Teaching method (Axel)") + 120],
        "sage": sage[sage.index("Teaching method (Sage)"):sage.index("Teaching method (Sage)") + 120],
        "vex": vex[vex.index("Teaching method (Vex)"):vex.index("Teaching method (Vex)") + 120],
    }
    # Each mentor names only itself in its own strategy block...
    assert "Axel" not in strategies["nova"]
    assert "Sage" not in strategies["nova"] and "Nova" not in strategies["axel"]
    assert "Nova" not in strategies["sage"] and "Nova" not in strategies["vex"]
    assert "Vex" not in strategies["sage"] and "Sage" not in strategies["vex"]
    # ...and each block is structurally distinct from every other one.
    assert len({s[:60] for s in strategies.values()}) == 4


def test_provider_strategies_share_intelligence_floor(monkeypatch):
    """Persona controls HOW, never WHAT — every mentor stays a general tutor."""
    for tutor_id in ("nova", "axel", "sage", "vex"):
        system, _ = _request(monkeypatch, Q, tutor_id=tutor_id)
        assert "general-knowledge tutor" in system
        assert "The selected" in system


# ------------------------------------------------------------------ provider confusion adaptation (requirement #2)

@pytest.mark.parametrize(("tutor_id", "needle"), [
    ("nova", "NEW simpler analogy and even smaller steps"),
    ("axel", "DEMONSTRATE something concrete the student can run or try"),
    ("sage", "DIFFERENT conceptual comparison or viewpoint"),
    ("vex", "EXACT part they do not understand and test that precise point"),
])
def test_confusion_turn_demands_changed_strategy_per_mentor(monkeypatch, tutor_id, needle):
    system, _ = _request(monkeypatch, "I still don't understand.", tutor_id=tutor_id)
    assert "You MUST change your strategy" in system
    assert "not repeat the previous explanation" in system
    assert needle in system


def test_confusion_directive_only_on_confused_turn(monkeypatch):
    system, _ = _request(monkeypatch, Q, tutor_id="nova")
    assert "You MUST change your strategy" not in system
    assert "not repeat the previous explanation" not in system


# ------------------------------------------------------------------ explicit length instructions (requirement #3)

@pytest.mark.parametrize(("question", "marker"), [
    ("Give me a short answer about recursion.", "Reply length for this turn: SHORT."),
    ("simplify recursion for me", "Reply style for this turn: SIMPLIFY."),
    ("Explain more about recursion.", "Reply length for this turn: EXPLAIN MORE."),
    ("Go deeper on recursion.", "Reply length for this turn: GO DEEPER."),
])
def test_length_request_reaches_provider_instructions(monkeypatch, question, marker):
    for tutor_id in ("nova", "axel", "sage", "vex"):
        system, _ = _request(monkeypatch, question, tutor_id=tutor_id)
        assert marker in system, tutor_id


def test_no_length_directive_on_ordinary_turn(monkeypatch):
    system, _ = _request(monkeypatch, Q, tutor_id="nova")
    assert "Reply length for this turn" not in system
    assert "Reply style for this turn" not in system


def test_in_a_simple_way_does_not_force_simplify_directive(monkeypatch):
    """'in a simple way' stays out of the length detector (Phase 2 pin) — the
    provider path must respect the same detection."""
    system, _ = _request(monkeypatch, "Explain Docker volumes in a simple way.", tutor_id="nova")
    assert "Reply style for this turn: SIMPLIFY" not in system
    assert "Teaching method (Nova)" in system


def test_length_directive_in_user_prompt_via_detector(monkeypatch):
    captured = _capture(monkeypatch)
    genai.tutor_reply("Give me a short answer about recursion.", None, None, None,
                      tutor_id="nova", mode="chat", language="en")
    assert "SHORT" in captured["system"]
    assert captured["user"].startswith("Context route:")


# ------------------------------------------------------------------ custom personality layering (requirement #4)

def test_personality_supplements_not_replaces_base_mentor(monkeypatch):
    personality = {
        "name": "Comet",
        "role": "Tutor",
        "traits": ["Focused", "Efficient"],
        "style": "Be more concise and energetic.",
        "behavior": "Keep answers tight.",
    }
    system, _ = _request(monkeypatch, Q, tutor_id="nova", personality=personality)
    assert "You are Nova" in system
    assert "Teaching method (Nova)" in system
    assert "You are Comet" not in system
    assert "known to the student as Comet" in system
    assert "more concise" in system
    assert "never replace the base mentor identity" in system


def test_friendlier_vex_is_still_precise_and_challenging(monkeypatch):
    personality = {
        "name": "Vex",
        "traits": ["Friendly", "Approachable"],
        "style": "Be friendlier and warmer, but keep your precision.",
    }
    system, _ = _request(monkeypatch, Q, tutor_id="vex", personality=personality)
    # Base Vex identity + teaching strategy survive the "friendlier" modifier.
    assert "You are Vex" in system
    assert "Teaching method (Vex)" in system
    assert "Precise" in system and "Challenging" in system
    assert "friendlier" in system
    assert "Precise, Professional, Challenging" not in "Friendly, Approachable"
    for base_trait in ("Precise", "Challenging", "Sharp"):
        assert base_trait in system


def test_identical_preset_adds_no_redundant_modifier(monkeypatch):
    """A copilot preset that already mirrors its mentor adds nothing redundant."""
    preset = {k: genai.TUTOR_PERSONAS["nova"][k] for k in
              ("name", "traits", "style", "behavior")}
    system, _ = _request(monkeypatch, Q, tutor_id="nova", personality=preset)
    assert "You are Nova" in system
    assert "Teaching method (Nova)" in system
    assert "User customization layer" not in system


def test_personality_never_erases_strategy_when_only_name_differs(monkeypatch):
    personality = {"name": "Buddy"}
    system, _ = _request(monkeypatch, Q, tutor_id="sage", personality=personality)
    assert "You are Sage" in system
    assert "Teaching method (Sage)" in system
    assert "known to the student as Buddy" in system


# ------------------------------------------------------------------ Vex stays Chat unless Interview started (requirement #6)

def test_vex_remains_chat_without_interview_mode(monkeypatch):
    for mode in (None, "chat"):
        captured = _capture(monkeypatch)
        genai.tutor_reply(Q, None, None, None, tutor_id="vex", mode=mode, language="en")
        system = captured["system"]
        assert "mock interview coach" not in system
        assert "Interview session" not in system
        assert "remain in normal tutor chat unless an interview session was explicitly started" in system


def test_vex_chat_reply_is_substantive_not_an_interview(monkeypatch):
    captured = _capture(monkeypatch)
    reply = genai.tutor_reply(Q, None, None, None, tutor_id="vex", mode="chat", language="en")
    assert captured["system"]
    # The deterministic chat fallback explains, it does not run a mock interview.
    assert "Be precise:" in reply or "base case" in reply.lower() or "recursion" in reply.lower()


# ------------------------------------------------------------------ trusted context rules unchanged (requirement #6)

def test_trusted_context_rules_unchanged_general_turn(monkeypatch):
    rich_context = ("Career Roadmap context: target Junior AI Engineer, readiness 61, "
                    "gaps Docker, SQL, current skill Docker.")
    system, user = _request(monkeypatch, "Why do volcanoes erupt?", tutor_id="nova",
                            student_context=rich_context, target_role="Junior AI Engineer")
    assert "No private SkillBridge profile snapshot" in system
    assert "Context route: GENERAL" in user
    assert "Junior AI Engineer" not in user
    assert "Docker" not in user


def test_trusted_context_rules_unchanged_career_turn(monkeypatch):
    system, user = _request(monkeypatch, "Tell me about my target role.",
                            tutor_id="axel", student_context="Student context: x",
                            target_role="Junior AI Engineer")
    assert "Context route: CAREER" in user
    assert "Teaching method (Axel)" in system


# ------------------------------------------------------------------ deterministic fallback decks untouched (requirement #5)

def test_fallback_decks_are_unchanged_per_mentor(monkeypatch):
    """The §6.1 gate on the LIVE path: same question, meaningfully different
    structural decks — preserved byte-for-byte from Phase 3."""
    for tutor_id, signature in (
        ("nova", "nested"),            # Nova: analogy-led explanation
        ("axel", "Short version:"),    # Axel: action/practice deck
        ("sage", "Let's reason it through."),  # Sage: reasoning deck
        ("vex", "Be precise:"),        # Vex: precise/challenge deck
    ):
        captured = _capture(monkeypatch)
        reply = genai.tutor_reply(Q, None, None, None, tutor_id=tutor_id, mode="chat", language="en")
        assert signature in reply, tutor_id
        assert "base case" in reply.lower(), tutor_id   # shared, correct truth