"""Topic lesson generation — Learn -> Example -> Practice -> Mini Check.

A lesson teaches ONE competency/topic inside a skill, contextualized to the
student's personalized path and target career — never a generic skill intro.

Two generation modes:
  1. Live GenAI call (when a provider key is set) — parsed into the canonical shape.
  2. Deterministic fallback (`_lesson_fallback`) — demoable with no API key,
     still clearly topic-specific and structured.

A lesson never touches `verified_skills`. Only a passing Mini Check (see the
centralized threshold) may mark a lesson topic complete in the personalized path.
"""
import json
import random
import re

from . import diagnostics as dx
from . import genai
from . import resources as resource_catalog
from . import knowledge_base


MINI_CHECK_PASS_THRESHOLD = 0.7


_SMALL_LABEL_WORDS = {
    "a", "an", "the", "to", "of", "for", "and", "or", "in", "on", "at", "by",
    "from", "with", "as", "is", "are", "was", "were", "be", "it", "its",
}

_ACRONYM_LABEL_WORDS = {
    "api", "sql", "http", "https", "json", "csv", "yaml", "yml", "xml", "ui",
    "ux", "css", "html", "ids", "ftp", "smtp", "tcp", "udp", "dns", "aws",
    "gcp", "ml", "cv", "svc",
}


def _has_slug_word(label):
    for word in (label or "").replace("_", " ").split():
        token = word.strip(".,!?;:'\"()[]{}")
        if (len(token) > 1 and token.islower()
                and token not in _SMALL_LABEL_WORDS and token not in _ACRONYM_LABEL_WORDS):
            return True
    return False


def humanize_competency(label):
    """Presentation helper: turn a topic slug into readable label text.

    `statistics_fundamentals` -> `Statistics Fundamentals`. Strings that already
    read naturally (no lowercase non-stopword tokens) are returned unchanged.
    Internal ids are never changed — this only shapes display text.
    """
    raw = (label or "").strip()
    if not raw or not _has_slug_word(raw):
        return raw
    words = [w for w in raw.replace("_", " ").split() if w]
    out = []
    for i, word in enumerate(words):
        if len(word) > 1 and (word.isupper() or word.lower() in _ACRONYM_LABEL_WORDS):
            out.append(word.upper())
        elif i > 0 and word.lower() in _SMALL_LABEL_WORDS:
            out.append(word.lower())
        else:
            out.append(word.capitalize())
    return " ".join(out)


def _lesson_human(competency):
    return humanize_competency(competency or "This topic")


def topic_learning_mode(topic_status, action_hint=None):
    """Resolve learn vs review: developing => review, otherwise learn."""
    if action_hint in ("learn", "review"):
        return action_hint
    return "review" if topic_status == dx.DEVELOPING else "learn"


def reason_for_learning(topic_status, diagnostic_score, action):
    """Human-readable 'why you are learning this' for the lesson header."""
    human = diagnostic_score if diagnostic_score is not None else None
    mode = action if action in ("learn", "review") else "learn"
    if mode == "review":
        return ("You understand the basics, but your diagnostic identified gaps to close.")
    return ("Your diagnostic showed this topic needs improvement.")


def _lesson_bank_questions(skill_name, competency, count):
    """Distribute curated/template questions for the given topic."""
    bank = genai._diag_bank_for(skill_name)
    pool = []
    if bank:
        pool = [dict(q) for q in bank]
        random.shuffle(pool)
    if len(pool) < count:
        template_pool = [f(skill_name, "a practical role") for f in genai._TEMPLATE_QUESTIONS]
        pool = pool + template_pool
    out = []
    idx = 0
    for q in pool:
        if len(out) >= count:
            break
        qtype = "free_text" if q.get("type") == "free_text" else "mcq"
        item = {
            "id": f"q{idx}",
            "type": qtype,
            "question": str(q.get("question") or ""),
            "options": [str(o) for o in (q.get("options") or [])] if qtype == "mcq" else [],
            "correct_answer": str(q.get("answer") or q.get("correct_answer") or ""),
            "competency": competency,
            "difficulty": "intermediate",
        }
        if qtype == "mcq":
            item = genai._balance_mc_options(item)
        out.append(item)
        idx += 1
    return out


