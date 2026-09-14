"""Skill Gap Analysis and Job Match Score engine.

Compares a student's available skills (self-reported, upgraded by verified level
where available) against their target role's required skills, categorizing each as
strong / gap / missing, and producing a live Job Match Score.

Evidence rules (locked by tests):
  - A required skill matched by its skill id is exact evidence.
  - A requirement whose *name* is identical (normalised) to a student skill is
    exact evidence for that skill.
  - A requirement whose name merely overlaps a student skill (token match or
    containment, e.g. ``security`` within ``cybersecurity``) is ADJACENT
    evidence: it always lands in the ``gap`` tier and earns reduced credit
    (never ``strong``). This stops differently-worded ESCO/O*NET requirement
    strings from silently producing a 0% profile when the student clearly has
    related skills. Generic frame tokens (manage/management/plan/policy/...)
    are excluded so unrelated requirements can never match.
"""
import re

from . import models, skill_registry

_LEVEL_SCORE = {"Beginner": 1, "Intermediate": 2, "Advanced": 3}

# Credit multiplier applied to ADJACENT-name evidence (honest partial credit).
_NAME_ADJACENT_CREDIT = 0.5

# Frame tokens that carry little subject signal in ESCO-style requirement
# phrases; excluded from adjacency matching so they can never cause a false
# match (e.g. Vulnerability Management must not match "ICT problem management").
_NAME_STOP_TOKENS = frozenset((
    "a", "an", "the", "of", "for", "to", "in", "on", "and", "or", "with",
    "at", "by", "as", "it", "its", "ict", "icts",
    "manage", "management", "maintain", "develop", "implement", "establish",
    "define", "lead", "solve", "plan", "plans", "planning", "techniques",
    "technique", "exercises", "exercise", "policy", "policies", "strategies",
    "strategy", "standards", "standard", "requirements", "requirement",
    "governance", "system", "systems", "problems", "problem", "quality",
    "legal", "internal", "internet", "project", "projects", "product",
    "products", "services", "process", "processes", "compliances",
    "compliance", "prevention", "information", "user", "users", "things",
))


def _tokens(name):
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return [w for w in words if w not in _NAME_STOP_TOKENS and len(w) >= 3]


def _first_token_hit(req_tokens, skill_tokens):
    for rt in req_tokens:
        for st in skill_tokens:
            if rt == st:
                return rt
    # Containment (either direction) requires a 4+ char token so short common
    # syllables can never force a match.
    for rt in req_tokens:
        for st in skill_tokens:
            if len(rt) >= 4 and (rt in st or st in rt):
                return rt
    return None


def _name_evidence(student, req_name):
    """Best student-skill evidence for a requirement BY NAME only (exact or
    adjacent), used when the requirement's skill id is not in the profile.

    Returns a dict {student_level, verified, matched_by, matched_skill} or None.
    """
    srs = student.get("self_reported_skills") or []
    vs = student.get("verified_skills") or []
    if (not srs and not vs) or not (req_name or "").strip():
        return None
    key = skill_registry._key(req_name)
    best_by_key = {}
    for ss in srs:
        n, lvl = (ss.get("name") or ""), ss.get("level")
        if n and lvl:
            best_by_key.setdefault(skill_registry._key(n), (lvl, False))
    for v in vs:
        n, lvl = (v.get("name") or ""), v.get("level")
        if n and lvl and skill_registry._key(n) in best_by_key:
            best_by_key[skill_registry._key(n)] = (lvl, True)
    if key in best_by_key:
        lvl, ver = best_by_key[key]
        return {"student_level": lvl, "verified": ver,
                "matched_by": "name_exact", "matched_skill": req_name}
    req_tokens = _tokens(req_name)
    best = None
    for ss in srs + vs:
        cand = _tokens(ss.get("name") or "")
        if not cand:
            continue
        hit = _first_token_hit(req_tokens, cand)
        if hit is None:
            continue
        lvl = ss.get("level")
        if best is None or _LEVEL_SCORE[lvl] > _LEVEL_SCORE[best["student_level"]]:
            best = {"student_level": lvl, "verified": False,
                    "matched_by": "name_adjacent",
                    "matched_skill": ss.get("name"), "matched_token": hit}
    return best


