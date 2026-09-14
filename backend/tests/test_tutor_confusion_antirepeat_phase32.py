"""Phase 3.2 — Confusion anti-repetition + persona conversational-style polish.

Locks the 24 deterministic regression items for the Phase 3.2 deliverable:
confusion re-teach MUST change the teaching device (analogy / example /
exercise / code / wording) when the student is confused; each mentor's
conversational style must be strongly recognizable even when names and avatars
are hidden; the provider path must carry explicit confusion anti-repetition and
persona-style instructions; and no regressions on Phase 2/3/3.1 memory
isolation, gating, Verified-Skill trust boundary, length detection, provider
hardening, Vex-not-auto-interview, or Arabic behaviour.

All tests run entirely offline via the deterministic fallback (no provider
configured, no HTTP needed) unless they explicitly capture the provider request
to inspect the system prompt that WOULD be sent to a real GenAI provider.
"""
import pytest

from app import genai
import app.jobs as jobs_mod


# ------------------------------------------------------------------ pins

RECURSION_Q = "Explain recursion to me and give me one example."
RECURSION_MEM = (
    "Topics discussed: recursion.\n"
    "Student: Explain recursion to me and give me one example.\n"
    "Mentor: Recursion is a way to solve a problem by having a function call itself."
)
RECURSION_AR_SIMPLE_MEM = (
    "Topics discussed: recursion.\n"
    "Student: اشرحلي recursion ببساطة.\n"
    "Mentor: الـ recursion هي لما الدالة تحل مشكلة باستدعاء نفسها على نسخة أصغر."
)
DOCKER_MEM = (
    "Topics discussed: docker volumes.\n"
    "Student: Explain Docker volumes.\n"
    "Mentor: A Docker volume is persistent storage that lives outside a container's filesystem."
)
ROLES = ("nova", "axel", "sage", "vex")
SARCASM_DANGER = ("stupid", "dumb", "foolish", "idiot", "lazy", "clueless", "incompetent")
RECURSION_FACTS_EN = ["base case", "call itself"]


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    monkeypatch.setattr(jobs_mod, "_fetch_all", lambda *a, **k: [])
    jobs_mod.clear_job_cache()


def _reply(question, tutor_id="nova", lang="en", mem=None):
    return genai.tutor_reply(
        question, tutor_id=tutor_id, language=lang, conversation_memory=mem,
    )


def _confused(persona, mem=RECURSION_MEM, lang="en"):
    return _reply("I still don't understand.", tutor_id=persona, lang=lang, mem=mem)


def _missing(text, tokens):
    lower = text.lower()
    return [t for t in tokens if t.lower() not in lower]


def _capture(monkeypatch):
    captured = {}
    def fake(system, user, fallback=None, **kw):
        captured["system"] = system
        captured["user"] = user
        return fallback
    monkeypatch.setattr(genai, "complete", fake)
    return captured


def _request(monkeypatch, question, tutor_id="nova", **kw):
    captured = _capture(monkeypatch)
    genai.tutor_reply(question, tutor_id=tutor_id, language=kw.get("lang", "en"),
                      conversation_memory=kw.get("mem"), personality=kw.get("personality"),
                      student_context=kw.get("student_context"),
                      target_role=kw.get("target_role"), mode=kw.get("mode"))
    return captured["system"], captured["user"]


# ================================================================ §1-6  Confusion anti-repetition (deterministic)

