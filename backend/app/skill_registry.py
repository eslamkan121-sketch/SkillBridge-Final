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
    "Cybersecurity": "Security", "Cybersecurity Analysis": "Security",
    "Cybersecurity Fundamentals": "Security", "Network Security": "Security",
    "Incident Response": "Security", "SIEM": "Security", "Risk Assessment": "Security",
    "Threat Detection": "Security", "Security Monitoring": "Security", "Cloud Security": "Security",
    "Penetration Testing": "Security", "ISO 27001": "Security", "Security+": "Security",
    "Digital Forensics": "Security", "Vulnerability Management": "Security",
    "Windows Server": "Security", "Active Directory": "Security",
    # Soft skills
    "Communication": "Soft Skills", "Teamwork": "Soft Skills", "Leadership": "Soft Skills",
    "Problem Solving": "Soft Skills", "Critical Thinking": "Soft Skills",
    "Time Management": "Soft Skills", "Presentation Skills": "Soft Skills",
}

# Trusted explicit synonyms: an accepted way a canonical skill may be written.
# These are the ONLY merges the system performs — there is no fuzzy or
# substring-based merging anywhere.
SYNONYMS = {
    "ml": "Machine Learning",
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
    "communication": "Communication", "communication skills": "Communication",
    "leadership": "Leadership", "team work": "Teamwork",
    "team collaboration": "Teamwork", "excel": "Excel",
    "python": "Python", "python programming": "Python",
    "java": "Java", "java programming": "Java",
    "problem-solving": "Problem Solving", "problem solving guidance": "Problem Solving",
    "problem-solving guidance": "Problem Solving",
    "c++": "C++", "c": "C++", "react": "React",
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
    "patient care": "Patient Care",
    "medical billing": "Medical Billing",
    "regulatory compliance": "Regulatory Compliance",
    "infection control": "Infection Control",
    "sterilization": "Sterilization",
    "medical records": "Medical Records",
    "electronic health records": "Electronic Health Records",
    "treatment planning": "Treatment Planning",
    "patient education": "Patient Education",
    "patient assessment": "Patient Assessment",
    "medical terminology": "Medical Terminology",
    "pharmacology": "Pharmacology",
    "anatomy": "Anatomy",
    "physiology": "Physiology",
    "vital signs": "Vital Signs",
    "patient safety": "Patient Safety",
    "medical ethics": "Medical Ethics",
    "medical devices": "Medical Devices",
    "clinical examination": "Clinical Examination",
    "diagnosis": "Diagnosis",
    "medical imaging": "Medical Imaging",
    # Dentistry
    "dentistry": "Dentistry",
    "general dentistry": "General Dentistry",
    "restorative dentistry": "Restorative Dentistry",
    "cosmetic dentistry": "Cosmetic Dentistry",
    "pediatric dentistry": "Pediatric Dentistry",
    "preventive dentistry": "Preventive Dentistry",
    "digital dentistry": "Digital Dentistry",
    "endodontics": "Endodontics",
    "root canal therapy": "Root Canal Therapy",
    "root canal": "Root Canal Therapy",
    "orthodontics": "Orthodontics",
    "clear aligner therapy": "Orthodontics",
    "invisalign": "Invisalign",
    "periodontics": "Periodontics",
    "periodontal treatment": "Periodontics",
    "scaling and root planing": "Periodontics",
    "prosthodontics": "Prosthodontics",
    "dental implants": "Dental Implants",
    "implantology": "Dental Implants",
    "crowns and bridges": "Prosthodontics",
    "dental crowns": "Dental Crowns",
    "dental bridges": "Dental Bridges",
    "dentures": "Dentures",
    "veneers": "Dental Veneers",
    "dental veneers": "Dental Veneers",
    "smile design": "Smile Design",
    "oral surgery": "Oral Surgery",
    "tooth extraction": "Tooth Extraction",
    "oral and maxillofacial surgery": "Oral Surgery",
    "oral medicine": "Oral Medicine",
    "oral pathology": "Oral Pathology",
    "dental radiography": "Dental Radiography",
    "digital radiography": "Dental Radiography",
    "cbct": "Dental Radiography",
    "cone beam computed tomography": "Dental Radiography",
    "intraoral scanning": "Digital Dentistry",
    "cad/cam": "Digital Dentistry",
    "cerec": "Digital Dentistry",
    "dental fillings": "Restorative Dentistry",
    "composite fillings": "Restorative Dentistry",
    "dental sealants": "Preventive Dentistry",
    "fluoride varnish": "Preventive Dentistry",
    "fluoride application": "Preventive Dentistry",
    "dental anesthesia": "Dental Anesthesia",
    "local anesthesia": "Local Anesthesia",
    "nitrous oxide sedation": "Sedation",
    "dental hygiene": "Dental Hygiene",
    "patient education and prevention": "Patient Education",
    "dental treatment planning": "Treatment Planning",
    "dental practice management": "Dental Practice Management",
    "dental records": "Medical Records",
    "dental radiographs": "Dental Radiography",
    "occlusal analysis": "Occlusal Analysis",
    "articulation": "Articulation",
    "dental materials": "Dental Materials",
    "bite analysis": "Bite Analysis",
    "orthodontic treatment": "Orthodontics",
    "orthodontics treatment": "Orthodontics",
    "periodontal disease management": "Periodontics",
    "gum disease treatment": "Periodontics",
    "dental X-rays": "Dental Radiography",
    "panoramic x-rays": "Dental Radiography",
    "panoramic radiography": "Dental Radiography",
    "dental prophylaxis": "Dental Hygiene",
    "prophylaxis": "Dental Hygiene",
    "dental prevention": "Preventive Dentistry",
    "tooth bonding": "Restorative Dentistry",
    "inlays and onlays": "Restorative Dentistry",
    "dental inlays": "Restorative Dentistry",
    "dental onlays": "Restorative Dentistry",
    "surgical extractions": "Oral Surgery",
    "impacted tooth removal": "Oral Surgery",
    "wisdom tooth extraction": "Oral Surgery",
    "biopsy": "Oral Pathology",
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
TRUSTED_DISPLAY_KEYS = {_key(display) for display, _category in KNOWN_META.values()}


def is_trusted_name(raw):
    """True when ``raw`` is one of the trusted canonical/domain display names."""
    return _key(raw) in TRUSTED_DISPLAY_KEYS


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
    r"^(?:managed|built|developed|worked|led|created|engineered|analy[a-z]*|designed|"
    r"implemented|responsible|delivered|collaborated|coordinated|assisted|completed|"
    r"successful\s+completion|validated\s+proficiency|demonstrated\s+ability|"
    r"contributed|applying|recognizing\s+ability|recognising\s+ability|including|"
    r"covering|have|has|had|used|use|experience|possess)\b", re.I)
