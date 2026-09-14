"""Phase J — explainable role and job matching.

Additive, read-only decomposition of the three displayed "match" numbers:

  TARGET_ROLE_MATCH_FORMULA  the Dashboard target-role ScoreRing
                             (matching.job_match_score / analyze_student)
  ROLE_MATCH_FORMULA         recommendation cards' rings
                             (recommendations.recommend)
  JOB_MATCH_FORMULA          jobs feed rows (jobs._score_job / _apply)

Every breakdown re-runs the SAME arithmetic with the SAME inputs used to
produce the number the app already displays, and emits every intermediate as
labelled components and adjustment lines that sum EXACTLY to that number. If a
recomputation ever disagrees with the displayed value, the code raises
``MatchExplainError(500)`` and the conflict is logged audibly — the guide's
"stop and document rather than change the displayed score silently" rule. No
phase-J code changes any displayed score.

Honesty rules (locked by tests):
  - Self-reported evidence is never presented as "verified".
  - Missing external data stays "unknown"/"none" — never converted to 0/false.
  - Evidence precedence: verified > self_reported
    (via matching.effective_skill_level for the target-role match).
"""
import datetime

from . import jobs, matching, recommendations

TARGET_ROLE_MATCH_FORMULA = "target-role-match"
TARGET_ROLE_MATCH_VERSION = "target-role-match-v1"
ROLE_MATCH_FORMULA = "role-match"
ROLE_MATCH_VERSION = "role-match-v1"
JOB_MATCH_FORMULA = "job-match"
JOB_MATCH_VERSION = "job-match-v1"


class MatchExplainError(Exception):
    """Raised by the breakdown builders when a request cannot be satisfied or
    when an exact total cannot be produced (status_code 500 + message)."""

    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _as_of():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _fmt(points):
    return round(float(points), 2) if points is not None else None


def _evidence_of(verified):
    return "verified" if verified else "self_reported"


def _role_data_version(role):
    v = (role or {}).get("source_version")
    return v or "local"


def _role_adjustment_lines(raw, displayed):
    """Adjustment lines that make a role-match total sum EXACTLY to the
    displayed percent: an optional cap-at-100 line (discovery credit can push
    the raw ratio past 100) and the always-present 1-decimal rounding line."""
    clamped = min(100.0, raw)
    lines = []
    if clamped != raw:
        lines.append({
            "label": "cap_at_100",
            "label_long": "Discovery credit may exceed total weight; the percent is capped at 100",
            "points": _fmt(clamped - raw),
        })
    lines.append({
        "label": "rounding",
        "label_long": "Round to 1 decimal place",
        "points": _fmt(displayed - clamped),
    })
    return lines


