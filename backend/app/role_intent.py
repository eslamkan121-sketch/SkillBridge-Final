"""Shared career-intent resolution for SkillBridge (ESCO + live jobs).

One source of truth for turning a student's *selected Target Role* into a
canonical career intent that both the ESCO occupation search and the Dashboard
live-jobs feed obey. This keeps the two surfaces from independently guessing the
career from generic CV skill words.

Responsibilities (and only these -- no provider/HTTP logic):
  - normalise a target-role title (harmless spelling / lexical variants)
  - resolve trusted aliases / close family titles for a target
  - extract the *domain-bearing* tokens of a title (tokens that are NOT generic
    role tails like "analyst"/"manager"/"engineer")
  - classify a candidate title against the target:
        EXACT / CLOSE / FAMILY / UNRELATED
  - derive bounded provider query terms primarily from the target title + aliases
  - derive the role's canonical family key

The design is deliberately small and curated rather than a giant occupation
database: an alias/family layer for high-value, common equivalents, with the
rest left to generic token logic. Same mechanism works for cybersecurity,
design, finance, marketing, architecture, clinical research, legal, data,
software/AI, and any future role.
"""
import re

# Generic role tails / suffixes that say WHAT a job is, never WHICH domain.
# They alone must never establish family similarity ("Cybersecurity Analyst" vs
# "Product Analyst" sharing "Analyst" is NOT a match).
_GENERIC_TAIL_TOKENS = frozenset({
    "analyst", "engineer", "developer", "scientist", "specialist", "manager",
    "consultant", "officer", "clerk", "assistant", "associate", "intern",
    "trainee", "representative", "coordinator", "administrator", "technician",
    "architect", "designer", "analyst", "supervisor", "auditor", "lead",
    "senior", "junior", "head", "director", "executive", "vp", "entry",
    "professional", "staff", "advisor", "strategist", "researcher", "analyst",
    "guard", "investigator", "inspector",
})

# Tokens that only describe the level/scope/nature of work, never the domain.
_LEVEL_TOKENS = frozenset({
    "senior", "junior", "lead", "head", "director", "executive", "entry",
    "staff", "principal", "mid", "associate", "graduate", "intern",
})

# Cross-domain noise words that can legitimately appear in ANY role's title
# without indicating a specific career domain. These must never become domain
# evidence ("Software Research Engineer" must not count as "research" for a
# Clinical Research target, nor "Analysis" for a Finance target).
_GENERIC_DOMAIN_NOISE = frozenset({
    "research", "analysis", "analytics", "development", "management",
    "business", "operations", "services", "solutions", "strategic",
    "technical", "professional", "consulting", "advisory", "administration",
    "planning", "reporting", "support", "leadership", "specialist",
    "coordinator", "supervisor", "specialist", "clerk", "associate",
})

# Harmless orthographic/morphological normalisation: fold spelling variants to a
# canonical token. Small and language-level (never an occupation database).
_NORMALIZE = {
    "cyber": "cybersecurity",
    "cyber-security": "cybersecurity",
    "cyber_security": "cybersecurity",
    "ml": "machine-learning",
    "machine-learning": "machine-learning",
    "frontend": "front-end",
    "front_end": "front-end",
    "fp&a": "fp-a",
    "fp-a": "fp-a",
    "fpanda": "fp-a",
    "ai": "ai",
    "infosec": "information-security",
    "information-security": "information-security",
    "soc": "security-operations",
    "security-operations": "security-operations",
    "it-security": "information-security",
    "bim": "bim",
    "bi": "bi",
    "ui": "ui",
    "ux": "ux",
    "seo": "seo",
    "sem": "sem",
    "eng": "engineer",
    "bd": "business-development",
    "recruiting": "recruitment",
    "devops": "devops",
}

# Canonical domain-bearing families, keyed by a family id. This is the SMALL
# curated alias layer the product contract allows: a candidate is FAMILY when it
# shares a domain term inside the same family without sharing the target's own
# domain token terms. Purposefully conservative -- a family must be grounded in
# the career's real vocabulary, never "both involve communication/analysis".
_HYPEN_SPLIT = re.compile(r"[^a-z0-9]+")

