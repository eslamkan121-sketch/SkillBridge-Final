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
import ipaddress
import logging
import os
import re
import threading
import time
import urllib.parse
from collections import OrderedDict
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
# Configurable cache TTL (default 15 min). Can be overridden via JOBS_CACHE_TTL_SECONDS env var.
_TTL_SECONDS_DEFAULT = 15 * 60
def _get_ttl_seconds():
    try:
        val = int(os.environ.get("JOBS_CACHE_TTL_SECONDS", ""))
        if val > 0:
            return val
    except Exception:
        pass
    return _TTL_SECONDS_DEFAULT

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
    "Jooble", "Himalayas", "Get on Board",
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

# Provider cooldown tracking for rate limits / repeated failures
_PROVIDER_COOLDOWN = {}  # source -> {"until": timestamp, "reason": "rate_limited"}

# Cooldown duration in seconds (configurable via JOBS_COOLDOWN_SECONDS)
_COOLDOWN_SECONDS_DEFAULT = 15 * 60
def _get_cooldown_seconds():
    try:
        val = int(os.environ.get("JOBS_COOLDOWN_SECONDS", ""))
        if val > 0:
            return val
    except Exception:
        pass
    return _COOLDOWN_SECONDS_DEFAULT


def _is_provider_cooled_down(source):
    """Check if a provider is currently cooled down."""
    now = time.time()
    cd = _PROVIDER_COOLDOWN.get(source)
    if cd and cd["until"] > now:
        return True
    if cd and cd["until"] <= now:
        # Expired - remove it
        _PROVIDER_COOLDOWN.pop(source, None)
    return False


def _set_provider_cooldown(source, reason="rate_limited", seconds=None):
    """Mark a provider as cooled down."""
    if seconds is None:
        seconds = _get_cooldown_seconds()
    _PROVIDER_COOLDOWN[source] = {"until": time.time() + seconds, "reason": reason}


def _clear_provider_cooldown(source):
    """Manually clear a provider's cooldown."""
    _PROVIDER_COOLDOWN.pop(source, None)


# ── Phase I — honest provider health vocabulary (guide lines 470-505) ──
# ``health`` is ADDITIVE and DERIVED at report-consolidation time from the
# legacy ``status``/``reason``/``error`` fields (which stay byte-for-byte
# intact). The 12 fetch functions never touch it; a request's outcomes are
# isolated and a request-id threads through every log line.
HEALTH = {
    "unconfigured": "unconfigured",
    "healthy": "healthy",
    "empty_success": "empty_success",
    "cached": "cached",
    "stale_fallback": "stale_fallback",
    "rate_limited": "rate_limited",
    "unauthorized": "unauthorized",
    "network_unreachable": "network_unreachable",
    "timeout": "timeout",
    "malformed_response": "malformed_response",
    "disabled_by_feature_flag": "disabled_by_feature_flag",
    "unknown": "unknown",
}
_HEALTH_FALLBACKS = {
    "rate_limited": HEALTH["rate_limited"],
    "forbidden": HEALTH["unauthorized"],
    "unauthorized": HEALTH["unauthorized"],
    "timeout": HEALTH["timeout"],
    "network_unreachable": HEALTH["network_unreachable"],
    "network_error": HEALTH["network_unreachable"],
    "connection_error": HEALTH["network_unreachable"],
    "malformed_response": HEALTH["malformed_response"],
}
_MALFORMED_MARKERS = ("jsondecode", "expecting value", "expecting property name",
                       "expecting ',' delimiter", "invalid \\u",
                       "unexpected end of data", "not a json")
_HEALTH_TTL_DEFAULT = 10
def _get_health_ttl():
    try:
        val = int(os.environ.get("JOBS_HEALTH_TTL_SECONDS", ""))
        if val > 0:
            return val
    except Exception:
        pass
    return _HEALTH_TTL_DEFAULT
_health_cache = {"at": 0.0, "payload": None, "fingerprint": None}

def _disabled_providers():
    """Feature-gated providers (JOBS_DISABLED_PROVIDERS CSV); never removed."""
    raw = os.environ.get("JOBS_DISABLED_PROVIDERS", "") or ""
    return {name.strip() for name in raw.split(",") if name.strip()}
def _provider_feature_flag_disabled(source):
    return source in _disabled_providers()
def _health_of(entry, source):
    """Derive the canonical Phase-I health code from a legacy report entry."""
    if _provider_feature_flag_disabled(source):
        return HEALTH["disabled_by_feature_flag"]
    status = entry.get("status") or ""
    reason = entry.get("reason") or ""
    count = entry.get("count") or 0
    if status == "ok":
        return HEALTH["healthy"] if count > 0 else HEALTH["empty_success"]
    if status == "skipped":
        if reason in ("no_credentials", "host_not_configured"):
            return HEALTH["unconfigured"]
        if reason in ("unsupported_country", "disabled_by_feature_flag"):
            return HEALTH["disabled_by_feature_flag"]
        if reason == "cooldown":
            return _HEALTH_FALLBACKS.get((entry.get("error") or "").strip(), HEALTH["unknown"])
        return HEALTH["unconfigured"] if not _provider_is_configured(source) else HEALTH["unknown"]
    if status == "failed":
        if reason in ("network_unreachable", "network_error", "connection_error"):
            cd = _PROVIDER_COOLDOWN.get(source) or {}
            return _HEALTH_FALLBACKS.get(cd.get("reason", ""), HEALTH["network_unreachable"])
        if reason in _HEALTH_FALLBACKS:
            return _HEALTH_FALLBACKS[reason]
        if reason == "request_failed":
            err = (entry.get("error") or "").lower()
            if "429" in err:
                return HEALTH["rate_limited"]
            if any(k in err for k in ("401", "403", "unauthorized",
                                          "not subscribed", "forbidden")):
                return HEALTH["unauthorized"]
            if any(k in err for k in ("timeout", "timed out")):
                return HEALTH["timeout"]
            if any(k in err for k in _MALFORMED_MARKERS):
                return HEALTH["malformed_response"]
            cd = _PROVIDER_COOLDOWN.get(source) or {}
            return _HEALTH_FALLBACKS.get(cd.get("reason", ""), HEALTH["unknown"])
        return HEALTH["unknown"]
    return HEALTH["unknown"]

# Secret-free diagnostic counters exposed through ``provider_status()``.
_stats = {
    "cache_hits": 0,
    "cache_misses": 0,
    "last_success_provider": "",
    "last_error_by_provider": {},  # source -> short stable reason code
    "fetch_times": [],             # rolling window of recent build durations (s)
}
_FETCH_TIMES_MAX = 20


def _provider_is_configured(source):
    """Whether a provider's credentials/setup are currently enabled.

    Keyless global boards are always enabled; keyed providers require their
    env vars (RapidAPI host-gated adapters additionally require the exact
    subscribed host). Never returns key values — only booleans.
    """
    keyless = {"Remotive", "RemoteOK", "Jobicy", "Arbeitnow", "Himalayas", "Get on Board"}
    if source in keyless:
        return True
    if source == "JSearch":
        return bool(os.environ.get("JSEARCH_API_KEY") or os.environ.get("RAPIDAPI_KEY"))
    if source == "LinkedIn":
        return bool(os.environ.get("LINKEDIN_JOBS_HOST")) and bool(
            os.environ.get("RAPIDAPI_LINKEDIN_KEY") or os.environ.get("RAPIDAPI_KEY"))
    if source == "Google Jobs":
        return bool(os.environ.get("GOOGLE_JOBS_HOST")) and bool(
            os.environ.get("RAPIDAPI_GOOGLE_JOBS_KEY") or os.environ.get("RAPIDAPI_KEY"))
    if source == "Adzuna":
        return bool(os.environ.get("ADZUNA_APP_ID")) and bool(os.environ.get("ADZUNA_APP_KEY"))
    if source == "USAJobs":
        return bool(os.environ.get("USAJOBS_API_KEY"))
    if source == "Jooble":
        return bool(os.environ.get("JOOBLE_API_KEY"))
    return False