_RE_FRAGMENT_START = re.compile(
    r"^(?:and|or|but|with|from|to|for|including|covering|using|applying)\b", re.I)
_RE_TRAILING_PREPOSITION = re.compile(r"\b(?:for|with|from|to|of|in|by|and|or)\s*$", re.I)
_RE_PROSE_CONNECTOR = re.compile(
    r"\b(?:using|including|covering|applying|recognizing|recognising|to\s+protect|"
    r"from\s+evolving|in\s+real)\b", re.I)
_RE_CERT_TITLE_HINT = re.compile(
    r"\b(?:certificates?|certifications?|associate|specialist|summer\s+camp|bootcamp|"
    r"course|training\s+program|internship\s+certificate)\b", re.I)
_RE_ORG_TITLE_HINT = re.compile(r"\b(?:comptia|microsoft|sprints?|uneeq|rak|ict)\b", re.I)
_RE_VERSION_ONLY = re.compile(r"^(?:microsoft\s+)?office\s+(?:19|20)\d{2}$", re.I)
# "advanced Spanish", "fluent French", "basic Arabic" — a proficiency qualifier
# plus a bare word is a language-level fragment from a CV "Languages" line, not a
# professional skill ("advanced Excel" is still recovered via the known-term
# scan, and multi-word skills like "Advanced Cardiac Life Support" are untouched).
_RE_LEVEL_LANGUAGE = re.compile(
    r"^(?:advanced|intermediate|beginner|elementary|fluent|native|proficient|"
    r"basic|working|conversational)\s+[A-Za-z]{2,}$", re.I)
_RE_NAME_HEADING = re.compile(
    r"^(?:skills?|technical\s+skills?|teaching\s*(?:&|and)\s*soft\s+skills?|"
    r"soft\s+skills?|hard\s+skills?|certificates?|certifications?|languages?|education|"
    r"employment\s+history|profile|projects?|experience|training)$", re.I)