def _normalize_question(q, i, prefix, competency):
    if not isinstance(q, dict):
        return {
            "id": f"{prefix}{i}", "type": "mcq", "question": "", "options": [],
            "correct_answer": "", "competency": competency, "difficulty": "beginner",
        }
    qtype = "free_text" if q.get("type") == "free_text" else "mcq"
    item = {
        "id": f"{prefix}{i}",
        "type": qtype,
        "question": str(q.get("question") or ""),
        "options": [str(o) for o in (q.get("options") or [])] if qtype == "mcq" else [],
        "correct_answer": str(q.get("correct_answer") or q.get("answer") or ""),
        "competency": str(q.get("competency") or competency or ""),
        "difficulty": str(q.get("difficulty") or "beginner"),
    }
    if qtype == "mcq":
        item = genai._balance_mc_options(item)
    return item


_PRACTICAL_RESPONSE_TYPES = {
    "code", "command", "query", "scenario", "dialogue", "analysis",
    "explanation", "code_explanation", "scenario_response", "communication",
    "decision", "write_response", "short_answer", "debug",
    "troubleshooting", "configuration", "implementation_plan",
}

_CODE_SKILL_HINTS = (
    "python", "pandas", "numpy", "sql", "database", "docker", "kubernetes",
    "javascript", "typescript", "react", "node", "git", "linux", "shell",
    "bash", "terraform", "ansible", "aws", "azure", "cloud", "api", "data",
    "machine learning", "deep learning", "tensorflow", "pytorch", "spark",
    "pyspark", "airflow", "tableau", "power bi", "excel", "pipeline",
)


def _practical_task_fallback(skill_name, competency, required_level):
    """Deterministic single open-ended applied practice task, skill-aware."""
    human = _lesson_human(competency)
    required = required_level or "Intermediate"
    coding = any(hint in skill_name.lower() for hint in _CODE_SKILL_HINTS)
    if coding:
        task = (
            f"Apply **{human}** to a realistic task. You are on a team working at {required} level "
            f"and a task needs {human.lower()}. Write the concrete commands, configuration, or code you "
            f"would use, explain what each piece does, and describe the signal that tells you it worked. "
            f"If something can go wrong, say how you would debug it."
        )
        response_type = "code_explanation"
    else:
        task = (
            f"Handle a realistic {skill_name} scenario that calls for **{human}**. Describe the "
            f"situation, the decision you would make, how you would explain your reasoning to the people "
            f"involved, and the steps you would take to confirm the outcome. Be specific about what you "
            f"would do first."
        )
        response_type = "scenario_response"
    return {
        "title": f"Practice: {human}",
        "task": task,
        "response_type": response_type,
        "competency": human,
    }


def canonical_practice(practice_data, competency, default_title=None, prefer_type=None):
    """Return the canonical single practical Practice block.

    Practice in a lesson is ONE open-ended applied task (Learn -> watch,
    Example -> see, Practice -> do). New content carries {title, task,
    response_type, competency}. Legacy content may still hold a `questions`
    array (MCQ/free_text) — this derives one open-ended task deterministically
    so no persisted lesson ever renders as a quiz. The `questions` list is kept
    as a single free_text mirror of the task so the existing evaluator and
    remediation pipeline work unchanged.
    """
    human = _lesson_human(competency)
    data = practice_data if isinstance(practice_data, dict) else {}
    task = str(data.get("task") or "").strip()
    title = str(data.get("title") or "").strip()
    response_type = str(data.get("response_type") or (prefer_type or "")).strip()
    comp = str(data.get("competency") or "").strip() or human
    questions = data.get("questions") if isinstance(data.get("questions"), list) else []

    if not task:
        free_text = next(
            (q for q in questions if isinstance(q, dict)
             and str(q.get("type") or "").lower() == "free_text"),
            None)
        if free_text:
            task = str(free_text.get("question") or "").strip()
            comp = str(free_text.get("competency") or "").strip() or comp
            response_type = response_type or "explanation"
        else:
            first_q = next(
                (q for q in questions if isinstance(q, dict)
                 and str(q.get("question") or "").strip()),
                None)
            if first_q:
                task = (
                    f"Apply this concept: {str(first_q.get('question')).strip()}. "
                    "Explain the concrete steps, commands, or code you would use, "
                    "and justify your choices."
                )
                response_type = response_type or "explanation"
            else:
                task = (
                    f"Explain how you would apply {human} to a realistic task. Describe the concrete "
                    f"steps, tools, commands, or code you would use, what you check at each step, and "
                    f"justify the main choice you make."
                )
                response_type = response_type or "explanation"

    if response_type not in _PRACTICAL_RESPONSE_TYPES:
        response_type = "explanation"
    if not comp:
        comp = human
    canonical = {
        "type": "practical",
        "title": title or default_title or f"Apply {human}",
        "task": task,
        "response_type": response_type,
        "competency": comp,
        "questions": [{
            "id": "p1",
            "type": "free_text",
            "question": task,
            "options": [],
            "correct_answer": "",
            "competency": comp,
            "difficulty": "intermediate",
        }],
    }
    # Optional, declarative coding-task details are safe to carry through the
    # legacy practice normalizer. They are displayed to the learner; execution
    # remains outside the web server.
    if data.get("starter_code"):
        canonical["starter_code"] = str(data["starter_code"])
    if isinstance(data.get("automated_tests"), list):
        canonical["automated_tests"] = [
            {"input": list(case.get("input") or []), "expected": case.get("expected")}
            for case in data["automated_tests"] if isinstance(case, dict)
        ]
    return canonical


