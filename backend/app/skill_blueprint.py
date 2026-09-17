"""Skill Blueprint — the canonical statement of required competencies.

Two layers:
  1. TRUSTED blueprints: a small, manually-authored set of competency decompositions
     (Docker, Git, Machine Learning, SQL). These are authoritative, never regenerated
     by AI, and always used as-is.
  2. DERIVED blueprints: for any skill NOT in the trusted set, competencies are
     derived server-side via GenAI (validated) or a deterministic fallback, cached,
     versioned, and reused.  This makes the competency / diagnostic / coverage /
     learning path pipeline work for Typography, Market Research, Revit, Financial
     Modeling, Clinical Research, and any other open-universe skill.

Resolution order (every caller sees the same thing):
  has_blueprint(skill)  ->  True if trusted OR a blueprint could be derived
  required_competencies(skill, from, to)  ->  union of competencies across level range
  competency_names_for(skill, level)  ->  competencies for one specific level

Trusted blueprints are NEVER regenerated.  Derived blueprints are cached with a
version tag so changing the generation logic does not silently mutate historical
student progress.
"""

import hashlib
import re

BLUEPRINT_VERSION = "skill-blueprint-v2"

# Bump DERIVED_VERSION when the derivation logic, prompt, or validation rules
# change.  Old cached entries keyed under a prior version are ignored.
DERIVED_VERSION = "derived-v1"

# Minimum/maximum competencies in a derived blueprint
_MIN_COMPETENCIES = 3
_MAX_COMPETENCIES = 8
_DEFAULT_COMPETENCIES = 5

# ------------------------------------------------------------------ TRUSTED

BLUEPRINT = {
    # Phase 1 curated vertical slice. Do not ask an LLM to extend this graph.
    "python": {
        # Curated sequence: Error Handling depends on callable functions, so a
        # weak Error Handling score must never move ahead of Functions.
        "Beginner": ["Python Functions", "Python Error Handling"],
        "Intermediate": [],
        "Advanced": [],
    },
    "docker": {
        "Beginner": ["Containers", "Images", "Basic commands"],
        "Intermediate": ["Dockerfile", "Ports", "Volumes", "Networking"],
        "Advanced": ["Compose", "Multi-stage builds", "Security & secrets", "Orchestration basics"],
    },
    "git": {
        "Beginner": ["Local repositories", "Committing", "Branching"],
        "Intermediate": ["Merging", "Rebasing", "Remotes & collaboration", "History rewriting"],
        "Advanced": ["Bisect & debugging", "Submodules", "Workflows & policy", "Large-repo strategies"],
    },
    "machine learning": {
        "Beginner": ["Data preparation", "Training a first model", "Evaluation basics"],
        "Intermediate": ["Feature engineering", "Model selection", "Validation & overfitting", "Hyperparameter tuning"],
        "Advanced": ["Model deployment", "Ensembles", "Drift & monitoring", "Experiment tracking"],
    },
    "sql": {
        "Beginner": ["Queries & filtering", "Sorting & limiting"],
        "Intermediate": ["Aggregation", "Joins", "Subqueries", "Indexing basics"],
        "Advanced": ["Window functions", "Query optimization", "Transactions", "Schema design"],
    },
}

_KNOWN_SKILLS = set(BLUEPRINT)

VALID_EDUCATION_LEVELS_NOT_USED_HERE = "unused"


# ------------------------------------------------------------------ DERIVED cache

# Key: _cache_key(skill_name, target_role)  ->  full blueprint dict
_DERIVED_CACHE = {}


def _normalise_raw(skill_name):
    """Minimal normalisation for blueprint keys: strip, collapse whitespace."""
    return re.sub(r"\s+", " ", (skill_name or "").strip()).strip()


def _cache_key(skill_name, target_role=None):
    """Deterministic cache key from skill + optional role context."""
    skill = _normalise_raw(skill_name).lower()
    role = (target_role or "").strip().lower()
    return f"{skill}|{role}"


def _skill_key(skill_name):
    """Return the lowercase key used to look up a skill in the trusted BLUEPRINT."""
    name = _normalise_raw(skill_name).lower()
    if name in BLUEPRINT:
        return name
    for key in BLUEPRINT:
        if key in name or name in key:
            return key
    return None