def _evidence_for_requirement(student, rs):
    """(student_level, verified, matched_by, matched_skill) for one required
    skill row.

    Resolution order: exact skill id -> normalised-name equality ->
    name-adjacent token overlap. ``matched_by`` is 'id' | 'name_exact' |
    'name_adjacent' (None when there is no evidence at all); ``matched_skill``
    is the student skill that produced name-based evidence (None otherwise).
    """
    sid = rs.get("skill_id")
    if sid is not None:
        level, verified = effective_skill_level(student, sid)
        if level is not None:
            return level, verified, "id", None
    ev = _name_evidence(student, rs.get("name"))
    if ev:
        return ev["student_level"], ev["verified"], ev["matched_by"], ev.get("matched_skill")
    return None, False, None, None


def requirement_credit(student_level, required_level, matched_by="id"):
    """0..1 credit for a single required skill. Shared by ``job_match_score``
    and the Phase-J target-role breakdown so the displayed sum always equals
    the ring. Exact evidence: full credit at/above the required level, else the
    progress ratio. Adjacent-name evidence: half that (honest partial credit)."""
    if student_level is None or not required_level:
        return 0.0
    sv = _LEVEL_SCORE[student_level]
    rv = _LEVEL_SCORE.get(required_level, 2)
    full = 1.0 if sv >= rv else sv / rv
    if matched_by == "name_adjacent":
        return round(full * _NAME_ADJACENT_CREDIT, 6)
    return full


def effective_skill_level(student, skill_id):
    """Best available evidence for a skill: verified level wins over self-reported.

    Returns (level, verified: bool).
    """
    for vs in student.get("verified_skills", []):
        if vs["skill_id"] == skill_id:
            return vs["level"], True
    for ss in student.get("self_reported_skills", []):
        if ss["skill_id"] == skill_id:
            return ss["level"], False
    return None, False


def categorize(student, role):
    """Return per-required-skill analysis: {skill, level, status, verified}.

    status: 'strong' (covered at/above requirement), 'gap' (present but below
    requirement, or adjacent-name evidence only), 'missing' (not present).
    Adjacent-name rows also carry ``matched_skill`` (the student skill that
    produced the evidence) so the UI can show honest partial evidence.
    """
    result = []
    for rs in role.get("required_skills", []):
        level, verified, matched_by, matched_skill = _evidence_for_requirement(student, rs)
        if level is None:
            status = "missing"
        elif matched_by != "name_adjacent" and _LEVEL_SCORE[level] >= _LEVEL_SCORE[rs["required_level"]]:
            status = "strong"
        else:
            status = "gap"
        result.append({
            "skill_id": rs["skill_id"],
            "skill_name": rs["name"],
            "category": rs.get("category"),
            "required_level": rs["required_level"],
            "student_level": level,
            "status": status,
            "verified": verified,
            "matched_by": matched_by,
            "matched_skill": matched_skill,
        })
    return result


def job_match_score(student, role):
    """Percent match: for each required skill, fully-satisfied requirements earn
    proportional credit; gaps earn partial credit proportional to progress toward
    the required level; adjacent-name evidence earns reduced credit; missing
    skills earn nothing. Equal weight per skill.
    """
    if not role or not role.get("required_skills"):
        return 0.0
    total = len(role["required_skills"])
    earned = 0.0
    for rs in role["required_skills"]:
        level, _verified, matched_by, _mat = _evidence_for_requirement(student, rs)
        earned += requirement_credit(level, rs["required_level"], matched_by)
    return round((earned / total) * 100, 1)


def gap_skills(student, role):
    """List of required skills the student still needs to work on (gaps + missing),
    sorted with missing first then by most deficient. Returns the detailed dicts."""
    rows = categorize(student, role)
    return [r for r in rows if r["status"] in ("gap", "missing")]


def analyze_student(student_id):
    """Convenience: load a student and their target role, return analysis bundle."""
    student = models.get_student(student_id)
    role = student.get("target_role") if student else None
    if not student or not role:
        return None
    analysis = categorize(student, role)
    score = job_match_score(student, role)
    return {
        "student_id": student_id,
        "role_id": role["id"],
        "role_title": role["title"],
        "company": role.get("company_name"),
        "match_score": score,
        "skill_gaps": analysis,
        "gap_count": len([a for a in analysis if a["status"] != "strong"]),
    }
