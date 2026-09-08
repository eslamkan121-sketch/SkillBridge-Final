"""Full end-to-end career roadmap for a student's target role.

This is the *master* roadmap: one big picture plan from absolute start to
job-ready, complementing the per-skill micro-roadmaps that appear inside each
learning item. It is generated deterministically from the target role's actual
required-skills catalog plus the student's current skill levels, so the phases
are always relevant to *their* role and never generic filler.

The roadmap is a sequence of numbered phases. Each phase has a title, a
goal / objective, concrete deliverables, the role skills it develops, a
checkpoint that tells the student how to know they are done, and a ``resources``
list of on-topic learning links for the phase (derived from its focus skills,
or topical general material for skill-less phases). The skills the
student still needs to build (their gaps) are pushed earlier / highlighted so
the plan reads start-to-finish.
"""
from . import resources as resources_mod

_LEVEL = {"Beginner": 1, "Intermediate": 2, "Advanced": 3}

# Phase template: (title, body_goal), body_goal receives the role title.
# Each phase can declare which skill *categories* it focuses on; skill
# placement is resolved at build time from the role's required skills.
_PHASE_SPECS = [
    ("Build a working foundation",
     "Before specialising you need the daily toolkit every {role} relies on. "
     "Set up your environment, master a version-control workflow, and get "
     "comfortable writing and reading code every day."),
    ("Core programming toolkit",
     "Solidify the programming skills a {role} actually uses at work — not "
     "just tutorials, but realistic, multi-file problems and clean code "
     "habits you can defend in code review."),
    ("Data handling & storage",
     "A {role} lives on data. Learn how to query, clean, transform and model "
     "data with the tools the role specifies, then practice on messy, "
     "realistic datasets."),
    ("Domain & platform skills",
     "Go deep on the technologies that are the heart of the {role}: the ML / "
     "cloud / analytics / engineering stack in the role spec. Build working "
     "examples end to end, not toy snippets."),
    ("Production skills (deploy, version, automate)",
     "Learn to ship — containers, automated pipelines, version control at "
     "team scale, and the operational skills that turn a demo into something "
     "a company would run."),
    ("Build a portfolio project",
     "Produce a polished, portfolio-quality project that exercises the full "
     "role stack, is documented, tested, and deployed, and that you can talk "
     "through in an interview."),
    ("Verify your skills",
     "Prove what you know by taking the role's assessments here on "
     "SkillBridge and turning self-reported skills into verified, shareable "
     "evidence recruiters can trust."),
    ("Soft skills & collaboration",
     "The role is technical, but jobs are won and kept through communication, "
     "teamwork, problem-solving and ownership. Develop these alongside your "
     "hard skills."),
    ("Sharpen your job application materials",
     "Turn your skills, verified evidence and portfolio into a strong CV, an "
     "optimised LinkedIn profile, and an elevator pitch targeted at the "
     "{role} role."),
    ("Practice interviews & applications",
     "Apply, get your CV reviewed, practice live technical and behavioural "
     "interviews, and iterate on feedback until you're ready to accept an "
     "offer."),
    ("First-job readiness & continuous growth",
     "Land the role, then keep the momentum: onboard fast, deliver early, and "
     "keep your verified-skill profile current so your next move is even "
     "better."),
]

