"""Global Student AI Career Copilot — centralized, trusted context builder.

Only SAFE structured identifiers are accepted from the frontend
(``page``, ``skill_id``, ``competency``, ``job_title``, ``job_url``). Everything
the assistant needs — profile, readiness, verified skills, gaps, path, lesson,
job match, career roadmap — is re-resolved from backend state in this module,
so a student can never inject authoritative claims (scores, requirements,
verified status) from the client.

``page='assessment'`` is BLOCKED: the Tutor must never receive context while
the student is inside a verified final assessment. The tutor endpoint rejects
that request before any context is built.
"""

import json

from . import models, matching, career_roadmap, jobs, skill_blueprint as sb

ALLOWED_TUTOR_IDS = ("nova", "axel", "sage", "vex")

# Unified tutor modes: the student can put the Global Copilot into one of these
# working modes regardless of which persona (tutor) is selected. The backend
# validates the mode and reuses the existing interview engine for "interview".
MODES = ("chat", "practice", "discuss", "interview")

# Each persona arrives in its natural mode by default; the student may switch.
# The persona and the working mode are deliberately independent: selecting Vex
# must NOT start a mock-interview session (that requires an explicit Interview
# mode / session), so Vex defaults to ordinary chat like Nova.
TUTOR_DEFAULT_MODES = {
    "nova": "chat",
    "axel": "practice",
    "sage": "discuss",
    "vex": "chat",
}


def validate_mode(mode):
    """Return a normalized mode, or None when the value is not one of MODES."""
    if not isinstance(mode, str):
        return None
    mode = mode.strip().lower()
    return mode if mode in MODES else None


def default_mode_for(tutor_id):
    """The default mode for a tutor persona, falling back to chat."""
    return TUTOR_DEFAULT_MODES.get((tutor_id or "").strip().lower(), "chat")


# ---------------------------------------------------------------- Build-Your-Copilot
#
# Mentor Experience Phase 1: the copilot choices ARE the four real SkillBridge
# mentors (nova / axel / sage / vex). There is no separate archetype layer —
# the old Navigator / Strategist / Confidant archetypes are gone from this
# module and never surface in onboarding or recommendation UI.
#
# All four mentors share the same underlying intelligence; their identity here
# is personality / communication / teaching style only (Phase 1 doesn't change
# mentor AI behavior). Each preset's behavior/style mirrors the mentor's
# canonical persona text (genai.TUTOR_PERSONAS) verbatim, so selecting a
# mentor in onboarding produces exactly the same composed AI persona the user
# already knows from chat — no intelligence change.
#
# Personality/capability is CONFIGURATION: the personality block below is
# composed into the dynamic system prompt at chat time (genai.tutor_reply
# ``personality`` override), so it is free to vary per user without touching
# the voice pool. The voice is a SCARCE resource (shared ElevenLabs agents) and
# is referenced, never duplicated, per copilot.
COPILOT_KEYS = ("nova", "axel", "sage", "vex")

COPILOT_CAPABILITIES = ("learning", "practice", "jobs", "planning")

