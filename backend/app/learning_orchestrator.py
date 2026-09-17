"""A small, deterministic Observe → Decide → Act → Observe learning agent.

The agent is intentionally not an evaluator or a curriculum generator. Its tool
functions expose existing persisted learning records and its policy only emits a
guarded next action with evidence. Existing lesson, practice, Mini Check, and
Final Assessment endpoints retain their respective authorities.
"""
from . import knowledge_base, models

EXPLAIN = "EXPLAIN"
PRACTICE = "PRACTICE"
GIVE_HINT = "GIVE_HINT"
REVIEW_PREREQUISITE = "REVIEW_PREREQUISITE"
MINI_CHECK = "MINI_CHECK"
ADVANCE = "ADVANCE"
REQUEST_REASSESSMENT = "REQUEST_REASSESSMENT"
ALLOWED_ACTIONS = {EXPLAIN, PRACTICE, GIVE_HINT, REVIEW_PREREQUISITE, MINI_CHECK, ADVANCE, REQUEST_REASSESSMENT}


# Tool wrappers. They are deliberately thin and read real project state only.
def get_student_learning_state(student_id, skill_id):
    return models.get_personalized_path(student_id, skill_id)


def get_diagnostic_results(student_id, skill_id):
    return models.public_diagnostic(models.get_latest_diagnostic(student_id, skill_id))


def get_trusted_lesson(student_id, skill_id, path, competency, skill_name):
    stored = models.get_lesson(student_id, path["id"], competency) if path else None
    canonical = knowledge_base.complete_lesson(skill_name, competency.replace("_", " "))
    return {"stored": stored, "canonical": canonical}


def get_prerequisites(skill_name, competency):
    return knowledge_base.prerequisites_for(skill_name, competency.replace("_", " "))


def get_practice_result(student_id, lesson):
    return models.list_practice_attempts(student_id, lesson["id"]) if lesson else []


def get_mini_check_result(lesson):
    return (lesson or {}).get("mini_check_result")


def update_learning_progress(student_id, skill_id, item_id, mini_check_result):
    """The sole progress writer used by this agent; requires an existing pass."""
    if not mini_check_result or not mini_check_result.get("passed"):
        return None
    return models.add_to_path_progress(student_id, skill_id, [item_id])


def _path_items(path):
    return (models.public_personalized_path(path).get("items") if path else []) or []


def _evidence(kind, detail):
    return {"kind": kind, "detail": detail}


def _result(action, topic_id, evidence, reason, next_step, objective=""):
    if action not in ALLOWED_ACTIONS:
        raise ValueError("unsupported orchestrator action")
    return {"action_type": action, "topic_id": topic_id, "evidence": evidence,
            "decision_reason": reason, "next_step": next_step, "objective": objective}


def _prerequisite_error(attempt):
    text = " ".join([attempt.get("answer") or ""] + (attempt.get("missing_points") or [])).lower()
    return any(term in text for term in ("parameter", "argument", "return", "print", "variable", "expression"))