def provider_status():
    """Secret-free job-provider observability (mirrors ``genai.provider_status``).

    Adds Phase-I honest ``providers_health`` (per-provider canonical health
    code derived from the last committed build) + ``last_build_at``. Every
    payload is redacted of keys/URLs; the health view never probes a
    provider and never spends quota. Existing keys keep their meaning.
    """
    with _lock:
        hits = _stats["cache_hits"]
        misses = _stats["cache_misses"]
        times = list(_stats["fetch_times"])
        report_snap = {p: dict(_provider_status.get(p) or {}) for p in PROVIDERS}
        last_build_at = _stats.get("last_build_at")
    fingerprint = tuple(sorted((p, report_snap[p].get("status"),
                                report_snap[p].get("count"),
                                report_snap[p].get("reason"))
                               for p in PROVIDERS))
    now = time.time()
    cached = _health_cache
    if (cached["payload"] is not None
            and now - cached["at"] < _get_health_ttl()
            and cached["fingerprint"] == fingerprint):
        return cached["payload"]
    avg_ms = round((sum(times) / len(times)) * 1000.0, 1) if times else 0.0
    last_success = _stats.get("last_success_provider") or ""
    health_map = {p: _health_of(report_snap[p], p) for p in PROVIDERS}
    payload = {
        "providers_total": len(PROVIDERS),
        "providers_configured": [p for p in PROVIDERS
                                 if _provider_is_configured(p)
                                 and not _provider_feature_flag_disabled(p)],
        "providers_available": [p for p in PROVIDERS
                                if report_snap[p].get("status") == "ok"
                                and not _provider_feature_flag_disabled(p)],
        "providers_health": health_map,
        "last_success_provider": last_success or None,
        "last_error_by_provider": {
            p: entry.get("reason") for p, entry in report_snap.items()
            if entry.get("status") == "failed" and entry.get("reason")
        },
        "last_build_at": last_build_at,
        "cache": {"hits": hits, "misses": misses, "avg_fetch_ms": avg_ms},
    }
    with _lock:
        _health_cache["at"] = time.time()
        _health_cache["payload"] = payload
        _health_cache["fingerprint"] = fingerprint
    return payload


def _redact(text):
    """Strip any configured credential out of a message before logging/sending.

    httpx error messages embed the full request URL (Adzuna puts app_id/app_key
    in the query string, Jooble in the path), so raw exceptions may carry
    secrets. Known key values are replaced with ``***`` wherever they appear.
    URLs and email addresses are also masked so no host or address ever
    reaches a public payload or a log.
    """
    s = str(text or "")
    for var in ("JSEARCH_API_KEY", "RAPIDAPI_KEY", "RAPIDAPI_LINKEDIN_KEY",
                "RAPIDAPI_GOOGLE_JOBS_KEY", "LINKEDIN_JOBS_API_KEY",
                "GOOGLE_JOBS_API_KEY", "ADZUNA_APP_ID",
                "ADZUNA_APP_KEY", "JOOBLE_API_KEY", "USAJOBS_API_KEY"):
        v = os.environ.get(var)
        if v and len(v) >= 4 and v in s:
            s = s.replace(v, "***")
    s = re.sub(r"https?://[^\s\"'<>)|]+", "<url>", s)
    s = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "<email>", s)
    return s


def _record_status(source, status, count=0, reason="", error=""):
    # Writes land in the ACTIVE per-build report when one is set (concurrent
    # builds stay isolated); otherwise they fall back to the global snapshot
    # (used by the health endpoint and by direct standalone calls).
    report = getattr(_thread_local, "report", None)
    target = report if report is not None else _provider_status
    target[source] = {
        "status": status,
        "count": count,
        "reason": reason,
        "error": _redact(error)[:120],
    }
    if status == "ok":
        _stats["last_success_provider"] = source
    elif status == "failed" and reason:
        _stats["last_error_by_provider"][source] = reason


def _skip_status(source, reason):
    """Mark a provider as skipped (key missing, unsupported country, etc.)."""
    report = getattr(_thread_local, "report", None)
    target = report if report is not None else _provider_status
    target[source] = {"status": "skipped", "count": 0,
                      "reason": reason, "error": ""}