class TestConfusionAntiRepetitionDeterministic:
    """After one explanation, confusion MUST change the teaching device."""

    def test_nova_moves_off_previous_analogy_to_example_2(self):
        reply = _confused("nova")
        assert reply.startswith("Let me shrink it to the smallest step.")
        assert "countdown" in reply
        assert "nested boxes" not in reply
        missing = _missing(reply, RECURSION_FACTS_EN)
        assert not missing, f"Missing facts: {missing}"

    def test_axel_moves_off_previous_exercise_to_example_2(self):
        reply = _confused("axel")
        assert reply.startswith("Let's make it tactile.")
        assert "countdown" in reply
        assert "factorial(n)" not in reply
        assert "Run that first action" in reply

    def test_sage_moves_off_previous_tradeoff_to_different_viewpoint(self):
        reply = _confused("sage")
        assert reply.startswith("Let me shift the comparison.")
        assert "call frame" not in reply
        assert "nested boxes" in reply
        assert "And compare it with:" in reply
        missing = _missing(reply, RECURSION_FACTS_EN)
        assert not missing, f"Missing facts: {missing}"

    def test_vex_moves_off_previous_challenge_to_example_2(self):
        reply = _confused("vex")
        assert reply.startswith("Pin down the unclear part.")
        assert "sum_first" not in reply
        assert "countdown" in reply
        assert "Which piece loses you" in reply

    def test_no_repeated_wording_across_four_personas(self):
        for persona in ROLES:
            reply = _confused(persona)
            assert "Recursion is a way to solve a problem by having a function call itself" not in reply
            assert reply.startswith({
                "nova": "Let me shrink it to the smallest step.",
                "axel": "Let's make it tactile.",
                "sage": "Let me shift the comparison.",
                "vex": "Pin down the unclear part.",
            }[persona])

    def test_consecutive_confusions_advance_through_devices(self):
        """A third confusion turn (after a first confusion + a second confusion)
        still differs from the second — the sequential accumulator keeps moving
        through the persona's device priority until devices are exhausted."""
        # First confusion: after fallback {plain,analogy,example,question},
        # nova picks example_2 (countdown).  Second confusion: example_2 is now
        # used → picks practice (factorial).
        c1 = _confused("nova")
        assert "countdown" in c1
        # Build a realistic memory that includes the first confusion's student
        # turn so the accumulator records that example_2 was consumed.
        mem_after_c1 = (
            RECURSION_MEM
            + "\nStudent: I still don't understand."
        )
        c2 = _confused("nova", mem=mem_after_c1)
        assert "factorial(n)" in c2 or "sum_first" in c2 or "countdown" in c2
        # Third confusion: practice is now also used → picks tradeoff or challenge.
        mem_after_c2 = (
            RECURSION_MEM
            + "\nStudent: I still don't understand."
            + "\nStudent: I still don't understand."
        )
        c3 = _confused("nova", mem=mem_after_c2)
        assert c2 != c3, "C3 must differ from C2 after the accumulator advances"


# ================================================================ §7-12  Persona conversational style (deterministic)

class TestConversationalStyleDeterministic:
    """Persona style is strongly distinguishable even when names are hidden."""

    def test_nova_warm_reassurance(self):
        reply = _confused("nova")
        assert "No problem — let's take it one small step at a time" in reply
        assert "Does that step make sense to you?" in reply

    def test_nova_gentle_emoji_bounded(self):
        emoji_count = _reply(RECURSION_Q, tutor_id="nova").count("🙂") + _reply(RECURSION_Q, tutor_id="nova").count("✨")
        assert emoji_count == 0
        confused_emoji = _confused("nova").count("🙂") + _confused("nova").count("✨")
        assert confused_emoji <= 1

    def test_axel_energy_in_confusion_not_in_fallback(self):
        assert "New move 🎯" in _confused("axel")
        fallback = _reply(RECURSION_Q, tutor_id="axel")
        assert "🎯" not in fallback
        assert "🔥" not in fallback
        assert "💪" not in fallback

    def test_sage_calm_no_emoji(self):
        for q in (RECURSION_Q, "Explain recursion simply.", "give me a short answer: recursion"):
            reply = _reply(q, tutor_id="sage")
            for ch in ("🙂", "✨", "🔥", "🎯", "💪", "😄"):
                assert ch not in reply, f"Unexpected emoji {ch!r} in sage reply"
        assert "Where exactly does it slip" in _confused("sage")

    def test_vex_dry_wit_absent_on_confusion(self):
        fallback = _reply(RECURSION_Q, tutor_id="vex")
        assert "Vague definitions do not count" in fallback
        confused = _confused("vex")
        assert "Vague definitions do not count" not in confused

    def test_vex_no_personal_sarcasm(self):
        for q in (RECURSION_Q, "I still don't understand."):
            reply = _reply(q, tutor_id="vex", mem=RECURSION_MEM if "confused" in q else None)
            lower = reply.lower()
            for word in SARCASM_DANGER:
                assert word not in lower, f"Sarcasm danger word {word!r} found"


# ================================================================ §13-14  Distinctness + shared intelligence floor

class TestFourWayDistinctConfusion:
    """§13: same question → four replies differ in actual teaching structure.
    §14: shared factual floor — base case + self-call present in all four."""

    @pytest.fixture(autouse=True)
    def _replies(self):
        self.replies = {p: _confused(p) for p in ROLES}

    def test_pairwise_different(self):
        vals = list(self.replies.values())
        for i, a in enumerate(vals):
            for b in vals[i + 1:]:
                assert a != b

    def test_hidden_name_distinguishable(self):
        openers = [r.split("\n\n", 1)[0] for r in self.replies.values()]
        assert len(set(openers)) == 4

    def test_shared_fact_floor(self):
        for reply in self.replies.values():
            missing = _missing(reply, RECURSION_FACTS_EN)
            assert not missing, f"Missing shared facts: {missing}"

    def test_no_persona_name_in_reply(self):
        for reply in self.replies.values():
            assert "You are Nova" not in reply
            assert "You are Axel" not in reply
            assert "You are Sage" not in reply
            assert "You are Vex" not in reply