def clear_derived_cache(skill_name=None, target_role=None):
    """Test helper: clear the derived blueprint cache."""
    if skill_name is None:
        _DERIVED_CACHE.clear()
        return
    ck = _cache_key(skill_name, target_role)
    _DERIVED_CACHE.pop(ck, None)


# ------------------------------------------------------------------ TRUSTED API

def has_blueprint(skill_name):
    """True if the skill has a trusted OR derived blueprint.

    Unknown-but-valid skills are derived on first access (cached afterwards), so
    this effectively returns True for any meaningful skill name.  Skills that
    cannot be derived (empty / garbage names) return False.
    """
    name = _normalise_raw(skill_name)
    if not name:
        return False
    if _skill_key(name):
        return True
    if _cache_key(name) in _DERIVED_CACHE:
        return True
    bp = derive_competencies(name)
    return bool(bp and bp.get("competencies"))


def _derived_names(skill_name):
    """Competency names for a derived (non-trusted) skill, deriving if needed."""
    bp = derive_competencies(skill_name)
    return [c["name"] for c in (bp.get("competencies") or [])]


def competency_names_for(skill_name, level):
    """The competency list for one specific level of a skill.

    Trusted: competencies for that level.
    Derived: all derived competencies (derived blueprints are level-flat).
    Returns [] only when the skill name cannot produce a blueprint.
    """
    key = _skill_key(skill_name)
    if key:
        return list(BLUEPRINT[key].get(level, []))
    return list(_derived_names(skill_name))


def required_competencies(skill_name, from_level, to_level):
    """Every competency a student must gain to go from `from_level` to `to_level`.

    Trusted: union of all competency lists from `from_level` up to and including
    `to_level` (same semantics as before).
    Derived: all derived competencies regardless of level (derived blueprints are
    level-flat — the learning path planner handles ordering and difficulty, and
    the competency IDs never change with the requested level).
    Returns [] only when the skill name cannot produce a blueprint.
    """
    order = {"Beginner": 0, "Intermediate": 1, "Advanced": 2}
    key = _skill_key(skill_name)
    if key:
        start = order.get(from_level, 0)
        end = order.get(to_level, 2)
        required = []
        for level in ("Beginner", "Intermediate", "Advanced"):
            if order[level] >= start and order[level] <= end:
                required.extend(BLUEPRINT[key].get(level, []))
        return list(required)
    return list(_derived_names(skill_name))


def modules_cover(modules, skill_name, from_level, to_level):
    """Deterministic coverage check: does the module list include every
    required competency for (from_level -> to_level)?

    Returns (covered: bool, missing: list).
    """
    required = required_competencies(skill_name, from_level, to_level)
    if not required:
        return True, []
    covered = set()
    for m in modules or []:
        comp = (m.get("competency") or "").strip()
        if m.get("beyond_blueprint"):
            continue
        if comp in required:
            covered.add(comp)
    missing = [c for c in required if c not in covered]
    return not missing, missing


def validate_competencies(modules, skill_name, from_level, to_level):
    """Every module's `competency` must be one of the allowed values.

    Returns (all_valid: bool, allowed: list, offending: list).
    """
    allowed = required_competencies(skill_name, from_level, to_level)
    offending = []
    for m in modules or []:
        if m.get("beyond_blueprint"):
            continue
        comp = (m.get("competency") or "").strip()
        if comp and comp not in allowed:
            offending.append(comp)
    return (not offending), allowed, offending


# ------------------------------------------------------------------ SLUGS / LABELS

def competency_slug(competency):
    """Machine-readable id for a competency, e.g. 'IAM Policies' -> 'iam_policies'.

    Guaranteed to match `diagnostics.competency_slug`.
    """
    words = (competency or "").strip().lower().split()
    return "_".join(w for w in words)


def required_competency_slugs(skill_name, from_level, to_level):
    """The allowed competency slug set for a (skill, level-range)."""
    return [competency_slug(c) for c in required_competencies(skill_name, from_level, to_level)]


def badge_blueprint_depth(skill_name, from_level, to_level):
    """Number of required competencies for (from_level -> to_level)."""
    return len(required_competencies(skill_name, from_level, to_level))


_LABEL_SLUG_CACHE = {}