def observe_and_decide(student_id, skill, act=True):
    """Observe persisted state, decide safely, and perform only idempotent progress sync."""
    skill_id, skill_name = skill["id"], skill["name"]
    diagnostic = get_diagnostic_results(student_id, skill_id)
    if not diagnostic or not diagnostic.get("completed_at"):
        return _result(REQUEST_REASSESSMENT, None, [_evidence("diagnostic", "No completed diagnostic is stored.")],
                       "A topic cannot be selected without a completed diagnostic.", "Complete the diagnostic first.")
    path = get_student_learning_state(student_id, skill_id)
    items = _path_items(path)
    if not items:
        return _result(REQUEST_REASSESSMENT, None, [_evidence("path", "No active learning-path topic is stored.")],
                       "There is no persisted gap topic to teach safely.", "Generate or retake the diagnostic path.")

    # Path-currency rule: a path belongs to exactly one diagnostic
    # (personalized_paths.diagnostic_id). A path is current only while that
    # diagnostic is still the latest COMPLETED one for the skill. A newer
    # completed diagnostic supersedes the stored gaps, so the path must be
    # regenerated (or explicitly refreshed) before it is taught again — the
    # agent never silently teaches from a stale path.
    latest_completed = models.public_diagnostic(models.get_latest_completed_diagnostic(student_id, skill_id)) if path else None
    if (latest_completed and path.get("diagnostic_id") is not None
            and latest_completed["id"] != path["diagnostic_id"]):
        return _result(
            REQUEST_REASSESSMENT,
            None,
            [_evidence("diagnostic", f"The active path was built from diagnostic #{path['diagnostic_id']}; the latest completed diagnostic is #{latest_completed['id']}."),
             _evidence("path", "The path is stale: a newer completed diagnostic supersedes its topic gaps.")],
            "A newer completed diagnostic exists, so the stored path no longer reflects the student's current gaps.",
            "Regenerate the learning path from the latest diagnostic, then continue.",
        )

    # Unresolved topics are never silently skipped. A path item whose identifier
    # has no canonical trusted lesson in the knowledge base/blueprint is surfaced
    # explicitly with a regeneration recovery instead of being dropped.
    unresolved = [i["competency"] for i in items
                  if not knowledge_base.complete_lesson(skill_name, i.get("competency", "").replace("_", " "))]
    if unresolved:
        return _result(
            REQUEST_REASSESSMENT,
            None,
            [_evidence("curriculum", "Unsupported topic identifiers in the active path: " + ", ".join(sorted(unresolved))),
             _evidence("path", "These topics have no canonical trusted lesson and cannot be taught without invented content.")],
            "The path still references legacy topic identifiers that the trusted knowledge base does not support.",
            "Regenerate the path from the latest diagnostic, or reassess the skill, so every gap resolves to a supported topic.",
        )

    completed_ids = set((models.public_personalized_path(path).get("progress") if path else []) or [])
    topic = next((i for i in items if i.get("id") not in completed_ids and knowledge_base.complete_lesson(skill_name, i.get("competency", "").replace("_", " "))), None)
    if topic is None and completed_ids:
        topic = next((i for i in items if knowledge_base.complete_lesson(skill_name, i.get("competency", "").replace("_", " "))), None)
    if not topic:
        return _result(REQUEST_REASSESSMENT, None, [_evidence("curriculum", "The active gap has no complete trusted lesson.")],
                       "The agent cannot invent curriculum for an unsupported topic.", "Choose a supported learning topic or reassess.")

    topic_id = topic["competency"]
    lesson_data = get_trusted_lesson(student_id, skill_id, path, topic_id, skill_name)
    canonical_topic = lesson_data["canonical"] or {}
    objective = canonical_topic.get("objective") or f"Learn the trusted topic: {topic_id}."
    lesson = lesson_data["stored"]

    # Prerequisite guard: never teach a topic whose declared prerequisite is a
    # not-yet-completed topic earlier in the same path. Send the student to the
    # prerequisite first (e.g. Python Functions before Python Error Handling).
    if canonical_topic:
        for prereq in canonical_topic.get("prerequisites") or []:
            pname = prereq.get("competency")
            pending = next(
                (i for i in items
                 if i.get("id") not in completed_ids
                 and knowledge_base.complete_lesson(skill_name, i.get("competency", "").replace("_", " "))
                 and knowledge_base.complete_lesson(skill_name, i.get("competency", "").replace("_", " ")).get("competency") == pname),
                None)
            if pending:
                return _result(
                    REVIEW_PREREQUISITE,
                    pending["competency"],
                    [_evidence("diagnostic", f"{canonical_topic.get('competency') or topic_id} declares prerequisite {pname}."),
                     _evidence("curriculum", f"{pname} is a not-yet-completed topic earlier in the same path.")],
                    f"Before {canonical_topic.get('competency') or topic_id}, the declared prerequisite {pname} must be completed.",
                    f"Complete the prerequisite topic first: {pname}.",
                )
    diag_topic = next((t for t in diagnostic.get("topic_results") or [] if t.get("competency") == topic_id), {})
    base_evidence = [_evidence("diagnostic", f"{diag_topic.get('label') or topic_id}: {diag_topic.get('status') or topic.get('topic_status')} at {diag_topic.get('score', topic.get('diagnostic_score'))}%"),
                     _evidence("curriculum", f"{canonical_topic.get('competency') or topic_id} is a complete trusted knowledge-base topic.")]
    if not lesson:
        return _result(EXPLAIN, topic_id, base_evidence, "The diagnosed gap has trusted content but no started lesson.", "Read the short explanation and example.", objective)

    mini = get_mini_check_result(lesson)
    if mini and mini.get("passed"):
        if act:
            update_learning_progress(student_id, skill_id, topic["id"], mini)
        return _result(ADVANCE, topic_id, base_evidence + [_evidence("mini_check", f"Passed with {mini.get('score', 0) * 100:.0f}%.")],
                       "A real Mini Check pass completed this topic; progress sync is idempotent.", "Continue to the next roadmap topic. This did not verify the skill.", objective)

    attempts = get_practice_result(student_id, lesson)
    if not attempts:
        return _result(PRACTICE, topic_id, base_evidence, "The explanation is available and no real practice attempt is stored.", "Submit the practical task.", objective)
    latest = attempts[0]
    attempt_evidence = _evidence("practice", f"Attempt {latest['id']} scored {latest['score']}% with status {latest['status']}; missing: {', '.join(latest.get('missing_points') or ['not specified'])}")
    if latest.get("status") == "ready":
        return _result(MINI_CHECK, topic_id, base_evidence + [attempt_evidence], "The latest real practice evaluation is ready.", "Take the Mini Check.", objective)
    static_check = (latest.get("practice_task") or {}).get("static_check") or {}
    if static_check.get("status") == "looks_structurally_sound":
        return _result(
            MINI_CHECK,
            topic_id,
            base_evidence + [attempt_evidence, _evidence("static_check", "The stored non-executing structural check found the required function, one parameter, return value, and conversion expression.")],
            "The reviewer remains inconclusive, but a stored static check supports trying the Mini Check. This did not execute the code or change the practice score.",
            "Take the Mini Check to confirm understanding; review the practice feedback if it does not pass.",
            objective,
        )
    prerequisite_errors = [a for a in attempts if a.get("status") == "needs_review" and _prerequisite_error(a)]
    if len(prerequisite_errors) >= 2:
        prereqs = get_prerequisites(skill_name, topic_id)
        names = ", ".join(p["competency"] for p in prereqs) or "the recorded prerequisite"
        return _result(REVIEW_PREREQUISITE, topic_id, base_evidence + [attempt_evidence, _evidence("practice_history", f"{len(prerequisite_errors)} needs-review attempts contain prerequisite-related evidence.")],
                       f"Repeated recorded errors point to {names}; the agent will not claim a different cause.", "Review the prerequisite, then retry the same practical task.", objective)
    hint = next((p for p in (lesson_data["canonical"] or {}).get("mini_check", {}).get("questions", []) if p.get("misconception_hint")), None)
    hint_text = hint.get("misconception_hint") if hint else "Use the evaluator's missing points to revise your response."
    return _result(GIVE_HINT, topic_id, base_evidence + [attempt_evidence, _evidence("hint", hint_text)],
                   "The latest real practice attempt needs review; one targeted retry is appropriate before prerequisite review.", "Use the targeted hint and retry the practical task.", objective)
