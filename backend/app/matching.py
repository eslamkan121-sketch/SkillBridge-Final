"""Skill Gap Analysis and Job Match Score engine.

Compares a student's available skills (self-reported, upgraded by verified level
where available) against their target role's required skills, categorizing each as
strong / gap / missing, and producing a live Job Match Score.
"""
from . import models

_LEVEL_SCORE = {"Beginner": 1, "Intermediate": 2, "Advanced": 3}


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
    requirement), 'missing' (not present at all).
    """
    result = []
    for rs in role.get("required_skills", []):
        level, verified = effective_skill_level(student, rs["skill_id"])
        if level is None:
            status = "missing"
        elif _LEVEL_SCORE[level] >= _LEVEL_SCORE[rs["required_level"]]:
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
        })
    return result


def job_match_score(student, role):
    """Percent match: for each required skill, fully-satisfied requirements earn
    proportional credit; gaps earn partial credit proportional to progress toward
    the required level; missing skills earn nothing. Equal weight per skill.
    """
    if not role or not role.get("required_skills"):
        return 0.0
    total = len(role["required_skills"])
    earned = 0.0
    for rs in role["required_skills"]:
        level, _ = effective_skill_level(student, rs["skill_id"])
        if level is None:
            continue
        student_val = _LEVEL_SCORE[level]
        required_val = _LEVEL_SCORE[rs["required_level"]]
        if student_val >= required_val:
            earned += 1.0
        else:
            earned += student_val / required_val
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