def _any_provider_ok(report=None):
    """True when at least one provider reported a successful response.

    ``report`` is the REQUEST's own per-build provider report when supplied;
    a request's outcomes must never be read from another build's view.
    """
    source = report if report is not None else _provider_status
    return any(source.get(p, {}).get("status") == "ok"
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


def _normalise_title_for_dedup(title):
    """Lowercase + strip punctuation for dedupe key."""
    if not title:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


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

# Canonical multi-entry job cache. Keyed by EVERY input that changes the ranked
# result (each skill's name + level + verified flag, role, country, city,
# requisites, market, the result limit) plus a config tag, so users, roles,
# markets, filters and limits can never overwrite or reuse incompatible rows.
# Memory is bounded by TTL + an LRU entry cap. The one canonical key drives
# reads, background-fetch dedup, and writes, so they can never diverge.
_CACHE_TAG = "jobs-cache-v1"   # bump when provider set / env semantics / ranking change
_CACHE_MAX_ENTRIES_DEFAULT = 256

# Phase H — internal-record normalization + link quality (offline, additive).
_NORM_TAG = "jobs-norm-v1"     # bump when fingerprint/provider-vocab semantics change

# Verified-dead apply URLs (user-reported or provably 404). Records are kept
# with listing_status link-unavailable so history/provenance survives; they are
# excluded from the surfaced feed (same end-user behavior as the old silent
# drop, but nothing is deleted from the pipeline).
_VERIFIED_DEAD_JOB_URLS = {
    "https://bebee.com/eg/jobs/cyber-security-analyst-ssh-design-nasr-city--fj-2328815129",
}

# Hostnames that can never be a legitimate public job apply target — reserved
# suffixes and any literal address in a non-public IP range. Comparison is
# offline and purely lexical/DNS-category based (no network probe ever).
_BLOCKED_INTERNAL_HOST_SUFFIXES = {
    "localhost", "local", "internal", "intranet", "lan", "home", "onion",
}
_DESCRIPTION_EXCERPT_LEN = 260


def _get_max_entries():
    try:
        val = int(os.environ.get("JOBS_CACHE_MAX_ENTRIES", ""))
        if val > 0:
            return val
    except Exception:
        pass
    return _CACHE_MAX_ENTRIES_DEFAULT


_cache = OrderedDict()           # canonical key -> {"at": float, "data": dict} (LRU-order)
_lock = threading.Lock()
_bg_fetching = set()             # canonical keys currently being fetched in background
_thread_local = threading.local()  # per-build provider-report context (see _build_result)


def clear_job_cache():
    """Test helper: drop every cached entry and in-flight dedup marker."""
    with _lock:
        _cache.clear()
        _bg_fetching.clear()


def _safe_key_component(text):
    """Prevent delimiter/whitespace/control injection into the cache key.

    Every component is lowercased, the record delimiter ``|`` is neutralised,
    and any credential value, email address, or URL is deterministically
    collapsed so raw CV text, tokens, and secrets can never reach a key even
    when an odd free-form input is provided.
    """
    s = str(text or "").lower().replace("|", " ").strip()
    s = _redact(s)
    s = re.sub(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", "<email>", s)
    s = re.sub(r"(https?://|www\.)\S+", "<url>", s)
    return s


def _cache_key(skills=(), role="", country="", location="", requisites=(), market="", limit=10):
    """Deterministic, secret-free canonical cache key.

    Every input that changes the ranked result is folded in: each skill's
    (name, level, verified) triple — levels drive ``_student_seniority`` and the
    reranker uses verified flags, so two users with the same skill names but
    different depth must NEVER share a row — plus role, normalised country/city,
    sorted requisites, normalised market, the result limit, and the config tag.
    User ids/emails, raw CV text, keys and secrets never appear.
    """
    skill_parts = []
    for s in skills or ():
        if isinstance(s, (tuple, list)):
            name = s[0]
            level = s[1] if len(s) > 1 else ""
            verified = "1" if (len(s) > 2 and s[2]) else "0"
        else:
            name, level, verified = s, "", "0"
        skill_parts.append(f"{_safe_key_component(name)}:{_safe_key_component(level)}:{verified}")
    parts = [
        "|".join(sorted(skill_parts)),
        _safe_key_component(role),
        _normalise_country(country or ""),
        _normalise_city(location or ""),
        "|".join(sorted(_safe_key_component(n) for n in requisites or ())),
        _normalise_country(market or ""),
        str(int(limit)),
        _CACHE_TAG,
    ]
    return "|".join(parts)

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

# Reranker weights — named constants for transparency and tuning.
W_TITLE_MATCH = 35.0
W_SKILL_OVERLAP = 20.0
W_GAP_RELEVANCE = 15.0
W_LOCATION_MATCH = 10.0
W_RECENCY = 5.0
W_CAREER_FAMILY_PENALTY = 40.0  # large negative for cross-family jobs


def _rerank_score(job, target_role, student_verified_skills, student_skill_gaps, student_location, job_role_family):
    """Deterministic reranker per the job quality spec.

    score = w1*title_match + w2*skill_overlap + w3*gap_relevance + w4*location_match + w5*recency - w6*career_family_penalty
    """
    title = (job.get("title") or "").lower()
    desc = (job.get("description") or "").lower()
    tags = " ".join(job.get("tags") or []).lower()
    haystack = f"{title} {desc} {tags}"

    # w1: title match — token overlap between listing title and target role variants
    role_tokens = {w for w in re.split(r"[^a-z0-9]+", (target_role or "").lower()) if len(w) >= 2}
    title_tokens = {w for w in re.split(r"[^a-z0-9]+", title) if len(w) >= 2}
    title_match = len(role_tokens & title_tokens) / max(1, len(role_tokens)) if role_tokens else 0.0

    # w2: skill overlap — student's verified skills present in listing
    verified = {s.lower() for s in (student_verified_skills or ())}
    skill_overlap = len([s for s in verified if s and s in haystack]) / max(1, len(verified)) if verified else 0.0

    # w3: gap relevance — listing skills that appear in student's gap list
    gap_tokens = {s.lower() for s in (student_skill_gaps or ())}
    gap_relevance = len([g for g in gap_tokens if g and g in haystack]) / max(1, len(gap_tokens)) if gap_tokens else 0.0

    # w4: location match — listing location vs student preferred location
    job_loc = (job.get("location") or "").lower()
    student_loc = (student_location or "").lower()
    job_country = _normalise_country(job.get("country") or "")
    student_country = _normalise_country(student_loc)
    location_match = 1.0 if job_country and student_country and job_country == student_country else 0.0
    if not location_match and job.get("remote") and student_country:
        location_match = 0.5  # remote in same country gets partial

    # w5: recency — newer postings score higher
    listed_days = job.get("listed_days_ago")
    recency = max(0.0, 1.0 - (listed_days / 30.0)) if listed_days is not None else 0.5

    # w6: career family penalty — different family gets large negative
    job_family = _role_family(title) or ""
    target_family = _role_family(target_role) or ""
    career_family_penalty = 1.0 if job_family and target_family and job_family != target_family else 0.0

    score = (W_TITLE_MATCH * title_match
             + W_SKILL_OVERLAP * skill_overlap
             + W_GAP_RELEVANCE * gap_relevance
             + W_LOCATION_MATCH * location_match
             + W_RECENCY * recency
             - W_CAREER_FAMILY_PENALTY * career_family_penalty)
    return max(0.0, score)


def _cluster_keywords(skills, role, role_requisites=()):
    """Split the student's skill names into a role-relevant primary cluster and
    an incidental minor cluster.

    Primary (drives search + score): the target-role title, its required skills,
    and any extracted skill whose vocabulary overlaps the role's at all — kept in
    importance order so search queries lead with the most distinctive terms.
    Minor (tie-breakers only): every other extracted skill. When no target
    career is set every skill is primary, preserving the original behaviour.
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
    for s in skills:
        rel = _skill_relevance_to_role(s, role, role_requisites)
        if rel >= _PRIMARY_RELEVANCE:
            primary = add(primary, s)
        else:
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
    if tier == "family" and not relevant:
        relevant = True
    return score, reason, relevant, loc_tier, loc_label, tier, title_evidence


def job_score_components(job, keywords, student_seniority, country, city="",
                         role_family="", minor_keywords=(), market_country="",
                         role_driven=False, verified_skills=(), role_title=""):
    """Full exact-total decomposition of ``_score_job`` (Phase J).

    Mirror of the ``_score_job`` arithmetic that returns every intermediate as
    labelled numbers. It reuses the SAME shared helpers (``_title_words``,
    ``role_intent``, ``_job_seniority``, ``_location_score``, ``_ROLE_FAMILIES``,
    ``_GENERIC_TITLE_TOKENS``), so the only duplicated text is the sequential
    relevance/exp/score block — documented as a mirror and locked equal to the
    live score by the Phase J parity test battery. ``final`` is the displayed
    ``match_pct``; the sum:

        relevance.final + experience.points + location.points
        + (rounded_total - raw_total)            # int rounding
        + (clamped_total - rounded_total)        # 0–100 clamp
        + (seniority_capped_total - clamped_total)   # entry-level cap
        + (location_capped_total - seniority_capped_total)  # relocation cap

    equals ``final`` exactly. ``role_title`` only feeds the dominance tier;
    the mirror keeps it for signature symmetry with ``_score_job`` (unused).
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

    base_points = min(56, hits * 14)
    relevance = base_points
    family = role_family
    title_family_hit = False
    family_cap_70 = None
    if family:
        syns = [
            s.strip() for s in _ROLE_FAMILIES.get(family, [family])
        ]
        if role_driven:
            role_vocab = set(keywords)
            syns = [s for s in syns if s and s not in _GENERIC_TITLE_TOKENS and _tokens(s) & role_vocab]
        if any(s in (" " + tlow) or s and s in tlow for s in syns):
            title_family_hit = True
            relevance += 24
    if title_family_hit:
        family_cap_70 = min(70, relevance)
        relevance = family_cap_70
    family_top_bump = None
    if title_family_hit and relevance >= 40:
        family_top_bump = min(80, relevance + 6)
        relevance = family_top_bump
    title_fallback_boost = None
    if not title_family_hit and title_hits:
        title_fallback_boost = max(relevance, min(60, 18 + len(title_hits) * 18))
        relevance = title_fallback_boost
    minor_bonus = min(8, len(minor_hits) * 2)
    relevance = min(90, relevance + minor_bonus)
    verified_bonus = min(6, len(verified_hits) * 3)
    relevance = min(94, relevance + verified_bonus)
    fresh = job.get("listed_days_ago")
    fresh_bonus = 0
    if fresh is not None and relevance > 0:
        fresh_bonus = min(4, max(0, 4 - int(fresh)))
        relevance = min(96, relevance + fresh_bonus)

    job_sen = _job_seniority(title)
    if job_sen > student_seniority:
        exp_points = 0
        exp_label = (f"Job level above yours (job {job_sen} > student "
                     f"{student_seniority})")
    elif job_sen == student_seniority:
        exp_points = 20
        exp_label = f"Job level matches yours ({job_sen})"
    else:
        exp_points = 12
        exp_label = f"Job below your level (job {job_sen} < student {student_seniority})"

    loc_tier, loc_points, loc_label = _location_score(job, country, city, market_country)
    raw_total = relevance + exp_points + loc_points
    rounded_total = int(round(raw_total))
    clamped_total = max(0, min(100, rounded_total))
    if student_seniority == 0 and job_sen > 1:
        seniority_capped_total = min(clamped_total, 15)
    else:
        seniority_capped_total = clamped_total
    if loc_tier == "different":
        location_capped_total = min(seniority_capped_total, 40)
    else:
        location_capped_total = seniority_capped_total
    final = location_capped_total

    return {
        "final": final,
        "raw_total": raw_total,
        "rounded_total": rounded_total,
        "clamped_total": clamped_total,
        "seniority_capped_total": seniority_capped_total,
        "location_capped_total": location_capped_total,
        "experience": {"points": exp_points, "label": exp_label,
                       "job_seniority": job_sen, "student_seniority": student_seniority},
        "location": {"tier": loc_tier, "points": loc_points, "label": loc_label},
        "relevance": {
            "final": relevance,
            "base_points": base_points,
            "family_bonus": 24 if title_family_hit else 0,
            "family_cap_70": family_cap_70,
            "family_top_bump": family_top_bump,
            "title_fallback_boost": title_fallback_boost,
            "minor_bonus": minor_bonus,
            "verified_bonus": verified_bonus,
            "fresh_bonus": fresh_bonus,
            "title_family_hit": bool(title_family_hit),
        },
        "matches": {
            "matched": matched,
            "title_hits": title_hits,
            "minor_hits": minor_hits,
            "verified_hits": verified_hits,
        },
    }


def locate_feed_job(skills, role, country, location, requisites, market,
                    fingerprint, limit=10):
    """Locate a specific surfaced job by fingerprint in the student's feed cache.

    Read-only (never clears the cache): rebuilds the exact cache key the feed
    uses, warms it with a sync build only when absent, and returns the located
    normalized record — the very record the user saw, so its stored
    ``match_pct`` is the displayed score. Returns ``None`` when the job is not
    in the current feed (honest 404, cross-profile/market mismatch).
    """
    key = _cache_key(skills, role, country, location, requisites, market, limit)
    with _lock:
        entry = _cache.get(key) if key in _cache else None
    if entry is None:
        data = _build_result(key, skills, role, country, location, limit,
                             role_requisites=requisites, market_country=market,
                             request_id="")
        with _lock:
            entry = _cache.get(key) or {"data": data, "at": time.time()}
    for j in (entry.get("data") or {}).get("jobs") or []:
        if j.get("fingerprint") == fingerprint:
            return j
    return None


def peek_feed_job(skills, role, country, location, requisites, market,
                  fingerprint, limit=10):
    """Cache-only ``locate_feed_job``: look up a fingerprint WITHOUT triggering
    a feed build.

    Never fetches and never warms the cache — used by the job tracker to
    opportunistically refresh a saved row's liveness (``listing_status`` /
    ``link_state`` / ``is_expired``) from an already-built feed entry. Returns
    ``None`` when the feed for this profile/market has not been built or the
    fingerprint is not in it, leaving the stored snapshot untouched."""
    key = _cache_key(skills, role, country, location, requisites, market, limit)
    with _lock:
        entry = _cache.get(key) if key in _cache else None
    if entry is None:
        return None
    for j in (entry.get("data") or {}).get("jobs") or []:
        if j.get("fingerprint") == fingerprint:
            return {"found": True, "job": j}
    return {"found": False, "job": None}


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


def _is_private_hostname(host):
    """Offline SSRF-style guard: True for internal/reserved host targets.

    Covers literal loopback/private/link-local/reserved/multicast addresses and
    the reserved internal hostname suffixes. Purely lexical — never a DNS look-
    up or network probe, so it is deterministic and safe in automated tests.
    """
    if not host:
        return False
    h = host.lower().strip().rstrip(".")
    bare = h.strip("[]")
    if h in _BLOCKED_INTERNAL_HOST_SUFFIXES:
        return True
    if any(h.endswith("." + suffix) for suffix in _BLOCKED_INTERNAL_HOST_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(bare)
    except ValueError:
        return False
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def _link_quality(url):
    """Offline, deterministic link validation (never probes the network).

    Returns ``(ok, state, reason)``; ``state`` is one of:
    - ``ok``       a probe verified the link (only behind ``live_check=True``);
    - ``unverified`` valid http(s) URL, not probed — the honest inconclusive
                   default. We never claim a link is live without evidence;
    - ``dead``     verified-dead URL, kept in history but not surfaced;
    - ``rejected`` unsafe scheme / private-network / unparseable / no host.
    """
    if not url:
        return False, "rejected", "missing_url"
    if url in _VERIFIED_DEAD_JOB_URLS:
        return False, "dead", "verified_dead"
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False, "rejected", "unparseable"
    scheme = parsed.scheme
    if scheme not in ("http", "https"):
        # An EXPLICIT non-http scheme (javascript:, data:, file:, ftp:, mailto:, …)
        # can never be a safe apply target. A scheme-less value is not a usable
        # link but is ambiguity we cannot resolve offline — honest inconclusive
        # state (``unverified``) rather than inventing either way.
        if scheme:
            return False, "rejected", "unsafe_scheme"
        return True, "unverified", ""
    netloc = (parsed.netloc or "").split("@")[-1]
    if netloc.startswith("["):
        # IPv6 literal, possibly with a port: "[::1]:8080" -> "::1"
        host = netloc.split("]")[0].strip("[]")
    else:
        host = netloc.split(":")[0]
    if not host:
        return False, "rejected", "no_host"
    if _is_private_hostname(host):
        return False, "rejected", "private_network"
    return True, "unverified", ""


def _probe_listing_link(url):
    """Optional live link probe. Deliberately NOT part of normal fetching:
    it is only reachable when an explicit ``live_check=True`` request opts in,
    so automated tests never touch the network. Returns True/False/None
    (None = inconclusive, honest unavailable)."""
    ok, state, reason = _link_quality(url)
    if not ok:
        return False
    try:
        resp = httpx.head(url, timeout=8, follow_redirects=True)
        return 200 <= resp.status_code < 400 and resp.status_code != 405
    except Exception:
        return None


def _fingerprint(source, provider_job_id, url):
    """Stable internal fingerprint.

    Provider job IDs are used when present (unique WITHIN a provider, so the
    source is folded in); otherwise the canonical apply URL. Never uses title/
    company text, so a repost keeps its identity while an unrelated vacancy
    with the same title can never collide.
    """
    if provider_job_id:
        seed = f"{source}|{provider_job_id}"
    else:
        seed = url or ""
    return hashlib.sha1(f"{_NORM_TAG}|{seed}".encode("utf-8")).hexdigest()[:16]


def normalise_listing(j, fetched_at=None):
    """Phase H — build ONE normalized internal record from a provider raw item.

    Returns a dict with the existing feed fields intact plus ADAPTIVE Phase H
    fields: provider/provider_job_id, fingerprint, original_*, work_type,
    seniority, description_excerpt, apply_url/source_url, published/timestamp
    trio, listing_status/link_state/link_checked, dedupe_basis, and a
    ``provenance`` map stating the basis of every inferred/normalized field.
    """
    source = j.get("source", "")
    title = (j.get("title") or "").strip()
    company = (j.get("company") or j.get("company_name") or "Unknown company").strip()
    url = j.get("url") or j.get("link") or ""
    listed_date = _parse_listing_date(j.get("date") or j.get("publication_date") or "")
    is_expired, expires_at, listed_days_ago = _expiry_props(j, listed_date)

    ok, link_state, link_reason = _link_quality(url)
    if link_state in ("rejected", "dead"):
        listing_status = "link-unavailable"
    elif is_expired:
        listing_status = "expired"
    else:
        listing_status = "live"

    location = (j.get("location") or j.get("candidate_required_location") or "").strip()
    city, country = _city_country_hint(location)
    basis_country, basis_city = "location_parse", "location_parse"
    explicit_country = _normalise_country(j.get("country") or "")
    if explicit_country:
        country = explicit_country
        basis_country = "provider_field"
    if not country:
        for tag in (j.get("tags") or []):
            c = _country_hint(tag)
            if c:
                country, basis_country = c, "tag_hint"
                break
    if not country:
        country, basis_country = "", "unknown"
    if not city:
        city, basis_city = "", "unknown"

    tags = [t for t in (j.get("tags") or []) if isinstance(t, str) and t.strip()][:6]
    raw_date = j.get("date") or j.get("publication_date") or ""
    if isinstance(raw_date, int):
        raw_date = time.strftime("%Y-%m-%d", time.gmtime(raw_date))
    fetched_at = fetched_at or time.time()

    item = {
        "title": title, "company": company, "url": url,
        "date": raw_date, "location": location, "country": country,
        "city": city, "remote": bool(j.get("remote")) or _is_remote(location),
        "tags": tags, "source": source,
        "is_expired": is_expired, "expires_at": expires_at,
        "listed_days_ago": listed_days_ago,
    }
    item["description"] = _clean_text(
        j.get("description") or j.get("snippet") or j.get("jobExcerpt")
        or j.get("jobDescription") or j.get("position_summary") or "")
    item["source_url"] = url
    item["source"] = source
    item["id"] = _job_id(source, url, title, company)
    item["employment_type"] = _clean_text(j.get("employment_type") or "")[:24]
    item["workplace_type"] = _workplace_type(item)
    item["salary"] = _clean_text(j.get("salary") or "")
    item["required_skills"] = _extract_required_skills(item)

    provider_job_id = _job_field(j, "id", "job_id", "jobId", "external_id",
                                 "identifier", "slug")
    if provider_job_id:
        provider_job_id = str(provider_job_id).strip()
        if provider_job_id == item["id"]:
            # ``item["id"]`` is OUR internal ``_job_id`` hash — never mistake
            # it for a provider-supplied identifier (defensive: only reachable
            # when a record is re-normalised, which production never does).
            provider_job_id = None
        elif len(provider_job_id) > 64:
            provider_job_id = provider_job_id[:64]

    explicit_wt = _clean_text(_job_field(j, "work_type", "workType", "type"))
    explicit_wt_l = explicit_wt.lower()
    if explicit_wt_l in {"remote", "hybrid", "onsite", "on-site", "in-person", "in_office"}:
        work_type = "remote" if explicit_wt_l == "remote" else (
            "hybrid" if explicit_wt_l == "hybrid" else "onsite")
        basis_work_type = "provider_field"
    elif item["workplace_type"]:
        work_type = item["workplace_type"]
        basis_work_type = "remote_token" if work_type == "remote" else "location_parse"
    else:
        work_type = "unknown"
        basis_work_type = "unknown"

    salary = item["salary"]
    employment_type = item["employment_type"]
    description = item.get("description", "")
    seniority_label = _seniority_label(item)

    item.update({
        "provider": source,
        "provider_job_id": provider_job_id or None,
        "fingerprint": _fingerprint(source, provider_job_id, url),
        "original_title": title,
        "original_company": company,
        "original_location": location,
        "work_type": work_type,
        "seniority": seniority_label,
        "description_excerpt": description[:_DESCRIPTION_EXCERPT_LEN],
        "apply_url": url,
        "published_date": raw_date,
        "fetched_at": datetime.fromtimestamp(fetched_at, tz=timezone.utc).isoformat(),
        "listing_status": listing_status,
        "link_state": link_state,
        "link_reason": link_reason,
        "link_checked": False,
        "dedupe_basis": "",
        "provenance": {
            "title": {"value": title, "basis": "provider_field"},
            "country": {"value": country, "basis": basis_country},
            "city": {"value": city, "basis": basis_city},
            "work_type": {"value": work_type, "basis": basis_work_type},
            "seniority": {"value": seniority_label, "basis": "title_keyword"},
            "employment_type": {
                "value": employment_type,
                "basis": "provider_field" if employment_type else "unknown",
            },
            "is_expired": {"value": is_expired, "basis": "provider_signal"},
        },
        "observed_salary": [salary] if salary else [],
        "observed_employment_type": [employment_type] if employment_type else [],
        "observed_work_type": [work_type] if work_type != "unknown" else [],
        "observed_seniority": [seniority_label] if seniority_label else [],
        "observed_location": [location] if location else [],
    })
    return item


def _merge(raw_jobs):
    """Normalise + dedupe raw listings from all feeds into one list.

    Dedup priority (conservative — two uncertain vacancies are never merged just
    because their titles look alike):
      1. (provider, provider_job_id) — a repost of the SAME provider vacancy;
      2. canonical apply URL — one vacancy surfaced by two providers sharing the
         same apply link;
      3. title + company + location identity — only when neither a provider id
         nor a shared apply link exists.
    Conflicting sources are PRESERVED in ``observed_*`` lists; verified-dead
    links are kept as records (link-unavailable, provenance intact) instead of
    silently deleted, and are excluded from the surfaced feed downstream.
    """
    fetched_at = time.time()
    merged = {}
    _pop_index = {}
    for j in raw_jobs:
        title = (j.get("title") or "").strip()
        url = j.get("url") or j.get("link") or ""
        if not title or not url:
            continue
        item = normalise_listing(j, fetched_at=fetched_at)
        company = item["company"]
        location = item["location"]
        country = item["country"]

        def richness(x):
            return (2 if x.get("description") else 0) + \
                   (2 if x.get("salary") else 0) + \
                   (1 if x.get("employment_type") else 0) + \
                   min(3, len(x.get("tags") or []))

        def _observe(acc, value):
            v = str(value or "").strip()
            if v and v not in acc:
                acc.append(v)

        def _status_over(prev_s, new_s):
            """Priority: link-unavailable > expired > live — never hides evidence."""
            both = [s for s in (prev_s, new_s) if s]
            for priority in ("link-unavailable", "expired", "live"):
                if priority in both:
                    return priority
            return new_s or prev_s or "live"

        def prefer(prev, new):
            if not prev:
                return new
            richer_first = richness(new) >= richness(prev)
            if richer_first:
                merged_item = dict(new)
                merged_item["description"] = new.get("description") or prev.get("description") or ""
                merged_item["salary"] = new.get("salary") or prev.get("salary") or ""
                merged_item["employment_type"] = new.get("employment_type") or prev.get("employment_type") or ""
                merged_item["workplace_type"] = new.get("workplace_type") or prev.get("workplace_type") or ""
                merged_item["is_expired"] = new.get("is_expired") or prev.get("is_expired")
                merged_item["expires_at"] = new.get("expires_at") or prev.get("expires_at")
                merged_item["work_type"] = new.get("work_type") or prev.get("work_type") or "unknown"
                merged_item["seniority"] = new.get("seniority") or prev.get("seniority") or ""
            else:
                merged_item = dict(prev)
            merged_item["tags"] = list(dict.fromkeys(
                (prev.get("tags") or []) + (new.get("tags") or [])))[:6]
            merged_item["required_skills"] = _extract_required_skills(merged_item)
            merged_item["listing_status"] = _status_over(prev.get("listing_status"),
                                                         new.get("listing_status"))
            if merged_item.get("is_expired") and merged_item["listing_status"] == "live":
                merged_item["listing_status"] = "expired"
            # Best-link selection: when sources disagree on link safety the
            # SAFEST surviving URL wins for the surfaced record; the weaker
            # links are never deleted — they are preserved in ``observed_urls``.
            _link_rank = {"dead": 0, "rejected": 1, "unverified": 2}
            prev_rank = _link_rank.get(prev.get("link_state"), 1)
            new_rank = _link_rank.get(new.get("link_state"), 1)
            if new_rank > prev_rank:
                merged_item["url"] = new["url"]
                merged_item["apply_url"] = new["apply_url"]
                merged_item["link_state"] = new["link_state"]
                merged_item["link_reason"] = new.get("link_reason", "")
            elif new_rank < prev_rank:
                merged_item["url"] = prev["url"]
                merged_item["apply_url"] = prev["apply_url"]
                merged_item["link_state"] = prev["link_state"]
                merged_item["link_reason"] = prev.get("link_reason", "")
            merged_item["listing_status"] = (
                "link-unavailable"
                if merged_item.get("link_state") in ("dead", "rejected")
                else ("expired" if merged_item.get("is_expired") else "live"))
            merged_item["observed_urls"] = [u for u in dict.fromkeys(
                (prev.get("observed_urls") or []) + [prev.get("url", "")] +
                (new.get("observed_urls") or []) + [new.get("url", "")]) if u]
            # Conflict preservation — every observed variant survives.
            seen_titles = list(dict.fromkeys(
                (prev.get("observed_titles") or []) + [prev.get("title", "")] +
                (new.get("observed_titles") or []) + [new.get("title", "")]))
            merged_item["observed_titles"] = [t for t in seen_titles if t]
            for fld in ("salary", "employment_type", "work_type", "seniority", "location"):
                key = "observed_" + fld
                acc = list(dict.fromkeys((prev.get(key) or []) + (new.get(key) or [])))
                _observe(acc, new.get(fld))
                _observe(acc, prev.get(fld))
                if fld == "work_type":
                    acc = [v for v in acc if v != "unknown"]
                merged_item[key] = acc
            return merged_item

        loc_key = (_normalise_city(location) + "|" + _normalise_country(country).lower())
        pop_key = (_normalise_title_for_dedup(title) + "|" + company.lower() + "|" + loc_key)
        node_key = ("u:" + url.lower()) if url else None
        pid_key = (item["provider"] + "|" + item["provider_job_id"]) if item["provider_job_id"] else None

        dest = None
        basis = ""
        if pid_key and pid_key in merged:
            dest, basis = pid_key, "provider_id"
        elif node_key and node_key in merged:
            dest, basis = node_key, "apply_url"
        elif pop_key in merged:
            dest, basis = pop_key, "identity"
        elif pop_key in _pop_index:
            dest, basis = _pop_index[pop_key], "identity"
        elif pid_key:
            dest, basis = pid_key, "provider_id"
        elif node_key:
            dest, basis = node_key, "apply_url"
        else:
            dest = pop_key
        merged[dest] = prefer(merged.get(dest), item)
        merged[dest]["dedupe_basis"] = merged[dest].get("dedupe_basis") or basis
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
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        detail = f"{code} {exc.response.text[:80]}"
        if code == 429:
            _set_provider_cooldown("Remotive", "rate_limited")
            _record_status("Remotive", "failed", 0, reason="rate_limited", error=detail)
            logger.warning("job provider Remotive rate limited (cooldown set): %s", _redact(detail))
        elif code == 403:
            _set_provider_cooldown("Remotive", "forbidden")
            _record_status("Remotive", "failed", 0, reason="forbidden", error=detail)
            logger.warning("job provider Remotive forbidden (cooldown set): %s", _redact(detail))
        else:
            _record_status("Remotive", "failed", 0, reason="request_failed", error=detail)
            logger.warning("job provider Remotive failed: %s", _redact(detail))
        return []
    except httpx.TimeoutException as exc:
        _set_provider_cooldown("Remotive", "timeout")
        _record_status("Remotive", "failed", 0, reason="network_unreachable", error=str(exc))
        logger.warning("job provider Remotive timeout (cooldown set): %s", _redact(exc))
        return []
    except Exception as exc:
        _record_status("Remotive", "failed", 0, reason="network_error", error=str(exc))
        logger.warning("job provider Remotive failed: %s", _redact(exc))
        return []
    _record_status("Remotive", "ok", len(jobs))
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
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        detail = f"{code} {exc.response.text[:80]}"
        if code == 429:
            _set_provider_cooldown("RemoteOK", "rate_limited")
            _record_status("RemoteOK", "failed", 0, reason="rate_limited", error=detail)
            logger.warning("job provider RemoteOK rate limited (cooldown set): %s", _redact(detail))
        elif code == 403:
            _set_provider_cooldown("RemoteOK", "forbidden")
            _record_status("RemoteOK", "failed", 0, reason="forbidden", error=detail)
            logger.warning("job provider RemoteOK forbidden (cooldown set): %s", _redact(detail))
        else:
            _record_status("RemoteOK", "failed", 0, reason="request_failed", error=detail)
            logger.warning("job provider RemoteOK failed: %s", _redact(detail))
        return []
    except httpx.TimeoutException as exc:
        _set_provider_cooldown("RemoteOK", "timeout")
        _record_status("RemoteOK", "failed", 0, reason="network_unreachable", error=str(exc))
        logger.warning("job provider RemoteOK timeout (cooldown set): %s", _redact(exc))
        return []
    except Exception as exc:
        _record_status("RemoteOK", "failed", 0, reason="network_error", error=str(exc))
        logger.warning("job provider RemoteOK failed: %s", _redact(exc))
        return []
    _record_status("RemoteOK", "ok", len(jobs))
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
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            detail = f"{code} {exc.response.text[:80]}"
            if code == 429:
                _set_provider_cooldown("Adzuna", "rate_limited")
                _record_status("Adzuna", "failed", 0, reason="rate_limited", error=detail)
                logger.warning("job provider Adzuna rate limited (cooldown set): %s", _redact(detail))
            elif code == 403:
                _set_provider_cooldown("Adzuna", "forbidden")
                _record_status("Adzuna", "failed", 0, reason="forbidden", error=detail)
                logger.warning("job provider Adzuna forbidden (cooldown set): %s", _redact(detail))
            else:
                _record_status("Adzuna", "failed", 0, reason="request_failed", error=detail)
                logger.warning("job provider Adzuna failed: %s", _redact(detail))
            return []
        except httpx.TimeoutException as exc:
            _set_provider_cooldown("Adzuna", "timeout")
            _record_status("Adzuna", "failed", 0, reason="network_unreachable", error=str(exc))
            logger.warning("job provider Adzuna timeout (cooldown set): %s", _redact(exc))
            return []
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
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        detail = f"{code} {exc.response.text[:80]}"
        if code == 429:
            _set_provider_cooldown("Jobicy", "rate_limited")
            _record_status("Jobicy", "failed", 0, reason="rate_limited", error=detail)
            logger.warning("job provider Jobicy rate limited (cooldown set): %s", _redact(detail))
        elif code == 403:
            _set_provider_cooldown("Jobicy", "forbidden")
            _record_status("Jobicy", "failed", 0, reason="forbidden", error=detail)
            logger.warning("job provider Jobicy forbidden (cooldown set): %s", _redact(detail))
        else:
            _record_status("Jobicy", "failed", 0, reason="request_failed", error=detail)
            logger.warning("job provider Jobicy failed: %s", _redact(detail))
        return []
    except httpx.TimeoutException as exc:
        _set_provider_cooldown("Jobicy", "timeout")
        _record_status("Jobicy", "failed", 0, reason="network_unreachable", error=str(exc))
        logger.warning("job provider Jobicy timeout (cooldown set): %s", _redact(exc))
        return []
    except Exception as exc:
        _record_status("Jobicy", "failed", 0, reason="network_error", error=str(exc))
        logger.warning("job provider Jobicy failed: %s", _redact(exc))
        return []
    _record_status("Jobicy", "ok", len(jobs))
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
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        detail = f"{code} {exc.response.text[:80]}"
        if code == 429:
            _set_provider_cooldown("Arbeitnow", "rate_limited")
            _record_status("Arbeitnow", "failed", 0, reason="rate_limited", error=detail)
            logger.warning("job provider Arbeitnow rate limited (cooldown set): %s", _redact(detail))
        elif code == 403:
            _set_provider_cooldown("Arbeitnow", "forbidden")
            _record_status("Arbeitnow", "failed", 0, reason="forbidden", error=detail)
            logger.warning("job provider Arbeitnow forbidden (cooldown set): %s", _redact(detail))
        else:
            _record_status("Arbeitnow", "failed", 0, reason="request_failed", error=detail)
            logger.warning("job provider Arbeitnow failed: %s", _redact(detail))
        return []
    except httpx.TimeoutException as exc:
        _set_provider_cooldown("Arbeitnow", "timeout")
        _record_status("Arbeitnow", "failed", 0, reason="network_unreachable", error=str(exc))
        logger.warning("job provider Arbeitnow timeout (cooldown set): %s", _redact(exc))
        return []
    except Exception as exc:
        _record_status("Arbeitnow", "failed", 0, reason="network_error", error=str(exc))
        logger.warning("job provider Arbeitnow failed: %s", _redact(exc))
        return []
    _record_status("Arbeitnow", "ok", len(jobs))
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
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        detail = f"{code} {exc.response.text[:80]}"
        if code == 429:
            _set_provider_cooldown("Jooble", "rate_limited")
            _record_status("Jooble", "failed", 0, reason="rate_limited", error=detail)
            logger.warning("job provider Jooble rate limited (cooldown set): %s", _redact(detail))
        elif code == 403:
            _set_provider_cooldown("Jooble", "forbidden")
            _record_status("Jooble", "failed", 0, reason="forbidden", error=detail)
            logger.warning("job provider Jooble forbidden (cooldown set): %s", _redact(detail))
        else:
            _record_status("Jooble", "failed", 0, reason="request_failed", error=detail)
            logger.warning("job provider Jooble failed (optional): %s", _redact(detail))
        return []
    except httpx.TimeoutException as exc:
        _set_provider_cooldown("Jooble", "timeout")
        _record_status("Jooble", "failed", 0, reason="network_unreachable", error=str(exc))
        logger.warning("job provider Jooble timeout (cooldown set): %s", _redact(exc))
        return []
    except Exception as exc:
        _record_status("Jooble", "failed", 0, reason="network_unreachable", error=str(exc))
        logger.warning("job provider Jooble failed (optional): %s", _redact(exc))
        return []
    _record_status("Jooble", "ok", len(jobs))
    return jobs


def _fetch_himalayas(n):
    """Himalayas job board — keyless, public JSON.
    Endpoint: https://himalayas.app/jobs/api
    Provides structured salary, seniority, country, timezone."""
    jobs = []
    try:
        resp = httpx.get("https://himalayas.app/jobs/api", headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        for j in (resp.json().get("jobs") or [])[:n]:
            loc = (j.get("location") or "").strip()
            if j.get("isRemote"):
                loc = "Remote"
            tags = list((j.get("skills") or []) + (j.get("jobType") or []))
            jobs.append({
                "title": j.get("title"),
                "company": j.get("company", {}).get("name"),
                "url": j.get("url"),
                "date": (j.get("publishedAt") or "")[:10],
                "location": loc,
                "tags": tags,
                "description": j.get("description") or "",
                "employment_type": j.get("jobType") or "",
                "salary": _salary_str(j.get("salaryMin"), j.get("salaryMax")),
                "source": "Himalayas",
            })
        _record_status("Himalayas", "ok", len(jobs))
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        detail = f"{code} {exc.response.text[:80]}"
        if code == 429:
            _set_provider_cooldown("Himalayas", "rate_limited")
            _record_status("Himalayas", "failed", 0, reason="rate_limited", error=detail)
            logger.warning("job provider Himalayas rate limited (cooldown set): %s", _redact(detail))
        elif code == 403:
            _set_provider_cooldown("Himalayas", "forbidden")
            _record_status("Himalayas", "failed", 0, reason="forbidden", error=detail)
            logger.warning("job provider Himalayas forbidden (cooldown set): %s", _redact(detail))
        else:
            _record_status("Himalayas", "failed", 0, reason="request_failed", error=detail)
            logger.warning("job provider Himalayas failed: %s", _redact(detail))
        return []
    except httpx.TimeoutException as exc:
        _set_provider_cooldown("Himalayas", "timeout")
        _record_status("Himalayas", "failed", 0, reason="network_unreachable", error=str(exc))
        logger.warning("job provider Himalayas timeout (cooldown set): %s", _redact(exc))
        return []
    except Exception as exc:
        _record_status("Himalayas", "failed", 0, reason="network_error", error=str(exc))
        logger.warning("job provider Himalayas failed: %s", _redact(exc))
        return []
    _record_status("Himalayas", "ok", len(jobs))
    return jobs


def _fetch_getonboard(n):
    """Get on Board — keyless public JSON for tech jobs (LATAM + remote).
    Endpoint: https://www.getonbrd.com/api/v0/categories/programming/jobs"""
    jobs = []
    try:
        resp = httpx.get("https://www.getonbrd.com/api/v0/categories/programming/jobs", headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        for j in (resp.json().get("data") or [])[:n]:
            attrs = j.get("attributes") or {}
            loc = (attrs.get("location") or "").strip()
            if attrs.get("remote"):
                loc = "Remote"
            jobs.append({
                "title": attrs.get("title"),
                "company": (attrs.get("company") or {}).get("name"),
                "url": attrs.get("url"),
                "date": (attrs.get("publishedAt") or "")[:10],
                "location": loc,
                "tags": attrs.get("skills") or [],
                "description": attrs.get("description") or "",
                "employment_type": attrs.get("contractType") or "",
                "salary": attrs.get("salary") or "",
                "source": "Get on Board",
            })
        _record_status("Get on Board", "ok", len(jobs))
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        detail = f"{code} {exc.response.text[:80]}"
        if code == 429:
            _set_provider_cooldown("Get on Board", "rate_limited")
            _record_status("Get on Board", "failed", 0, reason="rate_limited", error=detail)
            logger.warning("job provider Get on Board rate limited (cooldown set): %s", _redact(detail))
        elif code == 403:
            _set_provider_cooldown("Get on Board", "forbidden")
            _record_status("Get on Board", "failed", 0, reason="forbidden", error=detail)
            logger.warning("job provider Get on Board forbidden (cooldown set): %s", _redact(detail))
        else:
            _record_status("Get on Board", "failed", 0, reason="request_failed", error=detail)
            logger.warning("job provider Get on Board failed: %s", _redact(detail))
        return []
    except httpx.TimeoutException as exc:
        _set_provider_cooldown("Get on Board", "timeout")
        _record_status("Get on Board", "failed", 0, reason="network_unreachable", error=str(exc))
        logger.warning("job provider Get on Board timeout (cooldown set): %s", _redact(exc))
        return []
    except Exception as exc:
        _record_status("Get on Board", "failed", 0, reason="network_error", error=str(exc))
        logger.warning("job provider Get on Board failed: %s", _redact(exc))
        return []
    _record_status("Get on Board", "ok", len(jobs))
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
            _set_provider_cooldown(name, "rate_limited")
            _record_status(name, "failed", 0, reason="rate_limited", error=detail)
            logger.warning("job provider %s rate limited (cooldown set): %s", name, _redact(detail))
        elif code == 403:
            _set_provider_cooldown(name, "forbidden")
            _record_status(name, "failed", 0, reason="forbidden", error=detail)
            logger.warning("job provider %s forbidden (cooldown set): %s", name, _redact(detail))
        else:
            _record_status(name, "failed", 0, reason="request_failed", error=detail)
            logger.warning("job provider %s failed (optional): %s", name, _redact(detail))
        return []
    except httpx.TimeoutException as exc:
        _set_provider_cooldown(name, "timeout")
        _record_status(name, "failed", 0, reason="network_unreachable", error=str(exc))
        logger.warning("job provider %s timeout (cooldown set): %s", name, _redact(exc))
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
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        detail = f"{code} {exc.response.text[:80]}"
        if code == 429:
            _set_provider_cooldown("JSearch", "rate_limited")
            _record_status("JSearch", "failed", 0, reason="rate_limited", error=detail)
            logger.warning("job provider JSearch rate limited (cooldown set): %s", _redact(detail))
        elif code == 403:
            _set_provider_cooldown("JSearch", "forbidden")
            _record_status("JSearch", "failed", 0, reason="forbidden", error=detail)
            logger.warning("job provider JSearch forbidden (cooldown set): %s", _redact(detail))
        else:
            _record_status("JSearch", "failed", 0, reason="request_failed", error=detail)
            logger.warning("job provider JSearch failed: %s", _redact(detail))
        return []
    except httpx.TimeoutException as exc:
        _set_provider_cooldown("JSearch", "timeout")
        _record_status("JSearch", "failed", 0, reason="network_unreachable", error=str(exc))
        logger.warning("job provider JSearch timeout (cooldown set): %s", _redact(exc))
        return []
    except Exception as exc:
        _record_status("JSearch", "failed", 0, reason="request_failed", error=str(exc))
        logger.warning("job provider JSearch failed: %s", _redact(exc))
        return []
    _record_status("JSearch", "ok", len(jobs))
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
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        detail = f"{code} {exc.response.text[:80]}"
        if code == 429:
            _set_provider_cooldown("USAJobs", "rate_limited")
            _record_status("USAJobs", "failed", 0, reason="rate_limited", error=detail)
            logger.warning("job provider USAJobs rate limited (cooldown set): %s", _redact(detail))
        elif code == 403:
            _set_provider_cooldown("USAJobs", "forbidden")
            _record_status("USAJobs", "failed", 0, reason="forbidden", error=detail)
            logger.warning("job provider USAJobs forbidden (cooldown set): %s", _redact(detail))
        else:
            _record_status("USAJobs", "failed", 0, reason="request_failed", error=detail)
            logger.warning("job provider USAJobs failed: %s", _redact(detail))
        return []
    except httpx.TimeoutException as exc:
        _set_provider_cooldown("USAJobs", "timeout")
        _record_status("USAJobs", "failed", 0, reason="network_unreachable", error=str(exc))
        logger.warning("job provider USAJobs timeout (cooldown set): %s", _redact(exc))
        return []
    except Exception as exc:
        _record_status("USAJobs", "failed", 0, reason="request_failed", error=str(exc))
        logger.warning("job provider USAJobs failed: %s", _redact(exc))
        return []
    _record_status("USAJobs", "ok", len(jobs))
    return jobs


def _set_report_in_thread(report):
    """ThreadPoolExecutor initializer: workers record into the build's report."""
    _thread_local.report = report


def _fetch_all(limit_each, keywords=(), country="", adzuna_country="", report=None):
    """Fetch from all job feeds in parallel. Uses short timeouts to avoid blocking the
    request thread for too long. Each feed is tried independently so a
    slow/unreachable feed doesn't prevent the others from returning.

    When ``report`` is supplied (a dict keyed by provider name), every outcome —
    including the cooldown-skip branch and the executor threads — is recorded
    into THAT report so concurrent builds can never see each other's provider
    status. Without a report, outcomes update the global snapshot (standalone
    callers / tests). A ``request_id`` on the report threads through every
    log line for auditability.
    """
    # Country-scoped feeds follow the relocation market (codes → names, so
    # JSearch/Jooble get readable locations like "United Kingdom" / "Egypt").
    market_name = _normalise_country(adzuna_country) if adzuna_country else ""
    exec_loc = market_name or _normalise_country(country)
    rid = (report or {}).get("request_id", "") if report else ""
    prefix = f"[{rid}] " if rid else ""
    calls = [
        ("Remotive", lambda: _fetch_remotive(max(limit_each, 40))),
        ("RemoteOK", lambda: _fetch_remoteok(max(limit_each, 40))),
        ("Adzuna", lambda: _fetch_adzuna(max(limit_each, 40), list(keywords), exec_loc)),
        ("Jobicy", lambda: _fetch_jobicy(max(limit_each, 25))),
        ("Arbeitnow", lambda: _fetch_arbeitnow(max(limit_each, 25))),
        ("Himalayas", lambda: _fetch_himalayas(max(limit_each, 25))),
        ("Get on Board", lambda: _fetch_getonboard(max(limit_each, 25))),
        ("Jooble", lambda: _fetch_jooble(max(limit_each, 25), list(keywords), exec_loc)),
        ("JSearch", lambda: _fetch_jsearch(max(limit_each, 25), list(keywords), exec_loc)),
        ("LinkedIn", lambda: _fetch_linkedin_jobs(max(limit_each, 25), list(keywords), exec_loc)),
        ("Google Jobs", lambda: _fetch_google_jobs(max(limit_each, 25), list(keywords), exec_loc)),
        ("USAJobs", lambda: _fetch_usajobs(max(limit_each, 15), list(keywords), exec_loc)),
    ]

    if report is not None:
        _thread_local.report = report
    try:
        jobs = []
        with ThreadPoolExecutor(max_workers=len(calls),
                                initializer=_set_report_in_thread, initargs=(report,)) as ex:
            futures = {}
            for name, fn in calls:
                if _provider_feature_flag_disabled(name):
                    logger.info("%sjob provider %s disabled by feature flag", prefix, name)
                    _skip_status(name, "disabled_by_feature_flag")
                    continue
                if _is_provider_cooled_down(name):
                    cd = _PROVIDER_COOLDOWN.get(name) or {}
                    logger.info("%sjob provider %s skipped (cooldown: %s)", prefix, name,
                                cd.get("reason") or "active")
                    _record_status(name, "skipped", 0, reason="cooldown",
                                    error=(cd.get("reason") or "")[:120])
                    continue
                futures[ex.submit(fn)] = name
            for fut in futures:
                name = futures[fut]
                try:
                    jobs.extend(fut.result())
                except Exception as e:
                    # Each fetch internally catches and logs; this is defense in depth.
                    _record_status(name, "failed", reason="internal_error", error=str(e))
            for name in PROVIDERS:
                entry = (report if report is not None else _provider_status).get(name) or {}
                if (entry.get("status") == "skipped" and entry.get("count") == 0
                        and not (entry.get("reason") or entry.get("error"))):
                    continue
                logger.info("%sprovider %s -> %s (%d jobs, %s)", prefix, name,
                            _health_of(entry, name), entry.get("count") or 0,
                            entry.get("reason") or entry.get("error") or "")
        return jobs
    finally:
        if report is not None:
            _thread_local.report = None


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


def _build_result(key, skills, role, country, location, limit, role_requisites=(),
                  market_country="", request_id=""):
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

    # A clean per-build provider report — never a shared global — so concurrent
    # builds for different keys can't see or corrupt each other's outcomes.
    report = {p: {"status": "skipped", "count": 0, "reason": "", "error": ""}
              for p in PROVIDERS}
    report["request_id"] = request_id
    _t0 = time.time()
    raw = _fetch_all(limit * 3, search_terms, user_country, adzuna_country=market_country or "",
                     report=report)
    _t1 = time.time()
    with _lock:
        _stats["fetch_times"].append(_t1 - _t0)
        del _stats["fetch_times"][:-_FETCH_TIMES_MAX]
    merged = _merge(raw)

    # Rerank after dedup, before cache write (per spec)
    student_verified = [s for s in verified_skills]
    student_gaps = [r for r in role_requisites or () if r not in skill_names]
    merged.sort(key=lambda j: _rerank_score(j, role, student_verified, student_gaps,
                                             location, role_family), reverse=True)

    # Only listings that are still live make the feed — expired/stale ones
    # (provider close dates passed, availability flags, or postings older than
    # MAX_LISTING_AGE_DAYS) and verified-dead/rejected links are dropped from
    # the SURFACED list (their records + provenance stay in the merge output).
    live_jobs = [j for j in merged
                 if not j.get("is_expired")
                 and j.get("listing_status") != "link-unavailable"]
    if live_jobs:
        jobs = live_jobs
        feed_source = "live"
    elif _any_provider_ok(report):
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

    _rid = request_id or ""
    _prefix = f"[{_rid}] " if _rid else ""
    data = {
        "source": feed_source,
        "status": "fresh",
        "jobs": selected[:limit],
        "groups": {
            "local_count": len(local),
            "broader_count": len(broader),
            "other_count": len(other),
        },
        "providers": [
            {
                "source": p,
                "status": report[p]["status"],
                "count": report[p]["count"],
                "reason": report[p]["reason"],
                "error": report[p]["error"],
                "health": _health_of(report[p], p),
            }
            for p in PROVIDERS
        ],
    }

    now = time.time()
    with _lock:
        # Bounded LRU write: refresh recency, evict the oldest expired/far end
        # beyond the cap. The report is committed ONLY at the end of a finished
        # build so the health view never sees another build's mid-fetch state.
        _cache[key] = {"at": now, "data": data}
        _cache.move_to_end(key)
        while len(_cache) > _get_max_entries():
            _cache.popitem(last=False)
        _provider_status.update({k: v for k, v in report.items() if k in PROVIDERS})
        _stats["last_build_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _bg_fetching.discard(key)
    logger.info("%sjob build complete feed=%s jobs=%d", _prefix, feed_source, len(selected[:limit]))
    return data


def _background_fetch(key, skills, role, country, location, limit, role_requisites=(),
                      market_country="", request_id=""):
    """Run _build_result in a daemon thread so the HTTP request returns fast."""
    def _worker():
        try:
            _build_result(key, skills, role, country, location, limit,
                          role_requisites=role_requisites, market_country=market_country,
                          request_id=request_id)
        except Exception:
            with _lock:
                _bg_fetching.discard(key)
    t = threading.Thread(target=_worker, daemon=True)
    t.start()

def recent_jobs(skills=(), role="", country="", location="", limit=10, _sync=False,
                role_requisites=(), market_country="", request_id=""):
    """Return ``{source, jobs, groups}`` ranked most → least fitting for the profile.

    ``skills`` is a list of ``(name, level)`` or ``(name, level, verified)``
    tuples (the student's own skills; the final flag marks VERIFIED skills,
    which earn a small evidence boost in ranking). ``role`` is the display title
    of their target career. ``country`` and ``location`` are their profile
    region. ``role_requisites`` are the target role's required-skill names (the
    career's own vocabulary, for role-driven relevance weighting).
    ``market_country`` is an optional remote/relocation search target for feeds
    like Adzuna. ``limit`` affects the returned slice and is part of the cache
    key, so two callers with different limits can never reuse each other's rows.
    ``request_id`` threads through the provider fetch for auditability.

    Status vocabulary in the response (additive ``status`` next to the existing
    ``source``):
    - ``fresh``          just built by this call;
    - ``cached``         a fresh cached row whose TTL has not elapsed;
    - ``stale_fallback`` a row past TTL, served as-is while a background
                          refresh runs (never curated/demo jobs);
    - ``unavailable``    nothing cached for this key yet — an empty response is
                          returned immediately and live data is fetched in a
                          background thread so the dashboard never freezes.

    When ``_sync=True`` (used by tests), the fetch runs synchronously so
    monkeypatched ``_fetch_all`` results are returned directly.
    """
    key = _cache_key(skills, role, country, location, role_requisites,
                       market_country, limit)
    now = time.time()
    ttl = _get_ttl_seconds()

    with _lock:
        entry = _cache.get(key)
        if entry is not None:
            _cache.move_to_end(key)
    if entry is not None and now - entry["at"] < ttl:
        with _lock:
            _stats["cache_hits"] += 1
        logger.debug("jobs cache hit: key=%s age=%.1fs", key, now - entry["at"])
        return {**entry["data"], "status": "cached"}

    with _lock:
        _stats["cache_misses"] += 1

    if _sync:
        return _build_result(key, skills, role, country, location, limit,
                               role_requisites=role_requisites, market_country=market_country,
                               request_id=request_id)

    if entry is not None:
        # Expired but present: serve the last honest data as stale_fallback and
        # refresh in the background (one refresh per key, deduped atomically).
        logger.debug("jobs cache stale: key=%s age=%.1fs", key, now - entry["at"])
        _maybe_background_fetch(key, skills, role, country, location, limit,
                                role_requisites=role_requisites, market_country=market_country,
                                request_id=request_id)
        return {**entry["data"], "status": "stale_fallback"}

    # Cache miss — kick off a background fetch and return an honest
    # ``unavailable`` empty response immediately so the dashboard request never
    # blocks on external HTTP calls. Curated/demo jobs are never served here.
    logger.debug("jobs cache miss: key=%s", key)
    _maybe_background_fetch(key, skills, role, country, location, limit,
                            role_requisites=role_requisites, market_country=market_country,
                            request_id=request_id)
    return {
        "source": "unavailable",
        "status": "unavailable",
        "jobs": [],
        "groups": {"local_count": 0, "broader_count": 0, "other_count": 0},
        "providers": [],
    }


def _maybe_background_fetch(key, skills, role, country, location, limit,
                            role_requisites=(), market_country="", request_id=""):
    """Kick exactly one background fetch per key (atomic check+add under lock)."""
    with _lock:
        if key in _bg_fetching:
            return False
        _bg_fetching.add(key)
    _background_fetch(key, skills, role, country, location, limit,
                      role_requisites=role_requisites, market_country=market_country,
                      request_id=request_id)
    return True
