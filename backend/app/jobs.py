"""Real, recent, career-fitting job listings for students.

Aggregates live openings from multiple free job feeds and matches
them to a student's actual profile:

- **Sources**: Remotive (global remote) + RemoteOK (global remote/tech)
  + optional Adzuna (ADZUNA_APP_ID/KEY), JSearch / LinkedIn / Google Jobs
  (RapidAPI), Jooble and USAJobs when their keys are configured. Remote
  RapidAPI aggregators (LinkedIn, Google Jobs) are host-gated via
  LINKEDIN_JOBS_HOST / GOOGLE_JOBS_HOST (never guessed).
- **Relevance**: every job is scored against the student's skill names
  (a weighted keyword overlap) and their target role.
- **Experience fit**: the student's seniority is inferred from their skill
  levels (Beginner/Intermediate/Advanced) plus verified-skill depth; each job's
  seniority is inferred from its title. Senior roles are de-ranked (and, for a
  clear undergrad, filtered out entirely) so a student isn't shown "Senior"
  roles they aren't qualified for.
- **Country**: where a job listing carries a country/location tag, jobs in the
  student's own country get a relevance boost. Both feeds are remote-first, so
  country is a soft signal, not a hard filter.
- **Ranking**: results are sorted most-fitting → least-fitting, marked with a
  ``match_pct`` and a short ``match_reason`` the UI can show.

Results are cached in memory for a short TTL so a demo never hammers upstream.
Provider outcomes are honest: when at least one feed answers with live listings
the result is ``live``; providers that answered without relevant matches yield
an ``empty`` (no jobs injected); when every feed is unreachable/offline the
result is ``unavailable`` with no jobs — the UI tells the user providers are
temporarily down rather than serving fabricated or demo listings. The caller is
told with the ``source`` field, and a per-provider status report (ok / failed /
skipped, with redacted reasons) accompanies every payload.
"""
import hashlib
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

import httpx

from . import role_intent

logger = logging.getLogger("skillbridge.jobs")

REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
REMOTEOK_URL = "https://remoteok.com/api"
ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs"
JOBICY_URL = "https://jobicy.com/api/v2/remote-jobs"
ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
JOOBLE_BASE = "https://api.jooble.org/api"
JSEARCH_URL = "https://jsearch.p.rapidapi.com/search-v2"
USAJOBS_URL = "https://data.usajobs.gov/api/search"

# RapidAPI LinkedIn / Google Jobs adapters are HOST-GATED: the exact host of the
# subscribed RapidAPI app is configured via env (LINKEDIN_JOBS_HOST/LINKEDIN_JOBS_PATH,
# GOOGLE_JOBS_HOST/GOOGLE_JOBS_PATH). Until configured a provider reports
# ``host_not_configured`` and skips — the host is never guessed. Keys resolve
# provider-specific (RAPIDAPI_LINKEDIN_KEY / RAPIDAPI_GOOGLE_JOBS_KEY) then
# fall back to the shared RAPIDAPI_KEY.
TTL_SECONDS = 15 * 60

# Listings older than this (in days) are treated as stale/expired when the
# provider exposes no authoritative liveness signal (close date, availability
# flag, expiry timestamp). Aggregator boards (e.g. the beBee links returned by
# the JSearch feed) re-index closed postings and never mark them as such, so an
# age heuristic is the only honest way to keep the live feed to real openings.
MAX_LISTING_AGE_DAYS = 30

_HEADERS = {"User-Agent": "SkillBridge/1.0 (career platform; student job matching)"}

# All healthy providers, in priority order. Keyed providers stay disabled until
# their credentials are configured; a slow/failing provider is reported safely
# and never blocks the other feeds. Jooble is optional: its API can be
# unreachable from some regions and simply degrades to a no-op. LinkedIn and
# Google Jobs (RapidAPI) are host-gated — until the exact subscribed host is
# configured they report ``host_not_configured`` and skip.
PROVIDERS = (
    "JSearch", "LinkedIn", "Google Jobs", "Adzuna", "USAJobs",
    "Remotive", "Jobicy", "Arbeitnow", "RemoteOK",
    "Jooble",
)

# Countries Adzuna actually serves (their API 404s on any other two-letter code,
# e.g. `eg` for Egypt). A student in an unsupported country must NOT be silently
# switched to another country's jobs — Adzuna is skipped, never substituted.
_ADZUNA_SUPPORTED = {
    "Austria", "Australia", "Belgium", "Brazil", "Canada", "Switzerland",
    "Germany", "Spain", "France", "United Kingdom", "India", "Italy",
    "Mexico", "Netherlands", "New Zealand", "Poland", "Singapore", "South Africa",
}

# Per-provider outcome for the latest build: ``status`` is one of
#   "ok"       - responded successfully (count = listings returned)
#   "failed"   - attempted but errored/unreachable (reason + redacted error)
#   "skipped"  - not attempted (reason, e.g. unsupported_country / no_credentials)
# ``count`` is the number of listings, ``reason`` a short stable code, and
# ``error`` a SHORT redacted detail. Never contains credentials — every error
# string is passed through ``_redact``.
_provider_status = {p: {"status": "skipped", "count": 0, "reason": "", "error": ""}
                    for p in PROVIDERS}


def _redact(text):
    """Strip any configured credential out of a message before logging/sending.

    httpx error messages embed the full request URL (Adzuna puts app_id/app_key
    in the query string, Jooble in the path), so raw exceptions may carry
    secrets. Known key values are replaced with ``***`` wherever they appear.
    """
    s = str(text or "")
    for var in ("JSEARCH_API_KEY", "RAPIDAPI_KEY", "RAPIDAPI_LINKEDIN_KEY",
                "RAPIDAPI_GOOGLE_JOBS_KEY", "LINKEDIN_JOBS_API_KEY",
                "GOOGLE_JOBS_API_KEY", "ADZUNA_APP_ID",
                "ADZUNA_APP_KEY", "JOOBLE_API_KEY", "USAJOBS_API_KEY"):
        v = os.environ.get(var)
        if v and len(v) >= 4 and v in s:
            s = s.replace(v, "***")
    return s


def _record_status(source, status, count=0, reason="", error=""):
    _provider_status[source] = {
        "status": status,
        "count": count,
        "reason": reason,
        "error": _redact(error)[:120],
    }


def _skip_status(source, reason):
    """Mark a provider as skipped (key missing, unsupported country, etc.)."""
    _provider_status[source] = {"status": "skipped", "count": 0,
                                "reason": reason, "error": ""}


def _any_provider_ok():
    """True when at least one provider reported a successful response."""
    return any(_provider_status.get(p, {}).get("status") == "ok"
               for p in PROVIDERS)


def _clean_text(raw):
    """Strip provider HTML/markup and collapse whitespace; never fabricates."""
    if not raw:
        return ""
    s = re.sub(r"<[^>]+>", " ", str(raw))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:800]


def _salary_str(salary_min, salary_max, currency="", period=""):
    """Best-effort salary display; returns '' (unknown) when no value exists."""
    def fmt(v):
        try:
            return f"{float(v):,.0f}"
        except (TypeError, ValueError):
            return str(v or "").strip()
    parts = [fmt(v) for v in (salary_min, salary_max) if v not in (None, "")]
    if not parts:
        return ""
    out = " - ".join(parts)
    if currency:
        out = f"{out} {currency}"
    if period:
        out = f"{out}/{str(period).lower()}"
    return out


def _job_id(source, url, title, company):
    seed = "|".join([source or "", url or "", title or "", company or ""])
    return hashlib.md5(seed.encode("utf-8")).hexdigest()[:12]


def _workplace_type(job):
    raw = (job.get("location") or "").lower()
    hay = " ".join([raw, (job.get("description") or "")[:600].lower()])
    if job.get("remote") or _is_remote(raw):
        return "remote"
    if "hybrid" in hay:
        return "hybrid"
    return ""  # unknown — never invent "onsite"


# Cross-domain requirement vocabulary used to enrich--never filter--a listing.
# Unknown legitimate skills are preserved (tags pass through untouched); this
# list only surfaces recognized skill names as ``required_skills``. Matching is
# word-bounded so "Git" is not found inside "digital" and "EHR" not inside
# "share".
_SKILL_TERMS = [
    ("python", "Python"), ("docker", "Docker"), ("sql", "SQL"), ("git", "Git"),
    ("javascript", "JavaScript"), ("typescript", "TypeScript"), ("java", "Java"),
    ("golang", "Go"), ("react", "React"), ("node.js", "Node.js"), ("nodejs", "Node.js"),
    ("aws", "AWS"), ("azure", "Azure"), ("linux", "Linux"), ("kubernetes", "Kubernetes"),
    ("machine learning", "Machine Learning"), ("deep learning", "Deep Learning"),
    ("tensorflow", "TensorFlow"), ("pytorch", "PyTorch"), ("fastapi", "FastAPI"),
    ("django", "Django"), ("html", "HTML"), ("css", "CSS"),
    ("photoshop", "Photoshop"), ("illustrator", "Illustrator"), ("indesign", "InDesign"),
    ("figma", "Figma"), ("typography", "Typography"), ("brand identity", "Brand Identity"),
    ("ui design", "UI Design"), ("ux design", "UX Design"), ("wireframing", "Wireframing"),
    ("prototyping", "Prototyping"), ("motion graphics", "Motion Graphics"),
    ("graphic design", "Graphic Design"), ("adobe creative suite", "Adobe Creative Suite"),
    ("seo", "SEO"), ("sem", "SEM"), ("google analytics", "Google Analytics"),
    ("market research", "Market Research"), ("social media marketing", "Social Media Marketing"),
    ("content marketing", "Content Marketing"), ("email marketing", "Email Marketing"),
    ("ppc", "PPC"), ("google ads", "Google Ads"), ("copywriting", "Copywriting"),
    ("brand strategy", "Brand Strategy"), ("digital marketing", "Digital Marketing"),
    ("customer segmentation", "Customer Segmentation"), ("marketing automation", "Marketing Automation"),
    ("clinical research", "Clinical Research"), ("good clinical practice", "Good Clinical Practice"),
    ("data collection", "Data Collection"), ("medical documentation", "Medical Documentation"),
    ("electronic medical records", "Electronic Medical Records"), ("ehr", "EHR"),
    ("hipaa", "HIPAA"), ("regulatory compliance", "Regulatory Compliance"),
    ("patient care", "Patient Care"), ("medical writing", "Medical Writing"),
    ("clinical trials", "Clinical Trials"),
    ("autocad", "AutoCAD"), ("revit", "Revit"), ("bim", "BIM"), ("sketchup", "SketchUp"),
    ("cad", "CAD"), ("architectural design", "Architectural Design"),
    ("building codes", "Building Codes"), ("3d modeling", "3D Modeling"),
    ("financial modeling", "Financial Modeling"), ("accounting", "Accounting"),
    ("gaap", "GAAP"), ("financial analysis", "Financial Analysis"),
    ("forecasting", "Forecasting"), ("budgeting", "Budgeting"), ("banking", "Banking"),
    ("audit", "Audit"), ("valuation", "Valuation"), ("risk management", "Risk Management"),
    ("financial reporting", "Financial Reporting"), ("taxation", "Taxation"),
    ("corporate finance", "Corporate Finance"),
    ("project management", "Project Management"), ("communication", "Communication"),
    ("teamwork", "Teamwork"), ("leadership", "Leadership"), ("negotiation", "Negotiation"),
    ("data analysis", "Data Analysis"), ("problem solving", "Problem Solving"),
    ("presentation", "Presentation"), ("stakeholder management", "Stakeholder Management"),
]


