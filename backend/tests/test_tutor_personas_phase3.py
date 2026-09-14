"""Phase 3 — Mentor persona differentiation, length/confusion adaptation.

Exercises the 17 behavioral assertions for the tutor persona Phase 3
deliverable.  All tests run entirely offline via the deterministic fallback
(no provider configured, no HTTP needed for persona/length/confusion tests).
"""

import re

import pytest

from app import genai
import app.jobs as jobs_mod


RECURSION_Q = "Explain recursion to me and give me one example."
RECURSION_MEM = (
    "Topics discussed: recursion.\n"
    "Student: Explain recursion to me and give me one example.\n"
    "Mentor: Recursion is a way to solve a problem by having a function call itself."
)
RECURSION_FACTS_EN = ["base case", "call itself"]
RECURSION_FACTS_AR = ["recursion", "base case"]
TARGET_ROLE = "Junior AI Engineer"
ROLES = ("nova", "axel", "sage", "vex")


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
    """Force deterministic fallback + offline jobs."""
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    monkeypatch.setattr(jobs_mod, "_fetch_all", lambda *a, **k: [])
    jobs_mod.clear_job_cache()


# ------------------------------------------------------------------ helpers

def _reply(question, tutor_id="nova", lang="en", mem=None):
    return genai.tutor_reply(
        question, tutor_id=tutor_id, language=lang,
        conversation_memory=mem,
    )


def _missing(text, tokens):
    lower = text.lower()
    return [t for t in tokens if t.lower() not in lower]


# ---------------------------------------------------- P1–P3: four personas different + facts

class TestFourPersonasDifferent:
    """P1: four replies are pairwise structurally different.
    P2: each reply contains the factually correct base case + self-call.
    P3: Nova analogy-led, Axel practice/action, Sage tradeoff, Vex challenge."""

    @pytest.fixture(autouse=True)
    def _replies(self):
        self.replies = {
            p: _reply(RECURSION_Q, tutor_id=p) for p in ROLES
        }

    def test_pairwise_different(self):
        values = list(self.replies.values())
        for i, a in enumerate(values):
            for b in values[i + 1:]:
                assert a != b

    def test_nova_starts_with_plain_not_prefix(self):
        assert self.replies["nova"].startswith("Recursion is a way")

    def test_axel_starts_with_practical_prefix(self):
        assert self.replies["axel"].startswith("Short version:")

    def test_sage_starts_with_reasoning_prefix(self):
        assert self.replies["sage"].startswith("Let's reason it through.")

    def test_vex_starts_with_challenge_prefix(self):
        assert self.replies["vex"].startswith("Be precise:")

    def test_nova_includes_analogy(self):
        assert "nested boxes" in self.replies["nova"]

    def test_axel_includes_practice(self):
        assert "factorial" in self.replies["axel"]

    def test_sage_includes_tradeoff(self):
        assert "call frame" in self.replies["sage"]

    def test_vex_includes_challenge(self):
        assert "sum_first" in self.replies["vex"]

    def test_all_four_contain_recursion_facts(self):
        for reply in self.replies.values():
            missing = _missing(reply, RECURSION_FACTS_EN)
            assert not missing, f"Missing facts in reply: {missing}"


# ---------------------------------------------------- P4: EN simply → SIMPLE mode

class TestSimpleModeEN:
    """P4: 'explain recursion simply' routes to the SIMPLE deck per persona."""

    @pytest.fixture(autouse=True)
    def _replies(self):
        self.replies = {
            p: _reply("Explain recursion simply.", tutor_id=p) for p in ROLES
        }

    def test_nova_simple_starts_with_simpler_prefix(self):
        assert self.replies["nova"].startswith("Let me make that simpler.")

    def test_nova_simple_includes_analogy(self):
        assert "nested boxes" in self.replies["nova"]

    def test_axel_simple_starts_with_concrete_prefix(self):
        assert self.replies["axel"].startswith("Make it concrete.")

    def test_axel_simple_includes_practice(self):
        assert "factorial" in self.replies["axel"]

    def test_sage_simple_starts_with_reframe_prefix(self):
        assert self.replies["sage"].startswith("Let me reframe the same idea.")

    def test_vex_simple_starts_with_plainly_prefix(self):
        assert self.replies["vex"].startswith("Plainly:")

    def test_all_simple_contain_recursion_facts(self):
        for reply in self.replies.values():
            missing = _missing(reply, RECURSION_FACTS_EN)
            assert not missing, f"Missing facts in SIMPLE reply: {missing}"

    def test_nova_simple_is_different_from_nova_fallback(self):
        fallback = _reply(RECURSION_Q, tutor_id="nova")
        assert self.replies["nova"] != fallback