# ---------------------------------------------------------------------------
# 1. Target-role match (matching.job_match_score)
# ---------------------------------------------------------------------------
def target_role_match_breakdown(student):
    """Decompose the Dashboard's ``analysis.match_score`` for the student's
    current target role.

    Reuses ``matching.categorize`` for the per-skill rows and the SAME
    per-requirement credit helper ``job_match_score`` uses (equal weight per
    required skill; full credit at/above requirement, partial credit by
    progress, reduced credit for adjacent-name evidence, zero when missing) so
    the recomputed total must equal the displayed percent. Raises
    ``MatchExplainError`` on parity failure or a missing target role.
    """
    role = student.get("target_role") if student else None
    if not role:
        raise MatchExplainError(404, "No target role is set for this student.")
    rows = matching.categorize(student, role)
    total = len(rows)
    if not total:
        raise MatchExplainError(404, "Target role has no required skills.")
    earned = 0.0
    detail = []
    for r in rows:
        student_level = r["student_level"]
        contribution = matching.requirement_credit(
            student_level, r["required_level"], r.get("matched_by") or "id")
        earned += contribution
        detail.append({
            "skill_id": r["skill_id"],
            "skill_name": r["skill_name"],
            "category": r.get("category"),
            "required_level": r["required_level"],
            "student_level": student_level,
            "status": r["status"],
            "matched_by": r.get("matched_by"),
            "matched_skill": r.get("matched_skill"),
            "evidence": "none" if student_level is None else _evidence_of(r["verified"]),
            "contribution_points": round(contribution, 3),
            "max_points": 1.0,
        })
    raw_percent = earned / total * 100.0
    displayed_percent = matching.job_match_score(student, role)
    if abs(round(raw_percent, 1) - displayed_percent) > 1e-6:
        raise MatchExplainError(
            500, "Cannot decompose target-role match exactly: recomputed "
                 f"{raw_percent:.4f} != displayed {displayed_percent}. "
                 "No score was changed; refusing to present a wrong sum.")
    missing_rows = [d for d in detail if d["status"] == "missing"]
    gap_rows = [d for d in detail if d["status"] == "gap"]
    if not missing_rows and not gap_rows:
        next_action = "You meet this role's skill requirements — keep your evidence current."
    else:
        first = (missing_rows or gap_rows)[0]
        verb = "Learn or verify" if first["status"] == "missing" else "Close the gap on"
        next_action = (f"{verb} {first['skill_name']} (required: "
                       f"{first['required_level']}) to raise your role match.")
    return {
        "formula": TARGET_ROLE_MATCH_FORMULA,
        "version": TARGET_ROLE_MATCH_VERSION,
        "as_of": _as_of(),
        "role_data_version": _role_data_version(role),
        "role_title": role.get("title"),
        "company": role.get("company_name"),
        "requirements": detail,
        "total_points": _fmt(total),
        "max_points": _fmt(total),
        "raw_percent": _fmt(raw_percent),
        "displayed_percent": displayed_percent,
        "adjustment_lines": [{
            "label": "rounding",
            "label_long": "Round raw percent to 1 decimal place",
            "points": _fmt(displayed_percent - raw_percent),
        }],
        "evidence_precedence": "verified > self_reported (only passed assessments verify)",
        "missing_data": [d["skill_name"] for d in missing_rows],
        "next_action": next_action,
    }


# ---------------------------------------------------------------------------
# 2. Role recommendations (recommendations.recommend)
# ---------------------------------------------------------------------------
def _role_decode(query):
    """Role-match selection from query params: (role_id or None, external_id or None)."""
    if query is None:
        return None, None
    text_id = str(query).strip()
    # Local/catalog roles are identified by integer pk; ESCO by uri.
    if text_id.isdigit():
        return int(text_id), None
    if text_id:
        return None, text_id
    return None, None


def role_match_breakdown(student, query):
    """Decompose a recommendation card's ``match_score``.

    The candidate must appear in the student's CURRENT recommendation list
    (the exact list that rendered the ring), found by ``role_id`` (int) or
    ``external_id`` (ESCO uri). The detail rows come from
    ``recommendations.recommend(..., _include_detail=True)`` -- the SAME detail
    computed when the score was produced, so parity is by construction and the
    clamp/rounding adjustment lines sum exactly to the displayed ``match_score``.
    """
    if student is None:
        raise MatchExplainError(404, "Student not found.")
    role_id, external_id = _role_decode(query)
    bundle = recommendations.recommend(student, _include_detail=True)
    rec = None
    for r in bundle["recommendations"]:
        if role_id is not None and r.get("role_id") == role_id:
            rec = r
            break
        if external_id is not None and r.get("external_id") == external_id:
            rec = r
            break
    if rec is None:
        raise MatchExplainError(
            404, "That role is not in this student's current recommendations.")

    detail = rec.get("match_detail") or []
    # Discovery credits add to earned but never to the denominator (matching
    # ``_score_candidate``, where total_w only sums required-skill weights).
    total_w = sum((d.get("weight") or 0.0) for d in detail if not d.get("is_discovery"))
    earned_w = sum((d.get("credit") or 0.0) for d in detail)
    raw = (earned_w / total_w * 100.0) if total_w else 0.0
    clamped = min(100.0, raw)
    displayed = rec["match_score"]
    if abs(round(clamped, 1) - displayed) > 1e-6:
        raise MatchExplainError(
            500, "Cannot decompose role match exactly: recomputed "
                 f"{clamped:.4f} != displayed {displayed}. "
                 "No score was changed; refusing to present a wrong sum.")

    adjustment_lines = _role_adjustment_lines(raw, displayed)

    requirements = []
    for d in detail:
        requirements.append({
            "name": d["name"],
            "required_level": d["required_level"],
            "student_level": d["student_level"],
            "evidence": d["evidence"],
            "essential": d["essential"],
            "weight": _fmt(d["weight"]),
            "level_factor": _fmt(d["level_factor"]),
            "credit": _fmt(d["credit"]),
            "is_discovery": d["is_discovery"],
            "verified": d["verified"],
        })
    missing_key_skills = rec.get("missing_key_skills") or []
    verified_matches = rec.get("verified_matches") or []
    if rec.get("verified_matches"):
        next_action = "You have verified matches here — keep earning verified evidence to improve."
    elif missing_key_skills:
        next_action = (f"Learn or verify {missing_key_skills[0]} to raise this "
                       "role's match.")
    else:
        next_action = "This role matches your current profile."
    return {
        "formula": ROLE_MATCH_FORMULA,
        "version": ROLE_MATCH_VERSION,
        "as_of": _as_of(),
        "role_data_version": rec.get("source_version") or "local",
        "role_id": rec.get("role_id"),
        "external_id": rec.get("external_id"),
        "title": rec.get("title"),
        "source": rec.get("source"),
        "company_name": rec.get("company_name"),
        "requirements": requirements,
        "total_weight": _fmt(total_w),
        "earned_weight": _fmt(earned_w),
        "raw_percent": _fmt(raw),
        "displayed_percent": displayed,
        "adjustment_lines": adjustment_lines,
        "matched_skills": rec.get("matched_skills") or [],
        "missing_key_skills": missing_key_skills,
        "verified_matches": verified_matches,
        "evidence_precedence": "verified > self_reported (only passed assessments verify)",
        "missing_data": missing_key_skills,
        "next_action": next_action,
    }


