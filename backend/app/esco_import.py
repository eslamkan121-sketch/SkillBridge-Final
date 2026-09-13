"""Controlled, versioned ESCO adapter (Phase E).

This is the *managed* path: it downloads a pinned ESCO release behind a single
adapter contract and feeds the canonical role import/refresh service. It is
deliberately separate from ``escoe.py``, the live, cached client used by the
student-facing ESCO-market and target-role flows (which is untouched).

Key properties (per the approved ESCO_IMPORT_REFRESH_PLAN.txt):
- Pins/configured an explicit ESCO release (selectedVersion) instead of relying
  on the API's default (the hosted API answers from v1.0.9 unless told
  otherwise).
- One transport contract (``EscoTransport``) with a live implementation and an
  offline ``FixtureTransport`` that resolves recorded, sanitized payloads — no
  automated test ever touches the real API.
- Bounded timeouts, retries, pagination, and total import size.
- Never performs a live import itself; it only fetches and normalizes.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Iterable, Iterator, Optional, Protocol

import httpx

from . import database, models

# --- Configuration (env-configurable, never guessed) -------------------------

DEFAULT_ESCO_VERSION = os.environ.get("ESCO_VERSION", "1.2.0")
DEFAULT_ESCO_LANGUAGE = os.environ.get("ESCO_LANGUAGE", "en")

ESCO_SEARCH_URL = os.environ.get(
    "ESCO_SEARCH_URL", "https://ec.europa.eu/esco/api/search")
ESCO_RESOURCE_URL = os.environ.get(
    "ESCO_RESOURCE_URL", "https://ec.europa.eu/esco/api/resource/occupation")

ESCO_TIMEOUT_SECONDS = float(os.environ.get("ESCO_TIMEOUT_SECONDS", "8"))
ESCO_RETRIES = int(os.environ.get("ESCO_RETRIES", "2"))
ESCO_RETRY_BACKOFF_SECONDS = float(os.environ.get("ESCO_RETRY_BACKOFF_SECONDS", "0.5"))
ESCO_PAGE_SIZE = int(os.environ.get("ESCO_PAGE_SIZE", "30"))
ESCO_MAX_OCCUPATIONS = int(os.environ.get("ESCO_IMPORT_MAX_OCCUPATIONS", "250"))
ESCO_MAX_PAGES = int(os.environ.get("ESCO_IMPORT_MAX_PAGES", "10"))

_HEADERS = {"User-Agent": "SkillBridge/1.0 (ESCO publisher client)"}


def configured_version() -> str:
    return os.environ.get("ESCO_VERSION", DEFAULT_ESCO_VERSION)


def configured_language() -> str:
    return os.environ.get("ESCO_LANGUAGE", DEFAULT_ESCO_LANGUAGE)


def configured_max_occupations() -> int:
    return int(os.environ.get("ESCO_IMPORT_MAX_OCCUPATIONS", ESCO_MAX_OCCUPATIONS))


# --- Errors ------------------------------------------------------------------


class EscoError(Exception):
    """Base class for ESCO adapter failures."""


class EscoUnavailableError(EscoError):
    """ESCO could not be reached (network/timeout/server error)."""


class EscoMalformedError(EscoError):
    """ESCO responded, but the payload could not be normalized."""


class EscoApplyError(EscoError):
    """Apply validation failure (bad preview run id, config drift, ...)."""
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


# --- Adapter contract --------------------------------------------------------


@dataclass(frozen=True)
class EscoOccupation:
    """Normalized occupation behind the adapter contract.

    All upstream shapes (search result vs resource payload) fold into this one
    shape; application code never reads raw ESCO JSON.
    """
    uri: str
    title: str
    alt_titles: tuple = ()          # alternative titles in the requested language
    hidden_titles: tuple = ()       # hidden (non-preferred) titles in language
    code: Optional[str] = None      # ISCO-08 unit group (4-digit, or None)
    description: Optional[str] = None
    essential: tuple = ()           # skill titles
    optional: tuple = ()
    parent_uri: Optional[str] = None  # single broader occupation when unambiguous
    language: str = "en"
    full: bool = False              # True when built from the resource payload

    def to_dict(self):
        return asdict(self)


class EscoTransport(Protocol):
    """One adapter contract over any upstream source (live API or fixtures)."""

    def iter_search(self, text, language=None, version=None,
                    page_size=None, max_pages=None,
                    max_occupations=None) -> Iterator[EscoOccupation]:
        """Walk paginated search results for ``text``, deduplicated and bounded."""
        ...

    def fetch_occupation(self, uri, language=None, version=None) -> EscoOccupation:
        """Fetch one occupation resource by its stable URI."""
        ...


# --- Literal normalizers (defensive over both ESCO literal shapes) -----------


def _is_requested(text, language):
    return not language or text.lower() == language.lower()


def _text(value):
    """Best single literal from any ESCO literal shape."""
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s or None
    if isinstance(value, dict):
        if "@value" in value:
            s = _text(value["@value"])
            return s
        for key in ("literal", "title", "preferredLabel"):
            if key in value:
                s = _text(value[key])
                if s:
                    return s
        # language-keyed map -> first non-empty value
        for _, v in value.items():
            s = _text(v)
            if s:
                return s
        return None
    if isinstance(value, list):
        for item in value:
            s = _text(item)
            if s:
                return s
    return None


def _lang_text(value, language="en"):
    """Literal resolved to the requested language when the payload says so."""
    if value is None:
        return None
    if isinstance(value, dict):
        if "@language" in value or "@value" in value:
            if "@value" in value and _is_requested(value.get("@language"), language):
                s = _text(value["@value"])
                if s:
                    return s
        for key in ("en", language):
            if key in value:
                s = _text(value[key])
                if s:
                    return s
        for _, v in value.items():
            s = _lang_text(v, language)
            if s:
                return s
        return None
    return _text(value)


def _lang_texts(value, language="en"):
    """All literals in the requested language (alt/hidden label collections)."""
    out = []
    if isinstance(value, dict):
        if "@language" in value or "@value" in value:
            s = _lang_text(value, language)
            if s:
                return (s,)
        for key in (language, "en"):
            if key in value:
                for v in value[key] if isinstance(value[key], list) else [value[key]]:
                    s = _text(v)
                    if s:
                        out.append(s)
        if not out:
            for _, v in value.items():
                out.extend(_lang_texts(v, language))
        return tuple(dict.fromkeys(out))
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and ("@language" in item) and not _is_requested(item.get("@language"), language):
                continue
            s = _lang_text(item, language)
            if s:
                out.append(s)
        return tuple(dict.fromkeys(out))
    if isinstance(value, str):
        s = value.strip()
        return (s,) if s else tuple()
    return tuple()


def _parse_code(raw):
    """Normalise an ESCO/ISCO-08 code ("2511.3", "C2511") to its 4-digit unit
    group ("2511"); None when no usable code is present."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None
    return digits[:4] if len(digits) >= 4 else digits


