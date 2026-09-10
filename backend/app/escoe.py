"""Real market occupations from the European Commission's ESCO taxonomy.

ESCO (European Skills, Competences, Qualifications and Occupations) is an
official, open-data occupation catalogue. It lets SkillBridge surface actual
titles that exist in the labour market (e.g. "data scientist") together with
the essential skills those jobs require, so the Skills & Roles page can show
real job reality instead of only company-defined catalog roles.

Thin, cached client over two public ESCO REST endpoints (no key required):
- GET /api/search?text=...&type=occupation -> occupation titles
- GET /api/resource/occupation?uri=...      -> essential skills per occupation

ESCO's own search order is lexical (a query like "cybersecurity analyst" ranks
every occupation containing an "analyst" token, and misses the ICT security
occupations entirely). This module therefore uses ESCO only for *candidate
retrieval* (broad, deduplicated) and re-ranks the candidates itself with a
general-purpose, multi-signal relevance scorer:

1. Retrieval is widened: the raw text, compound-split variants of long tokens
   ("cybersecurity" -> "cyber security") and the individual tokens are all
   searched and merged, so the occupation the user actually means has a chance
   to be in the candidate pool even when ESCO's first page misses it.
2. Occupations are ranked by a weighted combination of:
   - title similarity (token overlap + character n-gram phrase similarity),
   - description/definition overlap (semantic context, not isolated words),
   - essential/optional skill evidence, with generic transferable skills
     (communication, data analysis, statistics, planning, ...) penalised,
   - ISCO-08 professional-domain compatibility between the candidate and the
     inferred domain of the query (occupations that merely share a head word —
     e.g. "security" in "security guard" vs "ICT security consultant" — are
     separated by their ISCO group).
3. A minimum-relevance threshold filters candidates that have no real
   connection to the query, so generic-token matches do not surface.

The query's *head* token is chosen to be the discriminating domain word, not a
generic role tail: a query like "software engineer" / "data scientist" /
"marketing manager" pairs a domain token with a shared role word ("engineer",
"scientist", "manager" ...) that many unrelated occupations carry, so the
ISCO-domain evidence is anchored on the domain token instead. A candidate
matches that domain only by a containment substring ("mechanic" inside
"mechanical", or "security" inside "cybersecurity") in a different ISCO major
group is treated as a false friend unless the candidate itself shows
information-technology vocabulary (which is how the ICT security family wins
"cybersecurity").

The algorithm is intentionally free of per-occupation rules: it behaves the
same for cybersecurity, accounting, nursing, teaching, mechanical engineering,
design, marketing, data science, and any other career path.

Results are cached in memory for a short TTL. When ESCO is unreachable, the
caller gets an empty list so the UI degrades cleanly.
"""
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from . import role_intent

ESCO_SEARCH_URL = "https://ec.europa.eu/esco/api/search"
ESCO_OCC_URL = "https://ec.europa.eu/esco/api/resource/occupation"
TTL_SECONDS = 30 * 60

_POOL_CAP = 42
_MAX_SUBQUERIES = 5
_MIN_RELEVANCE = 0.26
# Enrichment is one HTTP round-trip per candidate (sub-second when ESCO is
# healthy, up to 8s each on a slow day). Capping how many pooled candidates get
# enriched bounds a single request's worst-case latency instead of letting it
# stall for minutes (which manifests as a dropped browser fetch / "Failed to
# fetch"). Remaining candidates still rank on title/ISCO signals.
_ENRICH_CAP = 20
# Bounded concurrent enrichment. `_enrich` is one synchronous HTTP round-trip
# per candidate (sub-second on a healthy ESCO, up to 8s each when degraded).
# With _ENRICH_CAP=20 sequential fetches the worst case is ~160s, which is long
# enough for a browser fetch() to give up and the user to see a raw "Failed to
# fetch". Running a bounded pool concurrently collapses that worst case to
# ~8s * ceil(20 / workers). Workers deliberately small so we never hammer ESCO.
_ENRICH_WORKERS = 6
# A containment-only head match ("security" inside "cybersecurity") in a
# *different* ISCO sub-major group is treated as a false friend and capped
# below the relevance threshold. 0.9 == token equality / strict plural.
_HEAD_MATCH_KIND = 0.8
_FALSE_FRIEND_CAP = 0.18