def competency_label(competency):
    """Best-effort reverse of `competency_slug`: map a slug back to its blueprint
    label (guessing title case for display). Falls back to the slug itself."""
    slug = competency_slug(competency)
    label = _LABEL_SLUG_CACHE.get(slug)
    if label is not None:
        return label
    for skill, levels in (BLUEPRINT or {}).items():
        for names in (levels or {}).values():
            for name in names or []:
                if skill and competency_slug(name) == slug:
                    _LABEL_SLUG_CACHE[slug] = name
                    return name
    for _ck, bp in _DERIVED_CACHE.items():
        for comp in bp.get("competencies", []):
            if competency_slug(comp["name"]) == slug:
                _LABEL_SLUG_CACHE[slug] = comp["name"]
                return comp["name"]
    return slug


# ------------------------------------------------------------------ DERIVATION

def _validate_name(name):
    """Reject competency names that are too short, too long, or clearly wrong."""
    s = (name or "").strip()
    if not s or len(s) > 60:
        return False
    if len(s) < 3:
        return False
    if "://" in s or "www." in s.lower():
        return False
    if re.search(r"[.!?]\s", s):
        return False
    if len(s.split()) > 8:
        return False
    return True


def _validate_derived_competencies(competencies, skill_name):
    """Server-side validation of a list of derived competency dicts.

    Returns (valid_list, rejected_reasons). Each valid entry has
    {name, slug, objective, importance}. Rejected entries are dropped.
    """
    if not isinstance(competencies, list):
        return [], ["not a list"]
    valid = []
    rejected = []
    seen_slugs = set()
    skill_lower = (skill_name or "").strip().lower()
    for comp in competencies:
        if not isinstance(comp, dict):
            rejected.append("non-dict entry")
            continue
        name = (comp.get("name") or "").strip()
        if not _validate_name(name):
            rejected.append(f"invalid name: {name!r}")
            continue
        if name.lower() == skill_lower or name.lower() == f"{skill_lower} fundamentals":
            rejected.append(f"degenerate name: {name!r}")
            continue
        if re.search(r"(?:quiz|exam|assessment|test|question|certification|license|degree)", name, re.I):
            rejected.append(f"non-competency content: {name!r}")
            continue
        slug = competency_slug(name)
        if slug in seen_slugs:
            rejected.append(f"duplicate slug: {slug}")
            continue
        seen_slugs.add(slug)
        objective = str(comp.get("objective") or "")[:200]
        importance = comp.get("importance")
        if importance not in ("high", "medium", "low", None):
            importance = "medium"
        valid.append({
            "name": name,
            "slug": slug,
            "objective": objective,
            "importance": importance or "medium",
        })
    return valid, rejected


def _genai_derive_competencies(skill_name, target_role=None, required_level=None, context=None):
    """Try to derive competencies via GenAI. Returns (list_of_competency_dicts, True)
    on success or ([], False) on any failure (no exception propagation)."""
    try:
        from . import genai as genai_mod
        if not genai_mod.genai_enabled():
            return [], False
    except Exception:
        return [], False

    skill_cat = ""
    try:
        from . import skill_registry
        _, skill_cat = skill_registry.normalise_name(skill_name)
    except Exception:
        pass

    role_hint = f"\nTarget role: {target_role}" if target_role else ""
    level_hint = f"\nRequired proficiency: {required_level}" if required_level else ""
    context_hint = f"\nAdditional context: {context}" if context else ""

    system = (
        "You are a competency decomposition engine. Given a professional skill, "
        "produce a list of 3-8 core competencies (sub-capabilities) that a "
        "professional must master. Each competency must be a real, distinct "
        "sub-skill — NOT proficiency levels (no 'Basics', 'Intermediate', 'Advanced').\n\n"
        "RULES:\n"
        "- Every competency name must be 2-60 characters, short and specific.\n"
        "- No URLs, paragraphs, quiz questions, lesson content, or certifications.\n"
        "- No duplicate competencies.\n"
        "- Each competency must be genuinely part of the named skill.\n"
        "- Target role may shift emphasis but should not redefine the skill entirely.\n"
        "- Do NOT include the skill name itself as a competency.\n\n"
        "Return STRICT JSON: an array of objects, each:\n"
        '{"name": string, "objective": string (1 sentence, <=120 chars), '
        '"importance": "high"|"medium"|"low"}\n\n'
        "Return ONLY the JSON array, no prose."
    )

    user = (
        f"Skill: {skill_name}"
        f"{f' ({skill_cat})' if skill_cat else ''}\n"
        f"{role_hint}{level_hint}{context_hint}\n\n"
        "Decompose this skill into its core competencies."
    )

    try:
        # Reasoning models on NIM can take longer than 30s to decompose a complex
        # skill; a short timeout silently falls back. 60s keeps the real-provider
        # path usable while still failing fast on genuinely dead networks.
        raw = genai_mod.complete(system, user, fallback=None, max_tokens=1024, timeout=60)
        parsed = genai_mod._extract_json(raw)
        if not isinstance(parsed, list) or not parsed:
            return [], False
        valid, _rejected = _validate_derived_competencies(parsed, skill_name)
        if len(valid) < _MIN_COMPETENCIES:
            return [], False
        if len(valid) > _MAX_COMPETENCIES:
            valid = valid[:_MAX_COMPETENCIES]
        return valid, True
    except Exception:
        return [], False


