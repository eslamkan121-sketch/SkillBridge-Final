"""Learning diagnostic — topic-level foundation for personalized learning.

A diagnostic for a (student, skill) determines, per competency/topic inside that
skill, whether the student has *mastered*, is *developing* (needs practice), or is
*weak* (not demonstrated). It is deliberately separate from the skill-verification
assessment: a diagnostic NEVER verifies a skill or touches `verified_skills`.

All scoring is deterministic from the diagnostic questions (correct-per-competency
ratio), never an arbitrary LLM judgment. Thresholds are centralized here.
"""
from . import skill_blueprint as sb

# ------------------------------------------------------------------ topic statuses
# Centralized, consistent topic-level terminology. Deliberately distinct from the
# skill-level statuses (strong / gap / missing) used by matching.py.

MASTERED = "mastered"
DEVELOPING = "developing"
WEAK = "weak"

# thresholds: score_percent -> status
#   >= MASTERED_MIN      -> mastered
#   >= DEVELOPING_MIN    -> developing
#   else                 -> weak
MASTERED_MIN = 75.0
DEVELOPING_MIN = 40.0

# target size of a diagnostic (5-10 questions)
DIAGNOSTIC_MAX_QUESTIONS = 9
DIAGNOSTIC_MIN_QUESTIONS = 5


def topic_status(score_pct):
    """Classify a per-topic percentage score into a topic-level status."""
    if score_pct >= MASTERED_MIN:
        return MASTERED
    if score_pct >= DEVELOPING_MIN:
        return DEVELOPING
    return WEAK


def competency_slug(competency):
    """Machine-readable id for a competency, e.g. 'IAM Policies' -> 'iam_policies'."""
    words = (competency or "").strip().lower().split()
    return "_".join(w for w in words)


def resolve_topics(skill_name, learning_item=None):
    """Resolve the ordered list of topics/competencies to probe for a skill.

    Order (Phase C — never collapse to a bare '{skill} fundamentals' topic unless
    the skill genuinely cannot be decomposed):
      1. the trusted skill blueprint's competencies (all levels, union)
      2. derived competencies for the skill (GenAI-derived or honest fallback)
      3. the skill's existing generated plan's blueprint_competencies, if any
      4. a last-resort deterministic generic topic derived from the skill name
    """
    if sb.has_blueprint(skill_name):
        topics = sb.required_competencies(skill_name, "Beginner", "Advanced")
        if topics:
            return list(topics)
    blueprint = sb.derive_competencies(skill_name)
    topics = [c["name"] for c in blueprint.get("competencies", [])]
    if topics:
        return topics
    if learning_item:
        comps = learning_item.get("blueprint_competencies")
        if comps:
            return list(comps)
    # last-resort generic, deterministic fallback topic
    slug = competency_slug(skill_name) or "core_concepts"
    return [f"{skill_name} fundamentals"]


def build_topic_result(competency, correct, total):
    """Per-topic result dict with scope-aware status."""
    score = round((correct / total) * 100, 1) if total else 0.0
    return {
        "competency": competency_slug(competency),
        "label": competency,
        "score": score,
        "status": topic_status(score),
        "correct": correct,
        "total": total,
    }


def score_topics(questions, answers, grader_fn):
    """Deterministic per-topic scoring from diagnostic questions.

    `questions` is the list of diagnostic question dicts (each carries a
    `competency`), `answers` is the parallel list of student answers, and
    `grader_fn(index, question, answer) -> bool` returns whether the answer is
    correct (free-text grading reused through genai). Returns:
      { overall_score, topics, weak_topics, strong_topics }
    """
    by_topic = {}
    for i, q in enumerate(questions):
        comp = (q.get("competency") or "").strip()
        if not comp:
            continue
        ans = str(answers[i]) if i < len(answers) else ""
        correct = grader_fn(i, q, ans)
        bucket = by_topic.setdefault(comp, {"correct": 0, "total": 0})
        bucket["total"] += 1
        if correct:
            bucket["correct"] += 1

    topics = [
        build_topic_result(comp, bucket["correct"], bucket["total"])
        for comp, bucket in by_topic.items()
    ]
    # stable order: mastered first, then developing, then weak; then by name
    rank = {MASTERED: 0, DEVELOPING: 1, WEAK: 2}
    topics.sort(key=lambda t: (rank.get(t["status"], 3), t["label"]))

    weak_topics = [t["competency"] for t in topics if t["status"] == WEAK]
    strong_topics = [t["competency"] for t in topics if t["status"] == MASTERED]
    overall = round(sum(t["score"] for t in topics) / max(len(topics), 1), 1)
    return {
        "overall_score": overall,
        "topics": topics,
        "weak_topics": weak_topics,
        "strong_topics": strong_topics,
    }
