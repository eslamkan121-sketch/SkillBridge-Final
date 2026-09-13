"""Phase F: company role -> canonical role suggestion engine.

Pure, deterministic, offline. Suggestions are computed on demand and never
persisted; nothing is ever auto-linked. Confidence is a real weighted score
built from normalized title-token overlap (Dice) and required-skill-name
overlap (Jaccard), and every explanation is literal ("shares X of Y words /
P of Q required skills") -- never invented wording or certainty.

The pools and floors here mirror the approved COMPANY_ROLE_MAPPING_PLAN.txt.
"""

import app.models as models
from app import recommendations

# Score weights (title is the primary signal, skills corroborate).
TITLE_WEIGHT = 0.6
SKILL_WEIGHT = 0.4

# Deterministic labels; candidates below the floor are omitted entirely so a
# low-confidence mapping simply stays unmapped.
CONFIDENCE_FLOOR = 0.45
HIGH_CONFIDENCE = 0.70
AMBER_BAND = 0.10


def _title_tokens(title):
    return [t for t in (title or "").lower().split() if t]


def _skill_key(name):
    """Open-normalized matching key for a skill name (Phase A logic)."""
    return recommendations._key(name)


def _skill_keys(role):
    return set(_skill_key(rs.get("name"))
               for rs in (role.get("required_skills") or [])
               if _skill_key(rs.get("name")))


def _dice(a, b):
    if not a or not b:
        return 0.0
    return 2.0 * len(set(a) & set(b)) / (len(set(a)) + len(set(b)))


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    union = set(a) | set(b)
    return len(set(a) & set(b)) / len(union)


def score_role(local_role, canonical_role):
    """Weighted confidence in [0,1] that canonical_role matches local_role."""
    lt = _title_tokens(local_role.get("normalized_title") or local_role.get("title"))
    ct = _title_tokens(canonical_role.get("normalized_title") or canonical_role.get("title"))
    title_sim = _dice(lt, ct)
    skill_sim = _jaccard(_skill_keys(local_role), _skill_keys(canonical_role))
    return round(TITLE_WEIGHT * title_sim + SKILL_WEIGHT * skill_sim, 4)


def confidence_label(confidence):
    if confidence >= HIGH_CONFIDENCE:
        return "High"
    if confidence >= CONFIDENCE_FLOOR:
        return "Medium"
    return "Low"


def _explanation(local_role, canonical_role):
    lt = _title_tokens(local_role.get("title"))
    ct = _title_tokens(canonical_role.get("title"))
    shared_tokens = sorted(set(lt) & set(ct))
    lk, ck = _skill_keys(local_role), _skill_keys(canonical_role)
    shared_skills = [s for s in (canonical_role.get("required_skills") or [])
                     if _skill_key(s.get("name")) in lk]
    parts = [f"Title shares {len(shared_tokens)} of {len(lt)}"
             f" word{'s' if len(lt) != 1 else ''}"
             + (f" ({', '.join(shared_tokens[:5])}{'…' if len(shared_tokens) > 5 else ''})" if shared_tokens else "")
             + "."]
    parts.append(f"shares {len(shared_skills)} of {len(canonical_role.get('required_skills') or [])}"
                 f" required skills"
                 + (f" ({', '.join(s['name'] for s in shared_skills[:5])}"
                    f"{'…' if len(shared_skills) > 5 else ''})" if shared_skills else "")
                 + ".")
    return " ".join(parts)


def suggest_matches(role_id):
    """Ranked, above-the-floor canonical matches for one role.

    Returns ``{role_id, mapped, matches, ambiguous}`` where matches is
    confidence-descending, each with a real score + label + literal
    explanation. ``ambiguous`` is true when the top two suggestions are within
    the amber band (the UI then lets the company user decide explicitly; nothing
    is ever auto-selected). ``mapped`` reflects the confirmed mapping (if any).
    """
    local_role = models.get_role(role_id)
    if local_role is None:
        return None
    pool = models.canonical_mapping_pool()
    scored = []
    for cand in pool:
        if cand["id"] == role_id:
            continue
        conf = score_role(local_role, cand)
        if conf < CONFIDENCE_FLOOR:
            continue
        scored.append({
            "role_id": cand["id"],
            "title": cand["title"],
            "source": (cand.get("source") or "catalog"),
            "confidence": conf,
            "confidence_label": confidence_label(conf),
            "explanation": _explanation(local_role, cand),
        })
    scored.sort(key=lambda m: m["confidence"], reverse=True)
    ambiguous = (len(scored) >= 2 and
                 scored[0]["confidence"] - scored[1]["confidence"] <= AMBER_BAND)
    return {
        "role_id": role_id,
        "mapped": models.mapping_of(role_id),
        "matches": scored,
        "ambiguous": ambiguous,
    }