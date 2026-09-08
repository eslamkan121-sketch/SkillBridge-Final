"""Universal Target-Role Recommendation engine (Phase B).

Domain-agnostic, evidence-based role ranking against a student's *trusted*
backend skill profile (self-reported + verified). Candidates come from three
sources:

1. company roles (non-reference rows) -- first-party labour-market signal,
2. SkillBridge catalog roles (``is_reference``) -- curated demo profiles,
3. ESCO occupations -- discovered from the student's most informative skills.

Ranking is role-relative and explainable:

- A required skill's weight is its inverse candidate frequency: rare,
  role-defining skills (Typography, Revit, Financial Modeling) weigh far more
  than generic transferable skills that appear across many roles (Communication,
  Teamwork, Excel) -- no hard-coded blacklist is needed.
- Level compatibility is applied only where SkillBridge stores a trusted
  required level (company + catalog roles). ESCO supplies no proficiency, so an
  ESCO match earns full credit for presence alone, never an invented level.
- A matched *verified* skill earns a small, bounded boost (constant factor), so
  a single verified skill can never dominate a recommendation.
- Roles with zero matched skills are omitted, so one unrelated skill cannot
  guess a career. Confidence labels are honest and non-prescriptive
  (Strong/Good/Possible match); recommendations are career *targets*, never
  eligibility or licensure claims.

The endpoint stays deterministic given a fixed profile: ESCO discovery is
supplementary -- if it fails, local recommendations are still returned with an
honest ``esco_status``.
"""
import math

from . import escoe, models, skill_registry

LEVEL_RANK = {"Beginner": 1, "Intermediate": 2, "Advanced": 3}
INVERSE = {v: k for k, v in LEVEL_RANK.items()}

# ESCO imports carry no proficiency, so the platform's documented neutral level
# is used for imported roles (never claimed to be ESCO-supplied).
NEUTRAL_REQUIRED_LEVEL = "Intermediate"

ESCO_SKILL_LIMIT = 8          # max ESCO occupations surfaced per student
VERIFIED_BOOST = 0.05         # small, bounded edge for a matched verified skill
OPTIONAL_WEIGHT = 0.5         # ESCO optional skills weigh half their essential peers

# Best-effort titles that usually indicate licensed/regulated professions
# (medical, legal, some engineering/accounting). A recommendation for these
# remains a "potential target role" -- it never claims qualification.
_REGULATED_HINTS = (
    "doctor", "physician", "surgeon", "dentist", "veterinar", "pharmacist",
    "lawyer", "attorney", "solicitor", "barrister", "judge", "notary",
    "psychologist", "psychiatrist", "midwife", "nurse practitioner",
    "chartered accountant", "certified public",
)

NOTE = ("Potential target roles based on your current skill profile. This is a "
        "recommendation, not proof of professional qualification or eligibility.")
NOTE_EMPTY = "Add skills to your profile (upload a CV) to see role recommendations."
NOTE_ESCO_UNAVAILABLE = (" Live market (ESCO) lookup is currently unavailable, so "
                         "recommendations use local roles only.")
NOTE_PROFESSIONAL_BOUNDARY = (
    " For medical or legal pathways, SkillBridge verification is not medical "
    "licensure, board certification, legal licensure, or authorization to practice."
)


def _key(name):
    """Open-normalized matching key for a skill name (Phase A logic)."""
    return skill_registry.normalise_name(name) or (name or "").strip().lower()


def _student_skill_profile(student):
    """Trusted profile: normalized key -> {name, level_rank, level_label, verified}."""
    profile = {}
    for s in student.get("self_reported_skills") or []:
        k = _key(s.get("name"))
        if not k:
            continue
        profile[k] = {
            "name": s.get("name") or "",
            "level": LEVEL_RANK.get(s.get("level"), 1),
            "label": s.get("level") or "Beginner",
            "verified": False,
        }
    for v in student.get("verified_skills") or []:
        k = _key(v.get("name"))
        if not k:
            continue
        entry = profile.setdefault(k, {
            "name": v.get("name") or "",
            "level": LEVEL_RANK.get(v.get("level"), 1),
            "label": v.get("level") or "Beginner",
            "verified": False,
        })
        entry["verified"] = True
        rank = LEVEL_RANK.get(v.get("level"))
        if rank:
            entry["level"] = max(entry["level"], rank)
            entry["label"] = INVERSE[entry["level"]]
    return profile


