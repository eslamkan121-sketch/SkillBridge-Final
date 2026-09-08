"""Open-universe skill metadata + validation for CV extraction.

This module contains a small set of *trusted term* metadata plus the safe
lexical helpers shared by the deterministic extractor and the LLM post-processor.

It is NOT an allow-list. A skill never has to appear here to be extracted:
unknown skills that are genuinely grounded in a CV text are preserved verbatim.
Known terms only upgrade matching / display / category — they never gate what
may be extracted.
"""
import re

NEUTRAL_CATEGORY = "Professional Skill"

# Trusted canonical skill names with the category the app already trusted.
CANONICAL_CATEGORIES = {
    # Programming
    "Python": "Programming", "Java": "Programming", "C++": "Programming",
    "JavaScript": "Programming", "TypeScript": "Programming", "React": "Programming",
    "Node.js": "Programming", "HTML/CSS": "Programming", "Rust": "Programming",
    "Go": "Programming", "C#": "Programming", "FastAPI": "Programming",
    "Flask": "Programming", "Django": "Programming",
    # Data
    "SQL": "Data", "Statistics": "Data", "ETL": "Data", "Data Engineering": "Data",
    "Excel": "Analytics", "Pandas": "Data", "NumPy": "Data",
    "Data Modeling": "Data", "Data Analysis": "Data", "BigQuery": "Data",
    "Snowflake": "Data", "dbt": "Data", "Airflow": "Data", "Spark": "Data",
    # AI / ML
    "Machine Learning": "AI", "Deep Learning": "AI", "NLP": "AI", "PyTorch": "AI",
    "TensorFlow": "AI", "scikit-learn": "AI", "LLM Prompting": "AI",
    "Retrieval-Augmented Generation": "AI",
    # DevOps / infra
    "Docker": "DevOps", "Kubernetes": "DevOps", "Git": "DevOps", "AWS": "DevOps",
    "Azure": "DevOps", "GCP": "DevOps", "Linux": "DevOps", "CI/CD": "DevOps",
    "Terraform": "DevOps", "REST APIs": "DevOps", "SQLAlchemy": "DevOps",
    # Visualization
    "Tableau": "Visualization", "Power BI": "Visualization", "Data Visualization": "Visualization",
    # Analytics
    "Business Intelligence": "Analytics", "A/B Testing": "Analytics",
    "Data Storytelling": "Analytics",
    # Security
    "Cybersecurity": "Security", "Network Security": "Security",
    "Incident Response": "Security", "SIEM": "Security", "Risk Assessment": "Security",
    "Threat Detection": "Security", "Cloud Security": "Security",
    "Penetration Testing": "Security", "ISO 27001": "Security", "Security+": "Security",
    "Digital Forensics": "Security", "Vulnerability Management": "Security",
    "Windows Server": "Security", "Active Directory": "Security",
    # Soft skills
    "Communication": "Soft Skills", "Teamwork": "Soft Skills", "Leadership": "Soft Skills",
    "Problem Solving": "Soft Skills", "Critical Thinking": "Soft Skills",
    "Time Management": "Soft Skills",
}