_NON_SOFTWARE_PHASE_SPECS = [
    ("Build a professional foundation",
     "Before specialising you need the daily workflow, standards, and tools a "
     "{role} relies on. Set up a clean workspace, learn how work is reviewed, "
     "and practice documenting decisions others can follow."),
    ("Core role toolkit",
     "Build confidence with the core methods and tools a {role} actually uses "
     "at work. Focus on realistic tasks, clear judgement, and repeatable "
     "habits rather than disconnected tutorials."),
    ("Information, research & analysis",
     "Learn how a {role} gathers, evaluates, organises, and interprets "
     "information before making recommendations or producing deliverables."),
    ("Domain craft & tools",
     "Go deep on the domain-specific skills at the heart of the {role}. "
     "Produce realistic examples that show your process, decisions, and final "
     "output."),
    ("Workflow, quality & delivery",
     "Practice delivering work reliably: version your files, check quality, "
     "handle feedback, and prepare outputs so a team or client can use them."),
    ("Build a portfolio case study",
     "Produce a polished, portfolio-quality case study that exercises the full "
     "role toolkit, documents your reasoning, and gives you something concrete "
     "to discuss in an interview."),
    _PHASE_SPECS[6],
    ("Communication & collaboration",
     "The role is professional and collaborative: develop communication, "
     "feedback handling, problem-solving and ownership alongside your domain "
     "skills."),
    _PHASE_SPECS[8],
    _PHASE_SPECS[9],
    _PHASE_SPECS[10],
]

# Which phase(s) map to which skill category, and their display grouping.
# ``primary`` is the phase a category most belongs to; ``secondary`` lets an
# abundant category spill into neighbouring phases so a role whose skills all
# fall in one category (e.g. a Security-heavy role) still fills the whole
# journey instead of stacking everything into a single phase. Skills are
# distributed round-robin across primary + secondary phases.
_CATEGORY_PHASE = {
    "Programming": {"primary": [1], "secondary": [0, 5]},
    "Data": {"primary": [2], "secondary": [1, 3]},
    "AI": {"primary": [3], "secondary": [1, 5]},
    "DevOps": {"primary": [4], "secondary": [0, 5]},
    "Security": {"primary": [4], "secondary": [0, 1, 2, 3, 5]},
    "Analytics": {"primary": [2, 3], "secondary": [1]},
    "Visualization": {"primary": [2, 3], "secondary": [1]},
    "Design": {"primary": [3], "secondary": [0, 1, 5, 7]},
    "Marketing": {"primary": [2, 3], "secondary": [1, 5, 8]},
    "Finance": {"primary": [2, 3], "secondary": [1, 4, 5]},
    "Architecture": {"primary": [3, 4], "secondary": [0, 1, 5]},
    "Clinical": {"primary": [2, 3], "secondary": [1, 4, 7]},
    "Legal": {"primary": [2, 3], "secondary": [1, 5, 7]},
    "Soft Skills": {"primary": [7], "secondary": [8, 9]},
}

_PHASE_TITLES = [p[0] for p in _PHASE_SPECS]

# Topical resources for the phases that focus on process rather than a specific
# role skill, so every stage of the journey still has real, on-topic material.
# (These are intentionally specific pages — never channel or site homepages.)
_PHASE_EXTRA_RESOURCES = {
    5: [
        {"title": "GitHub Pages — publish your project site", "url": "https://pages.github.com/", "type": "doc"},
        {"title": "What is a portfolio project? (Indeed Career Advice)", "url": "https://www.indeed.com/career-advice/career-development/what-is-a-portfolio", "type": "article"},
    ],
    6: [
        {"title": "What an assessment centre is (Indeed Career Advice)", "url": "https://www.indeed.com/career-advice/interviewing/assessment-center", "type": "article"},
    ],
    7: [
        {"title": "What Is Effective Communication? (Indeed Career Advice)", "url": "https://www.indeed.com/career-advice/career-development/what-is-effective-communication", "type": "article"},
        {"title": "Teamwork Skills: Being an Effective Group Member (SkillsYouNeed)", "url": "https://www.skillsyouneed.com/ips/teamwork.html", "type": "article"},
    ],
    8: [
        {"title": "How to write a resume (Indeed Career Advice)", "url": "https://www.indeed.com/career-advice/resumes-cover-letters/resume-writing", "type": "article"},
        {"title": "How to optimise your LinkedIn profile (Indeed Career Advice)", "url": "https://www.indeed.com/career-advice/career-development/how-to-optimize-linkedin-profile", "type": "article"},
    ],
    9: [
        {"title": "How Google interviews (official careers guide)", "url": "https://careers.google.com/how-we-hire/interview/", "type": "article"},
        {"title": "STAR method for interview answers (Indeed Career Advice)", "url": "https://www.indeed.com/career-advice/interviewing/star-method", "type": "article"},
    ],
    10: [
        {"title": "Career development advice (Indeed Career Advice)", "url": "https://www.indeed.com/career-advice/career-development", "type": "article"},
    ],
}