def _source_for(role):
    source = role.get("source")
    if source in ("company", "catalog", "esco"):
        return source
    return "catalog" if role.get("is_reference") else "company"


def _local_candidate(role):
    req = []
    for rs in role.get("required_skills") or []:
        k = _key(rs.get("name"))
        if not k:
            continue
        req.append({
            "key": k,
            "name": rs["name"],
            "required_level": LEVEL_RANK.get(rs.get("required_level")),
            "essential": rs.get("skill_kind") != "optional",
        })
    return {
        "role_id": role["id"],
        "external_id": None,
        "title": role["title"],
        "source": _source_for(role),
        "company_name": role.get("company_name"),
        "req": req,
        "codes": {r["key"] for r in req},
        "skills": [r["name"] for r in req],
    }


def _esco_candidate(item):
    req = []
    for name in item.get("essential") or []:
        k = _key(name)
        if k:
            req.append({"key": k, "name": name, "required_level": None, "essential": True})
    for name in item.get("optional") or []:
        k = _key(name)
        if k:
            req.append({"key": k, "name": name, "required_level": None, "essential": False})
    if not req:
        for name in item.get("skills") or []:
            k = _key(name)
            if k:
                req.append({"key": k, "name": name, "required_level": None, "essential": True})
    discovery = {}
    for name in item.get("discovery_skills") or []:
        k = _key(name)
        if k:
            discovery[k] = name
    return {
        "role_id": None,
        "external_id": item["uri"],
        "title": item["title"],
        "source": "esco",
        "company_name": None,
        "req": req,
        "codes": {r["key"] for r in req},
        "skills": item.get("skills") or [r["name"] for r in req],
        "discovery": discovery,
    }


def _informative_skills(profile, local_candidates, max_skills=3):
    """Pick the student's most *informative* professional skills for ESCO
    discovery: skills that are rare across the local role pool (so away from
    generic transferables) up to ``max_skills``. Deterministic ordering."""
    freq = {}
    for cand in local_candidates:
        for code in cand["codes"]:
            freq[code] = freq.get(code, 0) + 1
    scored = sorted(
        ((freq.get(code, 0), entry["label"], entry["name"], code)
         for code, entry in profile.items() if entry["name"]),
        key=lambda x: (x[0], x[1].lower()))
    return [name for (_, _, name, _) in scored[:max_skills]]


def _confidence(pct, matched_count):
    if pct >= 55.0 and matched_count >= 2:
        return "Strong match"
    if pct >= 32.0:
        return "Good match"
    if matched_count >= 1:
        return "Possible match"
    return "Possible match"


def _regulated_warning(title):
    t = (title or "").lower()
    return any(h in t for h in _REGULATED_HINTS)


def _professional_boundary_warning(title, skills=()):
    text = " ".join([title or "", *[str(s or "") for s in (skills or [])]]).lower()
    return _regulated_warning(title) or any(
        h in text for h in (
            "clinical", "patient", "medical", "legal", "law", "court",
            "client advocacy", "dispute resolution",
        )
    )