# Trusted explicit synonyms: an accepted way a canonical skill may be written.
# These are the ONLY merges the system performs — there is no fuzzy or
# substring-based merging anywhere.
SYNONYMS = {
    "ml": "Machine Learning", "ai": "Machine Learning",
    "deep learning": "Deep Learning", "dl": "Deep Learning",
    "pandas": "Pandas", "numpy": "NumPy", "sklearn": "scikit-learn",
    "scikit learn": "scikit-learn", "javascript": "JavaScript", "js": "JavaScript",
    "typescript": "TypeScript", "ts": "TypeScript", "sqlalchemy": "SQLAlchemy",
    "rest api": "REST APIs", "restful": "REST APIs", "fast api": "FastAPI",
    "spark": "Spark", "kafka": "Data Engineering",
    "powerbi": "Power BI", "power bi": "Power BI", "tableau": "Tableau",
    "cyber security": "Cybersecurity", "cybersecurity": "Cybersecurity",
    "infosec": "Cybersecurity", "network security": "Network Security",
    "networking": "Network Security", "networking basics": "Network Security",
    "penetration testing": "Penetration Testing", "pen testing": "Penetration Testing",
    "pentesting": "Penetration Testing",
    "docker": "Docker", "kubernetes": "Kubernetes", "k8s": "Kubernetes",
    "git": "Git", "github": "Git", "linux": "Linux", "aws": "AWS",
    "azure": "Azure", "gcp": "GCP", "google cloud": "GCP",
    "communication": "Communication", "leadership": "Leadership",
    "team work": "Teamwork", "excel": "Excel", "python": "Python",
    "java": "Java", "c++": "C++", "c": "C++", "react": "React",
    "node": "Node.js", "nodejs": "Node.js", "html": "HTML/CSS",
    "css": "HTML/CSS", "terraform": "Terraform", "airflow": "Airflow",
    "snowflake": "Snowflake", "bigquery": "BigQuery", "dbt": "dbt",
    "nlp": "NLP", "pytorch": "PyTorch", "tensorflow": "TensorFlow",
}

# Category for synonym targets that do not have a canonical name of their own.
_SYNONYM_CATEGORY = {
    "kafka": "Data", "github": "DevOps", "node": "Programming", "k8s": "DevOps",
}

# Broader trusted vocabulary — exact product names / compound phrases the app
# must understand deterministically. All receive the neutral category: without
# domain evidence we never pretend to know a precise category. Multi-word or
# distinctive single terms only (no generic nouns like "Design", "Marketing").
DOMAIN_TERMS = {
    # Design / brand
    "adobe photoshop": "Adobe Photoshop",
    "photoshop": "Adobe Photoshop",
    "adobe illustrator": "Illustrator",
    "illustrator": "Illustrator",
    "typography": "Typography",
    "brand identity": "Brand Identity",
    "color theory": "Color Theory",
    "storyboarding": "Storyboarding",
    "brand strategy": "Brand Strategy",
    # Marketing
    "market research": "Market Research",
    "google analytics": "Google Analytics",
    "seo": "SEO",
    "customer segmentation": "Customer Segmentation",
    "campaign planning": "Campaign Planning",
    "copywriting": "Copywriting",
    # Architecture / design
    "autocad": "AutoCAD",
    "revit": "Revit",
    "architectural drawing": "Architectural Drawing",
    "spatial planning": "Spatial Planning",
    "3d modeling": "3D Modeling",
    # Finance
    "financial modeling": "Financial Modeling",
    "forecasting": "Forecasting",
    "budget analysis": "Budget Analysis",
    # Clinical / healthcare
    "clinical research": "Clinical Research",
    "research methods": "Research Methods",
    "data collection": "Data Collection",
    "medical documentation": "Medical Documentation",
    "patient communication": "Patient Communication",
    "medical billing": "Medical Billing",
    "regulatory compliance": "Regulatory Compliance",
    # Common software / platform names (exact product names only)
    "powerpoint": "PowerPoint",
    "wordpress": "WordPress",
    "figma": "Figma",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "mongodb": "MongoDB",
    "redis": "Redis",
    ".net": ".NET",
    "ui/ux": "UI/UX",
}


def category_for(display):
    if display in CANONICAL_CATEGORIES:
        return CANONICAL_CATEGORIES[display]
    return NEUTRAL_CATEGORY


def _key(s):
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _build_known():
    known = {}
    for display, cat in CANONICAL_CATEGORIES.items():
        known[_key(display)] = (display, cat)
    for alias, canon in SYNONYMS.items():
        k = _key(alias)
        if not k or k in known:
            continue
        lk = alias.strip().lower()
        cat = _SYNONYM_CATEGORY.get(lk, category_for(canon))
        known[k] = (canon, cat)
    for phrase, display in DOMAIN_TERMS.items():
        k = _key(phrase)
        if k and k not in known:
            known[k] = (display, category_for(display))
    return known