# Deterministic fallback templates keyed by broad category.
# These are honest, structured, and never pretend to be AI-generated.
_FALLBACK_TEMPLATES = {
    "Programming": [
        ("Syntax & Core Fundamentals", "Understand the core syntax, data types, and control structures"),
        ("Data Structures & APIs", "Work with built-in data structures and standard APIs"),
        ("Error Handling & Debugging", "Identify, diagnose, and resolve common errors"),
        ("Best Practices & Code Quality", "Apply idiomatic patterns, linting, and code review norms"),
        ("Applied Project Work", "Build a working deliverable combining all core concepts"),
    ],
    "Data": [
        ("Data Fundamentals", "Understand data types, formats, and basic operations"),
        ("Query & Manipulation", "Retrieve, transform, and aggregate data effectively"),
        ("Quality & Validation", "Identify and handle missing, inconsistent, or invalid data"),
        ("Analysis & Interpretation", "Draw meaningful conclusions from data patterns"),
        ("Visualization & Communication", "Present findings clearly to technical and non-technical audiences"),
    ],
    "AI": [
        ("Model Fundamentals", "Understand core concepts and types of models in this domain"),
        ("Data Preparation", "Collect, clean, and prepare data for model training"),
        ("Training & Evaluation", "Train models and evaluate performance with appropriate metrics"),
        ("Optimization & Tuning", "Improve model performance through iteration and tuning"),
        ("Deployment & Monitoring", "Deploy models to production and monitor for drift or degradation"),
    ],
    "DevOps": [
        ("Core Concepts", "Understand the fundamental principles and tooling"),
        ("Configuration & Setup", "Install, configure, and set up the environment"),
        ("Day-to-Day Operations", "Perform routine operational tasks confidently"),
        ("Troubleshooting & Debugging", "Diagnose and resolve common issues"),
        ("Security & Best Practices", "Apply security hardening and operational best practices"),
    ],
    "Security": [
        ("Threat Landscape", "Understand common threats, attack vectors, and risk models"),
        ("Defensive Controls", "Implement preventive measures and access controls"),
        ("Detection & Monitoring", "Set up detection, logging, and alerting systems"),
        ("Incident Response", "Detect, contain, and remediate security incidents"),
        ("Compliance & Governance", "Apply relevant frameworks, policies, and audit practices"),
    ],
    "Analytics": [
        ("Core Concepts", "Understand fundamental analytical principles and terminology"),
        ("Data Collection & Preparation", "Gather, clean, and structure data for analysis"),
        ("Analysis Techniques", "Apply appropriate analytical methods and tools"),
        ("Insight Generation", "Extract actionable insights from analytical results"),
        ("Communication & Reporting", "Present findings to stakeholders with clear narratives"),
    ],
    "Visualization": [
        ("Data Representation", "Choose appropriate chart types and visual encodings"),
        ("Tool Proficiency", "Navigate and use the primary visualization tool effectively"),
        ("Design Principles", "Apply clarity, hierarchy, and accessibility in visual design"),
        ("Storytelling with Data", "Construct a narrative that guides the audience through insights"),
        ("Interactive Dashboards", "Build interactive views that enable exploration"),
    ],
    "Professional Skill": [
        ("Core Concepts", "Understand the foundational principles of this skill area"),
        ("Practical Application", "Apply the skill to realistic, role-relevant scenarios"),
        ("Common Challenges & Decisions", "Navigate typical problems and trade-offs"),
        ("Quality & Evaluation", "Assess the quality of your work against professional standards"),
        ("Professional Use", "Demonstrate the skill in a professional or portfolio context"),
    ],
    "Soft Skills": [
        ("Core Principles", "Understand the foundational principles and why they matter"),
        ("Self-Awareness", "Recognize how this skill applies to your own work style"),
        ("Practical Techniques", "Learn and practice specific, actionable techniques"),
        ("Real-World Application", "Apply the skill in realistic workplace scenarios"),
        ("Reflection & Growth", "Evaluate your effectiveness and plan continued improvement"),
    ],
}


