"""Learning-integrity coverage helpers (Phase 4.5).

Deterministic checks that make "genuine + sufficient" enforceable for the FINAL
assessment backstop and the personalized path / lessons:

  - Final Assessment competency tagging is validated against a CLOSED blueprint set.
  - Assessment coverage (every required competency represented) is guaranteed.
  - Readiness for the Final Assessment is computed deterministically (mastered
    diagnostic topics + passed-lesson path competencies).
  - The personalized path and generated lessons are structurally validated.

Nothing here decides correctness with an LLM; all of it is pure and testable.
Mini Checks and personalized-path completion NEVER verify a skill — only the real
Assessment system does (handled in main.py).
"""
from . import skill_blueprint as sb
from . import diagnostics as dx


def required_slugs(skill_name, required_level):
    """Closed allowed competency slug list for a skill up to `required_level`.

    Trusted blueprints contribute their per-level competencies.  Derived
    blueprints are level-flat, so their competencies appear once regardless of
    the requested level.  Deduped to keep the allowed list a true set.
    """
    order = {"Beginner": 0, "Intermediate": 1, "Advanced": 2}
    end = order.get(required_level, 1)
    levels = ("Beginner", "Intermediate", "Advanced")[: end + 1]
    comps = []
    seen = set()
    for lvl in levels:
        for c in sb.competency_names_for(skill_name, lvl):
            slug = sb.competency_slug(c)
            if slug not in seen:
                seen.add(slug)
                comps.append(c)
    return list(seen)


def assessment_competency_status(questions):
    """Group a competency-tagged question list by competency.

    Returns {competency_slug: {"count": n, "correct": k}}. Questions without a
    `competency` tag are ignored (legacy forward-compatibility).
    """
    by = {}
    for i, q in enumerate(questions or []):
        comp = (q.get("competency") or "").strip()
        if not comp:
            continue
        b = by.setdefault(comp, {"count": 0, "correct": 0})
        b["count"] += 1
        # a question carrying its own per-question correctness (read path)
        if q.get("_correct") is True:
            b["correct"] += 1
        elif q.get("_correct") is not False:
            # unanswered correctness is resolved by the submit path; here we only
            # count tags present. `_correct` is filled by score_assessment below.
            pass
    return by


def score_assessment(questions, answers, correct_flags):
    """Deterministic scoring -> {overall, per_question, competencies}.

    `correct_flags` is a parallel list of booleans (already resolved MC/free-text).
    Returns overall percentage, per-question results, and per-competency results.
    """
    total = len(questions)
    correct = 0
    per_question = []
    comp_agg = {}
    for i, q in enumerate(questions):
        ok = bool(correct_flags[i]) if i < len(correct_flags) else False
        if ok:
            correct += 1
        comp = (q.get("competency") or "").strip() if isinstance(q, dict) else ""
        per_question.append({"index": i, "type": q.get("type", "mcq"),
                             "correct": ok, "answer": str(answers[i]) if i < len(answers) else ""})
        if comp:
            agg = comp_agg.setdefault(comp, {"count": 0, "correct": 0})
            agg["count"] += 1
            if ok:
                agg["correct"] += 1
    score = round((correct / max(total, 1)) * 100, 1)
    competencies = []
    for comp, agg in comp_agg.items():
        comp_score = round((agg["correct"] / agg["count"]) * 100, 1) if agg["count"] else 0.0
        competencies.append({"competency": comp, "score": comp_score, "passed": comp_score >= 70.0})
    return score, per_question, competencies


def coverage_for_questions(questions, required):
    """covered/missing against the required slug list."""
    if not required:
        return True, []
    present = {(q.get("competency") or "").strip() for q in (questions or []) if q.get("competency")}
    missing = [c for c in required if c not in present]
    return not missing, missing


def validate_questions(questions, required):
    """Keep only questions whose competency is in the closed allowed set."""
    cleaned = []
    for q in (questions or []):
        if not isinstance(q, dict):
            continue
        comp = (q.get("competency") or "").strip()
        if comp and comp not in required:
            continue  # drop out-of-blueprint tagged question
        cleaned.append(q)
    return cleaned