# ---------------------------------------------------------------------------
# 3. Jobs feed (jobs._score_job / _apply)
# ---------------------------------------------------------------------------
def _student_feed_inputs(student):
    """Mirror ``api_recent_jobs``' skill/role/requisite construction exactly so
    the breakdown rebuilds the identical feed cache key and scoring context."""
    skills = []
    requisites = []
    for s in student.get("self_reported_skills") or []:
        skills.append((s["name"], s.get("level") or "Beginner", False))
    for v in student.get("verified_skills") or []:
        skills.append((v["name"], v.get("level") or "Intermediate", True))
    target = student.get("target_role") or {}
    role_title = target.get("title") or ""
    for rs in target.get("required_skills") or []:
        if rs.get("name"):
            requisites.append(rs["name"])
    return skills, role_title, requisites


def _job_scoring_context(skills, role_title, requisites):
    """Derive the exact ``_score_job`` inputs ``_build_result`` uses."""
    skill_levels = [s[1] for s in skills if isinstance(s, (tuple, list)) and len(s) >= 2]
    skill_names = [s[0] if isinstance(s, (tuple, list)) else s for s in skills]
    verified_skills = [s[0] for s in skills
                       if isinstance(s, (tuple, list)) and len(s) >= 3 and s[2]]
    keywords, minor_keywords = jobs._cluster_keywords(skill_names, role_title, requisites)
    role_family = jobs._role_family(role_title)
    student_seniority = jobs._student_seniority(skill_levels)
    return {
        "keywords": keywords,
        "minor_keywords": minor_keywords,
        "role_family": role_family,
        "student_seniority": student_seniority,
        "verified_skills": verified_skills,
        "role_driven": bool(role_title),
        "role_title": role_title,
    }