# ---------------------------------------------------- P5: AR short → SHORT mode

class TestShortModeAR:
    """P5: Arabic short request routes to SHORT deck per persona."""

    @pytest.fixture(autouse=True)
    def _replies(self):
        self.replies = {
            p: _reply("عاوز الإجابة قصيرة عن recursion.", tutor_id=p, lang="ar")
            for p in ROLES
        }

    def test_nova_ar_short_prefix(self):
        assert self.replies["nova"].startswith("الخلاصة:")

    def test_axel_ar_short_prefix(self):
        assert self.replies["axel"].startswith("الخلاصة:")

    def test_sage_ar_short_prefix(self):
        assert self.replies["sage"].startswith("باختصار:")

    def test_vex_ar_short_prefix(self):
        assert self.replies["vex"].startswith("بدقة:")

    def test_ar_short_contains_recursion_ar_text(self):
        for reply in self.replies.values():
            missing = _missing(reply, RECURSION_FACTS_AR)
            assert not missing, f"Missing facts in AR SHORT: {missing}"


# ---------------------------------------------------- P6: AR simple → SIMPLE mode

class TestSimpleModeAR:
    """P6: 'اشرحلي recursion ببساطة' routes to the AR SIMPLE deck."""

    @pytest.fixture(autouse=True)
    def _replies(self):
        self.replies = {
            p: _reply("اشرحلي recursion ببساطة.", tutor_id=p, lang="ar")
            for p in ROLES
        }

    def test_nova_ar_simple_prefix(self):
        assert "أوضحها أبسط" in self.replies["nova"]

    def test_axel_ar_simple_prefix(self):
        assert "عملية" in self.replies["axel"]

    def test_sage_ar_simple_prefix(self):
        assert "منظور مختلف" in self.replies["sage"]

    def test_vex_ar_simple_prefix(self):
        assert self.replies["vex"].startswith("بوضوح:")

    def test_ar_simple_contains_recursion(self):
        for reply in self.replies.values():
            assert "recursion" in reply.lower()


# ---------------------------------------------------- P7: EN more → MORE mode

class TestMoreModeEN:
    """P7: 'explain recursion in more detail' routes to the MORE deck."""

    @pytest.fixture(autouse=True)
    def _replies(self):
        self.replies = {
            p: _reply("explain recursion in more detail", tutor_id=p)
            for p in ROLES
        }

    def test_nova_more_includes_example2(self):
        assert "countdown" in self.replies["nova"]

    def test_axel_more_prefix(self):
        assert self.replies["axel"].startswith("Short version:")

    def test_axel_more_includes_example2(self):
        assert "countdown" in self.replies["axel"]

    def test_sage_more_prefix(self):
        assert self.replies["sage"].startswith("Let's reason it through.")

    def test_sage_more_includes_example2(self):
        assert "countdown" in self.replies["sage"]

    def test_vex_more_prefix(self):
        assert self.replies["vex"].startswith("Be precise:")

    def test_vex_more_includes_example2(self):
        assert "countdown" in self.replies["vex"]


# ---------------------------------------------------- P8: EN go deep → DEEP mode

class TestDeepModeEN:
    """P8: 'go deep on recursion' routes to the DEEP deck."""

    @pytest.fixture(autouse=True)
    def _replies(self):
        self.replies = {
            p: _reply("go deep on recursion", tutor_id=p)
            for p in ROLES
        }

    def test_nova_deep_includes_tradeoff(self):
        assert "call frame" in self.replies["nova"]

    def test_axel_deep_prefix(self):
        assert self.replies["axel"].startswith("Short version:")

    def test_sage_deep_prefix(self):
        assert self.replies["sage"].startswith("Let's reason it through.")

    def test_sage_deep_includes_going_deeper(self):
        assert "Going deeper:" in self.replies["sage"]

    def test_vex_deep_prefix(self):
        assert self.replies["vex"].startswith("Precisely:")

    def test_vex_deep_includes_edge_case(self):
        assert "edge case" in self.replies["vex"]