COPILOT_PRESETS = {
    "nova": {
        "voice_agent_id": "nova",
        "name": "Nova",
        "title": "Warm • Patient • Clear",
        "role": "Explainer Tutor",
        "specialty": "Learn & Explain",
        "origin": "London, United Kingdom",
        "traits": ["Warm", "Patient", "Clear", "Supportive"],
        "behavior": (
            "Teach in this rhythm for the student: 1) explain the idea simply, 2) break it "
            "into small steps, 3) give a concrete example, 4) confirm they understood with a "
            "gentle check-in. For beginner questions, avoid unnecessary jargon and define the "
            "terms you use."
        ),
        "style": "Friendly, warm and encouraging like a supportive mentor. Acknowledge effort with genuine warmth, name one specific thing they did well, then gently push one step deeper.",
        "capabilities": {"learning": True, "practice": True, "jobs": True, "planning": True},
    },
    "axel": {
        "voice_agent_id": "axel",
        "name": "Axel",
        "title": "Energetic • Practical • Fun",
        "role": "Practical Coach",
        "specialty": "Practice & Build",
        "origin": "California, United States",
        "traits": ["Energetic", "Practical", "Direct", "Action-focused"],
        "behavior": (
            "Teach in this rhythm: 1) a short no-fluff explanation, 2) one practical example "
            "or command they can try, 3) a concrete action/task to lock it in. If the student "
            "explicitly asks for ONLY an explanation, do not force practice on them."
        ),
        "style": "Energetic, confident and hands-on like a practical coach. Be direct and motivating, insist on concrete built-and-tested examples, and use short punchy sentences.",
        "capabilities": {"learning": True, "practice": True, "jobs": True, "planning": True},
    },
    "sage": {
        "voice_agent_id": "sage",
        "name": "Sage",
        "title": "Calm • Analytical • Thoughtful",
        "role": "Discussion Mentor",
        "specialty": "Discuss & Think",
        "origin": "Alexandria, Egypt",
        "traits": ["Calm", "Analytical", "Thoughtful", "Reflective"],
        "behavior": (
            "Answer the question directly and correctly FIRST, then reason through it: give "
            "your interpretation, compare alternative approaches and their tradeoffs, and "
            "invite deeper reflection. Do not turn every answer into questions alone — always "
            "give a real answer first."
        ),
        "style": "Calm, analytical and Socratic. Reflect the student's own words back and ask thoughtful why/how questions, rewarding clear reasoning over rote recitation.",
        "capabilities": {"learning": True, "practice": True, "jobs": True, "planning": True},
    },
    "vex": {
        "voice_agent_id": "vex",
        "name": "Vex",
        "title": "Sharp • Precise • Professional",
        "role": "Examiner",
        "specialty": "Test & Interview",
        "origin": "Paris, France",
        "traits": ["Precise", "Professional", "Challenging", "Sharp"],
        "behavior": (
            "Be precise: state the accurate answer, call out the important technical "
            "distinction (terminology, edge cases, tradeoffs), and finish with a short "
            "optional knowledge check. Do not turn every normal question into a formal test."
        ),
        "style": "Serious, precise and demanding — a disciplined examiner. Be fair but unforgiving of vague answers; require specifics, tradeoffs and numbers, with minimal praise.",
        "capabilities": {"learning": True, "practice": True, "jobs": True, "planning": True},
    },
}


def validate_choice(choice):
    """Return a normalized copilot key, or None when the value is not one of the
    four current mentors."""
    if not isinstance(choice, str):
        return None
    choice = choice.strip().lower()
    return choice if choice in COPILOT_PRESETS else None


def copilot_options():
    """The exact four starting points as an additive API payload (never more)."""
    options = []
    for key in COPILOT_KEYS:
        p = COPILOT_PRESETS[key]
        options.append({
            "key": key,
            "name": p["name"],
            "title": p["title"],
            "voice_agent_id": p["voice_agent_id"],
            "capabilities": {c: bool((p.get("capabilities") or {}).get(c))
                             for c in COPILOT_CAPABILITIES},
        })
    return options


def snapshot_for(choice):
    """Frozen per-user snapshot for a choice (see models.set_copilot_config).

    The personality/capability fields are snapshotted at creation so later
    edits never need a schema change and each stored config stays
    self-contained.
    """
    preset = COPILOT_PRESETS[choice]
    return {
        "choice": choice,
        "voice_agent_id": preset["voice_agent_id"],
        "name": preset["name"],
        "title": preset["title"],
        "role": preset["role"],
        "specialty": preset["specialty"],
        "origin": preset["origin"],
        "traits": list(preset.get("traits") or []),
        "behavior": preset["behavior"],
        "style": preset["style"],
        "capabilities": dict(preset.get("capabilities") or {}),
    }


def personality_for_config(config):
    """TUTOR_PERSONAS-shaped personality dict from a stored copilot config.

    This is the additive ``personality`` override passed to
    ``genai.tutor_reply``: when present, the composed system prompt describes
    the mentor (e.g. "You are Nova") instead of the voice agent's own fixed
    persona, so personality/capability follow the per-user config while the
    voice stays a shared agent reference. ``None`` keeps current behavior.
    """
    if not config:
        return None
    return {
        "name": config.get("name") or "the copilot",
        "role": config.get("role"),
        "origin": config.get("origin"),
        "specialty": config.get("specialty"),
        "traits": list(config.get("traits") or []),
        "behavior": config.get("behavior"),
        "style": config.get("style"),
    }