def job_match_breakdown(student, fingerprint, location="", country="", market="",
                        limit=10):
    """Decompose a jobs feed row's ``match_pct``.

    Locates the EXACT normalized record the student saw (via the feed cache
    key, warmed synchronously only when absent), re-runs
    ``jobs.job_score_components`` with the same inputs ``_build_result`` used,
    and asserts the components' ``final`` equals the stored ``match_pct``
    (the displayed number). Raises ``MatchExplainError`` on conflict.
    """
    if student is None:
        raise MatchExplainError(404, "Student not found.")
    if not student.get("self_reported_skills"):
        raise MatchExplainError(404, "No CV profile is linked — the feed is not matched for this student.")
    skills, role_title, requisites = _student_feed_inputs(student)
    loc = location or student.get("location") or ""
    cty = country or student.get("country") or ""
    job_record = jobs.locate_feed_job(skills, role_title, cty, loc, requisites,
                                      market, fingerprint, limit=limit)
    if job_record is None:
        raise MatchExplainError(
            404, "That job is not in this student's current live feed "
                 "(its market/profile inputs may have changed).")
    ctx = _job_scoring_context(skills, role_title, requisites)
    c = jobs.job_score_components(
        job_record, ctx["keywords"], ctx["student_seniority"], cty, loc,
        ctx["role_family"], minor_keywords=ctx["minor_keywords"],
        market_country=market, role_driven=ctx["role_driven"],
        verified_skills=ctx["verified_skills"], role_title=ctx["role_title"])

    stored_match_pct = job_record.get("match_pct")
    if stored_match_pct is None or c["final"] != stored_match_pct:
        raise MatchExplainError(
            500, "Cannot decompose job match exactly: recomputed "
                 f"{c['final']} != displayed {stored_match_pct}. "
                 "No score was changed; refusing to present a wrong sum.")

    lines = [
        {"label": "Relevance (matched keywords)", "points": _fmt(c["relevance"]["final"])},
        {"label": "Experience level fit", "points": _fmt(c["experience"]["points"])},
        {"label": "Location fit", "points": _fmt(c["location"]["points"])},
        {"label": "Raw total", "points": _fmt(c["raw_total"])},
        {"label": "rounding", "label_long": "int() rounding applied to the raw total",
         "points": _fmt(c["rounded_total"] - c["raw_total"])},
        {"label": "clamp_0_100", "label_long": "Score is clamped to the 0–100 range",
         "points": _fmt(c["clamped_total"] - c["rounded_total"])},
    ]
    if _fmt(c["seniority_capped_total"] - c["clamped_total"]) != 0:
        lines.append({"label": "seniority_cap",
                      "label_long": "Entry-level profile: senior titles are capped at 15",
                      "points": _fmt(c["seniority_capped_total"] - c["clamped_total"])})
    if _fmt(c["location_capped_total"] - c["seniority_capped_total"]) != 0:
        lines.append({"label": "relocation_cap",
                      "label_long": "Differs from your market: capped at 40",
                      "points": _fmt(c["location_capped_total"] - c["seniority_capped_total"])})

    work_type = job_record.get("work_type")
    constraints = {
        "location": {
            "tier": c["location"]["tier"],
            "label": c["location"]["label"],
            "supported": c["location"]["tier"] != "different",
        },
        "work_type": {
            "value": work_type if str(work_type or "").lower() not in ("unknown", "none", "") else "unknown",
            "supported": bool(work_type) and str(work_type).lower() not in ("unknown", "none", ""),
        },
        "seniority": {
            "job": c["experience"]["job_seniority"],
            "student": c["experience"]["student_seniority"],
            "supported": c["experience"]["job_seniority"] <= c["experience"]["student_seniority"],
        },
    }

    verified_hits = c["matches"]["verified_hits"]
    matched_kw = [k for k in c["matches"]["matched"] if k not in verified_hits]
    if verified_hits:
        next_action = "Your verified skills back this match — keep your profile current."
    elif matched_kw:
        next_action = f"Verify a matched skill such as {matched_kw[0]} to strengthen this match."
    elif c["relevance"]["final"] <= 0:
        next_action = "This listing has little in common with your target career."
    elif not constraints["location"]["supported"]:
        next_action = "Consider adding this market as a relocation/remote search."
    else:
        next_action = "This is a strong current fit."
    return {
        "formula": JOB_MATCH_FORMULA,
        "version": JOB_MATCH_VERSION,
        "as_of": _as_of(),
        "role_data_version": _role_data_version(student.get("target_role")),
        "role_title": role_title,
        "job": {
            "title": job_record.get("title"),
            "company": job_record.get("company"),
            "location_label": job_record.get("location_label"),
            "work_type": work_type,
            "seniority": job_record.get("seniority"),
            "listed_days_ago": job_record.get("listed_days_ago"),
            "listing_status": job_record.get("listing_status"),
            "apply_url": job_record.get("apply_url"),
        },
        "components": {
            "relevance": c["relevance"],
            "experience": c["experience"],
            "location": c["location"],
        },
        "lines": lines,
        "displayed_percent": stored_match_pct,
        "matches": c["matches"],
        "verified_skill_hits": verified_hits,
        "other_matched_keywords": matched_kw,
        "constraints": constraints,
        "evidence_note": ("Matched keywords come from the job text itself. "
                          "Verified skill hits are the only evidence-level claim."),
        "next_action": next_action,
    }