def normalize_lesson_practice(lesson, competency):
    """Return a lesson copy with legacy practice normalized to one practical task.

    Stored content is never rewritten; this shapes the API response only.
    """
    if not isinstance(lesson, dict) or not isinstance(lesson.get("content"), dict):
        return lesson
    content = dict(lesson["content"])
    content["practice"] = canonical_practice(content.get("practice"), competency)
    normalized = dict(lesson)
    normalized["content"] = content
    return normalized


_CODE_LINE_HINTS = re.compile(
    r"(\b(import|from|def|class|return|print|docker|kubectl|terraform|aws|git|"
    r"npm|npx|pip|curl)\b|=(?:=)?|\(\)|\[|;|=>|\{|\}|&&|\|\||^\s*[A-Z]{2,12}\s)"
)


def _looks_like_code(text, threshold=0.6):
    lines = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#") or s.startswith("//") or s.startswith("--"):
            continue
        lines.append(s)
    if not lines:
        return False
    hits = sum(1 for ln in lines if _CODE_LINE_HINTS.search(ln))
    return (hits / len(lines)) >= threshold


def _fence_code_content(content):
    """Wrap multi-line code-like example content in a fenced block.

    AI-generated examples often carry real newlines but no markdown fence, so a
    naive markdown renderer collapses the program into one line. This is applied
    at the API boundary (stored content is never rewritten), and leaves fenced or
    prose content untouched.
    """
    text = str(content or "").strip()
    if not text or "\n" not in text:
        return text
    if re.search(r"(^|\n)[ \t]*```", text):
        return text
    if not _looks_like_code(text):
        return text
    return "```\n" + text + "\n```"


def normalize_remediation_review(remediation):
    """Presentation-boundary remediation shaping for existing and new attempts."""
    if not isinstance(remediation, dict):
        return remediation
    normalized = dict(remediation)
    normalized["targeted_example"] = _fence_code_content(
        normalized.get("targeted_example"))
    return normalized


def _lesson_resources(skill_name, skill_category=None, competency=None,
                      required_level=None, target_role=None):
    if not skill_name:
        return []
    try:
        return resource_catalog.recommend_lesson_resources(
            skill_name=skill_name,
            category=skill_category,
            competency=competency or skill_name,
            required_level=required_level,
            target_role=target_role,
            live_check=True,
            max_items=4,
        )
    except Exception:
        return []


def _grounding_sources(skill_name, skill_category, competency, required_level, target_role):
    """Trusted, curated sources to ground Learn content generation.

    Reuses the same curated catalogue as Phase 4 resources — never free LLM
    URLs. Returns a compact list of {title, url, source} the generator may cite
    to keep its technical claims accurate (official docs, framework guides).
    """
    try:
        res = resource_catalog.recommend_lesson_resources(
            skill_name=skill_name,
            category=skill_category,
            competency=competency or skill_name,
            required_level=required_level,
            target_role=target_role,
            live_check=False,
            max_items=4,
        )
    except Exception:
        return []
    out = []
    for r in res or []:
        if not isinstance(r, dict):
            continue
        url = str(r.get("url") or "").strip()
        title = str(r.get("title") or "").strip()
        if url and title:
            out.append({"title": title, "url": url,
                        "source": str(r.get("source") or "curated")})
        if len(out) >= 4:
            break
    return out