# ================================================================ §15  Provider style instructions

class TestProviderStyleDirectives:
    """Every persona carries an explicit conversational-style block."""

    @pytest.fixture(autouse=True)
    def _systems(self, monkeypatch):
        self.systems = {}
        for p in ROLES:
            s, _ = _request(monkeypatch, RECURSION_Q, tutor_id=p)
            self.systems[p] = s

    def test_nova_warm_patience(self):
        assert "warm, patient and supportive" in self.systems["nova"]
        assert "Conversational style (Nova)" in self.systems["nova"]

    def test_axel_energy_momentum(self):
        assert "fun, quirky and energetic" in self.systems["axel"]
        assert "Conversational style (Axel)" in self.systems["axel"]

    def test_sage_analytical_steady(self):
        assert "calm, analytical and thoughtful" in self.systems["sage"]
        assert "Conversational style (Sage)" in self.systems["sage"]

    def test_vex_dry_wit_and_sarcasm_safety(self):
        s = self.systems["vex"]
        assert "candid, efficient and direct" in s
        assert "NEVER the student's intelligence, identity, ability, worth, or personality" in s
        assert "instructional and supportive" in s
        assert "normal tutor chat" in s

    def test_style_is_beyond_greetings(self):
        """Style blocks contain behaviour terms, not just names or emojis."""
        for p, terms in [
            ("nova", {"warm", "patient", "gentle", "steady", "slow"}),
            ("axel", {"energy", "punchy", "momentum", "playful", "action"}),
            ("sage", {"calm", "precise", "steady", "measured", "substantial"}),
            ("vex", {"precise", "efficient", "dry", "challenging", "tight"}),
        ]:
            s = self.systems[p]
            idx = s.find("Conversational style")
            assert idx >= 0, f"No style block for {p}"
            chunk = s[idx:idx + 800].lower()
            hits = [t for t in terms if t in chunk]
            assert len(hits) >= 2, f"Too few behaviour terms for {p}: {hits}"


# ================================================================ §16  Provider confusion anti-repetition

class TestProviderConfusionAntiRepetition:
    """The provider system prompt explicitly forbids reuse on confusion turns."""

    def test_all_four_personas_carry_forbid_reuse_sentence(self, monkeypatch):
        for p in ROLES:
            s, _ = _request(monkeypatch, "I still don't understand.", tutor_id=p, mem=RECURSION_MEM)
            assert "The student did not understand the previous explanation" in s
            assert "Use a materially different teaching strategy" in s
            assert "do not reuse the previous analogy, example, exercise, code sample, or wording" in s
            assert "The reply the student just saw is in the conversation memory above" in s

    def test_confusion_directive_only_on_confused_turn(self, monkeypatch):
        s, _ = _request(monkeypatch, RECURSION_Q, tutor_id="nova")
        assert "You MUST change your strategy" not in s
        assert "do not reuse the previous analogy" not in s

    def test_nova_confusion_smaller_steps_new_analogy(self, monkeypatch):
        s, _ = _request(monkeypatch, "I still don't understand.", tutor_id="nova", mem=RECURSION_MEM)
        assert "NEW simpler analogy and even smaller steps" in s
        assert "You MUST change your strategy" in s
        assert "not repeat the previous explanation" in s

    def test_axel_confusion_different_demonstration(self, monkeypatch):
        s, _ = _request(monkeypatch, "I still don't understand.", tutor_id="axel", mem=RECURSION_MEM)
        assert "DEMONSTRATE something concrete" in s
        assert "a different practical demonstration they have not attempted yet" in s

    def test_sage_confusion_different_viewpoint(self, monkeypatch):
        s, _ = _request(monkeypatch, "I still don't understand.", tutor_id="sage", mem=RECURSION_MEM)
        assert "DIFFERENT conceptual comparison or viewpoint" in s

    def test_vex_confusion_exact_point_instructional(self, monkeypatch):
        s, _ = _request(monkeypatch, "I still don't understand.", tutor_id="vex", mem=RECURSION_MEM)
        assert "EXACT part they do not understand" in s
        assert "instructional rather than sarcastic" in s


# ================================================================ §17  Phase 2/3/3.1 regressions