def _phase_resources(phase_skills, phase_idx, phase_title=None):
    """On-topic learning links for one phase: one source per focus skill (from
    the curated/skill-scoped resource index, no live checks), then topical
    material for process phases. Every phase ends up with at least one real,
    topic-bearing link — never a bare platform homepage."""
    out, seen = [], set()
    for s in (phase_skills or [])[:3]:
        fetched = resources_mod.retrieve_resources(
            s["name"], s["category"], "", live_check=False, max_items=6)
        for r in fetched:
            r = dict(r)
            if r["url"] in seen or genai_is_generic(r["url"]):
                continue
            seen.add(r["url"])
            out.append({"title": r["title"], "url": r["url"], "type": r["type"]})
            break
        if len(out) >= 3:
            break
    for r in _PHASE_EXTRA_RESOURCES.get(phase_idx, []):
        if r["url"] not in seen:
            seen.add(r["url"])
            out.append(dict(r))
    if not out:
        # Skill-less phase with no topical extra: pull title-/topic-scoped,
        # titled search links (never bare platform homepages) and prefer the
        # phase's own title + any category name so the links say something
        # about the stage, not the platform.
        topic = " ".join(str(s.get("name", "")) for s in (phase_skills or [])[:2])
        topic = topic or phase_title or _PHASE_TITLES[phase_idx]
        out = [dict(r) for r in resources_mod._generic_fallback(topic)]
        out = out[:2]
    out = resources_mod.sanitize_resources(out)
    return out


def genai_is_generic(url):
    """Reuse the genai module's generic-URL detection without a hard import
    cycle (career_roadmap already imports resources; genai imports both)."""
    try:
        from . import genai as genai_mod
        return genai_mod._is_generic_resource_url(url)
    except Exception:
        return False


def _deliverables(idx, categories, cat_skills):
    """Human deliverables for a phase based on its focused skill categories and
    the concrete work of the journey stage. Every phase has actionable
    deliverables — never a "go figure it out" placeholder."""
    if categories:
        lines = []
        has = set()
        for cat in categories:
            for s in cat_skills.get(cat, [])[:3]:
                has.add(s)
        for s in sorted(has):
            lines.append(f"Reach a confident working level in **{s}** (see its "
                         "learning item for resources and a step-by-step plan).")
        if len(lines) >= 2:
            # Skill-specific phase: keep the learning-driven deliverables plus
            # one concrete artifact so there is something to actually produce.
            lines.append("Produce a short write-up of what you built and the "
                         "tooling you used, so each phase leaves evidence.")
        return lines or [f"Complete the learning items for the skills listed under this phase."]

    # Stage-specific deliverables for skill-less phases (portfolio, evidence,
    # applications, interview practice, first job).
    stage_deliverables = {
        0: ["Set up a clean role workspace, organise your files and notes, and "
            "track one first project from brief to reflection."],
        1: ["Complete one small role-relevant task using the role's core tools, "
            "then document what you did and why."],
        2: ["Gather realistic source material, analyse it, and produce one clear "
            "answer or recommendation."],
        3: ["Build one working example of the role's central tool or method end "
            "to end, and document how you produced it."],
        4: ["Create a repeatable quality-check and handoff workflow so someone "
            "else could review or continue your work."],
        5: ["Produce a polished, documented project that exercises the role toolkit "
            "and that you can demo and defend."],
        6: ["Take the role's assessments on SkillBridge, pass the ones you have "
            "not yet verified, and collect the verified proof to share."],
        7: ["Do one realistic collaborative task with peers, a reviewer, or a "
            "client-style stakeholder, then reflect on what changed."],
        8: ["Target your CV, LinkedIn headline and elevator pitch to the role and "
            "get one piece of external feedback on the result."],
        9: ["Apply to one real posting, record yourself answering a role-specific "
            "and a behavioural question, and note what to improve."],
        10: ["Accept a first role or commit to a growth plan, and schedule a "
             "quarterly check on your verified-skill profile."],
    }
    return stage_deliverables.get(idx) or [
        "Complete the actions described in this phase and confirm the checkpoint below."]