def _grounding_sources_from_model(model_value, trusted):
    """Merge a model-emitted grounding list with the trusted catalog.

    The model is asked to cite ONLY the provided trusted sources. To honor the
    grounding rule (URLs must come from the trusted catalog, never invented),
    we accept the model's picks only when their URL matches a trusted one.
    """
    trusted_urls = {str(s.get("url") or "").strip() for s in (trusted or [])}
    merged = {}
    for t in (trusted or []):
        merged[str(t.get("url") or "")] = {
            "title": str(t.get("title") or ""),
            "url": str(t.get("url") or ""),
            "source": str(t.get("source") or "curated"),
        }
    if isinstance(model_value, list):
        for s in model_value:
            if not isinstance(s, dict):
                continue
            url = str(s.get("url") or "").strip()
            if url in trusted_urls:
                merged[url] = {
                    "title": str(s.get("title") or merged[url]["title"]),
                    "url": url,
                    "source": str(s.get("source") or "curated"),
                }
    return list(merged.values())[:4]


def _self_check_lesson(content, skill_name, competency, target_role, action):
    """Lightweight static quality + grounding self-check on generated Learn content.

    Returns a checklist report (no execution sandbox exists; this is a static
    review). Any unverified/empty claim is surfaced rather than silently shipped.
    """
    learn = content.get("learn") or {}
    example = content.get("example") or {}
    practice = content.get("practice") or {}

    def check(name, ok, note=""):
        return {"name": name, "passed": bool(ok), "note": note}

    explanation = str(learn.get("explanation") or "").strip()
    checks = []
    flags = []
    for name, ok in (
        ("learn.explanation", bool(explanation)),
        ("learn.key_ideas", bool(learn.get("key_ideas"))),
        ("learn.key_terms", bool(learn.get("key_terms"))),
        ("example.content", bool(str(example.get("content") or "").strip())),
        ("practice.task", bool(str(practice.get("task") or "").strip())
         or bool((practice.get("questions") or []))),
        ("target role anchored", bool(target_role)
         or bool(str(learn.get("job_relevance") or "").strip())
         or bool(str(learn.get("why_for_role") or "").strip())),
        ("depth branch explicit", bool(
            str(learn.get("depth_note") or learn.get("depth") or "").strip())
         or action in ("learn", "review")),
        ("common mistake stated", bool(
            str(learn.get("common_mistake") or "").strip())),
    ):
        checks.append(check(name, ok))
        if not ok:
            flags.append(f"Self-check: {name} is missing.")

    grounded = _grounding_sources(skill_name, None, competency, None, target_role)
    grounding_hint = ""
    if learn.get("grounding_sources"):
        srcs = learn["grounding_sources"]
        if isinstance(srcs, list):
            names = [str(s.get("title") or s.get("name") or "") if isinstance(s, dict) else str(s)
                     for s in srcs]
            grounding_hint = "; ".join(n for n in names if n)[:400]
    grounded_ok = bool(grounded) or bool(grounding_hint)
    checks.append(check("administrative grounded source", grounded_ok,
                        grounding_hint or ("No curated source available for this topic." if not grounded
                                           else "Curated sources available")))
    checks.append(check("syntax/version note", bool(
        str(learn.get("version_note") or learn.get("version") or "").strip())
        or not _is_coding_skill(skill_name)))

    source_flags = learn.get("unsupported_claims") or learn.get("unverified_claims")
    if source_flags:
        if isinstance(source_flags, list):
            flags.extend(str(x) for x in source_flags if str(x).strip())
        elif str(source_flags).strip():
            flags.append(str(source_flags).strip())
    if not explanation:
        flags.append("Learn explanation is empty.")
    if not grounded and not grounding_hint:
        flags.append("No curated grounding source matched for this topic.")
    if _is_coding_skill(skill_name) and not str(
            learn.get("version_note") or learn.get("version") or "").strip():
        flags.append("Coding/version-sensitive topic without an explicit version note.")

    passed_all = all(c["passed"] for c in checks)
    return {"passed": passed_all, "checks": checks, "flags": flags}


def _is_coding_skill(skill_name):
    low = str(skill_name or "").lower()
    return any(h in low for h in _CODE_SKILL_HINTS)