def _fallback_competencies(skill_name, target_role=None):
    """Deterministic fallback: pick a template by category or use the neutral one.

    Returns list of competency dicts with source='fallback'.
    """
    skill_cat = ""
    try:
        from . import skill_registry
        _, skill_cat = skill_registry.normalise_name(skill_name)
    except Exception:
        pass
    templates = _FALLBACK_TEMPLATES.get(skill_cat) or _FALLBACK_TEMPLATES["Professional Skill"]
    competencies = []
    for name, objective in templates:
        slug = competency_slug(name)
        competencies.append({
            "name": name,
            "slug": slug,
            "objective": objective,
            "importance": "medium",
        })
    return competencies


def derive_competencies(skill_name, target_role=None, required_level=None, context=None):
    """Universal competency derivation — the main Phase C entry point.

    Resolution order:
      1. Trusted blueprint exists -> return its flat competency list (never AI-generated)
      2. Cached derived blueprint  -> return it
      3. GenAI derivation -> validate -> cache -> return
      4. Deterministic fallback -> cache -> return

    Returns a blueprint dict:
      {
        "skill": str,
        "source": "trusted" | "derived" | "fallback",
        "blueprint_version": str,
        "competencies": [{"name", "slug", "objective", "importance"}, ...]
      }
    """
    # 1. Trusted blueprint — authoritative, never regenerated
    key = _skill_key(skill_name)
    if key:
        all_comps = []
        seen = set()
        for level in ("Beginner", "Intermediate", "Advanced"):
            for name in BLUEPRINT[key].get(level, []):
                slug = competency_slug(name)
                if slug not in seen:
                    seen.add(slug)
                    all_comps.append({
                        "name": name,
                        "slug": slug,
                        "objective": f"Master {name.lower()} concepts and practices",
                        "importance": "high" if level == "Intermediate" else "medium",
                    })
        return {
            "skill": skill_name,
            "source": "trusted",
            "blueprint_version": BLUEPRINT_VERSION,
            "competencies": all_comps,
        }

    # 2. Cache check
    ck = _cache_key(skill_name, target_role)
    cached = _DERIVED_CACHE.get(ck)
    if cached and cached.get("blueprint_version") == DERIVED_VERSION:
        return cached

    # 3. GenAI derivation
    genai_comps, ok = _genai_derive_competencies(skill_name, target_role, required_level, context)
    if ok and genai_comps:
        blueprint = {
            "skill": skill_name,
            "source": "derived",
            "blueprint_version": DERIVED_VERSION,
            "competencies": genai_comps,
        }
        _DERIVED_CACHE[ck] = blueprint
        return blueprint

    # 4. Deterministic fallback
    fb_comps = _fallback_competencies(skill_name, target_role)
    blueprint = {
        "skill": skill_name,
        "source": "fallback",
        "blueprint_version": DERIVED_VERSION,
        "competencies": fb_comps,
    }
    _DERIVED_CACHE[ck] = blueprint
    return blueprint


def get_derived_blueprint(skill_name, target_role=None):
    """Public accessor for the full derived blueprint dict.  Used by coverage,
    diagnostics, and the assessment pipeline."""
    return derive_competencies(skill_name, target_role)


def source_for(skill_name, target_role=None):
    """The honest provenance of a skill's competencies: 'trusted', 'derived',
    or 'fallback'.  Never presented as live AI when it is the fallback."""
    bp = derive_competencies(skill_name, target_role)
    return bp.get("source", "trusted")