def _extract_required_skills(job):
    """Recognized skill names present in a listing's title/tags/description.

    Enrichment only — listings keep every provider tag even when nothing here
    matches, and an empty result simply means "no known skills stated".
    """
    text = " ".join([
        job.get("title") or "",
        " ".join(job.get("tags") or []),
        job.get("description") or "",
    ]).lower()
    hits = []
    for term, display in _SKILL_TERMS:
        pat = r"\b" + re.escape(term).replace(r"\ ", r"\s+") + r"\b"
        if re.search(pat, text):
            hits.append(display)
    return hits[:8]

_level_score = {"Beginner": 1, "Intermediate": 2, "Advanced": 3}
_level_to_want = {"Beginner": "entry", "Intermediate": "junior", "Advanced": "mid"}

_cache = {"at": 0.0, "key": "", "data": None}
_lock = threading.Lock()
_bg_fetching = set()  # keys currently being fetched in background

# Curated offline stand-ins, aligned with the app's own seeded companies and
# catalog, so a no-network demo still shows believable, dated roles.
FALLBACK_JOBS = [
    {"title": "Junior AI Engineer", "company": "Northstar Labs",
     "url": "https://www.google.com/search?q=junior+AI+engineer+job", "date": "2026-08-28",
     "location": "Remote", "country": "United States",
     "tags": ["AI", "Python", "Machine Learning"], "seniority": "junior"},
    {"title": "Data Analyst (Entry)", "company": "Signal Works",
     "url": "https://www.google.com/search?q=data+analyst+job", "date": "2026-08-26",
     "location": "Remote", "country": "United States",
     "tags": ["SQL", "Data", "Analytics"], "seniority": "entry"},
    {"title": "Backend Engineer, AI Products", "company": "Northstar Labs",
     "url": "https://www.google.com/search?q=backend+engineer+AI+job", "date": "2026-08-24",
     "location": "Remote", "country": "United Kingdom",
     "tags": ["Python", "Docker", "APIs"], "seniority": "junior"},
    {"title": "Machine Learning Engineer", "company": "Signal Works",
     "url": "https://www.google.com/search?q=machine+learning+engineer+job", "date": "2026-08-20",
     "location": "Remote", "country": "India",
     "tags": ["Machine Learning", "Python"], "seniority": "mid"},
    {"title": "Junior Data Engineer", "company": "Northstar Labs",
     "url": "https://www.google.com/search?q=junior+data+engineer+job", "date": "2026-08-18",
     "location": "Remote", "country": "Canada",
     "tags": ["SQL", "Docker", "ETL"], "seniority": "junior"},
    {"title": "Software Developer (Graduate)", "company": "Signal Works",
     "url": "https://www.google.com/search?q=graduate+software+developer+job", "date": "2026-08-15",
     "location": "Remote", "country": "United States",
     "tags": ["Python", "Git", "SQL"], "seniority": "entry"},
]


_FALLBACK_LOCAL = {
    "Egypt": [
        {"title": "Junior Data Analyst", "company": "Local Bank - Cairo",
         "url": "https://www.google.com/search?q=junior+data+analyst+cairo+egypt+job", "date": "2026-08-27",
         "location": "Cairo", "tags": ["SQL", "Data", "Analytics"], "seniority": "entry"},
        {"title": "Data Engineer (Junior)", "company": "Fintech Startup - Giza",
         "url": "https://www.google.com/search?q=data+engineer+giza+egypt+job", "date": "2026-08-25",
         "location": "Giza", "tags": ["SQL", "Python", "ETL"], "seniority": "junior"},
        {"title": "AI/ML Engineer (Junior)", "company": "Tech Hub - New Cairo",
         "url": "https://www.google.com/search?q=ai+ml+engineer+cairo+egypt+job", "date": "2026-08-23",
         "location": "New Cairo", "tags": ["Machine Learning", "Python", "AI"], "seniority": "junior"},
        {"title": "Backend Developer (Graduate)", "company": "Software House - Alexandria",
         "url": "https://www.google.com/search?q=backend+developer+alexandria+egypt+job", "date": "2026-08-21",
         "location": "Alexandria", "tags": ["Python", "Docker", "APIs"], "seniority": "entry"},
        {"title": "Frontend Developer (Junior, Remote Egypt)", "company": "Remote Team - Cairo",
         "url": "https://www.google.com/search?q=frontend+developer+remote+egypt+job", "date": "2026-08-19",
         "location": "Remote - Egypt", "tags": ["React", "JavaScript"], "seniority": "junior"},
        {"title": "Junior Data Scientist", "company": "Analytics Firm - Nasr City",
         "url": "https://www.google.com/search?q=junior+data+scientist+egypt+job", "date": "2026-08-17",
         "location": "Cairo", "tags": ["Machine Learning", "Python", "Statistics"], "seniority": "entry"},
    ],
    "United Arab Emirates": [
        {"title": "Junior Software Engineer", "company": "Tech Co - Dubai",
         "url": "https://www.google.com/search?q=junior+software+engineer+dubai+job", "date": "2026-08-26",
         "location": "Dubai", "tags": ["Python", "SQL"], "seniority": "junior"},
        {"title": "Data Analyst (Entry)", "company": "Consulting - Abu Dhabi",
         "url": "https://www.google.com/search?q=data+analyst+abu+dhabi+job", "date": "2026-08-22",
         "location": "Abu Dhabi", "tags": ["SQL", "Data", "Analytics"], "seniority": "entry"},
    ],
    "Saudi Arabia": [
        {"title": "Junior Data Engineer", "company": "Enterprise - Riyadh",
         "url": "https://www.google.com/search?q=junior+data+engineer+riyadh+job", "date": "2026-08-24",
         "location": "Riyadh", "tags": ["SQL", "Python", "ETL"], "seniority": "junior"},
        {"title": "AI Engineer (Junior)", "company": "GovTech - Riyadh",
         "url": "https://www.google.com/search?q=ai+engineer+riyadh+job", "date": "2026-08-20",
         "location": "Riyadh", "tags": ["Machine Learning", "Python"], "seniority": "junior"},
    ],
    "United Kingdom": [
        {"title": "Junior Software Engineer", "company": "Tech Start - London",
         "url": "https://www.google.com/search?q=junior+software+engineer+london+job", "date": "2026-08-26",
         "location": "London", "tags": ["Python", "SQL"], "seniority": "junior"},
        {"title": "Data Analyst (Entry)", "company": "Bank - Manchester",
         "url": "https://www.google.com/search?q=data+analyst+manchester+uk+job", "date": "2026-08-22",
         "location": "Manchester", "tags": ["SQL", "Data"], "seniority": "entry"},
    ],
    "United States": [
        {"title": "Junior Software Engineer", "company": "Tech Co - New York",
         "url": "https://www.google.com/search?q=junior+software+engineer+new+york+job", "date": "2026-08-26",
         "location": "New York", "tags": ["Python", "SQL"], "seniority": "junior"},
        {"title": "Data Analyst (Entry)", "company": "E-Commerce - San Francisco",
         "url": "https://www.google.com/search?q=data+analyst+entry+job", "date": "2026-08-22",
         "location": "San Francisco", "tags": ["SQL", "Data"], "seniority": "entry"},
    ],
}


def _fallback_jobs(country=""):
    norm = _normalise_country(country)
    out = []
    for job in _FALLBACK_LOCAL.get(norm, []):
        item = dict(job)
        remote = _is_remote(item.get("location") or "")
        city, inferred_country = _city_country_hint(item.get("location") or "")
        item["country"] = inferred_country or norm
        item["city"] = "" if remote else city
        item["remote"] = remote
        out.append(item)
    for job in FALLBACK_JOBS:
        item = dict(job)
        city, inferred_country = _city_country_hint(item.get("location") or "")
        item.setdefault("city", city)
        if not item.get("country") and inferred_country:
            item["country"] = inferred_country
        item.setdefault("remote", _is_remote(item.get("location") or ""))
        if norm and item["remote"] and not item.get("country"):
            item["country"] = norm
        out.append(item)
    return out

# Seniority markers extracted from a job title. Leadership titles (head,
# director, manager, chief, vp, executive) count as clearly senior so they can
# be conservatively de-ranked for entry-level students. Lower entries in the
# list win because a title carrying "Senior Associate" is senior, not entry.
_SENIORITY_PATTERNS = [
    (("director", "head", "chief", "vp", "v.p.", "executive", "manager",
      "senior", "staff", "principal", "lead", "sr", "sr.", "architect"), 3),
    (("mid", "mid-level", "intermediate"), 2),
    (("junior", "jr", "jr.", "entry", "graduate", "grad", "associate",
      "intern", "trainee"), 0),
]

# Country-name normalisation: common country names a job's location/tags might
# use, mapped to the canonical names the app stores.
_COUNTRY_ALIASES = {
    "usa": "United States", "us": "United States", "united states": "United States",
    "u.s": "United States", "u.s.a": "United States", "america": "United States",
    "united states of america": "United States",
    "uk": "United Kingdom", "gb": "United Kingdom", "england": "United Kingdom",
    "great britain": "United Kingdom", "britain": "United Kingdom",
    "uae": "United Arab Emirates", "emirates": "United Arab Emirates",
    "united arab emirates": "United Arab Emirates",
    "ksa": "Saudi Arabia", "saudi": "Saudi Arabia", "saudi arabia": "Saudi Arabia",
    "canada": "Canada", "ca": "Canada",
    "india": "India", "in": "India",
    "germany": "Germany", "de": "Germany",
    "france": "France", "fr": "France",
    "netherlands": "Netherlands", "nl": "Netherlands", "holland": "Netherlands",
    "australia": "Australia", "au": "Australia",
    "egypt": "Egypt", "eg": "Egypt", "egyptian": "Egypt", "misr": "Egypt",
    "qatar": "Qatar", "qa": "Qatar",
    "kuwait": "Kuwait", "kw": "Kuwait",
    "bahrain": "Bahrain", "bh": "Bahrain",
    "oman": "Oman", "om": "Oman",
    "jordan": "Jordan", "jo": "Jordan",
    "lebanon": "Lebanon", "lb": "Lebanon",
    "morocco": "Morocco", "ma": "Morocco",
    "algeria": "Algeria", "dz": "Algeria",
    "tunisia": "Tunisia", "tn": "Tunisia",
    "brazil": "Brazil", "br": "Brazil",
    "mexico": "Mexico", "mx": "Mexico",
    "italy": "Italy", "it": "Italy",
    "spain": "Spain", "es": "Spain",
    "ireland": "Ireland", "ie": "Ireland",
    "poland": "Poland", "pl": "Poland",
    "sweden": "Sweden", "se": "Sweden",
    "denmark": "Denmark", "dk": "Denmark",
    "norway": "Norway", "no": "Norway",
    "finland": "Finland", "fi": "Finland",
    "switzerland": "Switzerland", "ch": "Switzerland",
    "austria": "Austria", "at": "Austria",
    "belgium": "Belgium", "be": "Belgium",
    "japan": "Japan", "jp": "Japan",
    "south korea": "South Korea", "korea": "South Korea", "kr": "South Korea",
    "china": "China", "cn": "China",
    "singapore": "Singapore", "sg": "Singapore",
    "malaysia": "Malaysia", "my": "Malaysia",
    "indonesia": "Indonesia", "id": "Indonesia",
    "philippines": "Philippines", "ph": "Philippines",
    "vietnam": "Vietnam", "vn": "Vietnam",
    "thailand": "Thailand", "th": "Thailand",
    "argentina": "Argentina", "ar": "Argentina",
    "chile": "Chile", "cl": "Chile",
    "colombia": "Colombia", "co": "Colombia",
    "south africa": "South Africa", "za": "South Africa",
    "nigeria": "Nigeria", "ng": "Nigeria",
    "kenya": "Kenya", "ke": "Kenya",
    "pakistan": "Pakistan", "pk": "Pakistan",
    "bangladesh": "Bangladesh", "bd": "Bangladesh",
    "turkey": "Turkey", "turkiye": "Turkey", "tr": "Turkey",
}