def normalize_lesson(lesson, competency, skill_name=None, skill_category=None,
                     target_role=None, required_level=None):
    """API-boundary lesson shaping: practice canonicalization + presentation.

    Humanizes slug-bearing titles, fences unfenced multi-line code examples so
    line breaks survive markdown rendering, and keeps the existing practical
    practice shape. Stored rows are never rewritten.
    """
    if not isinstance(lesson, dict) or not isinstance(lesson.get("content"), dict):
        return lesson
    # A previously persisted generated lesson can contain fallback template
    # prose. Serve a reviewed replacement for a complete trusted topic unless
    # it already has a scored Mini Check (whose stored answers must stay
    # traceable to the content the learner answered).
    curated = knowledge_base.complete_lesson(skill_name, competency) if skill_name else None
    if curated and not lesson.get("mini_check_result"):
        lesson = dict(lesson)
        lesson["content"] = {
            "learn": curated["learn"],
            "example": curated["example"],
            "practice": canonical_practice(curated["practice"], competency, prefer_type="code"),
            "mini_check": curated["mini_check"],
            "locales": curated.get("locales", {}),
            "canonical": {
                "source": "trusted_cs_knowledge_base",
                "version": knowledge_base.KNOWLEDGE_BASE_VERSION,
                "prerequisites": curated["prerequisites"],
                "roadmap_rationale": curated["roadmap_rationale"],
            },
        }
    normalized = normalize_lesson_practice(lesson, competency)
    content = normalized["content"]
    content = dict(content)
    learn = content.get("learn")
    if isinstance(learn, dict):
        learn = dict(learn)
        learn["title"] = humanize_competency(str(learn.get("title") or "")) or learn.get("title")
        content["learn"] = learn
    example = content.get("example")
    if isinstance(example, dict):
        example = dict(example)
        example["title"] = humanize_competency(str(example.get("title") or "")) or example.get("title")
        example["content"] = _fence_code_content(example.get("content"))
        content["example"] = example
    practice = content.get("practice")
    if isinstance(practice, dict):
        practice = dict(practice)
        practice["title"] = humanize_competency(str(practice.get("title") or "")) or practice.get("title")
        content["practice"] = practice
    if skill_name:
        content["resources"] = _lesson_resources(
            skill_name, skill_category, competency, required_level, target_role)
    normalized["content"] = content
    return normalized