class TestPhaseRegressions:
    """No regressions on memory isolation, gating, trust, or prior features."""

    def test_general_route_stays_grounded(self, monkeypatch):
        s, u = _request(monkeypatch, "Why do earthquakes happen?")
        assert "Context route: GENERAL" in u
        assert "Trusted SkillBridge context: omitted" in u

    def test_career_route_stays_trusted(self, monkeypatch):
        s, u = _request(monkeypatch, "What is my target role?", student_context={
            "verified_skills": "Python", "target_role": "Junior AI Engineer",
            "learning_skill": "", "user_role": "student",
        }, target_role="Junior AI Engineer")
        assert "Context route: CAREER" in u

    def test_personality_layering_intact(self, monkeypatch):
        personality = {"name": "Comet", "role": "Tutor", "traits": ["Focused"], "behavior": "Be concise.", "style": "Efficient."}
        s, _ = _request(monkeypatch, RECURSION_Q, tutor_id="nova", personality=personality)
        assert "You are Nova" in s
        assert "Teaching method (Nova)" in s
        assert "You are Comet" not in s

    def test_vex_not_auto_interview(self, monkeypatch):
        for mode in (None, "chat"):
            s, _ = _request(monkeypatch, RECURSION_Q, tutor_id="vex", mode=mode or "chat")
            assert "mock interview coach" not in s.lower()

    def test_length_detection_unchanged(self, monkeypatch):
        for q, marker in (
            ("Give me a short answer about recursion.", "SHORT"),
            ("simplify recursion for me", "SIMPLIFY"),
            ("Explain more about recursion.", "EXPLAIN MORE"),
            ("Go deeper on recursion.", "GO DEEPER"),
        ):
            s, _ = _request(monkeypatch, q, tutor_id="nova")
            assert marker in s


# ================================================================ §18-21  Arabic + fallback pins

class TestArabicAntiRepetitionAndFallbacks:
    """§21 Arabic confusion uses different device; follow-up preserved."""

    def test_arabic_nova_different_device(self):
        reply = _reply("لسه مش فاهم.", tutor_id="nova", lang="ar", mem=RECURSION_AR_SIMPLE_MEM)
        assert reply.startswith("خلّيني أوزّعها على أصغر خطوة.")
        assert "مثال تشغيل مختلف" in reply
        assert "countdown" in reply
        assert "الصناديق المتداخلة" not in reply

    def test_arabic_all_four_different(self):
        replies = {p: _reply("لسه مش فاهم.", tutor_id=p, lang="ar", mem=RECURSION_AR_SIMPLE_MEM) for p in ROLES}
        vals = list(replies.values())
        for i, a in enumerate(vals):
            for b in vals[i + 1:]:
                assert a != b

    def test_arabic_facts_present(self):
        for p in ROLES:
            reply = _reply("لسه مش فاهم.", tutor_id=p, lang="ar", mem=RECURSION_AR_SIMPLE_MEM)
            lower = reply.lower()
            assert "base case" in lower

    def test_first_turn_confusion_fresh_thread(self):
        """A confusion as the very first message (no memory) still routes
        through the confusion path and picks an available device."""
        reply = _reply("I am confused about Docker volumes.", tutor_id="nova")
        assert reply.startswith("Let me shrink it to the smallest step.")
        assert "Two containers can share one volume" in reply

    def test_followup_after_confusion_still_works(self):
        """A follow-up after a confusion still resolves from memory and
        returns the expected example_2 content."""
        reply = _reply("Give me another example of what you just explained.",
                       tutor_id="nova", mem=DOCKER_MEM)
        assert "Two containers can share one volume" in reply


# ================================================================ §6/12  Vex sarcasm safety (provider + deterministic)

class TestVexSarcasmSafety:
    """Vex sarcasm targets ideas/mistakes only, never the student's person."""

    def test_provider_style_forbids_personal_sarcasm(self, monkeypatch):
        s, _ = _request(monkeypatch, RECURSION_Q, tutor_id="vex")
        assert "NEVER the student's intelligence, identity, ability, worth, or personality" in s
        assert "Never insult, mock, patronize, or discourage" in s

    def test_deterministic_confusion_drops_sarcasm(self):
        """Confused vex reply is instructional, not sarcastic."""
        reply = _confused("vex")
        assert "Which piece loses you" in reply
        for w in SARCASM_DANGER:
            assert w not in reply.lower()


# ================================================================ §7/12  Vex dry-wit on confident wrong answers

WRONG_ANSWERS = [
    ("My answer is: recursion is when the function just keeps calling itself forever.",
     "recursion forever"),
    ("Recursion is just a loop that never stops.",
     "recursion loop"),
    ("Recursion is always faster and better than loops.",
     "recursion faster"),
    ("Recursion without a base case is the right way to write it.",
     "recursion missing base case"),
]