# Per ESCO API policy, no special User-Agent is required, but one is sent so
# their access logs distinguish the app.
_HEADERS = {"User-Agent": "SkillBridge/1.0 (career platform; ESCO client)"}

_cache = {"at": 0.0, "query": "", "data": None}
_skills_cache = {"at": 0.0, "key": None, "data": None}
_lock = threading.Lock()

# Function words / generic search noise. Kept deliberately small and
# language-level (not occupation-specific).
_STOPWORDS = frozenset(
    "a an and the of in for on to from with at by or as is are was were be been "
    "being have has had do does did job jobs role position opening vacancy "
    "vacancies senior junior entry level middle".split()
)

# Common transferable skills that appear across many unrelated occupations.
# Matching one of these is weak evidence of career relevance, so they are
# penalised inside the skill-evidence signal.
_GENERIC_SKILLS = frozenset(
    "communication written communication oral communication teamwork "
    "collaboration report writing writing time management planning "
    "organising organization decision making problem solving management "
    "coordination leadership supervision customer service adaptability "
    "learning teaching mentoring interviewing data analysis statistics "
    "statistical analysis analysis research evaluation monitoring "
    "documentation presentation negotiation networking project management "
    "quality assurance quality management business processes process "
    "improvement compliance budgeting financial management strategic "
    "planning risk management stakeholder management digital literacy "
    "computer literacy analytical thinking attention to detail listening "
    "flexibility languages conflict management change management "
    "organisation innovation creativity".split()
)

# Orthographic hint only: common English compound tails used to widen
# retrieval for long single words ("cybersecurity" -> "cyber security").
# This is language-level morphology, not an occupation list.
_COMPOUND_TAILS = frozenset(
    "security engineering engineer scientist science technology management "
    "administration consultant officer analyst manager system systems "
    "technician researcher research services operator developer designer "
    "teacher nurse journalism marketing".split()
)

# Sector-context words for information-technology compounds. When the query's
# head token is itself a compound that ends in a generic ISCO tail ("cyber-
# security"), a candidate that matches that head only through the shared tail
# ("security guard", "social security administrator") needs to additionally
# demonstrate information-technology context in its title, definition or
# skills; otherwise the head match is treated as a false friend. This is a
# vocabulary-level (sector) hint, not an occupation list: non-ICT queries such
# as "accountant" or "nurse" never trigger it. Words are deliberately strict
# (equal/plural token matches only, never substring containment, and no
# ambiguous words like "systems" or "information") so physical-security and
# social-welfare occupations cannot inherit ICT context.
_ICT_HINTS = frozenset(
    "ict cyber cybersecurity network networking software computer "
    "computing digital internet online web database programming "
    "coding forensic telecommunication data".split()
)


def _words(text):
    return re.findall(r"[a-zA-Z]+", (text or "").lower())


def _content(text):
    """Meaningful tokens: drop function words / search noise."""
    return [w for w in _words(text) if w not in _STOPWORDS]


def _ngrams3(s):
    if len(s) < 3:
        return {s} if s else set()
    return {s[i:i + 3] for i in range(len(s) - 2)}


def _dice(a, b):
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


def _norm_phr(text):
    return re.sub(r"[^a-z]", "", (text or "").lower())


def _plural_y_ies(x, y):
    return x.endswith("y") and y == x[:-1] + "ies"


def _root_related(a, b):
    """Shared root with modest length difference, excluding the -y/-ies false
    friend pair ("security" vs "securities") which is the exact kind of
    morphological trap that conflates unrelated financial occupations with
    cybersecurity careers."""
    if len(a) < 5 or len(b) < 5:
        return False
    if (a.endswith("ies") and b.endswith("y")) or (b.endswith("ies") and a.endswith("y")):
        return False
    n = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        n += 1
    if n < 5:
        return False
    return abs(len(a) - len(b)) <= 2


def _token_pair(a, b):
    """Lexical relatedness of two tokens, 0..1.

    >1.0 equal
    >0.95 strict plural variant
    >0.85 containment (compound suffix, e.g. "security" in "cybersecurity")
    >0.65 shared root ("accounting"/"accountant", "design"/"designer")
    >0.0 otherwise
    """
    if a == b:
        return 1.0
    if (a + "s" == b) or (b + "s" == a) or (a + "es" == b) or (b + "es" == a):
        return 0.95
    if _plural_y_ies(a, b) or _plural_y_ies(b, a):
        return 0.95
    if min(len(a), len(b)) >= 4 and (a in b or b in a):
        return 0.85
    if _root_related(a, b):
        return 0.65
    return 0.0