_GENERIC_SINGLETONS = {
    "and", "program", "programs", "course", "courses", "certificate", "certificates",
    "function", "functions", "formula", "formulas", "network", "networks", "incident",
    "response", "ict",
}
_GENERIC_PROSE_ENDINGS = {
    "use", "program", "programs", "certificate", "certificates", "technique", "techniques",
    "concept", "concepts", "practice", "practices", "scenario", "scenarios",
    "environment", "environments", "tool", "tools", "coverage", "cases",
}
_FUNCTION_WORDS = {
    "and", "or", "for", "with", "from", "to", "of", "in", "by", "as", "into",
    "through", "during", "using", "including", "covering", "applying",
}
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
    lowered = re.sub(r"\s+", " ", s.strip().lower())
    if _RE_NAME_HEADING.fullmatch(s):
        return False
    if lowered in _GENERIC_SINGLETONS:
        return False
    if _RE_VERSION_ONLY.search(s):
        return False
    if _RE_LEVEL_LANGUAGE.fullmatch(s):
        return False
    if _RE_FRAGMENT_START.search(s):
        return False
    if _RE_TRAILING_PREPOSITION.search(s):
        return False
    if _RE_PROSE_CONNECTOR.search(s):
        return False
    if _RE_CERT_TITLE_HINT.search(s):
        return False
    if _RE_ORG_TITLE_HINT.search(s) and ("-" in s or len(re.findall(r"\b[\w]+\b", s)) <= 3):
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
    word_lowers = [w.lower() for w in words]
    if word_lowers and word_lowers[-1] in _GENERIC_PROSE_ENDINGS:
        return False
    function_count = sum(1 for w in word_lowers if w in _FUNCTION_WORDS)
    if len(words) >= 4 and function_count >= 2:
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
    s = re.sub(r"[,.،;\u00b7|\-–—]+$", "", s)  # trailing separators only
    return s.strip()


def normalise_name(raw):
    """Open-universe normalisation.

    Resolution order:
      1. trusted explicit synonym (full phrase, case-insensitive)
      2. exact trusted canonical / known term
      3. trailing parenthetical collapse: "Root Canal Therapy (endodontics)"
         -> "Root Canal Therapy" when the pre-parenthesis base is a trusted term
      4. safe lexical cleaning of the grounded original
    Returns (name, category) or (None, None) when the input is empty/garbage.
    Never collapse `Patient Communication` -> `Communication` or similar.
    """
    s = (raw or "").strip()
    if not s:
        return None, None
    hit = KNOWN_META.get(_key(s))
    if hit:
        return hit
    # Collapse a trailing parenthetical when the base itself is a trusted term,
    # so compound dental/medical names written parenthetically ("Root Canal
    # Therapy (endodontics)") resolve to the clean canonical form instead of a
    # fragmented duplicate.
    base = re.sub(r"\s*\([^()]*\)\s*$", "", s)
    if base and base != s:
        hit = KNOWN_META.get(_key(base))
        if hit:
            return hit
        base_clean = clean_unknown(base)
        if base_clean and base_clean != base:
            hit = KNOWN_META.get(_key(base_clean))
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
    line_spans = []
    offset = 0
    for line in (text or "").splitlines(True):
        line_spans.append((offset, offset + len(line), _line_is_non_skill_context(line)))
        offset += len(line)
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
            if any(m.start() >= s and m.end() <= e and skip for s, e, skip in line_spans):
                pos = m.end()
                continue
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
    r"(?:key|technical|professional|core|transferable|relevant|hard|soft|"
    r"teaching\s*(?:&|\band\b)\s*soft|additional|other|general)?\s*skills"
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
# excluded: those sections legitimately name skills. Common adjective prefixes
# (professional/work/career/clinical/...) are accepted so "PROFESSIONAL EXPERIENCE"
# and "PROFESSIONAL SUMMARY" stop a skills region just like the bare heading does.
_NON_SECTION_HEADING = re.compile(
    r"^\s*(?:"
    # prefixed forms first: adjective prefix + core noun (whole line)
    r"(?:professional|relevant|work|employment|career|clinical|research|teaching|"
    r"field|academic|previous|recent)\s+"
    r"(?:experience|history|summary|objective|profile|background|"
    r"certifications?|licenses?|projects?|activities|training)\b"
    r"|(?:education|experience|employment|work[\s-]+history|projects?|awards?|"
    r"honors?|achievements?|summary|objective|profile|about(?:\s+me)?|interests|"
    r"hobbies|publications?|references?|referees?|certificates?|certifications?|licenses?|"
    r"training|extra-?curricular|volunteer(?:ing)?|community\s+service|"
    r"memberships?|affiliations?|languages?|(?:teaching\s*(?:&|\band\b)\s*)?"
    r"leadership(?:\s+experience)?|additional\s+"
    r"(?:information|info|activities)|personal\s+details|contact(?:\s+details)?)"
    r")\s*:?\s*$",
    re.I)