def _lesson_fallback(skill_name, competency, action, topic_status, diagnostic_score,
                     required_level, target_role=None):
    """Deterministic, structured lesson content — no API key needed.

    Uses the same 5-part job-ready shape as the GenAI path (What & why, Core
    mechanics, Common mistake, Worked example, Recommended Resources) and
    branches depth on weak (learn, from fundamentals) vs developing (review,
    targeted to the gap). Technical claims stay generic-but-true and are
    grounded where a trusted source exists.
    """
    human = _lesson_human(competency)
    required = required_level or "Intermediate"
    role = target_role or "a junior professional in this field"
    is_review = action == "review"

    if is_review:
        depth_note = (
            "Your diagnostic showed you are Developing here: the basics are in place, "
            "so this review targets the specific gaps rather than restating fundamentals."
        )
        explanation = (
            f"You already have a working foundation in **{human}** for **{skill_name}**, but the "
            f"diagnostic showed some gaps. This is a focused review that sharpens the pieces you "
            f"may have missed and solidifies how {human.lower()} behaves under real, production-shaped "
            f"conditions (targeted at {required} level work). {depth_note}"
        )
        key_ideas = [
            f"Confirm the core mechanics of {human} in {skill_name}.",
            f"Revisit the pitfalls that commonly trip up practitioners at the {required} level.",
            f"Reinforce how {human} applies to a real deliverable for a {role}.",
        ]
        key_terms = {
            "pitfall": f"A common mistake that creeps in when applying {human} without care.",
            "best practice": f"The recommended, reliable way to use {human} in production {skill_name}.",
            "context": f"The constraints of the real task that shape how {human} is used.",
        }
    else:
        depth_note = (
            "Your diagnostic showed this topic is Weak: the lesson starts from fundamentals "
            "with extra scaffolding and worked examples before moving to practice."
        )
        explanation = (
            f"**{human}** is one of the building blocks of **{skill_name}**. It is the part of the "
            f"skill you will reach for whenever you need to {human.lower()} in a real task — for "
            f"example, working at a {required} level on an actual project. This lesson builds it up "
            f"from the ground so you understand not just the syntax or commands, but why it works. "
            f"{depth_note}"
        )
        key_ideas = [
            f"What {human} is and the problem it solves in {skill_name}.",
            f"How {human} fits together with the rest of {skill_name}.",
            f"The concrete steps to apply {human} in a real task.",
            f"Common mistakes to avoid when first using {human}.",
        ]
        key_terms = {
            "concept": f"The core idea behind {human} you need to internalize.",
            "application": f"How {human} translates into a practical step in a real {skill_name} task.",
            "tooling": f"The tools or commands involved in using {human}.",
        }

    role_how = (
        f"In a {role} role, {human.lower()} shows up mainly when you need to "
        f"{'configure, command, or inspect something concrete' if _is_coding_skill(skill_name) else 'make a decision or handle a real situation'} — "
        f"the day-to-day work is less about theory and more about producing a correct, "
        f"verifiable result others depend on."
    )
    common_mistake = (
        f"A common beginner mistake with {human} is assuming the syntax or a command is "
        f"correct without validating it against the actual tooling — interviewers and engineers "
        f"probe for whether you can state how you know something worked."
    )

    worked_example = (
        f"Worked example tied to the practice to come: walk through one concrete {skill_name} "
        f"case where you apply **{human}** at {required} level — name the action you take, the "
        f"expected result, and how you would confirm it worked or debug it if it did not."
    )

    example = {
        "title": f"{human} in practice",
        "type": "scenario",
        "content": (
            f"Walk through a realistic {skill_name} scenario where you need to use **{human}**. "
            f"Imagine you are on a team working at {required} level for a {role}. You have a task that calls "
            f"for {human.lower()}; here is how an experienced practitioner would approach it, "
            f"step by step, and the reasoning behind each step. {worked_example}"
        ),
        "explanation": (
            f"Notice how the example centers on {human} inside a believable {skill_name} task — "
            f"that is the level of applied understanding you are working toward."
        ),
    }
    resources = _lesson_resources(skill_name, None, human,
                                  required, target_role)

    return {
        "learn": {
            "title": f"What is {human}?",
            "explanation": explanation,
            "key_ideas": key_ideas,
            "key_terms": key_terms,
            "depth_note": depth_note,
            "job_relevance": role_how,
            "common_mistake": common_mistake,
            "worked_example": worked_example,
            "grounding_sources": _grounding_sources(skill_name, None, human,
                                                     required, target_role),
        },
        "example": example,
        "practice": canonical_practice(
            _practical_task_fallback(skill_name, human, required), human),
        "mini_check": {
            "questions": _lesson_bank_questions(skill_name, human, 2),
        },
        "resources": resources,
    }