_KNOWN_COUNTRIES = set(_COUNTRY_ALIASES.values())

_CITY_TO_COUNTRY = {
    "cairo": "Egypt", "alexandria": "Egypt", "giza": "Egypt",
    "new cairo": "Egypt", "nasr city": "Egypt", "6th of october": "Egypt",
    "london": "United Kingdom", "manchester": "United Kingdom", "birmingham": "United Kingdom",
    "new york": "United States", "new york city": "United States",
    "san francisco": "United States", "los angeles": "United States",
    "seattle": "United States", "austin": "United States", "chicago": "United States",
    "toronto": "Canada", "vancouver": "Canada", "montreal": "Canada",
    "mumbai": "India", "bangalore": "India", "bengaluru": "India",
    "hyderabad": "India", "delhi": "India", "pune": "India",
    "dubai": "United Arab Emirates", "abu dhabi": "United Arab Emirates",
    "riyadh": "Saudi Arabia", "jeddah": "Saudi Arabia", "dammam": "Saudi Arabia",
    "doha": "Qatar", "kuwait city": "Kuwait", "manama": "Bahrain",
    "amman": "Jordan", "beirut": "Lebanon", "casablanca": "Morocco",
    "berlin": "Germany", "munich": "Germany", "hamburg": "Germany",
    "paris": "France", "amsterdam": "Netherlands", "sydney": "Australia",
    "singapore": "Singapore", "tokyo": "Japan", "seoul": "South Korea",
}

_REMOTE_MARKERS = (
    "remote", "anywhere", "worldwide", "global", "work from home", "wfh",
    "fully remote", "100% remote", "distributed",
)


def _normalise_country(raw):
    if not raw:
        return ""
    low = re.sub(r"[^a-z ]", " ", raw.lower())
    low = re.sub(r"\s+", " ", low).strip()
    if low in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[low]
    return low.title() if low else ""


def _country_hint(raw):
    country = _normalise_country(raw)
    return country if country in _KNOWN_COUNTRIES else ""


def _normalise_city(raw):
    if not raw:
        return ""
    low = raw.split(",")[0].lower()
    low = re.sub(r"[^a-z ]", " ", low)
    low = re.sub(r"\s+", " ", low).strip()
    return low


def _is_remote(location):
    low = (location or "").lower()
    return any(marker in low for marker in _REMOTE_MARKERS)


def _city_country_hint(location):
    if not location:
        return "", ""
    low = re.sub(r"[^a-z ,]", " ", location.lower())
    parts = [p.strip() for p in low.split(",") if p.strip()]
    if parts:
        tail_country = _country_hint(parts[-1])
        if tail_country:
            return _normalise_city(parts[0]), tail_country
        full = " ".join(parts)
        full_country = _country_hint(full)
        if full_country:
            return "", full_country
    single_country = _country_hint(low)
    if single_country:
        return "", single_country
    city = _normalise_city(location)
    if city in _CITY_TO_COUNTRY:
        return city, _CITY_TO_COUNTRY[city]
    return city, ""


def _job_seniority(title):
    """Return 0..3 seniority bucket for a job title (0 entry, 3 clearly senior)."""
    low = (title or "").lower()
    for words, rank in _SENIORITY_PATTERNS:
        if any(re.search(r"\b" + w.replace(".", r"\.") + r"\b", low) for w in words):
            return rank
    return 1  # unmarked -> treat as junior-to-mid


def _student_seniority(skill_levels):
    """Infer a student's career seniority from their skill levels."""
    if not skill_levels:
        return 0  # no skills -> treat as beginner / entry
    vals = [_level_score.get(l, 1) for l in skill_levels]
    avg = sum(vals) / len(vals)
    if avg >= 2.6:
        return 3  # mostly Advanced -> mid/strong
    if avg >= 2.0:
        return 2  # mostly Intermediate -> mid
    if avg >= 1.4:
        return 1  # mixed beginner/intermediate -> junior
    return 0  # mostly Beginner -> entry


_ROLE_FAMILIES = {
    # role family token -> synonyms/role-type words that mark a matching job title
    "engineer": ["engineer", "developer", "software", "programmer", "backend", "frontend", "fullstack", "full-stack"],
    "developer": ["developer", "engineer", "software", "programmer", "cod"],
    "data": ["data", "analyst", "scientist", "analytics", "bi "],
    "scientist": ["scientist", "research", "ml", "machine learning", "ai ", "deep learning"],
    "analyst": ["analyst", "data", "business intelligence", "bi "],
    "cloud": ["cloud", "devops", "aws", "azure", "gcp", "infrastructure"],
    "security": ["security", "cyber", "pentest", "appsec"],
    "design": ["design", "ux", "ui ", "product designer"],
    "marketing": ["marketing", "growth", "seo", "content"],
    "finance": ["finance", "accounting", "financial"],
    "product": ["product", "program"],
    "project": ["project", "program", "delivery"],
    "support": ["support", "helpdesk", "service desk", "it support"],
    "qa": ["qa", "quality", "test"],
    "backend": ["backend", "server-side", "api"],
    "frontend": ["frontend", "front-end", "web", "react", "javascript"],
}

_ROLE_FAMILY_HINTS = [
    "ai", "machine learning", "ml", "data", "software", "developer", "engineer",
    "cloud", "devops", "security", "analyst", "scientist", "fullstack", "backend",
    "frontend", "qa", "product", "design", "web",
]

# Bounded title-token aliases used ONLY to widen the "close target-role match"
# band (never to fabricate exact matches): "AI Engineer" also accepts an ML /
# Machine role title as a close match. Kept deliberately tiny so a generic skill
# word (e.g. Python) can never promote an unrelated role into the same band.
_ROLE_ALIASES = {
    "ai": {"ml", "machine"},
    "ml": {"ai", "machine"},
}

# Dominance bands: target-role title relevance is the #1 ranking signal. A job
# in a higher band can never be outranked by one in a lower band, no matter how
# much skill overlap / verification / freshness the lower one carries. Within a
# band, how closely a title reflects the target role (title_evidence) sorts
# before the numeric score so a "Visual Designer" beats an Adobe-mentioning
# role for a Graphic Designer target.
_TIER_ORDER = {"exact": 0, "close": 1, "family": 2, "none": 3}

# Words that only say WHAT a job is, never WHAT skills it uses. They must not
# count as role-relevant evidence on their own (otherwise "Data Entry Clerk" or
# "Senior Data Analyst" could smuggle into a cybersecurity target's feed).
_GENERIC_TITLE_TOKENS = {
    "analyst", "engineer", "developer", "scientist", "specialist", "manager",
    "consultant", "officer", "clerk", "assistant", "data", "web", "junior",
    "senior", "lead", "head", "director", "coordinator", "associate", "intern",
    "trainee", "representative", "programmer", "architect", "entry",
}


# Generic tail nouns that often end a role-requirement phrase ("Vulnerability
# Management", "Risk Assessment", "Data Analysis"). On their own in a JOB TITLE
# ("Partnership Management", "Strategy") they are meaningless evidence, so they
# never qualify a job — while still contributing to the numeric score.
_TITLE_TAIL_TOKENS = {
    "management", "assessment", "analysis", "administration", "operations",
    "planning", "strategy", "support", "services", "analytics", "monitoring",
    "research", "development", "engineering", "design", "delivery",
}


def _role_family(role):
    """Return the family token(s) for a target role title, used to spot jobs in
    the same discipline even when specific skill keywords are absent.

    Uses a scored best-family match instead of first-synonym-hit so a title like
    "Cybersecurity Analyst" resolves to ``security`` (cybersecurity'S vocabulary)
    rather than ``data`` just because the word "analyst" is shared.
    """
    low = (role or "").lower().replace("-", " ").strip()
    if not low:
        return ""
    toks = {w for w in re.split(r"\s+", low) if w and w not in _STOPWORDS}
    best, best_score = "", 0
    for token, syns in _ROLE_FAMILIES.items():
        score = 0
        if token in toks:
            score += 2
        else:
            for w in toks:
                if token in w or (len(token) >= 3 and token.startswith(w)):
                    score += 3
                    break
        for s in syns:
            s2 = s.strip()
            if s2 in toks:
                score += 2
            elif len(s2) >= 3:
                for w in toks:
                    if s2 in w:
                        score += 1
                        break
        if score > best_score:
            best, best_score = token, score
    if best_score == 0:
        for hint in _ROLE_FAMILY_HINTS:
            if hint in low:
                return hint
    return best


def _term_keywords(skills, role):
    """Keywords used to match a job against the student's profile: skill names
    plus the target-role title fragments."""
    words = []
    for s in skills:
        for part in re.split(r"[/&\s]+", s):
            if 2 <= len(part) <= 24:
                words.append(part.lower())
    if role:
        for part in re.split(r"[/&\s]+", role):
            if len(part) > 2:
                words.append(part.lower())
    return words


# Stop words excluded from skill/role token matching.
_STOPWORDS = {"the", "and", "for", "with", "from", "your", "you", "skills",
              "of", "in", "on", "using", "a", "to", "at", "level"}


def _tokens(text):
    """Lowercased word tokens of a skill/role name (role-relevant vocabulary)."""
    return {w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(w) >= 2 and w not in _STOPWORDS}