# Equivalence classes of interchangeable domain tokens. Within one class the
# tokens denote the SAME career signal, so a target domain token that shares the
# candidate's class counts as a CLOSE (not merely FAMILY) match. Deliberately
# tiny and high-confidence ("AI" <-> "ML" <-> "machine learning").
_EQUIV_CLASSES = [
    frozenset({"ai", "ml", "machine-learning"}),
    frozenset({"front-end", "frontend"}),
    frozenset({"ui", "ux", "user-interface"}),
    frozenset({"cybersecurity", "cyber", "information-security", "infosec"}),
]

_FAMILY_TERMS = {
    "security": {"security", "cybersecurity", "cyber", "infosec", "information-security",
                 "penetration", "pentest", "appsec", "secops", "soc", "threat",
                 "network-security", "network", "identity", "malware", "forensics",
                 "cryptography", "splunk", "vulnerability", "incident", "incident-response",
                 "intrusion", "firewall", "endpoint", "cyber-defense", "siem", "ransomware",
                 "phishing", "exploit", "exploitation"},
    "software": {"software", "developer", "engineer", "programmer", "backend", "front-end",
                 "fullstack", "full-stack", "python", "java", "javascript",
                 "typescript", "golang", "node", "react", "api", "devops", "cloud",
                 "machine-learning", "ai", "ml", "infrastructure", "web"},
    "data": {"data", "analytics", "database", "sql", "bi", "warehouse", "etl",
             "machine-learning", "statistics", "datascience", "analytics"},
    "design": {"design", "graphic", "visual", "brand", "ui", "ux", "typography",
               "illustrator", "photoshop", "figma", "creative", "product-design"},
    "marketing": {"marketing", "growth", "seo", "sem", "content", "brand", "digital-marketing",
                  "social-media", "ppc", "copywriting", "market-research", "advertising",
                  "pr", "b2b", "b2c", "campaign"},
    "finance": {"finance", "financial", "accounting", "fp-a", "fp&a", "audit", "tax",
                "treasury", "forecasting", "budgeting", "investment", "controller",
                "revenue", "actuarial", "credit", "risk", "compliance"},
    "architecture": {"architecture", "architectural", "bim", "revit", "autocad", "drafting",
                     "interior-design", "landscape", "urban", "cad", "spatial"},
    "clinical": {"clinical", "clinical-research", "clinical-trials", "trial", "pharma",
                 "biospecimen", "crc", "cra", "regulatory", "medical", "study"},
    "legal": {"legal", "paralegal", "law", "litigation", "compliance", "contract",
              "attorney", "counsel", "courts", "legal-support", "notary", "jp"},
    "education": {"education", "teaching", "teacher", "trainer", "instructor", "curriculum",
                  "pedagogy", "elearning", "mentor"},
    "healthcare": {"healthcare", "nursing", "nurse", "patient", "clinical", "medical",
                   "hospital", "physical-therapy", "occupational"},
    "operations": {"operations", "supply-chain", "logistics", "procurement", "inventory",
                   "purchasing", "buyer", "warehouse", "sourcing"},
    "human-resources": {"human-resources", "hr", "recruitment", "talent", "people-operations",
                        "payroll", "benefits", "hiring", "onboarding"},
    "support": {"support", "helpdesk", "service-desk", "customer-support", "it-support",
                "technical-support", "call-center"},
    "qa": {"qa", "quality", "test", "testing", "quality-assurance", "automation-testing"},
    "product": {"product", "product-management", "program", "product-owner", "scrum"},
    "project": {"project", "delivery", "program", "scrum", "agile"},
    "sales": {"sales", "account-executive", "business-development", "bd", "sales-rep",
              "account-manager", "revenue"},
    "engineering": {"engineering", "mechanical", "electrical", "mechatronics", "civil",
                    "structural", "aerospace", "chemical", "industrial", "manufacturing",
                    "automotive"},
    "research": {"research", "r&d", "laboratory", "lab", "scientist", "biotech", "bio"},
}