# ------------------------------------------------------- First-run onboarding quiz
#
# A student's first authenticated session may run a short, skippable,
# four-question flow whose answers pick one of the EXACTLY four mentors above.
# The SPA mirrors this tally in lib/copilotArchetypes.ts (single source of
# truth in the frontend); the SERVER recomputes the winner from the submitted
# answers and stores its own result — a client-sent ``choice`` is always
# recomputed over (spec requirement: "treat the server's computation as the
# source of truth"). Answer entries are the per-question voted mentor keys, so
# tallying is a pure count. Ties are broken deterministically: the answer to
# Question 4, then the answer to Question 1, then the default (Nova).
ONBOARDING_STATES = ("not_started", "completed", "skipped")
ONBOARDING_SOURCES = ("quiz", "skip", "manual_change")
ONBOARDING_QUESTION_COUNT = 4
DEFAULT_ARCHETYPE = "nova"

# The four interview questions. Each option carries the mentor key it votes
# for; the answer array persisted is the list of the four voted keys. This
# copy (the owner-approved demo text) is the question/option/mentor source of
# truth and must stay in sync with frontend/src/lib/copilotArchetypes.ts
# (checked by a runtime checker).
ONBOARDING_QUESTIONS = [
    {
        "question": "When you're learning something difficult, what helps you most?",
        "options": [
            {"label": "Explain it clearly, step by step", "vote": "nova"},
            {"label": "Let me try something practical", "vote": "axel"},
            {"label": "Help me understand why it works", "vote": "sage"},
            {"label": "Test me and show me what I'm missing", "vote": "vex"},
        ],
    },
    {
        "question": "When you make a mistake, how should your mentor respond?",
        "options": [
            {"label": "Patiently explain it again", "vote": "nova"},
            {"label": "Tell me directly and let me retry", "vote": "axel"},
            {"label": "Discuss my thinking with me", "vote": "sage"},
            {"label": "Challenge me with another question", "vote": "vex"},
        ],
    },
    {
        "question": "What kind of mentor personality keeps you engaged?",
        "options": [
            {"label": "Friendly and supportive", "vote": "nova"},
            {"label": "Energetic and fun", "vote": "axel"},
            {"label": "Calm and thoughtful", "vote": "sage"},
            {"label": "Serious and challenging", "vote": "vex"},
        ],
    },
    {
        "question": "What do you expect to use SkillBridge for most?",
        "options": [
            {"label": "Learning new things", "vote": "nova"},
            {"label": "Practicing and building", "vote": "axel"},
            {"label": "Understanding concepts and decisions", "vote": "sage"},
            {"label": "Testing myself and preparing for interviews", "vote": "vex"},
        ],
    },
]

# Onboarding lives in its own table (see database._migration_0010), separate
# from copilot_config: removing a copilot must never reset "already asked".
ONBOARDING_TABLE = "copilot_onboarding"


def validate_onboarding_answers(answers):
    """Return the normalized 4-element answer list, or None when invalid.

    An answer set must be a sequence of EXACTLY four entries, each a valid
    mentor key (the four voted keys selected by the student).
    Everything else — wrong count, unknown keys, junk types — is None so callers
    reject with a 400.
    """
    if not isinstance(answers, (list, tuple)):
        return None
    if len(answers) != ONBOARDING_QUESTION_COUNT:
        return None
    out = []
    for entry in answers:
        key = validate_choice(entry)
        if key is None:
            return None
        out.append(key)
    return out


def score_archetype(answers):
    """The mentor the answers vote for (server-side source of truth).

    Pure tally over the answered mentor keys: the key with the most votes wins.
    Ties resolve deterministically — 1) the Question 4 answer, 2) the Question 1
    answer, 3) DEFAULT_ARCHETYPE (Nova) — and any degenerate input also falls
    back to DEFAULT_ARCHETYPE so a result is always one of the four real
    mentors and never fabricated.
    """
    if not validate_onboarding_answers(answers):
        return DEFAULT_ARCHETYPE
    counts = {}
    for key in answers:
        counts[key] = counts.get(key, 0) + 1
    best = max(counts.values())
    winners = [k for k in COPILOT_KEYS if counts.get(k, 0) == best]
    if len(winners) == 1:
        return winners[0]
    # Tie-break 1: the Question 4 answer (answers are indexed per question).
    if answers[3] in winners:
        return answers[3]
    # Tie-break 2: the Question 1 answer.
    if answers[0] in winners:
        return answers[0]
    # Tie-break 3: deterministic default.
    return DEFAULT_ARCHETYPE