KNOWN_META = _build_known()


# ------------------------------------------------------------------ name safety

_NAME_MAX = 60

_RE_URL = re.compile(r"://|www\.", re.I)
_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_RE_YEAR_RANGE = re.compile(r"\b(19|20)\d{2}\s*[-/.]\s*(19|20)?\d{2}\b")
_RE_NUM_DATE = re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b")
_RE_MONTH_YEAR = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?:19|20)\d{2}\b", re.I)
_RE_EDU_START = re.compile(
    r"^(?:bachelor|master|phd|doctoral|university|college|school|diploma|degree|higher[-\s]secondary|"
    r"bsc|msc|beng|llb|ba\b|ma\b|btech|a-?level|gce|gcse)\b", re.I)
_RE_ADDRESS_START = re.compile(r"^\d{2,4}\s")
_RE_SENTENCE_START = re.compile(
    r"^(?:managed|built|developed|worked|led|created|analy[a-z]*|designed|implemented|"
    r"responsible|delivered|collaborated|coordinated|assisted)\b", re.I)
_RE_CHARSET = re.compile(r"(?u)^[\w .+#_/()\-&'%·™®]{2,60}$")


def is_valid_name(raw):
    """Name-safety gate. Rejects empties, over-long strings, sentences, URLs,
    emails, dates, phone-like strings and education/address fragments. Tolerant
    of technical names (C++, C#, .NET, Node.js, A/B Testing, UI/UX, 3D Modeling)."""
    s = (raw or "").strip()
    if not s or len(s) > _NAME_MAX:
        return False
    if _RE_URL.search(s):
        return False
    if _RE_EMAIL.search(s):
        return False
    # phone-like: separators removed, everything else is digits
    stripped_digits = re.sub(r"[\s().+\-]", "", s).replace(",", "")
    digits = re.findall(r"\d", s)
    if len(digits) >= 7 and re.fullmatch(r"\d+", stripped_digits):
        return False
    if re.fullmatch(r"(19|20)\d{2}", s):
        return False
    if _RE_YEAR_RANGE.search(s) or _RE_NUM_DATE.search(s) or _RE_MONTH_YEAR.search(s):
        return False
    if _RE_EDU_START.search(s):
        return False
    if _RE_ADDRESS_START.search(s):
        return False
    # sentence-like fragments: ends with sentence punctuation, or has sentence
    # punctuation followed by a space inside, or reads like a past-tense clause
    if s.endswith((".", "?", "!")) or re.search(r"[.!?]\s", s):
        return False
    words = re.findall(r"\b[\w]+\w?\b", s, re.UNICODE)
    if len(words) > 8:
        return False
    if len(words) >= 4 and _RE_SENTENCE_START.search(s):
        return False
    if not _RE_CHARSET.fullmatch(s):
        return False
    if not re.search(r"(?u)[\w]", s):
        return False
    return True


def clean_unknown(raw):
    """Best-effort lexical cleaning for a skill not in the registry. Preserves
    casing and internal punctuation; never collapses or invents substrings."""
    s = re.sub(r"\s+", " ", (raw or "")).strip()
    s = re.sub(r"^[\"'\u201c\u2018(\[]+", "", s)
    s = re.sub(r"[\"'\u201d\u2019)\]]+$", "", s)
    s = re.sub(r"[,.،;\u00b7|]+$", "", s)  # trailing separators only
    return s.strip()


def normalise_name(raw):
    """Open-universe normalisation.

    Resolution order:
      1. trusted explicit synonym (full phrase, case-insensitive)
      2. exact trusted canonical / known term
      3. safe lexical cleaning of the grounded original
    Returns (name, category) or (None, None) when the input is empty/garbage.
    Never collapse `Patient Communication` -> `Communication` or similar.
    """
    s = (raw or "").strip()
    if not s:
        return None, None
    hit = KNOWN_META.get(_key(s))
    if hit:
        return hit
    cleaned = clean_unknown(s)
    if not cleaned:
        return None, None
    if not is_valid_name(cleaned):
        return None, None
    hit = KNOWN_META.get(_key(cleaned))
    if hit:
        return hit
    return cleaned, NEUTRAL_CATEGORY