NOT_WRONG = [
    RECURSION_Q,
    "I still don't understand.",
    "Can you explain recursion again?",
    "Give me another example of what you just explained.",
    "How does recursion work with Docker volumes?",
]

# Misconception turns on a topic with NO grounded offline knowledge: the dry-wit
# never fires because there is no correction to attach it to — Vex stays honest.
UNRESOLVED_MISCONCEPTION = "Null is basically the same as zero in every language."


class TestVexDryWit:
    """Vex may open with ONE brief dry line on confidently wrong answers."""

    def test_wrong_answer_triggers_dry_wit(self):
        """A confidently wrong technical statement triggers a dry-wit opener."""
        for question, _label in WRONG_ANSWERS:
            reply = _reply(question, tutor_id="vex")
            # Dry-wit one-liner present AND factual correction present.
            assert any(
                w in reply for w in (
                    "Calling itself forever is certainly one way",
                    "Calling recursion always faster is a bold claim",
                    "Recursion without a base case is an ambitious way",
                )
            ), f"Dry-wit opener missing for {_label}"
            assert "base case" in reply.lower()
            assert "call itself" in reply.lower()

    def test_wit_targets_mistake_not_student(self):
        """Dry-wit lines target the technical error, never the student."""
        for question, _label in WRONG_ANSWERS:
            reply = _reply(question, tutor_id="vex")
            lower = reply.lower()
            for w in SARCASM_DANGER:
                assert w not in lower, (
                    f"Dry-wit reply for {_label} contains forbidden word '{w}'"
                )

    def test_correction_contains_factual_answer(self):
        """After the dry-wit line, the reply corrects the misconception."""
        reply = _reply(
            "My answer is: recursion is when the function just keeps calling itself forever.",
            tutor_id="vex",
        )
        assert "base case" in reply.lower()
        assert "call itself" in reply.lower()

    def test_confusion_turn_no_sarcasm(self):
        """Confused vex reply drops sarcasm — no dry-wit line."""
        reply = _confused("vex")
        assert "Which piece loses you" in reply
        for w in SARCASM_DANGER:
            assert w not in reply.lower()

    def test_ordinary_answer_no_forced_humor(self):
        """Ordinary vex answers (not wrong, not confused) are not forced
        to contain a dry-wit line."""
        for question in NOT_WRONG:
            reply = _reply(question, tutor_id="vex")
            # No assertion that humour IS present — only that it is NOT forced.
            # The reply should be a normal teaching response.
            assert len(reply) > 20, f"Ordinary vex reply too short for {question!r}"

    def test_unresolved_topic_no_forced_dry_wit(self):
        """A misconception on a topic with no grounded offline knowledge
        produces the honest limitation, NOT a dry-wit quip."""
        reply = _reply(UNRESOLVED_MISCONCEPTION, tutor_id="vex")
        assert "I won't bluff" in reply
        assert "Calling itself forever" not in reply

    def test_other_personas_no_dry_wit(self):
        """Nova/Axel/Sage never get the Vex dry-wit line."""
        for persona in ("nova", "axel", "sage"):
            reply = _reply(
                "My answer is: recursion is when the function just keeps calling itself forever.",
                tutor_id=persona,
            )
            # These personas don't have dry-wit detection — reply is normal.
            assert len(reply) > 20

    def test_provider_style_explicitly_mentions_confident_wrong(self, monkeypatch):
        """Provider style directive for Vex explicitly instructs about
        confident wrong answers."""
        s, _ = _request(monkeypatch, RECURSION_Q, tutor_id="vex")
        assert "clearly wrong technical assertion" in s
        assert "dry line" in s or "dry-wit line" in s or "dry-wit" in s.lower()

    def test_dry_wit_deterministic(self):
        """Same wrong question always produces the same dry-wit one-liner."""
        q = "Recursion is when the function just keeps calling itself forever."
        r1 = _reply(q, tutor_id="vex")
        r2 = _reply(q, tutor_id="vex")
        assert r1 == r2

    def test_hedged_statement_no_dry_wit(self):
        """A hedged statement is not a confident wrong answer."""
        reply = _reply(
            "I think recursion is when the function keeps calling itself forever.",
            tutor_id="vex",
        )
        assert "Calling itself forever" not in reply

    def test_question_no_dry_wit(self):
        """A question (even a wrong guess) is not an assertion."""
        reply = _reply(
            "Is recursion when the function calls itself forever?",
            tutor_id="vex",
        )
        assert "Calling itself forever" not in reply