# Family aliases used to derive provider queries and close-title candidates.
_FAMILY_TITLES = {
    "security": ["Security Analyst", "SOC Analyst", "Information Security Analyst",
                 "Cyber Defense Analyst", "Security Operations Analyst",
                 "Cybersecurity Specialist", "Security Engineer"],
    "design": ["Graphic Designer", "Visual Designer", "Brand Designer",
               "Junior Graphic Designer", "UI/UX Designer", "Creative Designer"],
    "finance": ["Financial Analyst", "FP&A Analyst", "Finance Analyst",
                "Financial Planning Analyst", "Accountant"],
    "marketing": ["Marketing Analyst", "Digital Marketing Analyst", "Market Research Analyst",
                  "Marketing Specialist", "Growth Analyst"],
    "architecture": ["Architectural Designer", "BIM Designer", "BIM Modeler",
                     "Junior Architect", "Architectural Drafter"],
    "clinical": ["Clinical Research Assistant", "Clinical Trial Assistant",
                 "Clinical Research Coordinator", "Research Assistant"],
    "legal": ["Legal Assistant", "Paralegal", "Legal Support Specialist",
              "Legal Clerk"],
    "data": ["Data Analyst", "Business Intelligence Analyst", "Data Scientist",
             "Data Engineer"],
    "software": ["Software Engineer", "Frontend Developer", "Backend Engineer",
                 "Full Stack Developer", "Machine Learning Engineer", "AI Engineer"],
}


# Each alias family's bare domain name. An alias promotion is only credible
# when the alias contributes a domain token more specific than the bare family
# word: "Security Analyst" reduces to {security} exactly like "security
# manager" does, and letting the bare family word alone promote a candidate
# makes the generic "security X" jobs outrank the ICT security titles.
_BARE_FAMILY_NAME = {
    "security": "security", "data": "data", "software": "software",
    "design": "design", "finance": "finance", "marketing": "marketing",
    "clinical": "clinical", "legal": "legal", "architecture": "architecture",
}


def _words(text):
    return [w for w in _HYPEN_SPLIT.split((text or "").lower()) if len(w) >= 2]


def _normalise_token(tok):
    """Fold a single token to its canonical form ('' when unknown)."""
    t = tok.lower().strip("-")
    if t in _NORMALIZE:
        return _NORMALIZE[t]
    if "-" in t:
        joined = t.replace("-", "")
        if joined in _NORMALIZE:
            return _NORMALIZE[joined]
    return t


def normalize_title(title):
    """Return the normalised token sequence for a title (lowercased, folded).

    ``"Cybersecurity Analyst"`` -> ``["cybersecurity", "analyst"]``
    ``"Cyber Security Analyst"`` -> ``["cybersecurity", "analyst"]``
    ``"Frontend Engineer"`` -> ``["front-end", "engineer"]``
    """
    out = []
    for w in _words(title):
        n = _normalise_token(w)
        if n and n not in out:
            out.append(n)
    return out


def domain_tokens(title):
    """Domain-bearing tokens of a title: all normalised tokens minus generic
    role tails, level words, and cross-domain noise. These carry the *career*
    signal."""
    return [t for t in normalize_title(title)
            if (t not in _GENERIC_TAIL_TOKENS and t not in _LEVEL_TOKENS
                and t not in _GENERIC_DOMAIN_NOISE)]


def aliases_for(target):
    """Trusted close-title aliases for a target role (unbounded only when a
    family is known; otherwise an empty list). Used to widen matching safely.
    """
    fam = family_of(target)
    return [_FAMILY_TITLES.get(fam, [])] if fam else []


def family_of(title):
    """Canonical family key for a title, or '' when none is identifiable.

    A family is chosen by scoring the title's domain tokens against the curated
    family vocabularies; the strongest family wins. Generic tails never decide a
    family, so "Financial Analyst" -> finance (not "analyst"), and "Cybersecurity
    Analyst" -> security (not "analyst"/"data").
    """
    dom = domain_tokens(title)
    if not dom:
        return ""
    best, best_score = "", 0
    for fam, terms in _FAMILY_TERMS.items():
        score = 0
        for t in dom:
            if t in terms:
                score += 2
            else:
                for term in terms:
                    if (len(t) >= 4 and len(term) >= 4
                            and (t in term or term in t)):
                        score += 1
                        break
        if score > best_score:
            best, best_score = fam, score
    return best


def _title_is_exact(target_tokens, candidate_tokens):
    """True when the target's domain tokens are all present in the candidate
    (the target title is effectively a prefix of / contained in the candidate).
    Used only as the EXACT signal -- the candidate still has to be in the same
    canonical family, so a "Software Architect" never matches an "Architectural
    Designer" target merely by sharing the noun core.
    """
    t_dom = [t for t in target_tokens if t not in _GENERIC_TAIL_TOKENS
             and t not in _LEVEL_TOKENS and t not in _GENERIC_DOMAIN_NOISE]
    c_set = set(candidate_tokens)
    if not t_dom:
        return False
    return all(t in c_set for t in t_dom)