# ---------------------------------------------------- P9: Confusion + memory → CONFUSED mode

class TestConfusionWithMemory:
    """P9: confusion with memory resolves topic and uses the CONFUSED deck."""

    @pytest.fixture(autouse=True)
    def _replies(self):
        self.replies = {
            p: _reply("I still don't understand.", tutor_id=p, mem=RECURSION_MEM)
            for p in ROLES
        }

    def test_nova_confused_starts_with_smallest_step(self):
        assert self.replies["nova"].startswith("Let me shrink it to the smallest step.")

    def test_axel_confused_starts_with_tactile(self):
        assert self.replies["axel"].startswith("Let's make it tactile.")

    def test_sage_confused_starts_with_shift_comparison(self):
        assert self.replies["sage"].startswith("Let me shift the comparison.")

    def test_vex_confused_starts_with_pin_down(self):
        assert self.replies["vex"].startswith("Pin down the unclear part.")

    def test_confused_contains_recursion_facts(self):
        for reply in self.replies.values():
            missing = _missing(reply, RECURSION_FACTS_EN)
            assert not missing, f"Missing facts in confusion reply: {missing}"

    def test_confused_has_strategy_check_in(self):
        assert "Does that step make sense" in self.replies["nova"]
        assert "Run that first action" in self.replies["axel"]
        assert "Where exactly does it slip" in self.replies["sage"]
        assert "Which piece loses you" in self.replies["vex"]


# ---------------------------------------------------- P10: Confusion WITHOUT memory → limitation

class TestConfusionWithoutMemory:
    """P10: confusion with no memory thread → honest limitation."""

    def test_no_memory_gives_limitation(self):
        reply = _reply("I still don't understand.", tutor_id="nova")
        assert "reliably offline" in reply or "reliable" in reply.lower()
        assert "recursion" not in reply.lower()

    def test_confusion_identifies_not_followup(self):
        reply = _reply("I am confused.", tutor_id="sage")
        assert "reliably" in reply.lower() or "reliable" in reply.lower()


# ---------------------------------------------------- P11: Follow-up + memory → example_2

class TestFollowUpWithMemory:
    """P11: follow-up with memory resolves topic, returns example_2, no restatement."""

    @pytest.fixture(autouse=True)
    def _replies(self):
        self.replies = {
            p: _reply("Give me another example of what you just explained.",
                       tutor_id=p, mem=RECURSION_MEM)
            for p in ROLES
        }

    def test_all_contain_example2(self):
        for reply in self.replies.values():
            assert "countdown" in reply

    def test_nova_followup_prefix(self):
        assert self.replies["nova"].startswith("Another example:")

    def test_axel_followup_prefix(self):
        assert "different concrete angle" in self.replies["axel"]

    def test_followup_no_plain_restatement(self):
        for reply in self.replies.values():
            assert "Recursion is a way to solve a problem by having a function call itself" not in reply


# ---------------------------------------------------- P12: No target-role leakage

class TestNoTargetRoleLeakage:
    """P12: general topic replies never leak the target role."""

    def test_nova_recursion_no_role(self):
        reply = _reply(RECURSION_Q, tutor_id="nova")
        assert TARGET_ROLE not in reply
        assert "your target role" not in reply.lower()

    def test_axel_recursion_no_role(self):
        reply = _reply(RECURSION_Q, tutor_id="axel")
        assert TARGET_ROLE not in reply
        assert "your target role" not in reply.lower()

    def test_simple_en_no_role(self):
        reply = _reply("explain recursion simply.", tutor_id="sage")
        assert TARGET_ROLE not in reply

    def test_short_ar_no_role(self):
        reply = _reply("عاوز الإجابة قصيرة عن recursion.", tutor_id="vex", lang="ar")
        assert "Junior AI Engineer" not in reply
        assert "target role" not in reply.lower()

    def test_confusion_no_role(self):
        reply = _reply("I still don't understand.", tutor_id="nova", mem=RECURSION_MEM)
        assert TARGET_ROLE not in reply


# ---------------------------------------------------- P13: SHORT prefix per persona