def recommend(student):
    """Ranked ``{recommendations, note, esco_status, source_counts}`` for a
    student's trusted profile. Deterministic for a fixed profile + candidate
    pool; ESCO discovery is supplementary and never blocks local results."""
    local = [_local_candidate(r) for r in models.list_roles()]
    local += [_local_candidate(r) for r in models.list_catalog_roles()]
    profile = _student_skill_profile(student)

    esco_candidates = []
    esco_status = "unavailable"
    informative = _informative_skills(profile, local)
    if informative:
        try:
            esco_candidates = [
                _esco_candidate(x)
                for x in escoe.market_occupations_for_skills(informative, limit=ESCO_SKILL_LIMIT)
            ]
            esco_status = "ok"
        except Exception:
            esco_candidates = []
            esco_status = "unavailable"

    candidates = local + esco_candidates
    if not candidates:
        return {"recommendations": [], "note": NOTE_EMPTY,
                "esco_status": esco_status, "source_counts": {}}

    corpus = max(len(candidates), 1)
    df = {}
    for cand in candidates:
        for code in cand["codes"]:
            df[code] = df.get(code, 0) + 1

    def specificity(code):
        return math.log1p(corpus / (1.0 + df.get(code, 0)))

    results = []
    for cand in candidates:
        total_w = 0.0
        earned_w = 0.0
        matched = []
        missing = []
        matched_keys = set()
        for req in cand["req"]:
            w = specificity(req["key"]) * (1.0 if req["essential"] else OPTIONAL_WEIGHT)
            total_w += w
            hit = profile.get(req["key"])
            if hit:
                level_factor = 1.0
                if req["required_level"]:
                    level_factor = (1.0 if hit["level"] >= req["required_level"]
                                    else hit["level"] / req["required_level"])
                credit = w * level_factor
                if hit["verified"]:
                    credit *= (1.0 + VERIFIED_BOOST)
                earned_w += credit
                matched_keys.add(req["key"])
                matched.append({
                    "name": req["name"],
                    "student_level": hit["label"],
                    "required_level": req.get("required_level") and INVERSE[req["required_level"]],
                    "verified": bool(hit["verified"]),
                })
            else:
                missing.append(req)
        # ESCO occupations describe their skills as verb phrases ("present legal
        # arguments") that almost never lexically equal a profile skill name
        # ("Client advocacy"). When ESCO itself surfaced the occupation because
        # of one of the student's skills (discovery ground truth), that profile
        # skill is matched evidence for the occupation -- otherwise ESCO
        # candidates would be dropped for every domain except those whose
        # vocabulary coincides with ESCO phrasing (e.g. "Python").
        for dkey in cand.get("discovery") or {}:
            if dkey in matched_keys:
                continue
            hit = profile.get(dkey)
            if not hit:
                continue
            credit = specificity(dkey) * 1.0
            if hit["verified"]:
                credit *= (1.0 + VERIFIED_BOOST)
            earned_w += credit
            matched_keys.add(dkey)
            matched.append({
                "name": cand["discovery"][dkey],
                "student_level": hit["label"],
                "required_level": None,
                "verified": bool(hit["verified"]),
            })
        if not matched:
            continue
        pct = round(min(100.0, earned_w / total_w * 100.0), 1) if total_w else 0.0
        missing.sort(key=lambda m: -specificity(m["key"]))
        results.append({
            "role_id": cand["role_id"],
            "external_id": cand["external_id"],
            "title": cand["title"],
            "source": cand["source"],
            "company_name": cand["company_name"],
            "match_score": pct,
            "confidence": _confidence(pct, len(matched)),
            "matched_skills": matched,
            "missing_key_skills": [m["name"] for m in missing[:5]],
            "verified_matches": [m["name"] for m in matched if m["verified"]],
            "reason": (f"{len(matched)} of {len(cand['req'])} key skills for this role "
                       f"already appear in your profile."),
            "selectable": True,
            "regulated_warning": _professional_boundary_warning(cand["title"], cand["skills"]),
            "skills": cand["skills"],
        })

    # Real jobs that exist in the labour market (ESCO occupations and company
    # postings) rank ahead of SkillBridge's local catalog reference roles, so a
    # user aiming to become job-ready is pointed at actual occupations first.
    # Within each group, roles are ordered by evidence: coherent match score,
    # then number of matched skills, then title (deterministic).
    def _real_first(source):
        return 0 if source in ("esco", "company") else 1

    results.sort(key=lambda r: (_real_first(r["source"]),
                                -r["match_score"],
                                -len(r["matched_skills"]),
                                r["title"].lower()))
    source_counts = {}
    for r in results:
        source_counts[r["source"]] = source_counts.get(r["source"], 0) + 1

    note = NOTE + (NOTE_ESCO_UNAVAILABLE if esco_status == "unavailable" and informative else "")
    if any(r.get("regulated_warning") for r in results):
        note += NOTE_PROFESSIONAL_BOUNDARY
    return {"recommendations": results, "note": note,
            "esco_status": esco_status, "source_counts": source_counts}


def select_esco_role(uri, title, fallback_skills=()):
    """Import an ESCO occupation as a selectable target role (idempotent) and
    return the role. Never invents data: the occupation's real essential skills
    are preferred; when ESCO is unreachable the caller-provided discovery skills
    (already grounded in the ESCO result) are used as a fallback."""
    details = {"essential": [], "optional": []}
    try:
        details = escoe.occupation_skill_groups(uri)
    except Exception:
        details = {"essential": [], "optional": []}
    essential = details.get("essential") or []
    if not essential:
        essential = [s for s in (fallback_skills or []) if s]
    return models.import_esco_role(uri, title or details.get("title") or "ESCO occupation",
                                   essential, details.get("optional") or [])