# ------------------------------------------------------------------ phrase matching

_PHRASE_RE_CACHE = {}


def phrase_re(phrase):
    """Case-insensitive whole-phrase matcher. Whitespace between words is
    flexible; the original punctuation inside the phrase is preserved, so
    `a/b testing`, `c++`, `.net` and `ui/ux` match literally."""
    p = phrase.lower()
    rx = _PHRASE_RE_CACHE.get(p)
    if rx is not None:
        return rx
    esc = re.escape(p).replace(r"\ ", r"\s+")
    if p[:1].isalnum():
        esc = r"(?<![a-z0-9])" + esc
    if p[-1:].isalnum():
        esc = esc + r"(?![a-z0-9])"
    rx = _PHRASE_RE_CACHE[p] = re.compile(esc, re.I)
    return rx


def signal_len(phrase):
    """Length of alphanumeric signal in a phrase (used to skip noisy one-char
    aliases like the bare `c` alias for C++)."""
    return sum(len(t) for t in re.findall(r"[a-z0-9]+", phrase.lower()))


def match_known_terms(text):
    """Every known term present as a whole phrase in ``text`` (case-insensitive).

    Returns a list of {"name", "category", "evidence"}. A shorter term whose
    match is fully inside a longer matched term is suppressed, so
    `Communication` is not emitted from `Patient Communication`. Matching is
    longest-first and deduplicated by display name."""
    lowered = (text or "").lower()
    if not lowered:
        return []
    matches = []
    for key in sorted(KNOWN_META, key=len, reverse=True):
        if signal_len(key) < 2:
            continue
        rx = phrase_re(key)
        pos = 0
        while True:
            m = rx.search(lowered, pos)
            if not m:
                break
            matches.append((m.start(), m.end(), key))
            pos = m.end()
    matches.sort(key=lambda t: (t[1] - t[0], -t[0]), reverse=True)
    seen_spans = []
    out = []
    seen_names = set()
    for start, end, key in matches:
        if any(start >= s and end <= e for s, e in seen_spans):
            continue
        seen_spans.append((start, end))
        display, category = KNOWN_META[key]
        if display.lower() in seen_names:
            continue
        seen_names.add(display.lower())
        out.append({"name": display, "category": category,
                    "evidence": (text[start:end] or "").strip()[:300]})
    return out


# ------------------------------------------------------------------ skill sections

_SKILL_HEADING = (
    r"(?:key|technical|professional|core|transferable|relevant|hard|additional|other|general)?\s*skills"
    r"|(?:core|professional|key|technical)?\s*competenc(?:ies|y)"
    r"|areas?\s+of\s+(?:expertise|strength)"
    r"|expertise|tools(?:\s*(?:&|\band\b)\s*technolog(?:ies|y))?"
    r"|software|technolog(?:ies|y)"
)

_HEADING_ONLY = re.compile(r"^\s*(?:" + _SKILL_HEADING + r")\s*:?\s*$", re.I)
_HEADING_INLINE = re.compile(r"^\s*(?:" + _SKILL_HEADING + r")\s*:\s*(.+)$", re.I)

# Section headings that are NEVER skill content. Real CVs put referees/references,
# contact details, memberships, affiliations, languages, hobbies, achievements and
# volunteering in exactly these sections -- often in the SAME two-column grid layout
# as skills ("William Turner  Candice Palmer", "WGC Lawyers  Lander & Rogers").
# Without these boundaries the skills content-region swallows referee names, employer
# names and template boilerplate as if they were skills (observed on the real
# Graduate-Resume-Example-Law.pdf). "certifications"/"licenses"/"courses" are NOT
# excluded: those sections legitimately name skills.
_NON_SECTION_HEADING = re.compile(
    r"^\s*(?:education|experience|employment|work[\s-]+history|projects?|awards?|"
    r"honors?|achievements?|summary|objective|profile|about(?:\s+me)?|interests|"
    r"hobbies|publications?|references?|referees?|certifications?|licenses?|"
    r"training|extra-?curricular|volunteer(?:ing)?|community\s+service|"
    r"memberships?|affiliations?|languages?|leadership|additional\s+"
    r"(?:information|info|activities)|personal\s+details|contact(?:\s+details)?)\s*:?\s*$",
    re.I)