# Tutor language preferences (Phase 5.5 Step 4). "auto" resolves per single
# student message with backend detection; "en"/"ar" pin the reply language.
SUPPORTED_TUTOR_LANGUAGES = ("auto", "en", "ar")
TUTOR_DEFAULT_LANGUAGE = "auto"

# Arabic-dominant threshold for the mixed-language heuristic (see below).
_ARABIC_RATIO = 0.25


def validate_language(value):
    """Return a normalized language, or None when the value is unsupported.

    Rejects arbitrary strings, numeric junk and empty values so frontend data
    can never smuggle prompt instructions through the language field.
    """
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if value in SUPPORTED_TUTOR_LANGUAGES else None


def detect_language(text):
    """Decide 'ar' vs 'en' from a student message (backend owns the decision).

    Technical terminology is expected to stay English (Docker, Container, API,
    SQL, ...), so a message like "اشرحلي Docker networking" is Arabic-dominant
    even though it contains more Latin letters than Arabic ones. We therefore
    classify as Arabic when a meaningful ratio of the message is Arabic script;
    hints like the spec examples (arabic framing + English technical terms)
    land safely on Arabic with the ratio chosen below.
    """
    if not isinstance(text, str) or not text.strip():
        return "en"
    arabic = sum(1 for ch in text
                 if "\u0600" <= ch <= "\u06FF" or "\u0750" <= ch <= "\u077F"
                 or "\u08A0" <= ch <= "\u08FF" or "\uFB50" <= ch <= "\uFDFF"
                 or "\uFE70" <= ch <= "\uFEFF")
    latin = sum(1 for ch in text
                if ("\u0041" <= ch <= "\u005A") or ("\u0061" <= ch <= "\u007A"))
    if arabic <= 0:
        return "en"
    total = arabic + latin
    if total <= 0:
        return "ar"
    return "ar" if (arabic / total) >= _ARABIC_RATIO else "en"


def resolve_language(language, message_text):
    """Resolve a stored preference to an actual reply language.

    ``auto`` (and anything unset) is decided from ``message_text`` on the
    backend; ``en``/``ar`` always pin the reply. Explicit preference changes
    are never written back by detection.
    """
    lang = validate_language(language)
    if lang is None:
        lang = TUTOR_DEFAULT_LANGUAGE
    if lang in ("en", "ar"):
        return lang
    return detect_language(message_text)


def language_label(language):
    """Human-readable label used to thread the resolved language into context."""
    return "Arabic" if (language or "").strip().lower() == "ar" else "English"


PAGES = (
    "dashboard",
    "skills_roles",
    "learning",
    "jobs",
    "career_roadmap",
    "mock_interview",
    "assessment",
)

PAGE_LABELS = {
    "dashboard": "Dashboard",
    "skills_roles": "Skills & Roles",
    "learning": "Learning",
    "jobs": "Jobs",
    "career_roadmap": "Career Roadmap",
    "mock_interview": "Mock Interview",
    "assessment": "Verified Final Assessment",
}

_STATUS_LABEL = {
    "strong": "you already meet the requirement",
    "gap": "you have it but below the required level",
    "missing": "you do not have it yet",
}


def _profile_lines(student):
    """Shared baseline: who the student is (never includes scores or verdicts)."""
    lines = []
    if student.get("university"):
        lines.append(f"University: {student['university']}")
    if student.get("education_level"):
        lines.append(f"Education: {student['education_level']}")
    if not student.get("university") and not student.get("education_level"):
        lines.append("Independent learner")
    return lines


def _skills_for_jobs(student):
    skills = []
    for s in student.get("self_reported_skills") or []:
        skills.append((s["name"], s.get("level") or "Beginner"))
    for v in student.get("verified_skills") or []:
        skills.append((v["name"], v.get("level") or "Intermediate"))
    return skills


