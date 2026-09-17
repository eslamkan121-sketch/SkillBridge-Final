"""Personalized Learning Path builder — deterministic ordering (Phase 3).

Turns a completed topic-level diagnostic into an ordered, personalized path of
topics the student needs to improve, skipping mastered topics. Pure and
deterministic: ordering never depends on an LLM arbitrarily picking order.

Rules (see requirements):
  - mastered topics are skipped (never added as normal learning items)
  - weak topics come before developing topics (status priority)
  - within the same status, the skill blueprint's competency order is used as the
    prerequisite signal, then lower diagnostic score first
"""
from . import diagnostics as dx
from . import skill_blueprint as sb
from . import knowledge_base

# centralized constants (no magic numbers scattered)
ESTIMATED_MINUTES = {"learn": 30, "review": 20, "milestone": 20}
STATUS_RANK = {dx.WEAK: 0, dx.DEVELOPING: 1}  # mastered never enters the path

# frontend-visible milestone placeholders (behaviour implemented in a later phase)
MILESTONES = [
    {"id": "practical-challenge", "stage": "Practical Challenge", "action": "challenge"},
    {"id": "final-assessment", "stage": "Final Assessment", "action": "assessment"},
]

# Secondary prerequisite signal: existing generated modules/blueprint order.
# Full blueprint order (Beginner..Advanced) so topics at any level map to an index.


def _blueprint_order(skill_name):
    order = {}
    comps = sb.required_competencies(skill_name, "Beginner", "Advanced")
    for i, comp in enumerate(comps):
        order[comp.strip().lower()] = i
    return order


def _humanize(slug):
    return (slug or "").replace("_", " ").strip().title() or "Topic"


def build_personalized_path(skill, diagnostic, required_level=None):
    """Build a personalized path from a completed diagnostic.

    `skill` is a skill dict (id/name/category); `diagnostic` is a
    public_diagnostic dict (must be completed). Returns a dict with
    `path`, `skipped_mastered` and `stages`.
    """
    topics = diagnostic.get("topic_results") or []
    if not diagnostic.get("completed_at"):
        raise ValueError("cannot build a personalized path from an unanswered diagnostic")

    blueprint_order = _blueprint_order(skill.get("name") or "")

    # Only a declared trusted prerequisite may override the usual weak-before-
    # developing priority. This avoids inventing graph edges for other topics.
    topic_labels = {str(t.get("label") or "").strip().lower() for t in topics}
    topic_labels.update(str(t.get("competency") or "").replace("_", " ").strip().lower() for t in topics)
    prerequisite_rank = {}
    for t in topics:
        label = str(t.get("label") or "").strip()
        curated = knowledge_base.complete_lesson(skill.get("name"), label.replace("_", " "))
        canonical_name = (curated or {}).get("competency") or label
        prereqs = knowledge_base.prerequisites_for(skill.get("name"), canonical_name)
        def has_prerequisite_topic(prerequisite):
            wanted = str(prerequisite or "").strip().lower()
            wanted_short = wanted.removeprefix("python ")
            return any(name == wanted or name.removeprefix("python ") == wanted_short for name in topic_labels)
        if any(has_prerequisite_topic(p.get("competency")) for p in prereqs):
            # The curated name, not a legacy display label, is the stable graph id.
            prerequisite_rank[label.lower()] = blueprint_order.get(canonical_name.lower(), 1)

    selected = []
    skipped = []
    for t in topics:
        status = t.get("status")
        if status == dx.MASTERED:
            skipped.append(t.get("competency") or dx.competency_slug(t.get("label") or ""))
            continue
        label = t.get("label") or _humanize(t.get("competency"))
        slug = t.get("competency") or dx.competency_slug(label)
        score = float(t.get("score") or 0)
        action = "learn" if status == dx.WEAK else "review"
        b_order = blueprint_order.get((label or "").strip().lower(), 10**9)
        selected.append({
            "label": label,
            "slug": slug,
            "status": status,
            "score": score,
            "action": action,
            # A declared prerequisite comes first; otherwise retain the
            # established weak-before-developing ordering.
            "sort_key": (prerequisite_rank.get(label.strip().lower(), 0), STATUS_RANK.get(status, 2), b_order, score),
        })

    selected.sort(key=lambda r: r["sort_key"])

    path = []
    for i, r in enumerate(selected, start=1):
        title = r["label"]
        if r["action"] == "review":
            title = f"{title} Review"
        path.append({
            "id": f"{r['slug']}-{i}",
            "competency": r["slug"],
            "title": title,
            "topic_status": r["status"],
            "diagnostic_score": r["score"],
            "action": r["action"],
            "order": i,
            "estimated_minutes": ESTIMATED_MINUTES[r["action"]],
            "state": "not_started",
        })

    stages = []
    if path:
        for offset, m in enumerate(MILESTONES, start=1):
            stages.append({
                "id": m["id"],
                "stage": m["stage"],
                "action": m["action"],
                "order": len(path) + offset,
                "estimated_minutes": ESTIMATED_MINUTES["milestone"],
                "state": "locked",
            })

    return {
        "path": path,
        "skipped_mastered": skipped,
        "stages": stages,
    }