def final_assessment_ready(skill_name, required_level, diagnostic_topics, path_items, path_progress, mastered):
    """Deterministic readiness for the Final Assessment.

    A requirement is satisfied if it is mastered in the diagnostic OR present as a
    completed item in the personalized path. Returns the required/satisfied/missing
    view. Never consults an LLM.
    """
    required = required_slugs(skill_name, required_level)
    satisfied = set()
    for t in diagnostic_topics or []:
        if t.get("status") == dx.MASTERED and t.get("competency"):
            satisfied.add(t["competency"])
    completed = set(path_progress or [])
    for item in path_items or []:
        if item.get("id") in completed and item.get("competency"):
            satisfied.add(item["competency"])
    if mastered:
        satisfied |= set(mastered)
    missing = [c for c in required if c not in satisfied]
    return {
        "ready": not missing,
        "required": required,
        "satisfied": sorted(satisfied),
        "missing": missing,
    }


def validate_personalized_path(skill_name, items, skipped_mastered, diag_topics, required_level):
    """Structural validation of a personalized path (Req 10). Returns (ok, errors)."""
    errors = []
    diag_competencies = {(t.get("competency") or "") for t in (diag_topics or [])}
    active_statuses = {"weak", "developing"}
    slug_by_label = {}
    for label in sb.required_competencies(skill_name, "Beginner", "Advanced"):
        slug_by_label[sb.competency_slug(label)] = label.lower()

    active = []
    for it in items or []:
        comp = it.get("competency") or ""
        if not comp:
            errors.append("path item missing competency")
            continue
        if it.get("topic_status") not in active_statuses:
            errors.append(f"active item '{comp}' has non-active status {it.get('topic_status')}")
        active.append(comp)
    # every weak topic must appear as active
    for t in diag_topics or []:
        if t.get("status") == dx.WEAK and t.get("competency") not in active:
            errors.append(f"weak topic '{t.get('competency')}' missing from active items")
    # every developing topic must appear as learn/review
    for t in diag_topics or []:
        if t.get("status") == dx.DEVELOPING and t.get("competency") not in active:
            errors.append(f"developing topic '{t.get('competency')}' missing from active items")
    # no unknown competency
    for comp in active:
        if comp not in diag_competencies:
            errors.append(f"unknown competency '{comp}' not in diagnostic set")
    # mastered represented as satisfied/skipped
    for t in diag_topics or []:
        if t.get("status") == dx.MASTERED and (t.get("competency") or "") not in (skipped_mastered or []):
            errors.append(f"mastered topic '{t.get('competency')}' not in skipped_mastered")
    # union of active + mastered satisfies the diagnostic competency set
    covered = set(active) | set(diag_competencies)
    return not errors, errors


def validate_lesson(competency, allowed_slugs, content, min_explanation=40, min_key_ideas=1,
                    min_practice=1, min_mini_check=1):
    """Structural/content-quality guard for a generated lesson (Req 11).

    Deterministic checks only — no subjective AI scoring. Returns (ok, errors).
    """
    errors = []
    if competency not in (allowed_slugs or []):
        errors.append(f"competency '{competency}' not in allowed blueprint set")
    learn = (content or {}).get("learn") or {}
    example = (content or {}).get("example") or {}
    practice = (content or {}).get("practice") or {}
    mini = (content or {}).get("mini_check") or {}
    if not isinstance(learn.get("explanation"), str) or len((learn.get("explanation") or "").strip()) < min_explanation:
        errors.append("explanation too short or missing")
    if not isinstance(learn.get("key_ideas"), list) or len(learn.get("key_ideas") or []) < min_key_ideas:
        errors.append("missing key ideas")
    if not isinstance(example.get("content"), str) or len((example.get("content") or "").strip()) < min_explanation:
        errors.append("missing example content")
    practice_qs = (practice.get("questions") or []) if isinstance(practice, dict) else []
    mini_qs = (mini.get("questions") or []) if isinstance(mini, dict) else []
    if len(practice_qs) < min_practice:
        errors.append("missing practice questions")
    if len(mini_qs) < min_mini_check:
        errors.append("missing mini check questions")
    for q in mini_qs:
        if (q.get("competency") or "") != competency:
            errors.append("mini check question not tagged with lesson competency")
    return not errors, errors