def _analysis(student):
    try:
        return matching.analyze_student(student["id"])
    except Exception:
        return None


def _role_line(role, company=None):
    if not role:
        return None
    title = role.get("title") or role.get("name")
    if not title:
        return None
    if company:
        return f"{title} ({company})"
    return title


def _verified_skills_line(student):
    verified = student.get("verified_skills") or []
    if not verified:
        return None
    return "Verified skills: " + ", ".join(v["name"] for v in verified)


def _dashboard_context(student, analysis=None):
    analysis = analysis or _analysis(student)
    lines = _profile_lines(student)
    if not analysis:
        lines.append("No target career selected yet. Choose one on Skills & Roles and "
                     "the Tutor will help with the gap plan.")
        verified_line = _verified_skills_line(student)
        if verified_line:
            lines.append(verified_line)
        lines += _assessment_lines(student)
        return lines
    role = analysis.get("role_title") or ""
    score = analysis.get("match_score")
    lines.append(f"Target career: {_role_line({'title': role}, analysis.get('company'))}")
    if score is not None:
        lines.append(f"Career readiness: {score}% match to the target role")
    gaps = analysis.get("skill_gaps") or []
    bad = [g for g in gaps if g.get("status") != "strong"]
    lines.append(f"Required-skill status: {len(gaps)} required skills "
                 f"({len(bad)} below requirement).")
    for g in gaps:
        state = _STATUS_LABEL.get(g.get("status"), g.get("status"))
        tag = " [Verified]" if g.get("verified") else ""
        lines.append(f"- {g['skill_name']}: {state}{tag}")
    next_skills = [g["skill_name"] for g in bad]
    if next_skills:
        lines.append(f"Recommended next step: work on '{next_skills[0]}' next"
                     + (f", then '{next_skills[1]}'" if len(next_skills) > 1 else "") + ".")
    else:
        lines.append("Recommended next step: you meet every requirement — take the "
                     "Verified Final Assessment to confirm it.")
    verified_line = _verified_skills_line(student)
    if verified_line:
        lines.append(verified_line)
    lines += _assessment_lines(student)
    return lines


def _assessment_lines(student, skill_id=None):
    """Make the Tutor aware of the student's actual MEASURED weaknesses — the
    competency breakdown of their most recent assessment — so guidance is based
    on evidence, not just the self-reported profile. Derived from persisted
    assessment_attempts rows; never raises on missing data."""
    lines = []
    try:
        attempts = models.list_assessment_attempts(student_id=student["id"], skill_id=skill_id)
    except Exception:
        return lines
    attempt = next((a for a in attempts if a.get("per_question")), None)
    if not attempt:
        return lines
    try:
        flags = json.loads(attempt.get("flags") or "[]")
    except Exception:
        flags = []
    skill_name = attempt.get("skill_name") or "a skill"
    lines.append(f"Latest assessment for {skill_name}: overall {attempt.get('score')}% — "
                 f"{'PASSED' if attempt.get('passed') else 'did not pass'}.")
    per_q = []
    try:
        raw = attempt.get("per_question")
        per_q = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except Exception:
        per_q = []
    by = {}
    for pq in per_q:
        comp = ((pq or {}).get("competency") or "").strip()
        if not comp:
            continue
        b = by.setdefault(comp, {"count": 0, "correct": 0})
        b["count"] += 1
        if pq.get("correct"):
            b["correct"] += 1
    if by:
        worst = sorted(by.items(),
                       key=lambda kv: kv[1]["correct"] / max(kv[1]["count"], 1))[0]
        comp, agg = worst
        label = sb.competency_label(comp) or comp
        pct = round((agg["correct"] / max(agg["count"], 1)) * 100, 1)
        lines.append(f"Weakest measured competency in that assessment: {label} "
                     f"({pct}% correct) — prioritize it when explaining and give practice for it.")
    if any(isinstance(f, dict) and f.get("severity") == "high" for f in flags):
        lines.append("Note: that attempt raised a high-severity integrity flag, so its result "
                     "was discounted by the integrity rules.")
    return lines