def classify_title(target, candidate_title):
    """Classify a candidate job/occupation title against the selected target.

    Returns one of: EXACT, CLOSE, FAMILY, UNRELATED.

    - EXACT   : the target's domain tokens all appear in the candidate title
                (e.g. target "Cybersecurity Analyst" -> "Junior Cybersecurity
                Analyst", "Cybersecurity Analyst I").
    - CLOSE   : the candidate shares one of the target's *own* domain tokens or
                matches a trusted alias (e.g. "Information Security Analyst",
                "SOC Analyst" for a cybersecurity target).
    - FAMILY  : the candidate shares a domain term inside the same canonical
                career family but not the target's own tokens (e.g. a "Security
                Administrator" for a "Cybersecurity Analyst" target).
    - UNRELATED: no shared domain/family evidence -- must be excluded.

    Generic tails shared alone ("Analyst" in both) never produce a match.
    """
    at = normalize_title(target)
    ct = normalize_title(candidate_title or "")
    if not at or not ct:
        return "UNRELATED"
    a_dom = domain_tokens(target)
    c_set = set(ct)
    c_dom = domain_tokens(candidate_title)
    if not a_dom:
        return "UNRELATED"

    if _title_is_exact(at, ct) and _same_family(target, candidate_title):
        return "EXACT"

    # CLOSE: shares a target domain token, or an interchangeable-equivalent
    # domain token (AI/ML), or a full atomic title alias.
    if set(a_dom) & c_set:
        return "CLOSE"
    if _shares_equiv(a_dom, c_set):
        return "CLOSE"
# Atomic alias match: only a title that is *literally* one of the trusted
    # close aliases counts as CLOSE — a job merely *in the same family* (e.g.
    # "Python Backend Engineer" for an AI target) stays FAMILY, never promoted
    # by a subset match. The set-equality must not hinge on the bare family
    # word alone (both "Security Analyst" and "security manager" reduce to
    # {security}), so an alias only promotes when it carries a domain token
    # more specific than the family name. That keeps "ICT security consultant"
    # / "SOC Analyst" close while demoting "security manager" / "security
    # guard" to the same-family band.
    c_dom_set = set(c_dom)
    fam = family_of(target)
    bare = _BARE_FAMILY_NAME.get(fam)
    for alias in (a for f in aliases_for(target) for a in f):
        alias_dom = set(domain_tokens(alias))
        if not alias_dom:
            continue
        if c_dom_set == alias_dom and any(t != bare for t in alias_dom):
            return "CLOSE"

    # FAMILY: the candidate belongs to the SAME canonical career family as the
    # target (e.g. "Incident Response Analyst" / "Security Guard" for a
    # cybersecurity target). Requiring equal canonical families keeps a generic
    # "Data Entry Clerk" (data family) from counting as an AI/software-family
    # role just because one ambiguous token ("data") overlaps.
    fam = family_of(target)
    if fam and family_of(candidate_title) == fam:
        return "FAMILY"

    return "UNRELATED"


def _same_family(a, b):
    """True when two titles resolve to the same canonical career family."""
    fa = family_of(a)
    fb = family_of(b)
    return bool(fa) and fa == fb


def _shares_equiv(a_dom, c_set):
    """True when a target's domain token and a candidate token belong to the same
    high-confidence equivalence class (AI <-> ML <-> machine learning)."""
    for cls in _EQUIV_CLASSES:
        if any(t in cls for t in a_dom) and cls & c_set:
            return True
    return False


def provider_queries(target, max_queries=3):
    """Bounded provider query terms built primarily from the target role.

    Returns a prioritized list where the target title (and its close aliases)
    come first; broad generic skill words are never standalone career queries.
    ``max_queries`` bounds how many terms are actually sent to a provider so we
    do not issue dozens of searches.
    """
    queries = []
    title = (target or "").strip()
    if title:
        queries.append(title)
    # Trusted close aliases widen the provider net without drifting off-career.
    for alias in (a for fam in aliases_for(target) for a in fam):
        if alias.lower().strip() != title.lower().strip():
            queries.append(alias)
        if len(queries) >= max_queries:
            break
    return queries[:max_queries]