def _role_anchor_tokens(role_title, role_requisites=()):
    """The role's identity vocabulary: its title plus every named requirement.

    This is what makes relevance *generalized without hardcoded lists*: for any
    target career, the anchor is wherever that role's own definitions (title +
    required skills, from the platform's role catalog) say it is.
    """
    anchor = _tokens(role_title or "")
    for name in role_requisites or ():
        anchor |= _tokens(name)
    return anchor


def _skill_relevance_to_role(skill_name, role_title, role_requisites=()):
    """0..1: how central an extracted skill is to the student's target career.

    Uses token coverage/Jaccard against the role's identity vocabulary (title +
    required-skill names) plus literal containment against the required-skill
    names. Works the same for any career — cybersecurity, marketing, data
    science, whatever — because the anchor comes from the role itself.
    """
    a = _tokens(skill_name)
    anchor = _role_anchor_tokens(role_title, role_requisites)
    if not a or not anchor:
        return 0.0
    inter = a & anchor
    coverage = len(inter) / len(a)          # how much of the skill is role-vocabulary
    jac = len(inter) / len(a | anchor)      # how distinctive the overlap is
    rel = max(coverage, jac)
    low = (skill_name or "").lower().strip()
    for rn in (role_requisites or ()):
        rl = (rn or "").lower().strip()
        if rl and (rl == low or rl in low or low in rl):
            rel = max(rel, 1.0)
    return rel


_PRIMARY_RELEVANCE = 0.5


def _cluster_keywords(skills, role, role_requisites=()):
    """Split the student's skill names into a role-relevant primary cluster and
    an incidental minor cluster.

    Primary (drives search + score): the target-role title and its required
    skills. These are the career-identity vocabulary — the tokens that define
    which jobs belong to the target career family.

    Minor (tie-breakers only): every extracted CV skill. When a target career
    is set, CV skills are always minor — they rank jobs WITHIN the relevant
    career family but never push unrelated jobs through the relevance gate.
    This prevents generic skill words ("communication", "management", "excel",
    "data analysis") from creating keyword hits on descriptions of jobs from
    completely unrelated fields (Marketing, Sales, Operations) and inflating
    the relevance score above the threshold.

    When no target career is set every skill is primary, preserving the
    original behaviour (multi-skill search without role filtering).
    """
    def add(target, text):
        for w in sorted(_tokens(text)):
            if w not in target:
                target.append(w)
        return target

    def role_tokens(text):
        # Tokenize the chosen target role in its natural title order so the
        # lead search term is the role itself ("Graphic Designer" -> graphic,
        # designer) rather than alphabetical noise or the first CV skill.
        seen = set()
        out = []
        for w in re.split(r"[^a-z0-9]+", (text or "").lower()):
            if len(w) >= 2 and w not in _STOPWORDS and w not in seen:
                seen.add(w)
                out.append(w)
        return out

    primary = []
    minor = []
    if not role:
        for s in skills:
            primary = add(primary, s)
        return primary, minor
    for w in role_tokens(role):
        primary.append(w)
    for name in role_requisites or ():
        primary = add(primary, name)
    # When a target career is set, ALL CV skills are minor keywords — they
    # serve as tie-breakers for ranking within the relevant family but never
    # become primary search/score drivers. This prevents generic skills from
    # creating cross-domain keyword hits that push unrelated jobs through the
    # relevance gate (e.g. "management" matching a Marketing Manager when the
    # target is Cybersecurity Analyst).
    for s in skills:
        minor = add(minor, s)
    return primary, minor


_LOCATION_SCORES = {
    "city": 40,
    "country": 25,
    "market": 25,
    "country_remote": 20,
    "global_remote": 10,
    "unknown": 0,
    "different": -25,
}

_LOCATION_ORDER = {
    "city": 0,
    "country": 1,
    "country_remote": 2,
    "market": 3,
    "global_remote": 4,
    "unknown": 5,
    "different": 6,
}


def _location_score(job, user_country, user_city, market_country=""):
    """Return (tier, score, label) for a job's fit to the student's location.

    ``market_country`` is an optional "remote/relocation search" target — a job
    physically located there ranks with local roles but is labelled as a
    relocation option, never implied to be the student's own country.
    """
    user_country_n = _normalise_country(user_country)
    user_city_n = _normalise_city(user_city)
    job_country_n = _normalise_country(job.get("country") or "")
    job_city_n = _normalise_city(job.get("city") or "")
    remote = bool(job.get("remote"))
    raw_loc = job.get("location") or ""

    if remote:
        if user_country_n and (
            job_country_n == user_country_n or user_country_n.lower() in raw_loc.lower()
        ):
            return "country_remote", _LOCATION_SCORES["country_remote"], f"Remote - {user_country_n}"
        return "global_remote", _LOCATION_SCORES["global_remote"], "Remote"

    if user_city_n and job_city_n and user_city_n == job_city_n:
        return "city", _LOCATION_SCORES["city"], raw_loc or job_city_n.title()

    if user_country_n and job_country_n and user_country_n == job_country_n:
        return "country", _LOCATION_SCORES["country"], raw_loc or user_country_n

    market_n = _normalise_country(market_country)
    if market_n and job_country_n and job_country_n == market_n:
        return "market", _LOCATION_SCORES["market"], f"Relocation search · {raw_loc or job_country_n}"

    if job_country_n:
        if user_country_n and job_country_n != user_country_n:
            return "different", _LOCATION_SCORES["different"], job_country_n
        return "unknown", _LOCATION_SCORES["unknown"], job_country_n

    return "unknown", _LOCATION_SCORES["unknown"], raw_loc or "Location not listed"


def _title_words(title):
    return set(re.split(r"[^a-z0-9]+", (title or "").lower()))


def _score_job(job, keywords, student_seniority, country, city="", role_family="",
               minor_keywords=(), market_country="", role_driven=False,
               verified_skills=(), role_title=""):
    """Compute 0-100 fit score, reason, relevance, tier, and location metadata.

    ``keywords`` are the role-relevant primary cluster (role title + required
    skills + CV skills that relate to the role); ``minor_keywords`` are every
    other extracted CV skill. Under ``role_driven`` (a target career is set),
    only role-relevant hits can make a job relevant — a stray merge with
    incidental skills (e.g. "excel" on an admin role) can never push it above
    genuinely on-target jobs; it only earns a capped tie-breaker.

    ``role_title`` is the student's target role title. When present it drives
    the *dominance tier* (see ``_TIER_ORDER``): exact title match > close title
    match > broader family > skill-overlap only. A job in a higher band can
    never be outranked by one in a lower band no matter how much skill overlap,
    verification, or freshness the lower one carries.

    ``verified_skills`` (lowercased skill names the student has actually
    verified) earn a SMALL relevance/evidence boost on top of matched
    role-relevant skills — never enough to overpower target-role relevance.
    Job freshness (``listed_days_ago``) adds a small recency boost.

    Returns ``(score, reason, relevant, loc_tier, loc_label, tier,
    title_evidence)``.
    """
    title = (job.get("title", "") or "")
    haystack = (f"{title} {' '.join(job.get('tags') or [])} "
                f"{job.get('description') or ''} "
                f"{job.get('location', '')}").lower()
    tlow = title.lower()
    twords = _title_words(title)

    hits = 0
    matched = []
    for kw in keywords:
        if kw and kw in haystack:
            hits += 1
            matched.append(kw)
    title_hits = [kw for kw in keywords if kw and kw in twords]
    minor_hits = [kw for kw in minor_keywords if kw and kw in haystack]
    verified = {str(s).lower() for s in (verified_skills or ())}
    verified_hits = [kw for kw in matched if kw in verified]

    # Relevance (primary numeric signal) — base points, driven by the role's
    # own vocabulary only.
    relevance = min(56, hits * 14)
    family = role_family
    title_family_hit = False
    if family:
        syns = [
            s.strip() for s in _ROLE_FAMILIES.get(family, [family])
        ]
        if role_driven:
            # Never let a generic job word (analyst, data, clerk…) stand in for
            # the target career's actual vocabulary when gating relevance.
            role_vocab = set(keywords)
            syns = [s for s in syns if s and s not in _GENERIC_TITLE_TOKENS and _tokens(s) & role_vocab]
        if any(s in (" " + tlow) or s and s in tlow for s in syns):
            title_family_hit = True
            relevance += 24
    if title_family_hit:
        relevance = min(70, relevance)
    # A few named role-relevant hits on real tech stack words push a family match to the top.
    if title_family_hit and relevance >= 40:
        relevance = min(80, relevance + 6)
    # Without a family title, explicit role-relevant words in the title still count.
    if not title_family_hit and title_hits:
        relevance = max(relevance, min(60, 18 + len(title_hits) * 18))
    # Incidental (minor) skills: capped tie-breaker only — never the primary signal.
    relevance = min(90, relevance + min(8, len(minor_hits) * 2))
    # Verified-skills evidence boost — small, and only on role-relevant
    # (primary-cluster) hits, so a verified "Docker" can never lift an off-target
    # DevOps role above the student's chosen Graphic Designer target.
    relevance = min(94, relevance + min(6, len(verified_hits) * 3))
    # Freshness: recently posted live roles earn a minor recency edge.
    fresh = job.get("listed_days_ago")
    fresh_note = ""
    if fresh is not None and relevance > 0:
        relevance = min(96, relevance + min(4, max(0, 4 - int(fresh))))
        fresh_note = f" Posted {int(fresh)}d ago."

    # Experience-level fit.
    job_sen = _job_seniority(title)
    if job_sen > student_seniority:
        exp = 0
    elif job_sen == student_seniority:
        exp = 20
    else:
        exp = 12

    loc_tier, loc_score, loc_label = _location_score(job, country, city, market_country)
    score = max(0, min(100, int(round(relevance + exp + loc_score))))

    # ---- Dominance tier (target-role title relevance > skills > verification) ----
    # Only title identity decides the band; a generic skill hit (python, docker…)
    # can never promote a substantially different role into an upper band. The
    # classification comes from the shared role-intent helper, so the gate is
    # identical everywhere (ESCO + live jobs) and career-agnostic.
    rel_class = None
    if role_title:
        rel_class = role_intent.classify_title(role_title, title)
        tier = {"EXACT": "exact", "CLOSE": "close", "FAMILY": "family"}.get(rel_class, "none")
    else:
        tier = "none"
    # Title evidence drives intra-band ordering: how much of the target's own
    # domain vocabulary appears in the job title.
    title_evidence = 0.0
    if rel_class:
        rt = set(role_intent.domain_tokens(role_title))
        shared = rt & twords
        title_evidence = (float(len(shared))
                          + (0.5 if rel_class == "CLOSE" and shared else 0.0)
                          + (0.0 if rel_class == "FAMILY" else 0.0))
    # A family-title hit (same canonical career, different specialization) is
    # still a legitimate broader-field match.
    title_family_hit = rel_class in ("FAMILY", "CLOSE", "EXACT")

    # ---- Seniority penalty (conservative) ----
    # Clearly-senior/leadership titles (director, head, manager…) are capped for
    # entry-level students. Target-role title dominance still wins: bands are
    # decided first, so this only re-shapes ordering *within* a band.
    if student_seniority == 0 and job_sen > 1:
        score = min(score, 15)

    # ---- Explainable reason derived from the components actually used ----
    if job_sen > student_seniority:
        if tier in ("exact", "close"):
            reason = "Strong title match, but labeled more senior than your current level — listed for context."
        elif student_seniority == 0:
            reason = "This is a mid/senior role; not a fit for your experience yet."
        else:
            reason = "Labeled more senior than your current level — listed for context."
    elif tier == "exact":
        reason = "Target role closely matches your career title."
    elif tier == "close":
        reason = "Closely aligned with your target career title."
    elif tier == "family":
        reason = "Matches your target career's broader field."
    else:
        if matched:
            reason = f"Uses skills your target career needs ({', '.join(matched[:3])})."
        else:
            reason = "Low overlap with your target career."
    if tier in ("exact", "close") and matched:
        reason += f" Key skills: {', '.join(matched[:3])}."
    if loc_label:
        reason += f" Location: {loc_label}."
    if verified_hits:
        reason += (f" {len(verified_hits)} matched skill"
                   f"{'s' if len(verified_hits) > 1 else ''} verified.")
    if fresh_note:
        reason += fresh_note
    # Relevance gate. With a target career set, a job survives ONLY when its
    # title carries real career evidence for that target (EXACT / CLOSE / FAMILY
    # per the shared role-intent classifier). Generic skill words and broad
    # required-skill terms ("risk", "incident", "communication", "management")
    # never qualify a job on their own — otherwise a Data Scientist mentioning
    # "risk" or a Marketing manager mentioning "communication" would flood a
    # cybersecurity target's feed. Incidental skills are capped tie-breakers only.
    #
    # The gate requires evidence from the ROLE'S OWN VOCABULARY (title +
    # required skills), not from generic CV skills that appear in descriptions
    # of unrelated jobs. When a target role is set, CV skills are always minor
    # keywords (see _cluster_keywords), so they contribute to the numeric score
    # but cannot independently push a job through the relevance threshold.
    if role_driven:
        if role_title:
            relevant = rel_class in ("EXACT", "CLOSE", "FAMILY")
        else:
            # Degraded callers that pass only a role_family (no title): fall back
            # to a family-title or role-vocabulary hit gate. Production always
            # passes role_title, so the strict intent gate is the normal path.
            relevant = bool(title_family_hit) or hits >= 2
    else:
        relevant = bool(title_family_hit) or hits >= 2
    # FAMILY-tier override: a job classified FAMILY by the role-intent
    # classifier belongs to the same career family (e.g. "Security Analyst"
    # for a "Cybersecurity Analyst" target). However, the override is only
    # applied when the job demonstrates at least one primary keyword hit from
    # the role's own vocabulary — this prevents completely unrelated jobs
    # (zero role-vocabulary overlap) from being rescued by the family
    # classification alone, which can happen when generic CV keywords
    # ("management", "communication") appear in the job's description but
    # the title has no real connection to the target career.
    if tier == "family" and not relevant:
        relevant = hits >= 1
    return score, reason, relevant, loc_tier, loc_label, tier, title_evidence