def _skills_roles_context(student, analysis=None):
    analysis = analysis or _analysis(student)
    lines = _profile_lines(student)
    if not analysis:
        lines.append("Browse roles on Skills & Roles and pick a target career to get a "
                     "personalized skills plan.")
        lines += _assessment_lines(student)
        return lines
    role = analysis.get("role_title") or ""
    lines.append(f"Target role: {_role_line({'title': role}, analysis.get('company'))}")
    gaps = analysis.get("skill_gaps") or []
    lines.append(f"The role requires {len(gaps)} skills. Current standing:")
    for g in gaps:
        req = g.get("required_level")
        own = g.get("student_level") or "none"
        state = _STATUS_LABEL.get(g.get("status"), g.get("status"))
        tag = " [Verified]" if g.get("verified") else ""
        lines.append(f"- {g['skill_name']} (required: {req}, you: {own}) — {state}{tag}")
    lines += _assessment_lines(student)
    return lines


def _learning_context(student, skill_id=None, competency=None):
    lines = _profile_lines(student)
    if skill_id:
        skill = models.get_skill(skill_id)
        if skill:
            lines.append(f"Skill focus: {skill['name']} ({skill.get('category') or 'general'})")
            diagnostic = models.get_latest_diagnostic(student["id"], skill_id)
            if diagnostic and diagnostic.get("completed_at"):
                d = models.public_diagnostic(diagnostic)
                score = d.get("score")
                weak = d.get("weak_topics") or []
                if score is not None:
                    lines.append(f"Latest diagnostic score: {score}/100 "
                                 f"({'passing' if score >= 60 else 'needs work'}).")
                if weak:
                    w = ", ".join(t if isinstance(t, str) else (t.get("label") or t.get("competency") or str(t))
                                  for t in weak[:3])
                    lines.append(f"Weakest topics: {w}.")
            path = models.get_personalized_path(student["id"], skill_id)
            if path:
                p = models.public_personalized_path(path)
                items = p.get("items") or []
                done = sum(1 for i in items if i.get("state") == "done")
                lines.append(f"Personalized path: {len(items)} steps, {done} completed.")
                target = None
                if competency:
                    target = next((i for i in items if i.get("competency") == competency), None)
                if target:
                    lines.append(f"Current step: '{target.get('title')}' "
                                 f"({target.get('action') or 'learn'}) "
                                 f"— {target.get('state') or 'not started'}.")
                    lesson = models.get_lesson(student["id"], p["id"], competency)
                    if lesson:
                        st = lesson.get("state") or "not_started"
                        lines.append(f"Active lesson: '{lesson.get('title')}' ({st}).")
                else:
                    idx = next((i for i, it in enumerate(items) if it.get("state") != "done"), 0)
                    if items:
                        lines.append(f"Work on '{items[idx].get('title')}' next "
                                     f"({items[idx].get('state') or 'not started'}).")
            else:
                lines.append("No personalized path yet — complete the diagnostic to build one.")
            if not models.get_latest_diagnostic(student["id"], skill_id):
                lines.append("No diagnostic taken yet for this skill — start it to get a "
                             "personalized path.")
    else:
        lines.append("No skill selected on the Learning page yet.")
    lines += _assessment_lines(student, skill_id)
    return lines