def _parse_code(raw):
    """Normalise an ESCO/ISCO-08 code ("3341.1", "C3341") to its 4-digit unit
    group ("3341"). Returns None when no usable code is present."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None
    return digits[:4] if len(digits) >= 4 else digits


def _search(text, limit=30):
    resp = httpx.get(ESCO_SEARCH_URL,
                     params={"language": "en", "text": text, "type": "occupation"},
                     headers=_HEADERS, timeout=8)
    resp.raise_for_status()
    payload = resp.json()
    return (payload.get("_embedded") or {}).get("results") or []


def _compound_split(word):
    """Best-effort split of a long compound word into a two-token query using a
    generic English compound-tail hint ("cybersecurity" -> "cyber security").
    Returns None when no plausible lexical split exists."""
    if len(word) < 8:
        return None
    for i in range(len(word) - 2, 2, -1):
        head, tail = word[:i], word[i:]
        if len(head) >= 3 and len(tail) >= 3 and tail in _COMPOUND_TAILS:
            return f"{head} {tail}"
    return None


def _retrieve(text):
    """Collect a deduplicated candidate pool from several ESCO search queries.

    The raw query string is always searched first (it is the strongest intent
    signal). Long compound tokens get a split variant, and the individual
    content tokens are appended until the sub-query budget is used up.
    """
    words = _content(text) or _words(text)
    if not words:
        return []
    queries = [text]
    splits = []
    for w in words:
        s = _compound_split(w)
        if s and s not in queries and len(queries) + 1 < _MAX_SUBQUERIES:
            queries.append(s)
            splits.append(w)
    for w in words:
        if len(queries) >= _MAX_SUBQUERIES:
            break
        if w not in queries:
            queries.append(w)
    pool = {}
    for q in queries:
        try:
            for occ in _search(q, _POOL_CAP):
                uri = occ.get("uri")
                title = occ.get("title")
                if not uri or not title:
                    continue
                if uri not in pool:
                    pool[uri] = {
                        "title": title,
                        "uri": uri,
                        "code": _parse_code(occ.get("code")),
                        "description": None,
                        "skills": [],
                    }
        except Exception:
            continue
        if len(pool) >= _POOL_CAP:
            break
    return list(pool.values())[:_POOL_CAP]


def _enrich(entry):
    """Fetch the occupation resource (definition + essential/optional skills)
    for one candidate. Best effort; a failing candidate keeps its search-level
    metadata so ranking can still use title and ISCO code."""
    try:
        resp = httpx.get(ESCO_OCC_URL,
                         params={"uri": entry["uri"], "language": "en"},
                         headers=_HEADERS, timeout=8)
        resp.raise_for_status()
        payload = resp.json()
        desc_map = payload.get("description") or {}
        desc = desc_map.get("literal") or desc_map.get("en") or None
        if not isinstance(desc, str) and isinstance(desc, dict):
            desc = desc.get("literal") or desc.get("en") or None
        links = payload.get("_links") or {}
        essential = [s.get("title") for s in (links.get("hasEssentialSkill") or []) if s.get("title")]
        optional = [s.get("title") for s in (links.get("hasOptionalSkill") or []) if s.get("title")]
        if isinstance(desc, str) and desc:
            entry["description"] = desc
        entry["_essential"] = essential
        entry["_optional"] = optional[:12]
        entry["skills"] = (essential + optional)[:16]
        if not entry["code"] and payload.get("code"):
            entry["code"] = _parse_code(payload.get("code"))
    except Exception:
        pass


def _enrich_pool(pool):
    """Enrich up to ``_ENRICH_CAP`` candidates with bounded concurrency so the
    worst-case latency of one request is a few seconds instead of the ~160s a
    fully sequential run could reach (see ``_ENRICH_WORKERS`` note). Best effort;
    a failing candidate keeps its search-level metadata and ranking still works."""
    targets = pool[:_ENRICH_CAP]
    if not targets:
        return
    if len(targets) <= 1:
        _enrich(targets[0])
        return
    with ThreadPoolExecutor(max_workers=_ENRICH_WORKERS) as ex:
        list(ex.map(_enrich, targets))


def _score_enrich_score(cands, text, limit):
    """Score -> keep survivors -> enrich ONLY survivors -> re-score with skills.

    The raw pool is often far larger than ``_ENRICH_CAP`` (e.g. 90+ occupations
    for a "cybersecurity analyst" query). Enriching only the *pool head* before
    ranking leaves the actual winners -- which can live anywhere in the pool --
    with zero skill data and turns every result card into "0 essential skills".
    This bounds enrichment to the top ``max(limit*2, _ENRICH_CAP)`` candidates by
    search-metadata relevance, then re-ranks them with the skill evidence
    present.
    """
    if not cands:
        return []
    def _score_all(rows):
        try:
            return _score_occupations(text, rows)
        except Exception:
            return []

    ranked = _score_all(cands)
    if not ranked:
        return []
    # Enrich before thresholding: thresholding first would starve every
    # below-threshold row of the skill evidence that would lift it above (e.g.
    # "ethical hacker" reaches the head only through a skill's "cyber" token,
    # which has zero weight while skills are still empty).
    window = ranked[:max(limit * 2, _ENRICH_CAP)]
    if not window:
        return []
    _enrich_pool(window)
    rescored = _score_all(window)
    survivors = [e for e in rescored if e["score"] >= _MIN_RELEVANCE]
    if not survivors:
        survivors = rescored
    return survivors[:max(limit, 1)]


def _isco_group(code):
    if not code:
        return None
    return str(code)


def _has_ict_context(entry):
    """True when a candidate's title, definition or skills use
    information-technology vocabulary (docstring above). Tokens must match a
    hint word exactly or by plural form -- substring containment is rejected so
    generic phrases like "security systems" cannot create ICT context."""
    tokens = set(_words(entry.get("title")))
    raw = entry.get("description")
    tokens.update(_words(raw if isinstance(raw, str) else ""))
    for skill in entry.get("skills") or []:
        tokens.update(_words(skill))
    for t in tokens:
        for h in _ICT_HINTS:
            if t == h or _plural_y_ies(t, h) or _plural_y_ies(h, t):
                return True
    return False


def _domain_similarity(cand_code, anchor_code):
    """ISCO-08 field compatibility between two occupation codes.

    The ISCO-08 classification encodes both a professional field (the last
    digit of the 2-digit sub-major group) and a skill level (major group:
    2 = professionals, 3 = technicians and associate professionals). Each
    professional sub-major ``2X`` has a sibling technician sub-major ``3X`` in
    the same field (ICT professionals 25 / ICT technicians 35, science 21/31,
    health 22/32, legal-social 24/34). Scores:

    same unit group -> 1.0; same sub-major -> 0.9; professional<->technician
    sibling in the same field -> 0.7; same major group -> 0.4; unrelated
    groups -> 0.15. Missing codes are neutral (0.5).
    """
    if not cand_code or not anchor_code:
        return 0.5
    cand = str(cand_code)[:4]
    anchor = str(anchor_code)[:4]
    if cand == anchor:
        return 1.0
    if cand[:2] == anchor[:2]:
        return 0.9
    if cand[0] != anchor[0] and cand[1] == anchor[1]:
        return 0.7
    if cand[0] == anchor[0]:
        return 0.4
    return 0.15


def _score_occupations(text, cands):
    """Rank candidates against a free-text query using all retrieval signals.

    The query's head token (highest corpus specificity) anchors intent: a
    candidate that does not match it in title/description is heavily limited,
    and a candidate that matches it only through a shared generic containment
    tail ("security" inside "cybersecurity") in a different ISCO major group is
    treated as a false friend (e.g. "security guard" / "social security
    administrator" versus "ICT security consultant").

    For compound head tokens ("cybersecurity" -> "cyber security") the pool's
    occupancy of information-technology context decides whether containment
    matches are legitimate: if ICT-context candidates exist, candidates that
    reach the head only via the generic tail *and* show no ICT vocabulary in
    their own title/definition/skills are capped below the relevance
    threshold. This is a vocabulary-level rule, not an occupation list.
    """
    q = _content(text) or _words(text)
    if not q:
        return []
    q = list(dict.fromkeys(q))
    corpus = len(cands)
    df = {}
    for c in cands:
        seen = set(_words(c["title"]))
        seen.update(_words(c.get("description") or ""))
        for w in seen:
            df[w] = df.get(w, 0) + 1
    idf = {w: math.log1p(corpus / (1.0 + df.get(w, 0))) for w in q}
    max_idf = max(idf.values()) if idf else 0.0
    weight = {w: (idf[w] / max_idf if max_idf else 1.0) for w in q}

    # A query like "software engineer"/"data scientist"/"marketing manager"
    # pairs a *domain* token with a generic role tail ("engineer", "scientist",
    # "manager", ... — see _COMPOUND_TAILS). The tail is shared by many
    # unrelated occupations, so when a non-tail token exists the most
    # discriminating token should anchor intent: "software" must outrank
    # "engineer" (otherwise satellite/mechatronics engineers hijack the pool).
    has_tail = any(w in _COMPOUND_TAILS for w in q)
    non_tail = [w for w in q if w not in _COMPOUND_TAILS]
    # A head token that cannot match any candidate title in the pool has no
    # discriminatory power (e.g. "registered" for "registered nurse": it wins
    # the highest idf weight yet nothing in the pool contains it, collapsing
    # every score to that of its tail alone). Exclude such tokens from
    # consideration — but judge viability with the same _token_pair matching
    # the head uses, so split/containment forms ("cybersecurity" matching a
    # title's "security") stay viable.
    title_words = {w for c in cands for w in _words(c["title"]) if w not in _STOPWORDS}
    viable = [w for w in non_tail if any(_token_pair(w, t2) > 0 for t2 in title_words)]
    if not viable:
        viable = [w for w in q if any(_token_pair(w, t2) > 0 for t2 in title_words)] or q
    # Prefer the domain token ("software" in "software engineer") over the
    # generic role tail that many unrelated occupations share.
    head = max(viable, key=lambda w: (weight[w], len(w)))
    total_w = sum(weight.values())

    compound_head = _compound_split(head) is not None
    ict_available = compound_head and any(_has_ict_context(c) for c in cands)

    base = []
    for c in cands:
        title = [w for w in _words(c["title"]) if w not in _STOPWORDS]
        raw_desc = c.get("description")
        desc = [w for w in _words(raw_desc if isinstance(raw_desc, str) else "") if w not in _STOPWORDS]
        t_phr = _dice(_ngrams3(_norm_phr(text)), _ngrams3(_norm_phr(c["title"])))

        head_kind = max((_token_pair(head, t2) for t2 in title), default=0.0)

        title_hits = 0.0
        for w in q:
            best = 0.0
            for t2 in title:
                p = _token_pair(w, t2)
                if p > best:
                    best = p
            if best:
                title_hits += weight[w] * best
        title_overlap = title_hits / total_w if total_w else 0.0
        head_in_title = head_kind >= 0.8
        title_score = 0.7 * title_overlap + 0.3 * t_phr
        if not head_in_title:
            title_score *= 0.45

        desc_hits = 0.0
        for w in q:
            best = 0.0
            for t2 in desc:
                p = _token_pair(w, t2)
                if p > best:
                    best = p
            if best:
                desc_hits += weight[w] * best
        if desc:
            desc_score = desc_hits / total_w if total_w else 0.0
        else:
            desc_score = 0.15 * title_overlap
        # A title that contains no trace of the query's domain word is a much
        # weaker match than a title that does; halve the description evidence
        # so description-rich but title-unrelated occupations (e.g. an ICT
        # network engineer for a "software engineer" query) do not outrank
        # titles that actually name the domain.
        if head_kind == 0.0:
            desc_score *= 0.5

        spec = 0.0
        generic = 0.0
        head_in_skills = False
        for skill in c["skills"]:
            sw = [w for w in _words(skill) if w not in _STOPWORDS]
            if not sw:
                continue
            best = 0.0
            for w in q:
                for t2 in sw:
                    p = _token_pair(w, t2)
                    if p > best:
                        best = p
            if best >= 0.6:
                if any(t in _GENERIC_SKILLS for t in sw):
                    generic += best
                else:
                    spec += best
                if any(_token_pair(head, t2) >= 0.8 for t2 in sw):
                    head_in_skills = True
        skill_score = min(1.0,
                          (spec / max(1, len(q)))
                          + (0.4 if head_in_skills else 0.0)
                          + min(0.15, generic / max(2 * len(q), 1)))

        title_for_phr = [w for w in _words(c["title"]) if w not in _STOPWORDS]
        matched_anywhere = any(
            _token_pair(w, t2) >= 0.6
            for w in q for t2 in (title_for_phr + desc))
        phr = _dice(_ngrams3(_norm_phr(text)), _ngrams3(_norm_phr(c["title"])))

        base.append({
            **_bare(c),
            "_title": title_score,
            "_desc": desc_score,
            "_skill": skill_score,
            "_head_kind": head_kind,
            "_ict": _has_ict_context(c),
            "_matched": matched_anywhere,
            "_phr": phr,
        })

    # Anchor: the dominant ISCO sub-major group among candidates whose title
    # matches the head token *directly* (equal/plural token). For compound
    # heads, ICT-context candidates are additionally allowed to claim a
    # containment match of the head ("security" inside "cybersecurity"), which
    # keeps "ICT security manager" (ISCO 25) as the anchor instead of the
    # larger but unrelated physical-security family (ISCO 54). Restricting the
    # anchor to direct matches stops a generic-role family from hijacking it in
    # the other direction: for "mechanical engineer" the "mechanic" containment
    # matches (ISCO 72) must NOT outvote the direct "mechanical engineer"
    # (ISCO 2144).
    anchor_code = None
    anchor_cands = [b for b in base if b["_head_kind"] >= 0.9]
    if ict_available:
        anchor_cands += [b for b in base
                         if 0.8 <= b["_head_kind"] < 0.9 and b["_ict"]]
    groups = {}
    for b in anchor_cands:
        if b["code"]:
            groups.setdefault(b["code"][:2], []).append(b)
    if groups:
        best_sub = max(
            groups,
            key=lambda sub: (len(groups[sub]), sum(m["_title"] for m in groups[sub])))
        anchor_code = max(groups[best_sub], key=lambda m: m["_title"])["code"]
    if anchor_code is None:
        top = None
        for b in base:
            if b["_title"] >= 0.35 and b["code"]:
                if top is None or b["_title"] > top["_title"]:
                    top = b
        if top is not None:
            anchor_code = top["code"]

    out = []
    for b in base:
        title_s = b["_title"]
        desc_s = b["_desc"]
        skill_s = b["_skill"]
        base_score = 0.45 * title_s + 0.30 * desc_s + 0.25 * skill_s
        dom = _domain_similarity(b["code"], anchor_code)
        final = 0.78 * base_score + 0.22 * dom
        if anchor_code and b["code"] and str(b["code"])[0] != str(anchor_code)[0]:
            if title_s >= 0.35:
                final *= 0.55
        # False friend: the candidate reaches the query's head only through a
        # containment/partial match ("mechanic" inside "mechanical", "guard"
        # nowhere, "securities" vs "cybersecurity") in a *different* ISCO major
        # group and shows no information-technology vocabulary. The domain
        # anchor has already picked the correct (directly-matched) family, so
        # these candidates are capped below the relevance threshold. The ICT
        # exemption keeps genuine IT roles (e.g. ICT security technician 3512
        # vs anchor 25) alive even though their major-group digit differs.
        if (b["_head_kind"] < 0.9
                and not b["_ict"]
                and anchor_code and b["code"]
                and str(b["code"])[0] != str(anchor_code)[0]):
            final = min(final, _FALSE_FRIEND_CAP)

        if not b["_matched"] and b["_phr"] < 0.40:
            final = min(final, 0.12)

        b["score"] = round(max(0.0, min(final, 1.0)), 4)
        out.append(b)

    out.sort(key=lambda b: -b["score"])
    return out


def _bare(c):
    return {
        "title": c["title"],
        "uri": c["uri"],
        "code": c.get("code"),
        "description": c.get("description"),
        "skills": c.get("skills") or [],
        # Carried through scoring so pooled discovery keeps the occupation's
        # skill groups and the profile skills it was surfaced under.
        "_essential": c.get("_essential") or [],
        "_optional": c.get("_optional") or [],
        "_discovery": c.get("_discovery") or [],
    }


def market_occupations(text, limit=10):
    """Return the top-``limit`` ESCO occupations for ``text``, ranked by a
    general-purpose relevance score (see module docstring).

    Each returned item is ``{title, uri, skills, skill_count, description,
    code, score}`` - ``code`` is the ISCO-08 unit group and ``score`` the
    overall relevance (0..1). Cached per exact query. Never raises; returns []
    on failure.
    """
    text = (text or "").strip()
    if not text:
        return []
    now = time.time()
    with _lock:
        if (_cache["query"] == text and now - _cache["at"] < TTL_SECONDS
                and _cache["data"] is not None):
            return _cache["data"]
    try:
        pool = _retrieve(text)
    except Exception:
        return []
    results = _score_enrich_score(pool, text, max(limit, 1))
    out = []
    for e in results:
        skills = e["skills"]
        out.append({
            "title": e["title"],
            "uri": e["uri"],
            "skills": skills[:12],
            "skill_count": len(skills),
            "description": e.get("description"),
            "code": e.get("code"),
            "score": e["score"],
        })
    with _lock:
        _cache.update({"at": time.time(), "query": text, "data": out})
    return out


def market_occupations_for_skills(skill_names, limit=8, max_skills=3):
    """Pooled ESCO candidate discovery from a student's professional skills.

    Used by target-role recommendation: instead of querying ESCO once per skill,
    the per-skill retrieval pools are unioned by occupation URI and each unique
    occupation is enriched exactly once, bounding network volume. The combined
    pool is ranked with the same relevance scorer against the joined skill text.

    Each returned item is shaped like :func:`market_occupations` (``title``,
    ``uri``, ``skills``, ``skill_count``, ``description``, ``code``, ``score``)
    plus ``essential`` and ``optional`` skill lists so callers can honour ESCO's
    essential/optional distinction. Cached per input set for the same TTL.
    Never raises; returns [] on failure.
    """
    skills = [str(s).strip() for s in (skill_names or []) if str(s).strip()][:max_skills]
    if not skills:
        return []
    key = (tuple(skills), limit)
    now = time.time()
    with _lock:
        if (_skills_cache["key"] == key and now - _skills_cache["at"] < TTL_SECONDS
                and _skills_cache["data"] is not None):
            return _skills_cache["data"]
    pool = {}
    for sk in skills:
        try:
            for entry in _retrieve(sk):
                uri = entry.get("uri")
                if uri and uri not in pool:
                    pool[uri] = entry
                    entry["_discovery"] = []
                if uri in pool:
                    d = pool[uri].setdefault("_discovery", [])
                    if sk not in d:
                        d.append(sk)
        except Exception:
            continue
    _enrich_pool(list(pool.values()))
    # Score the shared pool per profile skill, not against the joined text:
    # a joined multi-skill query forces a single head token, which can discard
    # an occupation that is a strong match to one skill but not to the others
    # (a "dispute resolution and mediation" query must not be drowned out by a
    # "case analysis and interpretation" head). An occupation survives when it
    # clears the relevance bar for ANY profile skill; skills for which it does
    # are its discovery ground truth.
    scored_pool = list(pool.values())
    best = {}
    try:
        for sk in skills:
            for e in _score_occupations(sk, scored_pool):
                uri = e["uri"]
                if e["score"] < _MIN_RELEVANCE:
                    continue
                prev = best.get(uri)
                if prev is None or e["score"] > prev["score"]:
                    ms = {sk} if prev is None else (prev.get("_match_skills") | {sk})
                    best[uri] = {**e, "_match_skills": ms}
                else:
                    best[uri]["_match_skills"].add(sk)
    except Exception:
        return []
    ranked = sorted(best.values(), key=lambda e: -e["score"])
    out = []
    for e in ranked[:max(limit, 1)]:
        essential = e.get("_essential") or []
        optional = e.get("_optional") or []
        merged = e.get("skills") or (essential + optional)[:16]
        match_skills = e.get("_match_skills") or []
        out.append({
            "title": e["title"],
            "uri": e["uri"],
            "skills": merged[:12],
            "skill_count": len(merged),
            "description": e.get("description"),
            "code": e.get("code"),
            "score": e["score"],
            "essential": essential[:12],
            "optional": optional[:8],
            # The profile skills against which ESCO scoring itself proved this
            # occupation relevant. Grounded evidence the occupation matches that
            # skill -- not an invented label (see recommendations.py).
            "discovery_skills": list(match_skills),
        })
    with _lock:
        _skills_cache.update({"at": time.time(), "key": key, "data": out})
    return out


def market_occupations_for_role(target_title, limit=8):
    """ESCO occupations that genuinely belong to a student's *selected Target
    Role*, resolving title variation without requiring an exact ESCO preferred
    title.

    The bounded query set is built from the target role itself + its trusted
    close aliases (see role_intent.provider_queries) — never from a broad CV
    skill word. Candidates are pooled by ESCO URI, enriched once, and then ranked
    with the target role as the PRIMARY signal:

      1. EXACT  (title equals / fully contains the target's domain tokens)
      2. CLOSE  (shares an interchangeable domain token, or is a trusted alias)
      3. FAMILY (same canonical career family, different specialization)

    Occupations classified UNRELATED are excluded outright — an occupation is
    never shown merely because one generic skill overlaps. Best effort and never
    raising: returns [] when ESCO is unreachable or no close occupation exists
    (an honest no-result, never a fabricated occupation).
    """
    title = (target_title or "").strip()
    if not title:
        return []
    queries = role_intent.provider_queries(title, max_queries=5)
    # Always include the target title itself (its tokens pair better with the
    # lexical scorer than a bare alias).
    if title not in queries:
        queries.insert(0, title)

    # Pool candidates across the bounded query set, deduplicated by URI.
    pool = {}
    for q in queries:
        try:
            for entry in _retrieve(q):
                uri = entry.get("uri")
                if uri and uri not in pool:
                    pool[uri] = entry
        except Exception:
            continue
    if not pool:
        return []

    # Classify first (the primary signal; no skills needed), drop unrelated.
    kept = []
    for entry in pool.values():
        occ_title = entry.get("title") or ""
        if role_intent.classify_title(title, occ_title) == "UNRELATED":
            continue
        kept.append(entry)
    if not kept:
        return []

    # Score the survivors as ONE corpus. Scoring a single candidate at a time
    # is degenerate: with a one-document corpus the idf weights collapse and
    # every occupation scores within a hair of its neighbours.
    order = {"EXACT": 0, "CLOSE": 1, "FAMILY": 2}
    try:
        all_scored = {e["uri"]: e for e in _score_occupations(title, kept)}
    except Exception:
        return []
    entries = []
    for e in kept:
        sc = all_scored.get(e["uri"])
        entries.append({
            "title": e.get("title") or "",
            "uri": e.get("uri"),
            "code": e.get("code"),
            "description": e.get("description"),
            "skills": e.get("skills") or [],
            "score": round(sc["score"], 4) if sc else 0.0,
            "relevant": role_intent.classify_title(title, e.get("title") or ""),
        })
    entries.sort(key=lambda e: (order.get(e["relevant"], 3), -e["score"], e["title"].lower()))

    # Enrich the rows most likely to be shown (bounded: top `limit*2` of the
    # *relevant* survivors, capped by _ENRICH_CAP), re-rank with the
    # essential-skill evidence, then render only the top `limit`. Enriching the
    # raw pool head first (as the free path used to) left genuinely-relevant
    # occupations that ranked in the pool tail -- e.g. the ICT security family
    # for a "cybersecurity analyst" query -- with zero skills on every card.
    window = entries[:min(len(entries), max(limit * 2, 8))]
    _enrich_pool(window)
    try:
        rescored = {e["uri"]: e for e in _score_occupations(title, window)}
        for e in window:
            if e["uri"] in rescored:
                e["score"] = round(rescored[e["uri"]]["score"], 4)
    except Exception:
        pass
    entries.sort(key=lambda e: (order.get(e["relevant"], 3), -e["score"], e["title"].lower()))

    out = []
    for e in entries[:max(limit, 1)]:
        essential = e.get("_essential") or []
        optional = e.get("_optional") or []
        skills = e.get("skills") or (essential + optional)[:16]
        out.append({
            "title": e["title"],
            "uri": e["uri"],
            "skills": skills[:12],
            "skill_count": len(skills),
            "description": e.get("description"),
            "code": e.get("code"),
            "score": e["score"],
            "relevant": e["relevant"],
        })
    return out


def occupation_skill_groups(uri):
    """Essential/optional skill lists for one ESCO occupation (for import).

    Best effort and never raising: on failure both lists are returned empty so a
    caller can fall back to previously-seen skill names instead of injecting a
    fabricated level or an invented occupation.
    """
    entry = {"title": "", "uri": uri, "code": None, "description": None, "skills": []}
    try:
        _enrich(entry)
    except Exception:
        return {"essential": [], "optional": []}
    return {
        "essential": entry.get("_essential") or [],
        "optional": entry.get("_optional") or [],
    }