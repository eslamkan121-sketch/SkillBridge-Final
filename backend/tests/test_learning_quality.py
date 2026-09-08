"""Learning content quality & job-readiness refinements.

Covers the Quality & Job-Readiness brief:
- Grounding: Learn content cites ONLY trusted curated sources; the model cannot
  inject invented URLs; version/accurate-claim gaps are flagged, not silently shipped.
- Job-readiness: Learn anchors the concept to the target role via job_relevance.
- Personalization depth: weak (learn) vs developing (review) genuinely differ.
- 5-part lesson structure: what & why, core mechanics, common mistake, worked
  example, recommended resources.
- Self-evaluation: a self_check milestone/report is attached to lessons.
All GenAI calls forced to deterministic fallback except where explicitly mocked.
"""
import json

import pytest
from app import genai, lessons


@pytest.fixture(autouse=True)
def _force_deterministic_fallback(monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)


# ------------------------------------------------------------------ grounding


def test_grounding_sources_only_from_trusted_catalog():
    trusted = [
        {"title": "Official Docs A", "url": "https://docs.docker.com/a", "source": "Docker"},
        {"title": "Official Docs B", "url": "https://docs.docker.com/b", "source": "Docker"},
    ]
    model = trusted + [
        {"title": "Invented Site", "url": "https://evil.example.com", "source": "Hacker"},
    ]
    merged = lessons._grounding_sources_from_model(model, trusted)
    urls = {s["url"] for s in merged}
    assert urls == {"https://docs.docker.com/a", "https://docs.docker.com/b"}
    assert not any("evil" in str(s["url"]) or "hacker" in str(s["source"]).lower() for s in merged)


def test_grounding_sources_fallback_still_trusted_and_scoped():
    srcs = lessons._grounding_sources("Fake Skill 99", "FakeCat", "weirdness", None, None)
    assert isinstance(srcs, list)
    for s in srcs:
        assert s.get("title")
        assert s.get("url")
        # every grounding source is a direct, real, curated link — never a
        # fabricated URL and never a search/category deep-link for the skill
        assert not genai._is_generic_resource_url(s["url"])
    # an unknown skill has no citable curated links, so grounding is honestly
    # empty rather than fishing with a search-query deep-link
    assert srcs == []


def test_fallback_learn_grounding_sources_are_present_and_nonempty():
    content = lessons._lesson_fallback("Docker", "containers", "learn", "weak", 0.3,
                                       "Beginner", "Junior AI Engineer")
    sources = content["learn"].get("grounding_sources") or []
    assert sources
    for s in sources:
        assert s.get("title")
        assert s.get("url")


# ------------------------------------------------------------------ job-readiness


def test_fallback_learn_has_job_relevance_naming_target_role():
    content = lessons._lesson_fallback("Docker", "containers", "learn", "weak", 0.3,
                                       "Beginner", "Junior AI Engineer")
    relevance = content["learn"].get("job_relevance") or ""
    assert "Junior AI Engineer" in relevance
    assert len(relevance.split()) >= 8


def test_fallback_learn_has_common_mistake_and_worked_example():
    content = lessons._lesson_fallback("Pandas", "dataframes", "learn", "weak", 0.3,
                                       "Beginner", "Data Analyst")
    learn = content["learn"]
    assert learn.get("common_mistake")
    assert learn.get("worked_example")
    # worked example must reference the upcoming practice, not a disconnected toy
    assert "practice" in learn["worked_example"].lower()


# ------------------------------------------------------------------ 5-part structure


def test_fallback_learn_enforces_job_ready_parts():
    content = lessons._lesson_fallback("Docker", "containers", "learn", "weak", 0.3,
                                       "Beginner", "Junior AI Engineer")
    learn = content["learn"]
    # What & why (explanation + job_relevance), core mechanics (key_ideas/key_terms),
    # common mistake, worked example — all present.
    assert learn["explanation"]
    assert len(learn["key_ideas"]) >= 2
    assert learn["key_terms"]
    assert learn.get("job_relevance")
    assert learn.get("common_mistake")
    assert learn.get("worked_example")
    # Recommended Resources stay at top level (visually secondary), not in learn.
    assert content.get("resources")
    assert "resources" not in learn


# ------------------------------------------------------------------ depth branching


def test_weak_learn_vs_developing_review_differ():
    weak = lessons._lesson_fallback("Docker", "containers", "learn", "weak", 0.2,
                                    "Beginner", "Junior AI Engineer")
    dev = lessons._lesson_fallback("Docker", "containers", "review", "developing", 0.6,
                                   "Intermediate", "Junior AI Engineer")
    both = weak["learn"] and dev["learn"]
    assert both
    # depth notes genuinely differ
    assert weak["learn"]["depth_note"] != dev["learn"]["depth_note"]
    assert "weak" not in dev["learn"]["depth_note"].lower() or "Developing" in dev["learn"]["depth_note"]
    assert "Weak" in weak["learn"]["depth_note"]
    # review skips re-explaining fundamentals (no word-for-word basics restate)
    assert "working foundation" in dev["learn"]["explanation"].lower()
    assert "from the ground" not in dev["learn"]["explanation"].lower()
    assert "from the ground" in weak["learn"]["explanation"].lower()


def test_review_explanation_still_mentions_review():
    dev = lessons._lesson_fallback("Docker", "containers", "review", "developing", 0.6,
                                   "Intermediate", "Junior AI Engineer")
    assert "review" in dev["learn"]["explanation"].lower()


# ------------------------------------------------------------------ self-evaluation