def _uses_software_roadmap(role_title, cat_skills):
    title = (role_title or "").lower()
    if any(word in title for word in (
        "engineer", "developer", "software", "programmer", "cloud", "devops",
        "cybersecurity", "security analyst", "data scientist", "data engineer",
    )):
        return True
    return any(cat in cat_skills for cat in ("Programming", "AI", "DevOps", "Security"))


def _assign_phases(cat_skills):
    """Distribute the role's skills across phases by category affinity.

    Returns ``{phase_idx: [skill_name, ...]}``. Skills are spread round-robin
    across a category's primary + secondary phases so one-category roles still
    fill the whole technical journey.
    """
    assigned = {}
    for cat, skills in cat_skills.items():
        slots = _CATEGORY_PHASE.get(cat)
        if not slots:
            continue
        order = (slots.get("primary") or []) + (slots.get("secondary") or [])
        if not order:
            continue
        # Keep a stable round-robin distribution across the ordered slots.
        for i, name in enumerate(skills):
            phase = order[i % len(order)]
            assigned.setdefault(phase, []).append(name)
    return assigned


def normalize_roadmap(roadmap):
    """Coerce stored/cached roadmap data into a stable, frontend-safe shape."""
    if not isinstance(roadmap, dict):
        return {"role_title": None, "phases": [], "phase_count": 0,
                "summary": "Choose a target role on the Skills & Roles page first."}
    out = dict(roadmap)
    phases = []
    for phase in roadmap.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        p = dict(phase)
        if not isinstance(p.get("deliverables"), list):
            d = p.get("deliverables")
            p["deliverables"] = [str(d)] if d else []
        if not isinstance(p.get("skills"), list):
            p["skills"] = []
        if not isinstance(p.get("resources"), list):
            p["resources"] = []
        phases.append(p)
    out["phases"] = phases
    out["phase_count"] = len(phases)
    return out