class TestShortPrefixPerPersona:
    """P13: short-answer request produces the SHORT prefix for each persona."""

    @pytest.fixture(autouse=True)
    def _replies(self):
        self.replies = {
            p: _reply("give me a short answer: recursion", tutor_id=p)
            for p in ROLES
        }

    def test_nova_short_prefix(self):
        assert self.replies["nova"].startswith("Quick take:")

    def test_axel_short_prefix(self):
        assert self.replies["axel"].startswith("Bottom line:")

    def test_sage_short_prefix(self):
        assert self.replies["sage"].startswith("In short:")

    def test_vex_short_prefix(self):
        assert self.replies["vex"].startswith("Precisely:")

    def test_short_contains_recursion_fact(self):
        for reply in self.replies.values():
            missing = _missing(reply, RECURSION_FACTS_EN)
            assert not missing, f"Missing facts in SHORT reply: {missing}"


# ---------------------------------------------------- P14: AR personas different

class TestFourPersonasDifferentAR:
    """P14: AR recursion replies are pairwise structurally different."""

    @pytest.fixture(autouse=True)
    def _replies(self):
        self.replies = {
            p: _reply("اشرحلي recursion ببساطة.", tutor_id=p, lang="ar")
            for p in ROLES
        }

    def test_pairwise_different(self):
        values = list(self.replies.values())
        for i, a in enumerate(values):
            for b in values[i + 1:]:
                assert a != b

    def test_all_contain_recursion(self):
        for reply in self.replies.values():
            assert "recursion" in reply.lower()


# ---------------------------------------------------- P15: Confusion vs follow-up structurally distinct

class TestConfusionVsFollowUpDistinct:
    """P15: confusion and follow-up produce structurally different replies."""

    def test_nova_confusion_vs_followup(self):
        mem = RECURSION_MEM
        confused = _reply("I still don't understand.", tutor_id="nova", mem=mem)
        followup = _reply("Give me another example of what you just explained.",
                           tutor_id="nova", mem=mem)
        assert confused != followup
        assert "shrink" in confused.lower()
        assert "Another example" in followup

    def test_sage_confusion_vs_followup(self):
        mem = RECURSION_MEM
        confused = _reply("I still don't understand.", tutor_id="sage", mem=mem)
        followup = _reply("Give me another example of what you just explained.",
                           tutor_id="sage", mem=mem)
        assert confused != followup
        assert "shift the comparison" in confused
        assert "Another example" in followup


# ---------------------------------------------------- P16–P17: All four first-turn starters differ

class TestAllFourStartersDiffer:
    """P16: EN recursion replies have four distinct opening lines.
    P17: AR recursion replies have four distinct opening lines."""

    def test_en_first_lines_all_different(self):
        lines = [
            _reply(RECURSION_Q, tutor_id=p).split("\n")[0]
            for p in ROLES
        ]
        assert len(set(lines)) == 4

    def test_ar_first_lines_all_different(self):
        lines = [
            _reply("اشرحلي recursion ببساطة.", tutor_id=p, lang="ar").split("\n")[0]
            for p in ROLES
        ]
        assert len(set(lines)) == 4


# ---------------------------------------------------- Detection unit tests

class TestDetectionHelpers:
    """Direct unit tests for the detection helpers."""

    def test_short_precedence_over_simple(self):
        assert genai._detect_length_request("short answer, simply") == "short"

    def test_deep_precedence_over_more(self):
        assert genai._detect_length_request("go deeper, more detail") == "deep"

    def test_short_beats_simple_when_both(self):
        assert genai._detect_length_request("keep it short and simple") == "short"

    def test_more_beats_simple(self):
        assert genai._detect_length_request("explain more detail simply") == "more"

    def test_none_for_normal_question(self):
        assert genai._detect_length_request("Explain recursion.") is None

    def test_none_for_followup_without_length(self):
        assert genai._detect_length_request("Give me another example.") is None

    def test_confusion_request_i_am_confused(self):
        assert genai._is_confusion_request("I am confused about recursion.")

    def test_confusion_request_arabic(self):
        assert genai._is_confusion_request("فاهمتش حاجة")

    def test_confusion_not_followup(self):
        assert not genai._is_confusion_request("give me another example")

    def test_simple_did_not_match_simple_way(self):
        """'in a simple way' stays on fallback (Phase 2 acceptance contract)."""
        assert genai._detect_length_request("Explain Docker volumes in a simple way.") is None