def _parse_listing_date(raw):
    """Best-effort parse of a listing date to a ``datetime.date``.

    Accepts ISO dates/timestamps (``YYYY-MM-DD...``), epoch seconds (int,
    float, or numeric string), and ``YYYY-MM-DD HH:MM:SS`` serializations.
    Returns ``None`` when the value is missing or unparseable.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc).date()
        except Exception:
            return None
    s = str(raw).strip()
    if not s:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            return None
    if s.replace(".", "", 1).isdigit():
        try:
            return datetime.fromtimestamp(float(s), tz=timezone.utc).date()
        except Exception:
            return None
    return None


def _expiry_props(raw, listed_date):
    """Derive ``(is_expired, expires_at, listed_days_ago)`` for one listing.

    Authoritative liveness signals are used first, when the provider exposes
    them:
      - JSearch ``job_expired_flag`` -> ``raw["expired"]``
      - Arbeitnow ``available`` boolean
      - USAJobs ``PositionCloseDate`` / ``ApplicationCloseDate``, else the
        RemoteOK ``expires`` timestamp

    Otherwise the provenance is only a posted date, so the staleness heuristic
    applies: listings posted more than ``MAX_LISTING_AGE_DAYS`` ago are treated
    as expired.
    """
    listed_days_ago = None
    if listed_date:
        listed_days_ago = max(0, (date.today() - listed_date).days)
    expired_flag = raw.get("expired")
    available = raw.get("available")
    close_date = _parse_listing_date(raw.get("close_date"))
    expires = _parse_listing_date(raw.get("expires"))
    # JSearch job_expired_flag is a string ("expired" / "not_expired"), not a bool.
    expired_truthy = str(expired_flag).strip().lower() in {"true", "expired", "1", "yes"}
    if expired_truthy:
        is_expired, expires_at = True, None
    elif available is False:
        is_expired, expires_at = True, None
    elif close_date:
        is_expired, expires_at = close_date < date.today(), close_date.isoformat()
    elif expires:
        is_expired, expires_at = expires < date.today(), expires.isoformat()
    elif listed_days_ago is not None and listed_days_ago > MAX_LISTING_AGE_DAYS:
        is_expired, expires_at = True, None
    else:
        is_expired, expires_at = False, None
    return is_expired, expires_at, listed_days_ago


def _merge(raw_jobs):
    """Normalise + dedupe raw listings from all feeds into one list."""
    # Known-dead job URLs (user-reported or provably 404) — hard blocklist
    _DEAD_JOB_URLS = {
        "https://bebee.com/eg/jobs/cyber-security-analyst-ssh-design-nasr-city--fj-2328815129",
    }
    merged = {}
    _pop_index = {}
    for j in raw_jobs:
        title = (j.get("title") or "").strip()
        company = (j.get("company") or j.get("company_name") or "Unknown company").strip()
        url = j.get("url") or j.get("link") or ""
        if not title or not url or url in _DEAD_JOB_URLS:
            continue
        tags = [t for t in (j.get("tags") or []) if isinstance(t, str) and t.strip()][:6]
        location = (j.get("location") or j.get("candidate_required_location") or "").strip()
        city, country = _city_country_hint(location)
        explicit_country = _normalise_country(j.get("country") or "")
        if explicit_country:
            country = explicit_country
        if not country:
            for tag in tags:
                country = _country_hint(tag)
                if country:
                    break
        date = j.get("date") or j.get("publication_date") or ""
        if isinstance(date, int):
            date = time.strftime("%Y-%m-%d", time.gmtime(date))
        listed_date = _parse_listing_date(date)
        is_expired, expires_at, listed_days_ago = _expiry_props(j, listed_date)
        item = {"title": title, "company": company, "url": url,
                "date": date, "location": location, "country": country,
                "city": city, "remote": bool(j.get("remote")) or _is_remote(location),
                "tags": tags, "source": j.get("source", ""),
                "is_expired": is_expired, "expires_at": expires_at,
                "listed_days_ago": listed_days_ago}
        # Canonical enrichment (never fabricated — empty means unknown).
        item["description"] = _clean_text(
            j.get("description") or j.get("snippet") or j.get("jobExcerpt")
            or j.get("jobDescription") or j.get("position_summary") or "")
        item["source_url"] = url
        item["source"] = j.get("source", "")
        item["id"] = _job_id(item["source"], url, title, company)
        item["employment_type"] = _clean_text(j.get("employment_type") or "")[:24]
        item["workplace_type"] = _workplace_type(item)
        item["salary"] = _clean_text(j.get("salary") or "")
        item["required_skills"] = _extract_required_skills(item)

        def richness(x):
            return (2 if x.get("description") else 0) + \
                   (2 if x.get("salary") else 0) + \
                   (1 if x.get("employment_type") else 0) + \
                   min(3, len(x.get("tags") or []))

        def prefer(prev, new):
            if not prev:
                return new
            if richness(new) < richness(prev):
                return prev
            merged_item = dict(new)
            merged_item["tags"] = list(dict.fromkeys(
                (prev.get("tags") or []) + (new.get("tags") or [])))[:6]
            merged_item["description"] = new.get("description") or prev.get("description") or ""
            merged_item["salary"] = new.get("salary") or prev.get("salary") or ""
            merged_item["employment_type"] = new.get("employment_type") or prev.get("employment_type") or ""
            merged_item["workplace_type"] = new.get("workplace_type") or prev.get("workplace_type") or ""
            merged_item["is_expired"] = new.get("is_expired") or prev.get("is_expired")
            merged_item["expires_at"] = new.get("expires_at") or prev.get("expires_at")
            merged_item["required_skills"] = _extract_required_skills(merged_item)
            return merged_item

        # Dedupe the same apply link (one vacancy surfaced by two providers),
        # then a conservative title + company + location identity. Different
        # vacancies with similar titles are never merged just because titles
        # look alike — the location/company identity must agree.
        loc_key = (_normalise_city(location) + "|"
                   + _normalise_country(country).lower())
        pop_key = (title + "|" + company + "|" + loc_key).lower()
        node_key = ("u:" + url.lower()) if url else None
        dest = None
        if node_key and node_key in merged:
            dest = node_key
        elif pop_key in merged:
            dest = pop_key
        elif pop_key in _pop_index:
            dest = _pop_index[pop_key]
        elif node_key:
            dest = node_key
        else:
            dest = pop_key
        merged[dest] = prefer(merged.get(dest), item)
        _pop_index[pop_key] = dest
    # newest first by date, best-effort
    return sorted(merged.values(),
                  key=lambda j: j["date"] or "", reverse=True)


def _fetch_remotive(n):
    jobs = []
    try:
        resp = httpx.get(REMOTIVE_URL, params={"limit": n},
                         headers=_HEADERS, timeout=12)
        resp.raise_for_status()
        for j in (resp.json().get("jobs") or [])[:n]:
            location = (j.get("candidate_required_location") or "").strip()
            tags = [t for t in (j.get("tags") or []) if isinstance(t, str) and t.strip()]
            jobs.append({"title": j.get("title"), "company": j.get("company_name"),
                         "url": j.get("url"), "date": j.get("publication_date"),
                         "location": location, "tags": tags, "source": "Remotive",
                         "employment_type": j.get("job_type") or "",
                         "salary": j.get("salary") or ""})
        _record_status("Remotive", "ok", len(jobs))
    except Exception as exc:
        _record_status("Remotive", "failed", 0, reason="network_error", error=str(exc))
        logger.warning("job provider Remotive failed: %s", _redact(exc))
    return jobs


def _fetch_remoteok(n):
    jobs = []
    try:
        resp = httpx.get(REMOTEOK_URL, headers=_HEADERS, timeout=12)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            data = data.get("jobs", []) or []
        for j in (data or [])[:n]:
            tags = [t for t in (j.get("tags") or []) if isinstance(t, str) and t.strip()]
            jobs.append({"title": j.get("position"), "company": j.get("company"),
                         "url": j.get("url"), "date": j.get("date"),
                         "location": j.get("location"), "tags": tags,
                         "expires": j.get("expires"),
                         "description": j.get("description") or "",
                         "source": "RemoteOK"})
        _record_status("RemoteOK", "ok", len(jobs))
    except Exception as exc:
        _record_status("RemoteOK", "failed", 0, reason="network_error", error=str(exc))
        logger.warning("job provider RemoteOK failed: %s", _redact(exc))
    return jobs


def _fetch_adzuna(n, keywords, country):
    """Fetch Adzuna listings only when credentials are configured AND the
    requested country is supported. An unsupported country (e.g. Egypt) marks
    Adzuna as ``skipped`` with reason ``unsupported_country`` and returns no
    jobs — it is never silently converted to another country's feed."""
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        _skip_status("Adzuna", "no_credentials")
        return []

    country_map = {
        "united states": "us", "united kingdom": "gb", "canada": "ca",
        "australia": "au", "india": "in", "germany": "de", "france": "fr",
        "netherlands": "nl", "south africa": "za", "singapore": "sg",
        "new zealand": "nz", "italy": "it", "spain": "es", "switzerland": "ch",
        "austria": "at", "belgium": "be", "brazil": "br", "mexico": "mx",
        "poland": "pl",
    }
    norm = _normalise_country(country)
    if norm not in _ADZUNA_SUPPORTED:
        _skip_status("Adzuna", "unsupported_country")
        return []
    cc = country_map.get(norm.lower(), "gb")
    # Adzuna's `what` is AND-combined, so long multi-term strings often return
    # zero results. Clamp to the first 3 terms; if that still returns nothing,
    # retry with just the first term (usually the role title fragment).
    what_queries = []
    if keywords:
        what_queries.append(" ".join(keywords[:3]))
        what_queries.append(keywords[0])
    jobs = []
    ok = False
    last_error = ""
    for what in what_queries:
        try:
            resp = httpx.get(
                f"{ADZUNA_BASE}/{cc}/search/1",
                params={
                    "app_id": app_id,
                    "app_key": app_key,
                    "what": what,
                    "results_per_page": min(n, 50),
                    "content-type": "application/json",
                },
                headers=_HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            for j in (resp.json().get("results") or [])[:n]:
                tags = []
                category = j.get("category") or {}
                company = j.get("company") or {}
                if category.get("label"):
                    tags.append(category["label"])
                if company.get("display_name"):
                    tags.append(company["display_name"])
                jobs.append({
                    "title": j.get("title"),
                    "company": company.get("display_name", "Unknown company"),
                    "url": j.get("redirect_url"),
                    "date": j.get("created"),
                    "location": (j.get("location") or {}).get("display_name", ""),
                    "country": cc.upper(),
                    "tags": tags,
                    "description": j.get("description") or "",
                    "employment_type": (j.get("contract_time") or j.get("contract_type") or "").replace("_", " "),
                    "salary": _salary_str(j.get("salary_min"), j.get("salary_max"))
                              + (" (est.)" if j.get("salary_is_predicted") else ""),
                    "source": "Adzuna",
                })
            ok = True
            if jobs:
                break
        except Exception as exc:
            last_error = str(exc)
    _record_status("Adzuna", "ok" if ok else "failed", len(jobs),
                   reason="" if ok else "request_failed", error=last_error)
    if not ok:
        logger.warning("job provider Adzuna failed: %s", _redact(last_error))
    return jobs


def _fetch_jobicy(n):
    """Remote-first job board; free public API, no key required."""
    jobs = []
    try:
        resp = httpx.get(JOBICY_URL, params={"count": min(max(n, 5), 50)},
                         headers=_HEADERS, timeout=12)
        resp.raise_for_status()
        for j in (resp.json().get("jobs") or [])[:n]:
            tags = list((j.get("jobIndustry") or []) + (j.get("jobType") or []))
            level = (j.get("jobLevel") or "")
            if level:
                tags.append(level)
            jobs.append({
                "title": j.get("jobTitle"),
                "company": j.get("companyName"),
                "url": j.get("url"),
                "date": (j.get("pubDate") or "")[:10],
                "location": (j.get("jobGeo") or "").strip() or "Remote",
                "tags": tags,
                "description": j.get("jobDescription") or j.get("jobExcerpt") or "",
                "employment_type": " ".join(j.get("jobType") or []),
                "source": "Jobicy",
            })
        _record_status("Jobicy", "ok", len(jobs))
    except Exception as exc:
        _record_status("Jobicy", "failed", 0, reason="network_error", error=str(exc))
        logger.warning("job provider Jobicy failed: %s", _redact(exc))
    return jobs


def _fetch_arbeitnow(n):
    """ATS-sourced listings (Greenhouse, SmartRecruiters, Join, etc.); free,
    no key required."""
    jobs = []
    try:
        resp = httpx.get(ARBEITNOW_URL, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        for j in (resp.json().get("data") or [])[:n]:
            loc = (j.get("location") or "").strip()
            if not loc and j.get("remote"):
                loc = "Remote"
            tags = list((j.get("job_types") or []) + (j.get("tags") or []))
            jobs.append({
                "title": j.get("title"),
                "company": j.get("company_name"),
                "url": j.get("url"),
                "date": j.get("created_at") or "",
                "location": loc,
                "tags": tags,
                "available": j.get("available"),
                "description": j.get("description") or "",
                "employment_type": " ".join(j.get("job_types") or []),
                "source": "Arbeitnow",
            })
        _record_status("Arbeitnow", "ok", len(jobs))
    except Exception as exc:
        _record_status("Arbeitnow", "failed", 0, reason="network_error", error=str(exc))
        logger.warning("job provider Arbeitnow failed: %s", _redact(exc))
    return jobs


def _fetch_jooble(n, keywords, country=""):
    """Country-scoped aggregation of local boards; JOOBLE_API_KEY required.
    Optional provider: when Jooble's API is unreachable it degrades to a no-op
    exactly like a missing key -- the live feed never depends on it."""
    key = os.environ.get("JOOBLE_API_KEY")
    if not key:
        _skip_status("Jooble", "no_credentials")
        return []
    what = " ".join(keywords[:5]) if keywords else ""
    jobs = []
    ok = False
    last_error = ""
    try:
        resp = httpx.post(f"{JOOBLE_BASE}/{key}",
                          json={"keywords": what, "location": country or ""},
                          headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        for j in (resp.json().get("jobs") or [])[:n]:
            tags = ((j.get("type") or "") + " " + (j.get("source") or "")).split()
            jobs.append({
                "title": j.get("title"),
                "company": j.get("company"),
                "url": j.get("link"),
                "date": j.get("pubdate") or j.get("updated") or "",
                "location": (j.get("location") or "").strip() or "Remote",
                "tags": tags,
                "description": j.get("snippet") or "",
                "employment_type": j.get("type") or "",
                "salary": j.get("salary") or "",
                "source": "Jooble",
            })
        ok = True
    except Exception as exc:
        last_error = str(exc)
    _record_status("Jooble", "ok" if ok else "failed", len(jobs),
                   reason="" if ok else "network_unreachable", error=last_error)
    if not ok:
        logger.warning("job provider Jooble failed (optional): %s", _redact(last_error))
    return jobs


# ---------------------------------------------------------------------------
# RapidAPI job-search providers (LinkedIn, Google Jobs). Host-gated: the exact
# subscribed host is configured via env, never guessed. All three RapidAPI
# apps share RAPIDAPI_KEY unless a provider-specific override is set.
# ---------------------------------------------------------------------------
def _rapidapi_key(provider_env):
    """Provider-specific RapidAPI key, falling back to the shared account key."""
    return os.environ.get(provider_env) or os.environ.get("RAPIDAPI_KEY")


def _provider_rapidapi_cfg(host_env, path_env, key_env, name):
    """Resolve (host, path, key) for a RapidAPI job provider from env.

    Only returns non-empty when BOTH the exact subscribed host and a key are
    configured; otherwise records an honest skip so the provider shows up as
    ``host_not_configured`` / ``no_credentials`` (never guessed, never tried).
    """
    host = os.environ.get(host_env, "").strip().lower()
    path = os.environ.get(path_env, "").strip()
    key = _rapidapi_key(key_env)
    if not host:
        _skip_status(name, "host_not_configured")
        return "", "", ""
    if not key:
        _skip_status(name, "no_credentials")
        return "", "", ""
    return host, path, key


def _job_field(item, *names):
    """First non-empty value from any of the common provider key spellings."""
    for n in names:
        v = item.get(n)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            v = str(v)
        elif isinstance(v, str):
            v = v.strip()
        if v:
            return v
    return ""


def _extract_job_items(payload):
    """Best-effort location of the job list in a RapidAPI job response.

    Aggregators wrap jobs differently (``data.jobs``, ``data:[...]``,
    ``jobs:[...]``, ``results``...). This flexible finder avoids assuming one
    specific schema; each item is then mapped field-by-field via _job_field.
    """
    if not isinstance(payload, dict):
        return []
    for key in ("jobs", "results", "items", "result", "data"):
        v = payload.get(key)
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            return v
        if isinstance(v, dict):
            for sub in ("jobs", "results", "items", "data"):
                sv = v.get(sub)
                if isinstance(sv, list) and sv and all(isinstance(x, dict) for x in sv):
                    return sv
    return []


def _fetch_rapidapi_jobs(name, host_env, path_env, key_env, n, keywords, country=""):
    """Shared RapidAPI job-search adapter with the existing provider contract.

    Returns provider-normalised listings (the same shape JSearch/Jooble emit),
    records health, handles timeouts / 429 rate limits / auth errors, and never
    raises. One provider failing never affects the unified feed.
    """
    host, path, key = _provider_rapidapi_cfg(host_env, path_env, key_env, name)
    if not host:
        return []
    query = " ".join(keywords[:5]) if keywords else ""
    if path.startswith("/"):
        url = f"https://{host}{path}"
    else:
        url = f"https://{host}/{path}"
    jobs = []
    try:
        resp = httpx.get(
            url,
            params={"query": query, "location": country or ""},
            headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": host, **_HEADERS},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        items = _extract_job_items(payload)
        # Some APIs surface auth/plan errors as a 200 body with a message and
        # no job list — that is a provider failure, not a healthy empty result.
        body_message = str((payload.get("message") or payload.get("error") or ""))[:120] \
            if isinstance(payload, dict) else ""
        if body_message and not items:
            _record_status(name, "failed", 0, reason="request_failed", error=body_message)
            logger.warning("job provider %s failed (optional): %s", name, _redact(body_message))
            return []
        for it in items[:n]:
            title = _job_field(it, "job_title", "jobTitle", "title",
                               "position", "position_title", "positionTitle")
            url2 = _job_field(it, "job_apply_link", "job_google_link", "url",
                              "link", "external_url", "job_url", "apply_url",
                              "jobPostingUrl", "source_url")
            if not title or not url2:
                continue
            loc = _job_field(it, "job_location", "job_city", "location",
                             "city", "formattedLocation", "formatted_location",
                             "locality")
            is_remote = bool(it.get("job_is_remote") or it.get("remote") or it.get("isRemote"))
            if not loc:
                loc = "Remote" if is_remote else ""
            date = (_job_field(it, "job_posted_at_datetime_utc", "job_posted_at",
                               "posted_at", "posted_date", "publication_date",
                               "date", "publishDate", "createdAt") or "")[:10]
            jobs.append({
                "title": title,
                "company": _job_field(it, "employer_name", "company_name",
                                      "company", "companyName",
                                      "hiring_organization", "organizationName",
                                      "organization") or "Unknown company",
                "url": url2,
                "date": date,
                "location": loc,
                "country": _job_field(it, "job_country", "country"),
                "tags": [],
                "remote": is_remote,
                "expired": False,
                "description": _job_field(it, "job_description", "description",
                                          "summary", "snippet", "jobExcerpt",
                                          "position_summary"),
                "employment_type": _job_field(it, "job_employment_type",
                                              "employment_type", "job_type",
                                              "type", "work_type", "workType"),
                "salary": _job_field(it, "salary", "salaryRange", "compensation",
                                     "salary_min", "job_min_salary"),
                "source": name,
            })
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        detail = f"{code} {exc.response.text[:80]}"
        if code == 429:
            _record_status(name, "failed", 0, reason="rate_limited", error=detail)
            logger.warning("job provider %s rate limited: %s", name, _redact(detail))
        else:
            _record_status(name, "failed", 0, reason="request_failed", error=detail)
            logger.warning("job provider %s failed (optional): %s", name, _redact(detail))
        return []
    except httpx.TimeoutException as exc:
        _record_status(name, "failed", 0, reason="network_unreachable", error=str(exc))
        logger.warning("job provider %s failed (optional): %s", name, _redact(exc))
        return []
    except Exception as exc:
        _record_status(name, "failed", 0, reason="request_failed", error=str(exc))
        logger.warning("job provider %s failed (optional): %s", name, _redact(exc))
        return []
    _record_status(name, "ok", len(jobs))
    return jobs


def _fetch_linkedin_jobs(n, keywords, country=""):
    """LinkedIn Job Search via RapidAPI. Exact host + path are config-driven
    (LINKEDIN_JOBS_HOST / LINKEDIN_JOBS_PATH) — the API host is never guessed.
    Key: RAPIDAPI_LINKEDIN_KEY, falling back to RAPIDAPI_KEY."""
    return _fetch_rapidapi_jobs("LinkedIn", "LINKEDIN_JOBS_HOST", "LINKEDIN_JOBS_PATH",
                                "RAPIDAPI_LINKEDIN_KEY", n, keywords, country)


def _fetch_google_jobs(n, keywords, country=""):
    """Google Jobs via RapidAPI. Exact host + path are config-driven
    (GOOGLE_JOBS_HOST / GOOGLE_JOBS_PATH) — the API host is never guessed.
    Key: RAPIDAPI_GOOGLE_JOBS_KEY, falling back to RAPIDAPI_KEY."""
    return _fetch_rapidapi_jobs("Google Jobs", "GOOGLE_JOBS_HOST", "GOOGLE_JOBS_PATH",
                                "RAPIDAPI_GOOGLE_JOBS_KEY", n, keywords, country)


# Canonical country name -> ISO 3166-1 alpha-2, used by the JSearch v5 API's
# ``country`` parameter (JSearch only accepts two-letter ISO codes, not free
# text like "Egypt"). See _JSEARCH_COUNTRY_PARAM.
_JSEARCH_ISO2 = {
    "United States": "us", "United Kingdom": "gb", "United Arab Emirates": "ae",
    "Saudi Arabia": "sa", "Canada": "ca", "India": "in", "Germany": "de",
    "France": "fr", "Netherlands": "nl", "Australia": "au", "Egypt": "eg",
    "Qatar": "qa", "Kuwait": "kw", "Bahrain": "bh", "Oman": "om",
    "Jordan": "jo", "Lebanon": "lb", "Morocco": "ma", "Algeria": "dz",
    "Tunisia": "tn", "Brazil": "br", "Mexico": "mx", "Italy": "it",
    "Spain": "es", "Ireland": "ie", "Poland": "pl", "Sweden": "se",
    "Denmark": "dk", "Norway": "no", "Finland": "fi", "Switzerland": "ch",
    "Austria": "at", "Belgium": "be", "Japan": "jp", "South Korea": "kr",
    "China": "cn", "Singapore": "sg", "Malaysia": "my", "Indonesia": "id",
    "Philippines": "ph", "Vietnam": "vn", "Thailand": "th",
    "Argentina": "ar", "Chile": "cl", "Colombia": "co",
    "South Africa": "za", "Nigeria": "ng", "Kenya": "ke",
    "Pakistan": "pk", "Bangladesh": "bd", "Turkey": "tr",
}


def _jsearch_country_param(country):
    """Best-effort ISO alpha-2 for the JSearch v5 ``country`` parameter."""
    if not country:
        return ""
    iso = _JSEARCH_ISO2.get(_normalise_country(country))
    if iso:
        return iso
    low = re.sub(r"[^a-z]", "", country.lower())
    return low if len(low) == 2 else ""


def _fetch_jsearch(n, keywords, country=""):
    """RapidAPI JSearch v5 aggregator — broad international/MENA coverage.
    Enables Egypt/Middle-East searches (e.g. ``country="Egypt"``) that
    Adzuna/Arbeitnow can't serve well. Requires JSEARCH_API_KEY (or
    RAPIDAPI_KEY); otherwise a no-op. v5 returns ``data: {jobs: [...],
    cursor}`` (a legacy ``data: [...]`` is also tolerated)."""
    key = os.environ.get("JSEARCH_API_KEY") or os.environ.get("RAPIDAPI_KEY")
    if not key:
        _skip_status("JSearch", "no_credentials")
        return []
    query = " ".join(keywords[:3]) if keywords else ""
    jobs = []
    ok = False
    last_error = ""
    try:
        # language=en is required: without it JSearch auto-selects "ar" for
        # Egypt/UAE markets and returns zero results for otherwise-available
        # regional listings (e.g. "dentist" in ae/eg).
        params = {"query": query, "page": 1, "num_pages": 1, "date_posted": "all", "language": "en"}
        iso = _jsearch_country_param(country)
        if iso:
            params["country"] = iso
        elif country:
            params["location"] = country
        resp = httpx.get(
            JSEARCH_URL, params=params, timeout=20,
            headers={
                "X-RapidAPI-Key": key,
                "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
                **_HEADERS,
            },
        )
        resp.raise_for_status()
        data = resp.json().get("data") or {}
        if isinstance(data, dict):
            items = data.get("jobs") or []
        elif isinstance(data, list):
            items = data
        else:
            items = []
        for j in items[:n]:
            city = (j.get("job_city") or "").strip()
            st = (j.get("job_state") or "").strip()
            ctry = (j.get("job_country") or "").strip()
            raw_loc = (j.get("job_location") or "").strip()
            parts = [p for p in (city, st, ctry) if p]
            is_remote = j.get("job_is_remote") is True
            loc = ", ".join(parts) if parts else (raw_loc or ("Remote" if is_remote else ""))
            emp_types = [t for t in (j.get("job_employment_types") or []) if isinstance(t, str) and t]
            emp = str(j.get("job_employment_type") or "").strip()
            if not emp and emp_types:
                emp = emp_types[0]
            tags = [t.replace("_", " ").title() for t in emp_types]
            if emp and emp.title() not in tags:
                tags.append(emp.title())
            if j.get("job_publisher"):
                tags.append(j["job_publisher"])
            jobs.append({
                "title": j.get("job_title"),
                "company": j.get("employer_name"),
                "url": j.get("job_apply_link") or j.get("job_google_link"),
                "date": ((j.get("job_posted_at_datetime_utc") or j.get("job_posted_at") or "") or "")[:10],
                "location": loc,
                "country": ctry,
                "remote": is_remote,
                "tags": tags[:6],
                "expired": j.get("job_expired_flag"),
                "description": j.get("job_description") or "",
                "employment_type": emp.title() if emp else "",
                "salary": _salary_str(j.get("job_min_salary"), j.get("job_max_salary"),
                                      j.get("job_salary_currency"), j.get("job_salary_period")),
                "source": "JSearch",
            })
        ok = True
    except Exception as exc:
        last_error = str(exc)
    _record_status("JSearch", "ok" if ok else "failed", len(jobs),
                   reason="" if ok else "request_failed", error=last_error)
    if not ok:
        logger.warning("job provider JSearch failed: %s", _redact(last_error))
    return jobs


def _fetch_usajobs(n, keywords, country=""):
    """US federal job postings; USAJOBS_API_KEY required. Only queried for US
    students (or when no country is known) so non-US feeds stay relevant."""
    key = os.environ.get("USAJOBS_API_KEY")
    if not key:
        _skip_status("USAJobs", "no_credentials")
        return []
    if country and _normalise_country(country) != "United States":
        _skip_status("USAJobs", "unsupported_country")
        return []
    what = " ".join(keywords[:5]) if keywords else ""
    jobs = []
    ok = False
    last_error = ""
    try:
        resp = httpx.get(
            USAJOBS_URL,
            params={"Keyword": what, "ResultsPerPage": min(max(n, 1), 100)},
            headers={
                "Host": "data.usajobs.gov",
                "User-Agent": "SkillBridgeJobs@skillbridge.local",
                "Authorization-Key": key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        items = (resp.json().get("SearchResult") or {}).get("SearchResultItems") or []
        for it in items[:n]:
            d = it.get("MatchedObjectDescriptor") or {}
            locs = [x.get("LocationName") for x in (d.get("PositionLocation") or [])]
            locs = [l for l in locs if l]
            # usaJobs nests a JobSummary under UserArea.Details.
            summary = (((d.get("UserArea") or {}).get("Details") or {}) or {}).get("JobSummary") or ""
            jobs.append({
                "title": d.get("PositionTitle"),
                "company": d.get("OrganizationName"),
                "url": d.get("PositionURI") or d.get("ApplyURI"),
                "date": d.get("PositionStartDate") or d.get("PublicationStartDate") or "",
                "location": "; ".join(locs),
                "tags": [c.get("Name") for c in (d.get("JobCategory") or []) if c.get("Name")],
                "close_date": d.get("PositionCloseDate") or d.get("ApplicationCloseDate") or "",
                "description": summary,
                "source": "USAJobs",
            })
        ok = True
    except Exception as exc:
        last_error = str(exc)
    _record_status("USAJobs", "ok" if ok else "failed", len(jobs),
                   reason="" if ok else "request_failed", error=last_error)
    if not ok:
        logger.warning("job provider USAJobs failed: %s", _redact(last_error))
    return jobs


def _fetch_all(limit_each, keywords=(), country="", adzuna_country=""):
    """Fetch from all job feeds in parallel. Uses short timeouts to avoid blocking the
    request thread for too long. Each feed is tried independently so a
    slow/unreachable feed doesn't prevent the others from returning."""
    # Country-scoped feeds follow the relocation market (codes → names, so
    # JSearch/Jooble get readable locations like "United Kingdom" / "Egypt").
    market_name = _normalise_country(adzuna_country) if adzuna_country else ""
    exec_loc = market_name or _normalise_country(country)

    calls = [
        ("Remotive", lambda: _fetch_remotive(max(limit_each, 40))),
        ("RemoteOK", lambda: _fetch_remoteok(max(limit_each, 40))),
        ("Adzuna", lambda: _fetch_adzuna(max(limit_each, 40), list(keywords), exec_loc)),
        ("Jobicy", lambda: _fetch_jobicy(max(limit_each, 25))),
        ("Arbeitnow", lambda: _fetch_arbeitnow(max(limit_each, 25))),
        ("Jooble", lambda: _fetch_jooble(max(limit_each, 25), list(keywords), exec_loc)),
        ("JSearch", lambda: _fetch_jsearch(max(limit_each, 25), list(keywords), exec_loc)),
        ("LinkedIn", lambda: _fetch_linkedin_jobs(max(limit_each, 25), list(keywords), exec_loc)),
        ("Google Jobs", lambda: _fetch_google_jobs(max(limit_each, 25), list(keywords), exec_loc)),
        ("USAJobs", lambda: _fetch_usajobs(max(limit_each, 15), list(keywords), exec_loc)),
    ]

    jobs = []
    with ThreadPoolExecutor(max_workers=len(calls)) as ex:
        futures = {ex.submit(fn): name for name, fn in calls}
        for fut in futures:
            name = futures[fut]
            try:
                jobs.extend(fut.result())
            except Exception as e:
                # Each fetch internally catches and logs; this is defense in depth.
                _record_status(name, "failed", reason="internal_error", error=str(e))
    return jobs


def _seniority_label(job):
    i = _job_seniority(job.get("title"))
    return ["Entry", "Junior", "Mid", "Senior"][min(3, i)]


def _normalise_job_location(job):
    if "remote" not in job or "city" not in job:
        raw_loc = (job.get("location") or "").strip()
        city, country = _city_country_hint(raw_loc)
        explicit_country = _normalise_country(job.get("country") or "")
        if explicit_country:
            country = explicit_country
        job.setdefault("country", country)
        job.setdefault("city", city)
        job.setdefault("remote", _is_remote(raw_loc))
    return job


def _apply(jobs, keywords, student_seniority, country, city="", role_family="",
           minor_keywords=(), market_country="", role_driven=False, verified_skills=(),
           role_title=""):
    """Score + rank jobs most-fitting → least. Clearly-senior roles are
    de-ranked; a beginner student never has senior roles ranked ahead of
    fitting ones. Jobs with zero relevance to the student's target career are
    dropped so unrelated listings never fill the list.

    Ranking priority: target-role title dominance tier → how strongly the title
    reflects the target role → location fit → numeric match. This keeps a highly
    verified/skilled but substantially different job from ever outranking a real
    target-role match (e.g. Python Backend Engineer stays below ML Engineer for
    an AI Engineer target).
    """
    scored = []
    for j in jobs:
        _normalise_job_location(j)
        (score, reason, relevant, loc_tier, loc_label, tier,
         title_evidence) = _score_job(
            j, keywords, student_seniority, country, city, role_family,
            minor_keywords=minor_keywords, market_country=market_country,
            role_driven=role_driven, verified_skills=verified_skills,
            role_title=role_title)
        if not relevant:
            continue
        if student_seniority == 0 and _job_seniority(j.get("title")) > 1:
            score = min(score, 15)
        if loc_tier == "different":
            score = min(score, 40)
        scored.append({**j, "match_pct": score, "match_reason": reason,
                       "seniority": _seniority_label(j),
                       "location_tier": loc_tier, "location_label": loc_label,
                       "rank_tier": tier, "title_evidence": title_evidence})
    scored.sort(key=lambda j: (_TIER_ORDER.get(j["rank_tier"], 3),
                               -j["title_evidence"],
                               _LOCATION_ORDER.get(j["location_tier"], 9),
                               -j["match_pct"]))
    return scored


def _build_result(key, skills, role, country, location, limit, role_requisites=(), market_country=""):
    """Build the ranked job list for a given cache key (runs in background).

    Provider reachability drives the honest empty-vs-offline decision:
    - at least one provider answered AND returned listings   -> ``live`` jobs;
    - providers answered but no relevant jobs matched        -> honest EMPTY,
      ``jobs: []`` — curated/demo jobs are never injected here;
    - every provider failed/unreachable                       -> ``unavailable``,
      ``jobs: []`` (the UI says providers are temporarily down).
    One provider failing never blocks the others and never raises an error to
    the student; per-provider outcomes are reported (redacted) in the payload.
    """
    skill_levels = [s[1] for s in skills if isinstance(s, (tuple, list)) and len(s) >= 2]
    skill_names = [s[0] if isinstance(s, (tuple, list)) else s for s in skills]
    verified_skills = [s[0] for s in skills if isinstance(s, (tuple, list)) and len(s) >= 3 and s[2]]
    keywords, minor_keywords = _cluster_keywords(skill_names, role, role_requisites)
    role_family = _role_family(role)
    role_driven = bool(role)
    student_seniority = _student_seniority(skill_levels)
    user_country = _normalise_country(country)

    # Provider search terms are driven by the TARGET ROLE, never by broad
    # required-skill words ("risk", "incident", "communication", "management")
    # that would pull unrelated careers (a Buyer, a Data Scientist, a Marketing
    # manager) into the feed. The role title + trusted close aliases lead; CV
    # skill words are used later only to rerank within the matched family.
    search_terms = list(role_intent.provider_queries(role, max_queries=6)) if role_driven else list(keywords)

    # Start a clean per-build provider report; each real fetch records its own
    # outcome. If ``_fetch_all`` is substituted (tests), nothing records, so the
    # empty path falls back like the original offline behaviour.
    with _lock:
        for p in PROVIDERS:
            _provider_status[p] = {"status": "skipped", "count": 0, "reason": "", "error": ""}
    raw = _fetch_all(limit * 3, search_terms, user_country, adzuna_country=market_country or "")
    merged = _merge(raw)

    # Only listings that are still live make the feed — expired/stale ones
    # (provider close dates passed, availability flags, or postings older than
    # MAX_LISTING_AGE_DAYS) are dropped before scoring/ranking.
    live_jobs = [j for j in merged if not j.get("is_expired")]
    if live_jobs:
        jobs = live_jobs
        feed_source = "live"
    elif _any_provider_ok():
        jobs = []
        feed_source = "empty"
    else:
        jobs = []
        feed_source = "unavailable"
    ranked = _apply(jobs, keywords, student_seniority, user_country, location, role_family,
                    minor_keywords=minor_keywords, market_country=market_country,
                    role_driven=role_driven, verified_skills=verified_skills,
                    role_title=role or "")

    local = [j for j in ranked if j.get("location_tier") in ("city", "country", "country_remote", "market")]
    broader = [j for j in ranked if j.get("location_tier") in ("global_remote", "unknown")]
    other = [j for j in ranked if j.get("location_tier") == "different"]
    selected = list(local)
    if len(selected) < limit:
        selected.extend(broader[:limit - len(selected)])
    if len(selected) < limit:
        selected.extend(other[:limit - len(selected)])

    if not selected and feed_source == "live":
        feed_source = "empty"

    data = {
        "source": feed_source,
        "jobs": selected[:limit],
        "groups": {
            "local_count": len(local),
            "broader_count": len(broader),
            "other_count": len(other),
        },
        "providers": [
            {
                "source": p,
                "status": _provider_status.get(p, {}).get("status", "skipped"),
                "count": _provider_status.get(p, {}).get("count", 0),
                "reason": _provider_status.get(p, {}).get("reason", ""),
                "error": _provider_status.get(p, {}).get("error", ""),
            }
            for p in PROVIDERS
        ],
    }

    now = time.time()
    with _lock:
        _cache.update({"at": now, "key": key, "data": data})
        _bg_fetching.discard(key)
    return data


def _background_fetch(key, skills, role, country, location, limit, role_requisites=(), market_country=""):
    """Run _build_result in a daemon thread so the HTTP request returns fast."""
    def _worker():
        try:
            _build_result(key, skills, role, country, location, limit,
                          role_requisites=role_requisites, market_country=market_country)
        except Exception:
            with _lock:
                _bg_fetching.discard(key)
    t = threading.Thread(target=_worker, daemon=True)
    t.start()

def recent_jobs(skills=(), role="", country="", location="", limit=10, _sync=False,
                role_requisites=(), market_country=""):
    """Return ``{source, jobs, groups}`` ranked most → least fitting for the profile.

    ``skills`` is a list of ``(name, level)`` or ``(name, level, verified)``
    tuples (the student's own skills; the final flag marks VERIFIED skills,
    which earn a small evidence boost in ranking). ``role`` is the display title
    of their target career. ``country`` and ``location`` are their profile
    region. ``role_requisites`` are the target role's required-skill names (the
    career's own vocabulary, for role-driven relevance weighting).
    ``market_country`` is an optional remote/relocation search target for feeds
    like Adzuna.

    On a cache miss the endpoint immediately returns an ``unavailable`` empty
    response (never curated/demo jobs) and fetches live data in a background
    thread so the dashboard never freezes; the next read returns the live data.

    When ``_sync=True`` (used by tests), the fetch runs synchronously so
    monkeypatched ``_fetch_all`` results are returned directly.
    """
    skill_levels = [s[1] for s in skills if isinstance(s, (tuple, list)) and len(s) >= 2]
    skill_names = [s[0] if isinstance(s, (tuple, list)) else s for s in skills]
    verified_skills = [s[0] for s in skills if isinstance(s, (tuple, list)) and len(s) >= 3 and s[2]]
    key = ("|".join(sorted(n.lower() for n in skill_names))
           + "|" + (role or "").lower() + "|" + _normalise_country(country or "")
           + "|" + _normalise_city(location or "")
           + "|" + "|".join(sorted(n.lower() for n in role_requisites or ()))
           + "|" + _normalise_country(market_country or ""))
    now = time.time()

    with _lock:
        cached = _cache["data"] if (_cache["key"] == key and now - _cache["at"] < TTL_SECONDS) else None
    if cached:
        return cached

    if _sync:
        return _build_result(key, skills, role, country, location, limit,
                             role_requisites=role_requisites, market_country=market_country)

    # Cache miss — kick off a background fetch and return an honest
    # ``unavailable`` empty response immediately so the dashboard request never
    # blocks on external HTTP calls. Curated/demo jobs are never served here.
    if key not in _bg_fetching:
        _bg_fetching.add(key)
        _background_fetch(key, skills, role, country, location, limit,
                          role_requisites=role_requisites, market_country=market_country)
    return {
        "source": "unavailable",
        "jobs": [],
        "groups": {"local_count": 0, "broader_count": 0, "other_count": 0},
        "providers": [],
    }