def _link_title(link):
    """A _links entry is `{uri, title}` (or a plain uri string)."""
    if isinstance(link, str):
        return None, link
    if isinstance(link, dict):
        uri = link.get("uri")
        return _text(link.get("title")), uri
    return None, None


def _broadest_parent(payload, language="en"):
    """Exactly one explicit broader occupation -> its uri; otherwise None."""
    links = payload.get("_links") or {}
    broader = links.get("broaderOccupation")
    parent = None
    if isinstance(broader, dict) and broader.get("uri"):
        parent = broader["uri"]
    elif isinstance(broader, list) and len(broader) == 1 and broader[0].get("uri"):
        parent = broader[0]["uri"]
    return parent


# --- Live transport ----------------------------------------------------------


def build_default_transport():
    """The transport the admin endpoints use: the live publisher client,
    configured exclusively through the environment (version/language are read
    per-call so the config-drift guard sees the current values)."""
    return LiveTransport()


class LiveTransport:
    """The real ESCO publisher API with bounded timeouts/retries/pagination.

    The public endpoints are keyless. ``selectedVersion`` is always sent so a
    future default change cannot silently move results under the importer.
    """

    def __init__(self, client=None, headers=None):
        self._client = client
        self._headers = dict(headers or _HEADERS)

    def _get(self, url, params):
        last_error = None
        for attempt in range(ESCO_RETRIES + 1):
            try:
                if self._client is not None:
                    resp = self._client.get(url, params=params, headers=self._headers,
                                            timeout=ESCO_TIMEOUT_SECONDS)
                else:
                    resp = httpx.get(url, params=params, headers=self._headers,
                                     timeout=ESCO_TIMEOUT_SECONDS)
            except httpx.HTTPError as exc:
                last_error = EscoUnavailableError(
                    f"ESCO unreachable ({type(exc).__name__})")
                time.sleep(ESCO_RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = EscoUnavailableError(
                    f"ESCO server error (status={resp.status_code})")
                if attempt < ESCO_RETRIES:
                    time.sleep(ESCO_RETRY_BACKOFF_SECONDS * (attempt + 1))
                    continue
                raise last_error
            if resp.status_code != 200:
                raise EscoUnavailableError(f"ESCO request failed (status={resp.status_code})")
            try:
                return resp.json()
            except ValueError as exc:
                raise EscoMalformedError("ESCO returned non-JSON payload") from exc
        raise last_error  # type: ignore[misc]

    def _search_page(self, text, language, version, offset, limit):
        params = {
            "text": text, "type": "occupation",
            "language": language, "selectedVersion": version,
            "offset": offset, "limit": limit,
        }
        payload = self._get(ESCO_SEARCH_URL, params)
        return (payload.get("_embedded") or {}).get("results") or []

    def iter_search(self, text, language=None, version=None,
                    page_size=None, max_pages=None, max_occupations=None):
        language = language or configured_language()
        version = version or configured_version()
        page_size = page_size or ESCO_PAGE_SIZE
        max_pages = max_pages or ESCO_MAX_PAGES
        max_occupations = max_occupations if max_occupations is not None else ESCO_MAX_OCCUPATIONS
        seen = set()
        count = 0
        for page in range(max_pages):
            rows = self._search_page(text, language, version,
                                     offset=page * page_size, limit=page_size)
            if not rows:
                break
            for row in rows:
                occ = _normalize_search_occupation(row, language)
                if not occ or occ.uri in seen:
                    continue
                seen.add(occ.uri)
                yield occ
                count += 1
                if count >= max_occupations:
                    return
            if len(rows) < page_size:
                break

    def fetch_occupation(self, uri, language=None, version=None):
        language = language or configured_language()
        version = version or configured_version()
        payload = self._get(ESCO_RESOURCE_URL, {
            "uri": uri, "language": language, "selectedVersion": version,
        })
        occ = _normalize_resource_occupation(payload, language)
        if not occ:
            raise EscoMalformedError("ESCO resource payload missing occupation data")
        return occ


# --- Fixture transport (offline) --------------------------------------------


def _slug_version(version):
    """Canonical component for fixture filenames: strip a leading "v".
    The API param (``selectedVersion``) is sent verbatim from the same value."""
    return re.sub(r"^[vV]", "", (version or "").strip())


class FixtureTransport:
    """Deterministic offline transport over recorded, sanitized fixtures.

    Resolved as ``<fixtures_dir>/<version>_<language>_search_<slug>.json`` for
    search and ``<fixtures_dir>/<version>_<language>_resource_<slug>.json`` for
    resources. Normalized (not raw) ESCO shapes; no network access.
    """

    def __init__(self, fixtures_dir):
        self._dir = fixtures_dir

    def _path(self, *parts):
        return os.path.join(self._dir, *parts)

    def _load(self, filename):
        try:
            with open(self._path(filename), encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            raise EscoUnavailableError(f"fixture missing: {filename}") from exc
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise EscoMalformedError(f"fixture malformed: {filename}") from exc

    @staticmethod
    def _slug(value):
        m = re.search(r"([0-9a-f-]{8,})\s*[)/]*$", value.strip().rstrip("/"), re.IGNORECASE)
        return m.group(1) if m else re.sub(r"[^a-z0-9_-]", "_", value.strip().lower())[:80]

    def iter_search(self, text, language=None, version=None,
                    page_size=None, max_pages=None, max_occupations=None):
        language = language or configured_language()
        version = _slug_version(version or configured_version())
        page_size = page_size or ESCO_PAGE_SIZE
        max_pages = max_pages or ESCO_MAX_PAGES
        max_occupations = max_occupations if max_occupations is not None else ESCO_MAX_OCCUPATIONS
        payload = self._load(f"{version}_{language}_search_{self._slug(text)}.json")
        results = list(payload.get("results") or [])
        seen = set()
        count = 0
        for page in range(max_pages):
            chunk = results[page * page_size: (page + 1) * page_size]
            if not chunk:
                break
            for row in chunk:
                occ = _normalize_search_occupation(row, language)
                if not occ or occ.uri in seen:
                    continue
                seen.add(occ.uri)
                yield occ
                count += 1
                if count >= max_occupations:
                    return

    def fetch_occupation(self, uri, language=None, version=None):
        language = language or configured_language()
        version = _slug_version(version or configured_version())
        payload = self._load(f"{version}_{language}_resource_{self._slug(uri)}.json")
        occ = _normalize_resource_occupation(
            list(payload.get("results") or payload.values())[0] if isinstance(payload, dict) and "results" in payload
            else payload, language)
        if not occ:
            raise EscoMalformedError("fixture resource missing occupation data")
        return occ

    def iter_fetches(self, uris, language=None, version=None) -> Iterable[EscoOccupation]:
        for uri in uris:
            yield self.fetch_occupation(uri, language=language, version=version)


_NORMALIZED = {"uri", "title", "alt_titles", "hidden_titles", "code",
               "description", "essential", "optional", "parent_uri", "language", "full"}


def _normalize_search_occupation(row, language="en"):
    """Fold a search-result entry into the adapter contract (a stub: skills and
    description are only available from the resource fetch)."""
    if not isinstance(row, dict):
        return None
    uri = _text(row.get("uri"))
    title = _lang_text(row.get("title") or row.get("preferredLabel"), language) \
        or _text(row.get("preferredLabel"))
    if not uri or not title:
        return None
    alt = _lang_texts(row.get("altLabels"), language) if row.get("altLabels") is not None else ()
    hidden = _lang_texts(row.get("hiddenLabels"), language) if row.get("hiddenLabels") is not None else ()
    return EscoOccupation(
        uri=uri,
        title=title,
        alt_titles=alt,
        hidden_titles=hidden,
        code=_parse_code(row.get("code")),
        description=None,
        essential=(),
        optional=(),
        parent_uri=None,
        language=language,
        full=False,
    )


def _normalize_resource_occupation(payload, language="en"):
    """Fold a resource payload into the adapter contract (full record)."""
    if not isinstance(payload, dict):
        return None
    uri = _text(payload.get("uri"))
    if not uri:
        return None
    title = _lang_text(
        payload.get("preferredLabel") or payload.get("title"), language) \
        or _text(payload.get("title")) or _text(payload.get("preferredLabel"))
    if not title:
        return None
    links = payload.get("_links") or {}
    essential, optional = [], []
    for item in links.get("hasEssentialSkill") or []:
        name, _ = _link_title(item)
        if name:
            essential.append(name)
    for item in links.get("hasOptionalSkill") or []:
        name, _ = _link_title(item)
        if name:
            optional.append(name)
    return EscoOccupation(
        uri=uri,
        title=title,
        alt_titles=_lang_texts(payload.get("altLabels"), language) if payload.get("altLabels") is not None else (),
        hidden_titles=_lang_texts(payload.get("hiddenLabels"), language) if payload.get("hiddenLabels") is not None else (),
        code=_parse_code(payload.get("code")) or _parse_code(
            ((links.get("iscoGroup") or {}).get("code") if isinstance(links.get("iscoGroup"), dict) else None)),
        description=_text(payload.get("description")) if payload.get("description") is not None else None,
        essential=tuple(dict.fromkeys(essential)),
        optional=tuple(dict.fromkeys(optional)),
        parent_uri=_broadest_parent(payload, language),
        language=language,
        full=True,
    )


# --- Imprint + dry-run plan engine (Phase E Slice 2) -------------------------

VALID_ACTIONS = ("add", "change", "deprecate", "supersede", "conflict", "noop", "unmanaged")


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@dataclass(frozen=True)
class EscoChange:
    """One dry-run/apply verdict for a single occupation."""
    uri: str
    title: Optional[str]
    action: str
    role_id: Optional[int]
    reason: str
    detail: dict


def _norm_items(items):
    return sorted({str(x).strip().lower() for x in (items or ()) if str(x).strip()})


def occupation_imprint(occ):
    """Deterministic fingerprint of the state an import would write. Stored on
    the role row at apply time; comparing the stored imprint against the imprint
    of freshly fetched data is what makes change detection honest and exact."""
    blob = json.dumps({
        "title": (occ.title or "").strip(),
        "normalized_title": models._canonical_title(occ.title or ""),
        "family": models._canonical_family(occ.title or ""),
        "code": occ.code,
        "parent_uri": occ.parent_uri,
        "language": occ.language,
        "essential": _norm_items(occ.essential),
        "optional": _norm_items(occ.optional),
        "alt_titles": _norm_items(occ.alt_titles),
        "hidden_titles": _norm_items(occ.hidden_titles),
    }, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


_MANAGED_COLUMNS = (
    "id, title, source, external_id, role_key, canonical_status, "
    "is_local_authoring, source_version, source_language, import_imprint, "
    "normalized_title, family, imported_at, updated_at"
)


def _managed_esco_rows():
    with database.get_cursor() as conn:
        rows = conn.execute(
            f"SELECT {_MANAGED_COLUMNS} FROM roles WHERE source='esco'").fetchall()
        return [dict(r) for r in rows]


def _row_by_uri(uri):
    with database.get_cursor() as conn:
        r = conn.execute(
            f"SELECT {_MANAGED_COLUMNS} FROM roles WHERE source='esco' AND external_id=?",
            (uri,)).fetchone()
        return dict(r) if r else None


def _locally_modified(row):
    if row.get("is_local_authoring"):
        return True
    imported_at = row.get("imported_at") or ""
    updated_at = row.get("updated_at") or ""
    return bool(imported_at) and bool(updated_at) and updated_at > imported_at


def plan_refresh(occupations, version="", language=""):
    """Classify every fetched occupation and every managed ESCO row into the
    dry-run action set. Read-only with respect to role data: it persists
    nothing and can never mutate a role.

    ``unmanaged`` rows (existing ESCO rows not created by a managed import) are
    reported but never scheduled for modification; deprecation/supersession only
    ever applies to managed rows (``import_imprint`` present).
    """
    version = version or configured_version()
    language = language or configured_language()
    fetched = [o for o in occupations if o]
    fetched_by_uri = {o.uri: o for o in fetched}
    rows = _managed_esco_rows()
    rows_by_uri = {r["external_id"]: r for r in rows}
    changes = []
    stats = Counter()

    for occ in fetched:
        row = rows_by_uri.get(occ.uri)
        expected = occupation_imprint(occ)
        if row is None:
            changes.append(EscoChange(
                occ.uri, occ.title, "add", None,
                "new occupation in this pinned version",
                {"version": version, "language": language}))
            stats["add"] += 1
        elif not row.get("import_imprint"):
            changes.append(EscoChange(
                occ.uri, occ.title, "unmanaged", row["id"],
                "existing ESCO row was not created by a managed import; never auto-modified",
                {}))
            stats["unmanaged"] += 1
        elif row.get("import_imprint") == expected:
            changes.append(EscoChange(
                occ.uri, occ.title, "noop", row["id"],
                "unchanged at this pinned version", {}))
            stats["noop"] += 1
        elif _locally_modified(row):
            changes.append(EscoChange(
                occ.uri, occ.title, "conflict", row["id"],
                "row was edited outside the import; upstream change will not overwrite it",
                {}))
            stats["conflict"] += 1
        else:
            changes.append(EscoChange(
                occ.uri, occ.title, "change", row["id"],
                "upstream data changed at this pinned version", {}))
            stats["change"] += 1

    present_uris = set(fetched_by_uri)
    by_title_key = {}
    for occ in fetched:
        key = (models._canonical_title(occ.title), models._canonical_family(occ.title))
        by_title_key.setdefault(key, []).append(occ)

    for row in rows:
        uri = row["external_id"]
        if uri in present_uris or not row.get("import_imprint"):
            continue
        if row.get("canonical_status") in ("deprecated", "superseded"):
            continue
        key = (row.get("normalized_title") or models._canonical_title(row["title"]),
               row.get("family") or models._canonical_family(row["title"]))
        successors = by_title_key.get(key, [])
        if len(successors) == 1:
            changes.append(EscoChange(
                uri, row["title"], "supersede", row["id"],
                "exactly one matching occupation at this pinned version",
                {"successor_uri": successors[0].uri,
                 "successor_title": successors[0].title,
                 "successor_imprint": occupation_imprint(successors[0])}))
            stats["supersede"] += 1
        else:
            changes.append(EscoChange(
                uri, row["title"], "deprecate", row["id"],
                "occupation absent from this pinned version",
                {}))
            stats["deprecate"] += 1

    return changes, dict(stats)


# --- Import-run ledger + dry-run preview (Phase E Slice 2) -------------------


def create_import_run(mode, version, language, triggered_by_user_id=None,
                      previewed_run_id=None):
    with database.get_cursor() as conn:
        cur = conn.execute(
            "INSERT INTO esco_import_runs (mode, status, version, language, "
            "triggered_by_user_id, previewed_run_id, started_at) "
            "VALUES (?, 'running', ?, ?, ?, ?, ?)",
            (mode, version, language, triggered_by_user_id, previewed_run_id, _now()))
        return cur.lastrowid


def record_changes(run_id, changes):
    if not changes:
        return
    with database.get_cursor() as conn:
        for ch in changes:
            conn.execute(
                "INSERT INTO esco_import_changes "
                "(run_id, uri, title, action, role_id, reason, detail_json) "
                "VALUES (?,?,?,?,?,?,?)",
                (run_id, ch.uri, ch.title, ch.action, ch.role_id, ch.reason,
                 json.dumps(ch.detail)))


def finish_import_run(run_id, stats=None, error=None):
    status = "failed" if error else "succeeded"
    with database.get_cursor() as conn:
        conn.execute(
            "UPDATE esco_import_runs SET status=?, finished_at=?, stats_json=?, error=? "
            "WHERE id=?",
            (status, _now(), json.dumps(stats or {}), error, run_id))


def get_import_run(run_id):
    with database.get_cursor() as conn:
        r = conn.execute(
            "SELECT * FROM esco_import_runs WHERE id=?", (run_id,)).fetchone()
        return dict(r) if r else None


def get_run_changes(run_id):
    with database.get_cursor() as conn:
        rows = conn.execute(
            "SELECT * FROM esco_import_changes WHERE run_id=? ORDER BY id",
            (run_id,)).fetchall()
        return [dict(r) for r in rows]


def latest_import_runs(limit=5):
    limit = min(max(int(limit), 1), 200)
    with database.get_cursor() as conn:
        rows = conn.execute(
            "SELECT * FROM esco_import_runs ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in rows]


def _fetch_targets(transport, uris, query, language, version, max_occupations):
    if uris:
        for uri in uris:
            yield transport.fetch_occupation(uri, language=language, version=version)
    else:
        yield from transport.iter_search(
            query or "", language=language, version=version,
            max_occupations=max_occupations)


def enrich_occupations(transport, occupations, language=None, version=None):
    """Best-effort upgrade of search stubs (titles only) to full occupation
    records (skills, aliases, parent) by fetching each resource once.

    A failing resource keeps the search stub so a single flaky occupation can
    never fail the whole plan; already-full records are never re-fetched.
    """
    language = language or configured_language()
    version = version or configured_version()
    out = []
    for occ in occupations:
        if getattr(occ, "full", False):
            out.append(occ)
            continue
        try:
            full = transport.fetch_occupation(occ.uri, language=language, version=version)
            if full:
                out.append(full)
                continue
        except EscoError:
            pass
        out.append(occ)
    return out


def _change_row(ch):
    return {"uri": ch.uri, "title": ch.title, "action": ch.action,
            "role_id": ch.role_id, "reason": ch.reason, "detail": ch.detail}


def preview(transport, version="", language="", *, uris=(), query="",
            max_occupations=None, triggered_by_user_id=None):
    """Dry-run import/refresh: fetch, classify, and persist the run + change
    ledger. Never creates or modifies any role row.

    ``uris`` wins when provided; otherwise ``query`` is searched. A transport
    failure is recorded as a failed run (ESRO is not touched by this call).
    """
    version = (version or configured_version()).strip() or configured_version()
    language = language or configured_language()
    fetched = []
    error = None
    try:
        fetched = list(_fetch_targets(transport, list(uris or []), query,
                                      language, version, max_occupations))
    except EscoError as exc:
        error = str(exc)

    if error is not None:
        run_id = create_import_run("dry_run", version, language, triggered_by_user_id)
        finish_import_run(run_id, stats={"fetched": 0, "uris": list(uris or []),
                                         "query": query or ""}, error=error)
        return {"run_id": run_id, "status": "failed", "error": error,
                "version": version, "language": language}

    fetched = enrich_occupations(transport, fetched, language, version)
    changes, stats = plan_refresh(fetched, version, language)
    run_id = create_import_run("dry_run", version, language, triggered_by_user_id)
    record_changes(run_id, changes)
    stats = {"fetched": len(fetched), "uris": list(uris or []),
             "query": query or "", **stats}
    finish_import_run(run_id, stats)
    return {"run_id": run_id, "status": "succeeded", "version": version,
            "language": language, "stats": stats,
            "changes": [_change_row(c) for c in changes]}


# --- Apply executor (Phase E Slice 3) ----------------------------------------

_ROLE_DESCRIPTION = "Occupation imported from the ESCO labour-market catalogue."


def _skill_id(conn, name, category="Professional Skill"):
    """Get-or-create a skill on the SAME connection so the apply transaction
    stays committed/rolled-back as a unit (models.get_or_create_skill opens its
    own committing cursor)."""
    row = conn.execute("SELECT id FROM skills WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO skills (name, category) VALUES (?,?)",
                       (name, category))
    return cur.lastrowid


def _ensure_skill_link(conn, role_id, name, kind, version):
    skill_id = _skill_id(conn, name)
    existing = conn.execute(
        "SELECT 1 FROM role_skills WHERE role_id=? AND skill_id=?",
        (role_id, skill_id)).fetchone()
    if existing:
        return
    conn.execute(
        "INSERT INTO role_skills (role_id, skill_id, required_level, skill_kind) "
        "VALUES (?,?, 'Intermediate', ?)",
        (role_id, skill_id, kind))
    conn.execute(
        "INSERT OR IGNORE INTO role_skill_sources (role_id, skill_id, source, source_uri, attested_at) "
        "VALUES (?,?, 'esco', NULL, ?)",
        (role_id, skill_id, _now()))


def _parent_role_id(conn, parent_uri):
    if not parent_uri:
        return None
    row = conn.execute("SELECT id FROM roles WHERE source='esco' AND external_id=?",
                       (parent_uri,)).fetchone()
    return row["id"] if row else None


def _apply_add(conn, occ, version, language):
    """Whole-row managed import inside the caller's transaction. Returns the new
    role id, or None when the occupation carried no importable skills (the plan
    classified the search stub; without skills there is nothing honest to
    write)."""
    role = models.import_esco_role(
        occ.uri, occ.title, occ.essential, occ.optional,
        source_version=version, isco_code=occ.code,
        aliases=[
            {"alias": a, "type": "hidden", "language": language} for a in occ.hidden_titles
        ] + [
            {"alias": a, "type": "alternative", "language": language} for a in occ.alt_titles
        ],
        source_language=language, import_imprint=occupation_imprint(occ),
        parent_uri=occ.parent_uri, conn=conn)
    return role["id"] if role else None


def _apply_change(conn, occ, row, version, language):
    """Refresh a managed row in place. R7 forbids DELETE here, so reconciliation
    updates text/canonical fields and only ADDS skills/aliases/codes missing from
    the row (stale historical entries are preserved, never destroyed)."""
    now = _now()
    imprint = occupation_imprint(occ)
    conn.execute(
        "UPDATE roles SET title=?, description=?, role_key=?, canonical_status='active', "
        "is_local_authoring=0, source_version=?, source_language=?, import_imprint=?, "
        "normalized_title=?, family=?, parent_role_id=?, imported_at=?, updated_at=? "
        "WHERE id=?",
        (occ.title, _ROLE_DESCRIPTION, models._role_key_for("esco", occ.title, occ.uri),
         version, language, imprint, models._canonical_title(occ.title),
         models._canonical_family(occ.title), _parent_role_id(conn, occ.parent_uri),
         now, now, row["id"]))
    for name in occ.essential:
        _ensure_skill_link(conn, row["id"], name, "essential", version)
    for name in occ.optional:
        _ensure_skill_link(conn, row["id"], name, "optional", version)
    for a in occ.alt_titles:
        models._insert_alias(conn, row["id"], a, "alternative", language, now)
    for a in occ.hidden_titles:
        models._insert_alias(conn, row["id"], a, "hidden", language, now)
    models._insert_isco_code(conn, row["id"], occ.code or "", "esco", occ.uri, now)


def _apply_supersede(conn, old_role_id, succ_occ, version, language):
    """Link the old managed row to its single successor at the new version.
    Imports the successor only when it does not exist locally yet; flips the old
    row to canonical_status='superseded'. Returns (successor_role_id, created)."""
    row = conn.execute("SELECT id FROM roles WHERE source='esco' AND external_id=?",
                       (succ_occ.uri,)).fetchone()
    created = False
    if row:
        succ_id = row["id"]
    else:
        succ_id = _apply_add(conn, succ_occ, version, language)
        created = succ_id is not None
    if not succ_id:
        return None, created
    now = _now()
    conn.execute(
        "UPDATE roles SET canonical_status='superseded', superseded_by_role_id=?, "
        "imported_at=?, updated_at=? "
        "WHERE id=? AND source='esco' AND import_imprint IS NOT NULL",
        (succ_id, now, now, old_role_id))
    return succ_id, created


def apply_refresh(transport, preview_run_id, version="", language="", *, uris=(),
                  query="", max_occupations=None, triggered_by_user_id=None):
    """Apply exactly a previewed dry-run set -- the single write path that can
    mutate managed ESCO catalogue rows.

    Accepts ONLY a succeeded dry-run run created for the same pinned
    version+language (config-drift guard: a previewed set is a snapshot, and
    applying it under different config is refused). The same target set is
    re-fetched and re-planned at apply time, then executed inside one
    transaction. Never deletes roles, skills, aliases, or codes. Deprecations
    and supersessions flip canonical_status only; conflicting local edits are
    skipped with a recorded reason; every applied row gets a fresh
    source_version/source_language/import_imprint and imported_at=updated_at.
    """
    version = (version or configured_version()).strip() or configured_version()
    language = language or configured_language()

    preview_run = get_import_run(preview_run_id)
    if not preview_run:
        raise EscoApplyError(f"preview run {preview_run_id} not found", status_code=404)
    if preview_run["mode"] != "dry_run" or preview_run["status"] != "succeeded":
        raise EscoApplyError("apply requires a succeeded dry-run preview", status_code=400)
    if preview_run["version"] != version or preview_run["language"] != language:
        raise EscoApplyError(
            f"config drift: preview pinned {preview_run['version']}/{preview_run['language']}, "
            f"current version/language is {version}/{language}; preview again",
            status_code=409)
    try:
        preview_spec = json.loads(preview_run["stats_json"] or "{}")
    except (TypeError, ValueError):
        preview_spec = {}
    if not uris and not query:
        query = preview_spec.get("query") or ""
    uris = list(uris or preview_spec.get("uris") or [])
    if not uris and not query:
        raise EscoApplyError(
            "previewed run locked no fetch target; preview again", status_code=409)

    def fail(msg):
        run_id = create_import_run("apply", version, language,
                                   triggered_by_user_id, preview_run_id)
        finish_import_run(run_id, stats={"fetched": 0}, error=msg)
        return {"run_id": run_id, "status": "failed", "error": msg,
                "version": version, "language": language}

    try:
        fetched = list(_fetch_targets(transport, list(uris or []), query,
                                      language, version, max_occupations))
    except EscoError as exc:
        return fail(str(exc))

    fetched = enrich_occupations(transport, fetched, language, version)
    changes, plan_stats = plan_refresh(fetched, version, language)

    run_id = create_import_run("apply", version, language,
                               triggered_by_user_id, preview_run_id)
    by_uri = {o.uri: o for o in fetched}
    applied = Counter()
    ledger = []
    created_for_supersede = set()
    try:
        with database.get_cursor() as conn:
            for ch in changes:
                occ = by_uri.get(ch.uri)
                if ch.action in ("supersede", "deprecate"):
                    # A removed occupation is absent from today's fetch by
                    # design, so these actions must NOT require occ present.
                    if ch.action == "supersede":
                        succ_uri = ch.detail.get("successor_uri")
                        succ_occ = by_uri.get(succ_uri) if succ_uri else None
                        if succ_occ is None:
                            ledger.append((ch.uri, ch.title, "supersede", ch.role_id,
                                           "successor occupation unavailable at apply time",
                                           {}))
                            continue
                        succ_id, created = _apply_supersede(
                            conn, ch.role_id, succ_occ, version, language)
                        if not succ_id:
                            ledger.append((ch.uri, ch.title, "supersede", ch.role_id,
                                           "successor carried no importable skills", {}))
                            continue
                        applied["supersede"] += 1
                        if created:
                            created_for_supersede.add(succ_uri)
                        ledger.append((ch.uri, ch.title, "supersede", ch.role_id,
                                       ch.reason,
                                       {**ch.detail, "successor_role_id": succ_id}))
                    else:
                        conn.execute(
                            "UPDATE roles SET canonical_status='deprecated', imported_at=?, updated_at=? "
                            "WHERE id=? AND source='esco' AND import_imprint IS NOT NULL",
                            (_now(), _now(), ch.role_id))
                        applied["deprecate"] += 1
                        ledger.append((ch.uri, ch.title, "deprecate", ch.role_id,
                                       ch.reason, {"version": version, "language": language}))
                    continue
                if occ is None:
                    ledger.append((ch.uri, ch.title, ch.action, ch.role_id,
                                   ch.reason, ch.detail))
                    continue
                if ch.action == "add":
                    if ch.uri in created_for_supersede:
                        ledger.append((ch.uri, occ.title, "add", ch.role_id,
                                       "already imported by a supersession",
                                       {"version": version, "language": language}))
                        continue
                    role_id = _apply_add(conn, occ, version, language)
                    if role_id:
                        applied["add"] += 1
                        created_for_supersede.add(ch.uri)
                        ledger.append((ch.uri, occ.title, "add", role_id,
                                       ch.reason, {"version": version, "language": language}))
                    else:
                        ledger.append((ch.uri, occ.title, "skipped", None,
                                       "upstream resource carried no importable skills",
                                       {"version": version, "language": language}))
                elif ch.action == "change":
                    _apply_change(conn, occ, {"id": ch.role_id}, version, language)
                    applied["change"] += 1
                    ledger.append((ch.uri, occ.title, "change", ch.role_id,
                                   ch.reason, {"version": version, "language": language}))
                else:  # noop / conflict / unmanaged
                    ledger.append((ch.uri, ch.title, ch.action, ch.role_id,
                                   ch.reason, ch.detail))

            now = _now()
            for uri, title, action, role_id, reason, detail in ledger:
                conn.execute(
                    "INSERT INTO esco_import_changes "
                    "(run_id, uri, title, action, role_id, reason, detail_json) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (run_id, uri, title, action, role_id, reason,
                     json.dumps(detail or {})))
            run_stats = {"fetched": len(fetched), **plan_stats,
                         "applied": dict(applied)}
            conn.execute(
                "UPDATE esco_import_runs SET status='succeeded', finished_at=?, "
                "stats_json=? WHERE id=?",
                (now, json.dumps(run_stats), run_id))
    except Exception as exc:  # pragma: no cover - defensive rollback path
        finish_import_run(run_id, stats={"applied": dict(applied)},
                          error=f"apply aborted: {type(exc).__name__}: {exc}")
        return {"run_id": run_id, "status": "failed",
                "error": f"apply aborted: {type(exc).__name__}",
                "version": version, "language": language}

    return {"run_id": run_id, "status": "succeeded", "version": version,
            "language": language, "previewed_run_id": preview_run_id,
            "stats": run_stats, "changes": ledger}