# Editor/recruiter guidance boilerplate that ships inside CV templates ("TIP: ...",
# "Note: ..."). These sentences read like list items after delimiter splitting
# ("name, title, organisation and phone" -> "phone", "title", "organisation") and
# must never become skills.
_RE_EDIT_GUIDANCE = re.compile(r"^\s*(?:tip|note|hint)\s*[:\-]|^\s*\(?\s*(?:tip|note)\b", re.I)


_ENUM_DELIMS = re.compile(r"[,;\u2022|\u00b7\t]")
_ENTRY_DELIMS = re.compile(r"[,;\u2022|\u00b7\t]|\s{2,}")
_RE_JOINED_SKILL_SUBHEADING = re.compile(
    r"(?P<head>(?:teaching\s*(?:&|\band\b)\s*soft|technical|soft|hard)\s+skills\b.*)$",
    re.I)


def _line_is_non_skill_context(line):
    stripped = (line or "").strip()
    if not stripped:
        return False
    if _RE_EDIT_GUIDANCE.match(stripped):
        return True
    if _HEADING_ONLY.match(stripped) or _HEADING_INLINE.match(stripped):
        return True
    if _NON_SECTION_HEADING.match(stripped):
        return True
    words = re.findall(r"\b[\w]+\b", stripped)
    if len(words) <= 5 and re.search(r"\b(?:experience|certificates?|certifications?|languages?|education)\s*:?\s*$", stripped, re.I):
        return True
    return False


def _expand_joined_skill_subheadings(lines):
    expanded = []
    for line in lines:
        stripped = (line or "").strip()
        if _HEADING_ONLY.match(stripped):
            expanded.append(line)
            continue
        m = _RE_JOINED_SKILL_SUBHEADING.search(line or "")
        if not m or m.start() <= 0:
            expanded.append(line)
            continue
        prefix = line[:m.start()].rstrip()
        heading = line[m.start():].strip()
        if prefix.strip() and heading and not line[m.start() - 1].isspace():
            expanded.append(prefix)
            expanded.append(heading)
        else:
            expanded.append(line)
    return expanded


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
    (``Python, SQL and Docker``).

    Parenthetical lists are protected: commas/semicolons INSIDE a balanced
    ``(...)`` group do NOT split the entry, so a compound skill written as
    "Restorative Dentistry (composite fillings, inlays, onlays)" or "AWS (EC2,
    S3, Lambda)" stays one entry instead of fragmenting mid-parenthesis."""
    has_enum = bool(_ENUM_DELIMS.search(line))
    # Protect a trailing level annotation: "Python  (Advanced)" must not be read
    # as a two-column layout, so its 2+ space gap is collapsed to a single space
    # before column splitting.
    line = re.sub(r"\s{2,}(\([^()]*\))\s*$", r" \1", line)
    # Mask enum delimiters that sit inside balanced parentheses so the split
    # below cannot cut compound parenthetical skill names into fragments.
    protected = _mask_parenthetical_delims(line)
    entries = []
    for piece in re.split(_ENTRY_DELIMS, protected):
        piece = _restore_parenthetical_delims(piece)
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


_PAREN_DELIM_PLACEHOLDER = "\uE000"


def _mask_parenthetical_delims(line):
    """Replace enum delimiters that appear inside balanced parentheses with a
    private-use placeholder so they survive the entry split untouched."""
    out = []
    depth = 0
    for ch in line or "":
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth > 0 and ch in ",;\u2022|\u00b7\t":
            out.append(_PAREN_DELIM_PLACEHOLDER)
        else:
            out.append(ch)
    return "".join(out)


def _restore_parenthetical_delims(piece):
    """Restore the enum delimiters that were protected inside parentheses."""
    return (piece or "").replace(_PAREN_DELIM_PLACEHOLDER, ",")


def skill_section_entries(text):
    """Extract candidate skill phrases from explicit skills sections.

    Recognised headings: Skills, Technical/Professional/Core Skills, Key Skills,
    Competencies, Core Competencies, Areas of Expertise, Expertise, Tools,
    Tools & Technologies, Software, Technologies. Entries may be comma, bullet,
    pipe, ampersand or newline separated."""
    candidates = []
    lines = _expand_joined_skill_subheadings((text or "").splitlines())
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