def build_career_roadmap(student, role):
    """Generate the full start-to-finish roadmap for a student's target role.

    ``student`` is the student dict (with self_reported_skills / verified_skills).
    ``role`` is the role dict with ``required_skills``.
    """
    role_title = (role or {}).get("title") or "the role"
    required = (role or {}).get("required_skills") or []

    # Categorise the role's required skills by category.
    cat_skills = {}
    for rs in required:
        cat = rs.get("category") or "Other"
        cat_skills.setdefault(cat, []).append(rs.get("name", ""))

    # Determine the student's strongest level per role-relevant skill to decide
    # whether a phase can be described as "you already have this".
    own = {}
    for s in student.get("self_reported_skills") or []:
        own.setdefault(s["skill_id"], _LEVEL.get(s.get("level"), 1))
    for v in student.get("verified_skills") or []:
        own.setdefault(v["skill_id"], max(own.get(v["skill_id"], 1), _LEVEL.get(v.get("level"), 1)))

    # How many distinct categories does the role actually require up front?
    had = sum(1 for rs in required if own.get(rs["skill_id"]) is not None)
    ready = 3 if had >= 6 else 2 if had >= 3 else 1 if had >= 1 else 0

    # Distribute the role's skills across phases by category affinity so the
    # whole journey is populated (not just the phases with a matching category).
    assigned = _assign_phases(cat_skills)
    software_roadmap = _uses_software_roadmap(role_title, cat_skills)
    phase_specs = _PHASE_SPECS if software_roadmap else _NON_SOFTWARE_PHASE_SPECS

    phases = []
    for idx, (title, goal_template) in enumerate(phase_specs):
        names = assigned.get(idx, [])
        cats = sorted({c for c, skills in cat_skills.items() if any(n in skills for n in names)})
        focus_names = names
        steps = _deliverables(idx, cats, {c: [n for n in cat_skills.get(c, []) if n in focus_names] for c in cats})
        phase_skills = [{"name": n, "category": c} for c in cats for n in cat_skills.get(c, []) if n in focus_names]
        if not phase_skills and idx not in (6, 7):
            # A skill-less technical phase still needs focus skills so the stage
            # has real learning material: pull the role's remaining hard skills
            # round-robin (deterministic order = role spec order).
            all_technical = [n for c in _CATEGORY_PHASE if c in cat_skills
                             for n in cat_skills[c]]
            if all_technical:
                pick = all_technical[idx % len(all_technical)]
                matched = next(
                    ({"name": pick, "category": c} for c in cat_skills if pick in cat_skills[c]),
                    None)
                phase_skills = [matched] if matched else []
        phases.append({
            "phase": idx + 1,
            "title": title,
            "goal": goal_template.format(role=role_title),
            "skills": phase_skills,
            "deliverables": steps,
            "resources": _phase_resources(phase_skills, idx, title),
            "checkpoint": _checkpoint(idx, ready, role_title, software_roadmap),
        })
    return {
        "role_title": role_title,
        "resources_version": 4,
        "summary": (f"A complete, start-to-finish path from zero to a "
                    f"job-ready {role_title}. Finish every phase and you'll have "
                    f"the skills, verified evidence, portfolio and interview "
                    f"readiness to apply with confidence."),
        "student_starting_point": ready,
        "phase_count": len(phases),
        "phases": phases,
    }


def _checkpoint(idx, ready, role_title, software=True):
    if not software:
        if idx == 0:
            return "You can organise a role-relevant project and explain the standards you are following."
        if idx == 1:
            return "You can complete a small role task with the core tools and explain your decisions."
        if idx == 2:
            return "You can gather and evaluate information, then turn it into a clear recommendation."
        if idx == 3:
            return "You can produce a realistic role deliverable and describe the process behind it."
        if idx == 4:
            return "You can review, revise and hand off work so another person can use it confidently."
        if idx == 5:
            return "You have a polished case study or portfolio piece you can discuss in an interview."
        if idx == 6:
            return "You have passed the role's skill assessments and can share verified proof."
        if idx == 7:
            return "You can communicate decisions and respond to stakeholder feedback on realistic tasks."
        if idx == 8:
            return "Your CV, LinkedIn and pitch are targeted at a {role_title} and ready to send.".replace("{role_title}", role_title)
        if idx == 9:
            return "You've practiced interviews and applications, collected feedback, and know what to improve."
        return "You've accepted a role or committed to a growth plan, and you know how to keep improving."
    if idx == 0:
        return "You can set up a project from scratch, commit cleanly, and explain what you're building."
    if idx == 1:
        return "You can solve multi-file problems in your core language without looking things up constantly."
    if idx == 2:
        return "You can load a messy dataset, query it, and produce a clean, correct result."
    if idx == 3:
        return "You can build and run a working example of the role's core technologies end to end."
    if idx == 4:
        return "You can containerise, version and automate your work so someone else can run it too."
    if idx == 5:
        return "You have a deployed, documented, portfolio-ready project you can demo in an interview."
    if idx == 6:
        return "You have passed the role's skill assessments and can share verified proof."
    if idx == 7:
        return "You can describe your experience and work with a team on realistic tasks."
    if idx == 8:
        return "Your CV, LinkedIn and pitch are targeted at a {role_title} and ready to send.".replace("{role_title}", role_title)
    if idx == 9:
        return "You've interviewed, collected feedback, and know exactly what to improve for your next application."
    return "You've accepted an offer and have a plan to keep your skills verified and growing."