def test_fallback_content_reports_self_check():
    content = lessons._lesson_fallback("Cybersecurity", "password security", "learn", "weak", 0.3,
                                       "Beginner", "Security Analyst")
    report = lessons._self_check_lesson(content, "Cybersecurity", "password security",
                                        "Security Analyst", "learn")
    assert report["passed"] is True
    assert report["checks"]
    names = [c["name"] for c in report["checks"]]
    assert "learn.explanation" in names
    assert "learn.key_ideas" in names
    assert "learn.key_terms" in names
    assert "example.content" in names
    assert "practice.task" in names
    assert "target role anchored" in names
    assert "depth branch explicit" in names
    assert "common mistake stated" in names
    assert "administrative grounded source" in names
    assert "syntax/version note" in names
    assert all(c["passed"] for c in report["checks"]), report["flags"]


def test_missing_parts_fail_self_check_and_flag():
    content = {
        "learn": {"title": "T", "explanation": "", "key_ideas": [], "key_terms": {},
                  "job_relevance": "", "common_mistake": "", "worked_example": ""},
        "example": {"title": "E", "type": "scenario", "content": "", "explanation": ""},
        "practice": {"title": "P", "task": "", "competency": "c"},
        "mini_check": {"questions": []},
    }
    report = lessons._self_check_lesson(content, "Docker", "containers", None, "learn")
    assert report["passed"] is False
    failed = [c["name"] for c in report["checks"] if not c["passed"]]
    assert "learn.explanation" in failed
    assert "example.content" in failed
    assert "practice.task" in failed
    assert any("target role anchored" in f for f in failed)


def test_misleading_source_flag_is_preserved():
    content = lessons._lesson_fallback("Docker", "containers", "learn", "weak", 0.3,
                                       "Beginner", "Junior AI Engineer")
    content["learn"]["unsupported_claims"] = ["The -x flag is deprecated in 14.x"]
    report = lessons._self_check_lesson(content, "Docker", "containers",
                                        "Junior AI Engineer", "learn")
    assert any("deprecated" in str(f) for f in report["flags"])
    assert not report["passed"] or report["flags"]


# ------------------------------------------------------------------ AI path (mocked)


def test_ai_path_carries_grounded_sources_and_self_check(monkeypatch):
    trusted_source = {"title": "Docker Docs", "url": "https://docs.docker.com/net/",
                      "source": "Docker"}
    monkeypatch.setattr(
        lessons, "_grounding_sources",
        lambda *a, **k: [trusted_source])
    fake_content = {
        "learn": {"title": "Containers", "explanation": "What containers are and why.",
                  "key_ideas": ["i1", "i2"], "key_terms": {"c": "d"},
                  "job_relevance": "A Junior AI Engineer runs containers for model deploys.",
                  "common_mistake": "Assuming syntax is valid without checking.",
                  "worked_example": "A practice walkthrough for the task to come.",
                  "depth_note": "Weak: starts from fundamentals.",
                  "grounding_sources": [trusted_source,
                                        {"title": "Bad link", "url": "https://nope.example.com",
                                         "source": "Unknown"}]},
        "example": {"title": "Ex", "type": "code", "content": "docker run --rm app",
                    "explanation": "e"},
        "practice": {"type": "practical", "title": "Deploy containers",
                     "task": "Deploy a containerized app and verify it runs.",
                     "response_type": "code", "competency": "containers"},
        "mini_check": {"questions": [
            {"id": "m1", "type": "mcq", "question": "q?", "options": ["a", "b"],
             "correct_answer": "a", "competency": "containers", "difficulty": "beginner"}]},
    }
    monkeypatch.setattr(genai, "genai_enabled", lambda: True)
    monkeypatch.setattr(genai, "complete", lambda *a, **k: json.dumps(fake_content))
    content = lessons.generate_lesson(
        skill_name="Docker", competency="containers", action="learn",
        target_role="Junior AI Engineer")
    # grounding merge drops the invented URL
    srcs = content["learn"]["grounding_sources"] or []
    assert all(s["url"] != "https://nope.example.com" for s in srcs)
    assert any(s["url"] == "https://docs.docker.com/net/" for s in srcs)
    # new fields flow through
    assert content["learn"]["job_relevance"]
    assert content["learn"]["common_mistake"]
    assert content["learn"]["worked_example"]
    assert content["learn"]["depth_note"]
    # self-check attached
    assert "self_check" in content
    assert content["self_check"].get("checks")


def test_ai_path_fallback_exception_still_returns_grounded_content(monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: True)

    def boom(*a, **k):
        raise RuntimeError("genai unavailable")

    monkeypatch.setattr(genai, "complete", boom)
    content = lessons.generate_lesson(
        skill_name="Docker", competency="containers", action="learn",
        target_role="Junior AI Engineer")
    assert content["learn"]["job_relevance"]
    assert content["learn"]["common_mistake"]
    assert content["learn"]["worked_example"]
    assert content["learn"]["depth_note"]
    assert content["learn"]["grounding_sources"]
    assert "self_check" in content


# ------------------------------------------------------------------ normalization


def test_normalize_lesson_preserves_new_quality_fields():
    content = lessons._lesson_fallback("Docker", "containers", "learn", "weak", 0.3,
                                       "Beginner", "Junior AI Engineer")
    lesson = {"id": 1, "content": content, "state": "in_progress"}
    normalized = lessons.normalize_lesson(lesson, "containers", skill_name="Docker",
                                          target_role="Junior AI Engineer")
    learn = normalized["content"]["learn"]
    assert learn.get("job_relevance")
    assert learn.get("common_mistake")
    assert learn.get("worked_example")
    assert learn.get("depth_note")
    assert learn.get("grounding_sources")
    assert normalized["content"].get("resources")