def generate_lesson(skill_name, competency, action, topic_status=None,
                    diagnostic_score=None, target_role=None, required_level=None,
                    student_context=None, skill_category=None):
    """Generate a topic lesson. Returns the canonical lesson content dict."""
    action = action if action in ("learn", "review") else "learn"
    human = _lesson_human(competency)
    required = required_level or "Intermediate"

    # Canonical CS entries are always served verbatim. This intentionally runs
    # before the provider check so a configured LLM can never invent curriculum
    # facts, prerequisites, examples, or Mini Check answers for this topic.
    canonical = knowledge_base.complete_lesson(skill_name, human)
    if canonical:
        content = {
            "learn": canonical["learn"],
            "example": canonical["example"],
            "practice": canonical_practice(canonical["practice"], human, prefer_type="code"),
            "mini_check": canonical["mini_check"],
            "locales": canonical.get("locales", {}),
            "canonical": {
                "source": "trusted_cs_knowledge_base",
                "version": knowledge_base.KNOWLEDGE_BASE_VERSION,
                "prerequisites": canonical["prerequisites"],
                "roadmap_rationale": canonical["roadmap_rationale"],
            },
        }
        content["self_check"] = _self_check_lesson(
            content, skill_name, human, target_role, action)
        return content

    def fallback():
        return _lesson_fallback(skill_name, human, action, topic_status,
                                diagnostic_score, required, target_role)

    def attach_resources(content):
        shaped = dict(content or {})
        shaped["resources"] = _lesson_resources(
            skill_name, skill_category, human, required, target_role)
        return shaped

    def fallback_with_check():
        fb = fallback()
        fb["self_check"] = _self_check_lesson(
            fb, skill_name, human, target_role, action)
        return attach_resources(fb)

    if not genai.genai_enabled():
        return fallback_with_check()

    grounding = _grounding_sources(skill_name, skill_category, human,
                                   required, target_role)
    depth_directive = (
        "DEPTH BRANCHING (weak vs developing — make these genuinely different):\n"
        "  - WEAK topic (mode 'learn'): start from fundamentals, add more scaffolding and worked "
        "example detail, explicitly address the likely beginner misconception.\n"
        "  - DEVELOPING topic (mode 'review'): skip re-explaining the basics, zoom in on the specific "
        "gap, and move quickly toward practice. Do NOT pad with basics the student already knows.\n"
    )
    system = (
        "You are a friendly but rigorous skills coach building a SINGLE focused topic lesson "
        "inside a larger skill. The learner has been diagnosed: they know the rest of the skill, "
        "but THIS topic needs work. Do NOT teach the whole skill — only the given topic.\n\n"
        "GROUNDING & ACCURACY — CRITICAL:\n"
        "- Never invent APIs, commands, flags, library behavior, versions, or version-specific "
        "syntax. If you are not confident about a technical claim, either cite the provided "
        "trusted source or state 'verify in the source' rather than fabricate a plausible answer.\n"
        "- Version-sensitive content (e.g. Docker Compose, Pandas/PyTorch APIs) must state or "
        "infer the version it teaches, because wrong-version syntax is the most common LLM "
        "tutorial failure.\n"
        "- Any code you show must be valid/runnable. There is no execution sandbox, so be "
        "conservative: prefer well-known, stable syntax and keep code minimal and correct.\n"
        "- Treat the provided 'Trusted grounding sources' as the only allowed source of URLs/named "
        "official resources. Do NOT attach invented links to Learn content.\n\n"
        "JOB-READINESS — the learner is preparing for a real junior role:\n"
        "- Anchor the concept to why it shows up in the target role, what a working professional "
        "actually does with it day-to-day, and a common mistake beginners make (interviewers probe "
        "for these). Keep this concise, not a marketing paragraph.\n\n"
        f"{depth_directive}\n"
        "LEARN CONTENT — enforce this 5-part shape (adjust wording, keep structure):\n"
        "1. What & why: the concept and why it matters for the target role (field: explanation, "
        "plus a short 'job_relevance' string naming the target role).\n"
        "2. Core mechanics: the actual how (commands/code/steps), grounded & version-aware.\n"
        "3. Common mistake: the beginner trap, stated explicitly (field: 'common_mistake').\n"
        "4. Worked example: tied 1:1 to the practice task coming next, not a disconnected toy "
        "(field: 'worked_example').\n"
        "5. Recommended Resources are added by the system — do not emit resource links in JSON.\n\n"
        "Output STRICT JSON (no prose) with this exact shape:\n"
        '{"learn": {"title": string, "explanation": string, "key_ideas": [string], '
        '"key_terms": {term: string}, "job_relevance": string, "common_mistake": string, '
        '"worked_example": string, "depth_note": string, "version_note": string, '
        '"grounding_sources": [{"title": string, "url": string, "source": string}], '
        '"unsupported_claims": [string]}, '
        '"example": {"title": string, "type": "code|scenario|command|query|dialogue", '
        '"content": string, "explanation": string}, '
        '"practice": {"type": "practical", "title": string, "task": string, '
        '"response_type": "code|command|scenario|analysis|dialogue|explanation|debug|configuration", '
        '"competency": string}, '
        '"mini_check": {"questions": [{"id": "m1", "type": "mcq|free_text", '
        '"question": string, "options": [string] or [], "correct_answer": string, '
        '"competency": string, "difficulty": string}]}}\n'
        "The Example section must apply the SAME scenario as Learn's worked example (not a new, "
        "unrelated scenario) so Practice does not feel like a third disconnected task.\n"
        "Practice is a SINGLE open-ended applied task, not a quiz: give the student a realistic "
        "scenario they must DO something with — for coding topics, code, commands, configuration, "
        "debugging, or an implementation plan; for non-coding topics, a scenario response, decision, "
        "explanation, or communication task. Do NOT use MCQ/True-False or recall questions for "
        "practice. Give 2-3 mini check questions mixing mcq and free_text. Make the example concrete "
        "and specific to the topic. All content must target the given topic only. For "
        "security/cybersecurity topics, point the learner to TryHackMe (https://tryhackme.com/) for "
        "hands-on practice and never to Cybrary — its course links are broken or unavailable."
    )
    user = (
        f"Skill: {skill_name}\n"
        f"Topic/Competency: {human}\n"
        f"Mode: {'review' if action == 'review' else 'learn'}\n"
        f"Diagnostic status: {topic_status or 'not scored'}\n"
        f"Diagnostic score: {diagnostic_score}\n"
        f"Target level: {required}\n"
        f"Target role: {target_role or 'unspecified'}\n"
        f"Learner context: {student_context or 'not provided'}\n"
        f"Graphic of target role signal for job-readiness anchoring: {target_role or 'unspecified'}\n\n"
        "Trusted grounding sources (the ONLY allowed source URLs; prefer official docs / framework "
        "guides when relevant):\n"
        f"{json.dumps(grounding, ensure_ascii=True) if grounding else 'none provided'}\n\n"
        "Build the lesson now."
    )

    try:
        raw = genai.complete(system, user, max_tokens=3600, timeout=180)
    except Exception:
        return fallback_with_check()

    parsed = genai._extract_json(raw)
    if not isinstance(parsed, dict):
        return fallback_with_check()

    learn_raw = parsed.get("learn") if isinstance(parsed.get("learn"), dict) else {}
    example = parsed.get("example") if isinstance(parsed.get("example"), dict) else {}
    practice = parsed.get("practice") if isinstance(parsed.get("practice"), dict) else {}
    mini_check = parsed.get("mini_check") if isinstance(parsed.get("mini_check"), dict) else {}
    mini_questions = mini_check.get("questions") if isinstance(mini_check.get("questions"), list) else []

    def _str_list(value):
        if isinstance(value, list):
            return [str(x) for x in value if str(x).strip()]
        if isinstance(value, str) and value.strip():
            return [value]
        return []

    def _str_dict(value):
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items() if isinstance(k, str)}
        return {}

    learn = {
        "title": str(learn_raw.get("title") or f"Understanding {human}"),
        "explanation": str(learn_raw.get("explanation") or "") if isinstance(learn_raw, dict) else "",
        "key_ideas": _str_list(learn_raw.get("key_ideas"))[:6],
        "key_terms": _str_dict(learn_raw.get("key_terms")),
        "job_relevance": str(learn_raw.get("job_relevance") or "").strip(),
        "common_mistake": str(learn_raw.get("common_mistake") or "").strip(),
        "worked_example": str(learn_raw.get("worked_example") or "").strip(),
        "depth_note": str(learn_raw.get("depth_note") or "").strip(),
        "version_note": str(learn_raw.get("version_note") or learn_raw.get("version") or "").strip(),
        "grounding_sources": _grounding_sources_from_model(
            learn_raw.get("grounding_sources"), grounding),
        "unsupported_claims": _str_list(learn_raw.get("unsupported_claims")),
    }

    content = {
        "learn": learn,
        "example": {
            "title": str(example.get("title") or f"{human} in practice"),
            "type": str(example.get("type") or "scenario"),
            "content": str(example.get("content") or ""),
            "explanation": str(example.get("explanation") or ""),
        },
        "practice": canonical_practice(practice, human),
        "mini_check": {
            "questions": [_normalize_question(q, i, "m", human) for i, q in enumerate(mini_questions)],
        },
    }
    if not content["mini_check"]["questions"]:
        content["mini_check"] = {
            "questions": _lesson_bank_questions(skill_name, human, 2),
        }
    content["self_check"] = _self_check_lesson(
        content, skill_name, human, target_role, action)
    return attach_resources(content)


# ------------------------------------------------------------------ Mini Check scoring

def is_answer_correct(question, answer):
    """Determine whether a student answer is correct for a lesson question."""
    qtype = question.get("type")
    ans = (answer or "").strip()
    if qtype == "free_text":
        model = question.get("correct_answer") or ""
        return genai.grade_free_text(model, ans)
    # mcq
    return ans == str(question.get("correct_answer") or "")


def score_mini_check(questions, answers):
    """Score a Mini Check submission. Returns (correct, total, passed)."""
    correct = 0
    total = len(questions)
    for i, q in enumerate(questions):
        a = answers[i] if i < len(answers) else ""
        if is_answer_correct(q, a):
            correct += 1
    score = (correct / total) if total else 0.0
    return correct, total, score >= MINI_CHECK_PASS_THRESHOLD