# Editor/recruiter guidance boilerplate that ships inside CV templates ("TIP: ...",
# "Note: ..."). These sentences read like list items after delimiter splitting
# ("name, title, organisation and phone" -> "phone", "title", "organisation") and
# must never become skills.
_RE_EDIT_GUIDANCE = re.compile(r"^\s*(?:tip|note|hint)\s*[:\-]|^\s*\(?\s*(?:tip|note)\b", re.I)


_ENUM_DELIMS = re.compile(r"[,;\u2022|\u00b7\t]")
_ENTRY_DELIMS = re.compile(r"[,;\u2022|\u00b7\t]|\s{2,}")


def _split_entries(line):
    """Extract candidate skill phrases from one skills-section content line.

    Every explicit list delimiter (comma, semicolon, bullet, pipe, tab) splits
    entries, and so does a run of 2+ spaces, which is how PDF/column CV layouts
    render a two-column skills grid ("Legal research and writing  Dispute
    resolution and mediation"). Bare ``and`` is honoured as a phrase part, NOT a
    separator, so compound competency names ("Dispute resolution and
    mediation", "Legal research and writing", "Case analysis and
    interpretation") survive intact -- the ``and``-join is treated as a list
    only inside lines that already use explicit enumeration delimiters
    (``Python, SQL and Docker``)."""
    has_enum = bool(_ENUM_DELIMS.search(line))
    # Protect a trailing level annotation: "Python  (Advanced)" must not be read
    # as a two-column layout, so its 2+ space gap is collapsed to a single space
    # before column splitting.
    line = re.sub(r"\s{2,}(\([^()]*\))\s*$", r" \1", line)
    entries = []
    for piece in re.split(_ENTRY_DELIMS, line):
        piece = piece.strip()
        piece = re.sub(r"^[\s\-–—*•▪▸>#]+", "", piece)
        piece = re.sub(r"^\d+[.)]\s*", "", piece)
        if not piece:
            continue
        if not has_enum:
            entries.append(piece)
            continue
        for sub in re.split(r"\s+(?:&|and)\s+", piece, flags=re.I):
            sub = sub.strip()
            if sub:
                entries.append(sub)
    return entries


def skill_section_entries(text):
    """Extract candidate skill phrases from explicit skills sections.

    Recognised headings: Skills, Technical/Professional/Core Skills, Key Skills,
    Competencies, Core Competencies, Areas of Expertise, Expertise, Tools,
    Tools & Technologies, Software, Technologies. Entries may be comma, bullet,
    pipe, ampersand or newline separated."""
    candidates = []
    lines = (text or "").splitlines()
    i, n = 0, len(lines)
    while i < n:
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        m = _HEADING_ONLY.match(line)
        inline = None
        if not m:
            m2 = _HEADING_INLINE.match(line)
            if m2:
                m = m2
                inline = m2.group(1)
        if not m:
            i += 1
            continue
        content_lines = []
        if inline is not None:
            content_lines.append(inline)
        j = i + 1
        while j < n:
            nxt = lines[j].strip()
            if not nxt:
                content_lines.append("")
                j += 1
                continue
            if _HEADING_ONLY.match(nxt) or _HEADING_INLINE.match(nxt) or _NON_SECTION_HEADING.match(nxt):
                break
            if _RE_EDIT_GUIDANCE.match(nxt):
                j += 1
                continue
            if len(nxt) > 200:
                break
            content_lines.append(nxt)
            j += 1
        i = j
        for cl in content_lines:
            for entry in _split_entries(cl):
                if entry:
                    candidates.append(entry)
    return candidates