def _jobs_context(student, job_title=None, job_url=None, country="", location="", analysis=None):
    analysis = analysis or _analysis(student)
    lines = _profile_lines(student)
    role_title = (student.get("target_role") or {}).get("title") or ""
    lines.append(f"Job-hunting as someone aiming for: {role_title or 'a technical role'}.")
    skills = _skills_for_jobs(student)
    role = student.get("target_role") or {}
    requisites = [rs.get("name") for rs in role.get("required_skills") or [] if rs.get("name")]
    try:
        feed = jobs.recent_jobs(skills=skills, role=role_title or "", country=country or "",
                                location=location or "", limit=10, role_requisites=requisites)
    except Exception:
        feed = {"jobs": [], "source": "unavailable"}
    ranked = feed.get("jobs") or []
    selected = None
    if not job_title and not job_url and ranked:
        selected = ranked[0]
    elif job_title or job_url:
        sel = None
        if job_title:
            sel = next((j for j in ranked if (j.get("title") or "").strip().casefold()
                        == job_title.strip().casefold()), None)
        if sel is None and job_url:
            sel = next((j for j in ranked if str(j.get("url") or "") == job_url), None)
        selected = sel or {"title": job_title, "url": job_url, "match_pct": None,
                           "match_reason": None, "company": None, "location": None}
    if selected:
        title = selected.get("title") or ""
        company = selected.get("company")
        loc = selected.get("location")
        lines.append(f"Selected job: {title}"
                     + (f" at {company}" if company else "")
                     + (f" ({loc})" if loc else "") + ".")
        pct = selected.get("match_pct")
        if pct is not None:
            lines.append(f"Your estimated fit: {pct}% with this role.")
        reason = selected.get("match_reason")
        if reason:
            lines.append(f"Why: {reason}.")
    gaps = [g for g in (analysis.get("skill_gaps") or []) if g.get("status") != "strong"] if analysis else []
    if gaps:
        missing = ", ".join(g["skill_name"] for g in gaps[:4])
        lines.append(f"Skills this career wants that you don't fully meet yet: {missing}.")
    elif not selected and ranked:
        lines.append("Openings to consider: " + ", ".join(
            (j.get("title") or "").splitlines()[0] if (j.get("title") or "") else "?"
            for j in ranked[:3]) + ".")
    return lines


def _roadmap_context(student, analysis=None):
    lines = _profile_lines(student)
    analysis = analysis or _analysis(student)
    role = student.get("target_role") or {}
    if not role:
        lines.append("Choose a target career first — the roadmap builds itself from the "
                     "skills that role requires.")
        return lines
    try:
        saved = models.get_career_roadmap(student["id"], role.get("id"))
        roadmap = career_roadmap.normalize_roadmap(
            saved.get("roadmap") if saved else
            career_roadmap.build_career_roadmap(student, role))
    except Exception:
        roadmap = {"role_title": None, "phases": [], "summary": "Roadmap unavailable."}
    lines.append(f"Career roadmap for: {roadmap.get('role_title') or role.get('title')}.")
    summary = roadmap.get("summary")
    if summary:
        lines.append(summary)
    phases = roadmap.get("phases") or []
    if phases:
        lines.append(f"The roadmap has {len(phases)} phases:")
        for i, ph in enumerate(phases[:3]):
            lines.append(f"- Phase {ph.get('phase') or i + 1}: {ph.get('title')} — {ph.get('goal')}")
        first = phases[0]
        lines.append(f"Next step: start Phase {first.get('phase') or 1} ({first.get('title')}).")
    else:
        lines.append("The roadmap is empty — select a target career on Skills & Roles.")
    return lines


def _mock_interview_context(student):
    lines = _profile_lines(student)
    role_title = (student.get("target_role") or {}).get("title")
    lines.append("The student is in a mock interview.")
    if role_title:
        lines.append(f"Target role for the interview: {role_title}.")
    return lines


def build_context(student, page="dashboard", skill_id=None, competency=None,
                  job_title=None, job_url=None, country="", location=""):
    """Build the trusted context string for a page. Never raises on missing data."""
    page = (page or "dashboard").strip().lower()
    if page not in PAGES:
        page = "dashboard"
    label = PAGE_LABELS.get(page, page.replace("_", " ").title())
    if page == "assessment":
        return {
            "page": page,
            "label": label,
            "context": ("The Verified Final Assessment is in progress. The AI Tutor is "
                        "unavailable during the assessment to protect its integrity."),
        }
    analysis = None
    if page in ("dashboard", "skills_roles", "jobs", "career_roadmap"):
        analysis = _analysis(student)
    builder = {
        "dashboard": lambda: _dashboard_context(student, analysis),
        "skills_roles": lambda: _skills_roles_context(student, analysis),
        "learning": lambda: _learning_context(student, skill_id, competency),
        "jobs": lambda: _jobs_context(student, job_title, job_url, country, location, analysis),
        "career_roadmap": lambda: _roadmap_context(student, analysis),
        "mock_interview": lambda: _mock_interview_context(student),
    }[page]
    try:
        lines = builder()
    except Exception:
        lines = _profile_lines(student) + [
            "Some context could not be loaded — answer from general knowledge."]
    return {"page": page, "label": label, "context": "\n".join(lines)}