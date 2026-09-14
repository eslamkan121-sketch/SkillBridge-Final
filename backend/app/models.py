"""Data access layer — CRUD for the five record types plus supporting lookups.

Pure functions over sqlite3 Row dictionaries. Kept free of framework imports so
they can be unit tested in isolation.
"""
from .database import get_cursor, MAX_ROLE_VIEW_EVENTS
from . import role_intent
from . import skill_registry
import contextlib
import datetime as dt
import json
import re

LEVEL_ORDER = {"Beginner": 1, "Intermediate": 2, "Advanced": 3}
VALID_LEVELS = set(LEVEL_ORDER)

# Status values the canonical role model understands. Existing rows default to
# 'active' (honest: nothing previously marked them otherwise).
VALID_ROLE_STATUS = ("active", "deprecated", "superseded")
CATALOG_COMPANY_NAME = "SkillBridge Talent Catalog"

_SLUG_KEEP = re.compile(r"[^a-z0-9]+")


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _canonical_title(title):
    """Normalized search form of a title (never replaces the display title)."""
    parts = role_intent.normalize_title(title) or []
    return " ".join(parts).strip() or (title or "").strip().lower()


def _canonical_family(title):
    """Family label from the same classifier the rest of the app uses, or ''."""
    return role_intent.family_of(title) or ""


def _slugify(text):
    parts = [p for p in _SLUG_KEEP.split((text or "").lower()) if p]
    return "-".join(parts) if parts else "role"


def _esc_like(text):
    """Escape a LIKE pattern so user input '%'/'_'/'\' is treated literally
    (matched against the normalized search form only)."""
    return str(text).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _role_key_for(source, title, external_id=None):
    """Stable, human-readable canonical key for a role (identity hint, not an
    enforced unique constraint - legacy duplicates may share a title)."""
    if source == "esco" and external_id:
        seg = str(external_id).rstrip("/").split("/")[-1]
        slug = _slugify(seg) or _slugify(title)
        return f"esco:{slug}"
    return f"{source or 'company'}:{_slugify(title)}"


def _row(r):
    return dict(r) if r is not None else None


def _safe_user(r):
    """Strip plaintext password column from a user row before it leaks to any caller."""
    d = dict(r) if r is not None else None
    if d and "password" in d:
        del d["password"]
    return d


# ---------------------------------------------------------------- skills

def list_skills():
    with get_cursor() as c:
        rows = c.execute("SELECT * FROM skills ORDER BY name").fetchall()
        return [_row(r) for r in rows]


def _json_loads(value):
    if not value:
        return None
    import json
    try:
        return json.loads(value)
    except Exception:
        return None


def _json_dumps(value):
    if value is None:
        return None
    import json
    return json.dumps(value)


def get_skill(skill_id):
    with get_cursor() as c:
        return _row(c.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone())


def get_skill_by_name(name):
    with get_cursor() as c:
        return _row(c.execute("SELECT * FROM skills WHERE name=?", (name,)).fetchone())


def create_skill(name, category):
    with get_cursor() as c:
        cur = c.execute("INSERT INTO skills (name, category) VALUES (?,?)", (name, category))
        return get_skill(cur.lastrowid)


def get_or_create_skill(name, category):
    existing = get_skill_by_name(name)
    if existing:
        return existing
    return create_skill(name, category)


def update_skill(skill_id, name=None, category=None):
    with get_cursor() as c:
        cur = c.execute("UPDATE skills SET name=COALESCE(?,name), category=COALESCE(?,category) WHERE id=?",
                        (name, category, skill_id))
        return cur.rowcount


def delete_skill(skill_id):
    with get_cursor() as c:
        cur = c.execute("DELETE FROM skills WHERE id=?", (skill_id,))
        return cur.rowcount


# ---------------------------------------------------------------- companies

def list_companies():
    with get_cursor() as c:
        return [_row(r) for r in c.execute("SELECT * FROM companies ORDER BY name").fetchall()]


def get_company(company_id):
    with get_cursor() as c:
        return _row(c.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone())


def get_company_by_user(user_id):
    with get_cursor() as c:
        return _row(c.execute("SELECT * FROM companies WHERE user_id=?", (user_id,)).fetchone())


def create_company(name, industry, user_id=None, location=None):
    with get_cursor() as c:
        cur = c.execute("INSERT INTO companies (name, industry, location, user_id) VALUES (?,?,?,?)",
                        (name, industry, location, user_id))
        return get_company(cur.lastrowid)


def update_company(company_id, name=None, industry=None, location=None):
    with get_cursor() as c:
        cur = c.execute("UPDATE companies SET name=COALESCE(?,name), industry=COALESCE(?,industry), location=COALESCE(?,location) WHERE id=?",
                        (name, industry, location, company_id))
        return cur.rowcount


def delete_company(company_id):
    with get_cursor() as c:
        c.execute("DELETE FROM companies WHERE id=?", (company_id,))
    return 1


# ---------------------------------------------------------------- roles

_ACTIVE_ROLE_CLAUSE = "(canonical_status IS NULL OR canonical_status = 'active')"


def list_roles(company_id=None, search=None):
    """Company-created openings, optionally filtered by a free-text title
    search (matched against ``normalized_title``, never against the display
    title)."""
    with get_cursor() as c:
        q = """SELECT r.*, c.name AS company_name, c.location AS company_location
               FROM roles r LEFT JOIN companies c ON c.id=r.company_id"""
        conds = []
        params = []
        if company_id is not None:
            conds.append("r.company_id=?")
            params.append(company_id)
        else:
            # Company-created openings only: imported ESCO occupations are not
            # company openings (source='esco') and must never leak into rosters.
            conds.append("r.is_reference=0 AND (r.source IS NULL OR r.source != 'esco')")
        search = (search or "").strip()
        if search:
            conds.append("r.normalized_title LIKE ? ESCAPE '\\'")
            params.append("%" + _esc_like(_canonical_title(search)) + "%")
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY r.title"
        rows = c.execute(q, tuple(params)).fetchall()
        out = []
        for r in rows:
            rd = _row(r)
            rd["required_skills"] = role_skills(c, r["id"])
            out.append(rd)
        return out


def list_catalog_roles(search=None):
    """Reference roles seeded as the talent catalog (read-only baseline)."""
    with get_cursor() as c:
        q = ("SELECT r.*, c.name AS company_name FROM roles r "
             "LEFT JOIN companies c ON c.id=r.company_id WHERE r.is_reference=1")
        params = []
        search = (search or "").strip()
        if search:
            q += " AND r.normalized_title LIKE ? ESCAPE '\\'"
            params.append("%" + _esc_like(_canonical_title(search)) + "%")
        q += " ORDER BY r.title"
        rows = c.execute(q, tuple(params)).fetchall()
        out = []
        for r in rows:
            rd = _row(r)
            rd["required_skills"] = role_skills(c, r["id"])
            out.append(rd)
        return out


def list_feed_roles(location=None, country=None, limit=8):
    """Live openings (company-posted, non-reference roles) ranked by how close
    they are to the requesting user's location: same location first, roles with
    no location (remote/global) next, the rest after. Supplies the 'available
    roles' live feed on the student dashboard. Deprecated/superseded roles are
    excluded but stay resolvable by id for existing links."""
    location = (location or "").strip()
    country = (country or "").strip()
    with get_cursor() as c:
        rows = c.execute("""SELECT r.id, r.title, r.description, r.is_reference,
                                   c.name AS company_name, c.location AS company_location
                            FROM roles r LEFT JOIN companies c ON c.id=r.company_id
                            WHERE r.is_reference=0 AND (r.source IS NULL OR r.source != 'esco')
                              AND """ + _ACTIVE_ROLE_CLAUSE + """
                            ORDER BY r.title""").fetchall()
        out = []
        for r in rows:
            rd = _row(r)
            rd["required_skills"] = role_skills(c, r["id"])
            out.append(rd)
        def rank(r):
            loc = (r.get("company_location") or "").strip()
            if not loc:
                return 1
            if loc.lower() == location.lower():
                return 0
            if country and (country.lower() in loc.lower() or loc.lower() in country.lower()):
                return 0
            return 2
        out.sort(key=lambda r: (rank(r), 0 if not (r.get("company_location") or "").strip() else 1, r["title"].lower()))
        return out[:limit]


def role_skills(cur, role_id):
    return [_row(r) for r in cur.execute("""
        SELECT rs.required_level, s.id AS skill_id, s.name, s.category, rs.skill_kind
        FROM role_skills rs JOIN skills s ON s.id=rs.skill_id
        WHERE rs.role_id=? ORDER BY s.name""", (role_id,)).fetchall()]


def get_role(role_id):
    with get_cursor() as c:
        r = c.execute("""SELECT r.*, c.name AS company_name
                         FROM roles r LEFT JOIN companies c ON c.id=r.company_id
                         WHERE r.id=?""", (role_id,)).fetchone()
        if not r:
            return None
        rd = _row(r)
        rd["required_skills"] = role_skills(c, role_id)
        return rd


def get_roles_by_company(company_id):
    with get_cursor() as c:
        rows = c.execute("SELECT * FROM roles WHERE company_id=?", (company_id,)).fetchall()
        out = []
        for r in rows:
            rd = _row(r)
            rd["required_skills"] = role_skills(c, r["id"])
            out.append(rd)
        return out


def list_saved_roles(student_id):
    """Saved role ids for a student (either reference catalog or company roles)."""
    with get_cursor() as c:
        rows = c.execute("SELECT role_id FROM saved_roles WHERE student_id=? ORDER BY saved_at DESC",
                         (student_id,)).fetchall()
        return [r["role_id"] for r in rows]


def create_saved_role(student_id, role_id):
    with get_cursor() as c:
        c.execute("INSERT OR IGNORE INTO saved_roles (student_id, role_id) VALUES (?,?)",
                  (student_id, role_id))
        return True


def remove_saved_role(student_id, role_id):
    with get_cursor() as c:
        c.execute("DELETE FROM saved_roles WHERE student_id=? AND role_id=?", (student_id, role_id))
        return True


# ------------------------------------------------------------------ job tracker (Phase K)
# Private, per-student application tracker. Stage vocabulary is EXACTLY the ten
# guide stages; transitions are validated against an allow-list and every stage
# change is appended to tracker_stage_history (an audit record, never rewritten).

JOB_TRACKER_STAGES = (
    "saved", "preparing", "applied", "screening", "interview", "offer", "hired",
    "rejected", "withdrawn", "archived_or_expired",
)

JOB_TRACKER_TRANSITIONS = {
    "saved": {"preparing", "applied", "archived_or_expired"},
    "preparing": {"applied", "withdrawn", "archived_or_expired"},
    "applied": {"screening", "interview", "rejected", "withdrawn", "archived_or_expired"},
    "screening": {"interview", "rejected", "archived_or_expired"},
    "interview": {"offer", "rejected", "withdrawn", "archived_or_expired"},
    "offer": {"hired", "rejected", "withdrawn", "archived_or_expired"},
    "hired": {"archived_or_expired"},
    "rejected": {"archived_or_expired"},
    "withdrawn": {"saved", "archived_or_expired"},
    # archived/expired rows stay stored forever; a student may reactivate one.
    "archived_or_expired": {"saved", "preparing", "applied"},
}


class TrackerError(Exception):
    """Tracker validation error; ``code`` becomes the HTTP status.

    400 = unknown stage / bad payload, 409 = know legal stage but not reachable
    from the row's current stage (delete or transition refusal)."""

    def __init__(self, message, code=400):
        super().__init__(message)
        self.message = message
        self.code = code


def _validate_iso_date(value, field):
    if value is None or str(value).strip() == "":
        return None
    s = str(value).strip()
    if len(s) != 10 or not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        raise TrackerError(f"{field} must be an ISO date (YYYY-MM-DD)")
    return s


def _tracker_history_rows(tracker_id, conn=None):
    """Append-only stage-history rows for one tracker entry (oldest first)."""
    rows = conn.execute(
        "SELECT id, stage, changed_from, note, created_at FROM tracker_stage_history "
        "WHERE tracker_id=? ORDER BY id", (tracker_id,)).fetchall()
    return [{"id": r["id"], "stage": r["stage"], "changed_from": r["changed_from"],
             "note": r["note"], "created_at": r["created_at"]} for r in rows]


def _tracker_row(tracker_id, conn):
    row = conn.execute(
        "SELECT * FROM student_job_tracker WHERE id=?", (tracker_id,)).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"], "student_id": row["student_id"], "fingerprint": row["fingerprint"],
        "title": row["title"], "company": row["company"], "url": row["url"],
        "apply_url": row["apply_url"], "location": row["location"], "country": row["country"],
        "provider": row["provider"], "source": row["source"], "match_pct": row["match_pct"],
        "work_type": row["work_type"], "seniority": row["seniority"],
        "listing_status": row["listing_status"], "link_state": row["link_state"],
        "is_expired": bool(row["is_expired"]), "stage": row["stage"], "note": row["note"],
        "interview_date": row["interview_date"], "application_deadline": row["application_deadline"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "history": _tracker_history_rows(tracker_id, conn),
    }


def save_job_snapshot(student_id, job):
    """Idempotently snapshot a normalized live-feed job into the tracker.

    ``job`` must be the surfaced feed record (with ``fingerprint``). The
    snapshot is stored as-is at save time and is NEVER re-derived from the live
    feed on read, so the row survives feed churn/expiry honestly. Returns
    ``(tracker_id, created)`` — created is False when the row already existed
    (UNIQUE(student_id, fingerprint))."""
    if not (job or {}).get("fingerprint"):
        raise TrackerError("A saved job needs its feed fingerprint")
    now = _now()
    fields = {
        "fingerprint": job["fingerprint"],
        "title": (job.get("title") or "").strip() or "Untitled listing",
        "company": (job.get("company") or "").strip(),
        "url": job.get("url") or "",
        "apply_url": job.get("apply_url") or "",
        "location": job.get("location") or "",
        "country": job.get("country") or "",
        "provider": job.get("provider"),
        "source": job.get("source"),
        "match_pct": job.get("match_pct"),
        "work_type": job.get("work_type"),
        "seniority": job.get("seniority"),
        "listing_status": job.get("listing_status"),
        "link_state": job.get("link_state"),
        "is_expired": 1 if job.get("is_expired") else 0,
    }
    with get_cursor() as c:
        existing = c.execute("SELECT id FROM student_job_tracker "
                             "WHERE student_id=? AND fingerprint=?",
                             (student_id, fields["fingerprint"])).fetchone()
        if existing:
            return existing["id"], False
        tracker_id = c.execute(
            "INSERT INTO student_job_tracker (student_id, fingerprint, title, company, url,"
            " apply_url, location, country, provider, source, match_pct, work_type, seniority,"
            " listing_status, link_state, is_expired, stage, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (student_id, fields["fingerprint"], fields["title"], fields["company"],
             fields["url"], fields["apply_url"], fields["location"], fields["country"],
             fields["provider"], fields["source"], fields["match_pct"], fields["work_type"],
             fields["seniority"], fields["listing_status"], fields["link_state"],
             fields["is_expired"], "saved", now, now),
        ).lastrowid
        c.execute("INSERT INTO tracker_stage_history (tracker_id, stage, changed_from, note, created_at)"
                  " VALUES (?,?,?,?,?)",
                  (tracker_id, "saved", None, "Saved from the job feed", now))
        return tracker_id, True


def list_job_tracker(student_id):
    """Tracker entries for a student, newest-updated first, each with its
    append-only stage history. Private to the student."""
    with get_cursor() as c:
        rows = c.execute("SELECT id FROM student_job_tracker WHERE student_id=?"
                         " ORDER BY updated_at DESC, id DESC", (student_id,)).fetchall()
        return [_tracker_row(r["id"], c) for r in rows]


def get_tracker_entry(student_id, tracker_id):
    with get_cursor() as c:
        row = c.execute("SELECT id FROM student_job_tracker WHERE id=? AND student_id=?",
                        (tracker_id, student_id)).fetchone()
        return _tracker_row(row["id"], c) if row else None


def update_tracker_entry(student_id, tracker_id, stage=None, note=None,
                         interview_date=None, application_deadline=None):
    """Apply a validated patch. Stage changes go through the transition
    allow-list and append an audit row; re-applying the same stage is a no-op
    that never writes history. Returns the refreshed entry."""
    with get_cursor() as c:
        row = c.execute("SELECT * FROM student_job_tracker WHERE id=? AND student_id=?",
                        (tracker_id, student_id)).fetchone()
        if row is None:
            raise TrackerError("Tracker entry not found", 404)
        now = _now()
        updates = {}
        new_stage = None
        if stage is not None:
            if stage not in JOB_TRACKER_STAGES:
                raise TrackerError(f"Unknown stage '{stage}'")
            if stage != row["stage"] and stage not in JOB_TRACKER_TRANSITIONS.get(row["stage"], set()):
                raise TrackerError(f"Cannot move a '{row['stage']}' job to '{stage}'", 409)
            new_stage = stage
        if note is not None:
            updates["note"] = str(note or "").strip()
        death_line = _validate_iso_date(interview_date, "interview_date")
        if death_line is not None or interview_date is not None:
            updates["interview_date"] = death_line
        deadline = _validate_iso_date(application_deadline, "application_deadline")
        if deadline is not None or application_deadline is not None:
            updates["application_deadline"] = deadline
        if not updates and new_stage is None:
            return _tracker_row(tracker_id, c)
        values = list(updates.values())
        sets = [f"{k}=?" for k in updates]
        if new_stage is not None:
            sets.append("stage=?")
            values.append(new_stage)
        values.extend([now, tracker_id, student_id])
        c.execute(f"UPDATE student_job_tracker SET {', '.join(sets)}, updated_at=? "
                  f"WHERE id=? AND student_id=?", values)
        if new_stage is not None and new_stage != row["stage"]:
            history_note = updates.get("note", "") or ""
            c.execute("INSERT INTO tracker_stage_history (tracker_id, stage, changed_from, note, created_at)"
                      " VALUES (?,?,?,?,?)",
                      (tracker_id, new_stage, row["stage"], history_note, now))
        return _tracker_row(tracker_id, c)


def archive_tracker_entry(student_id, tracker_id):
    """Archive a tracked job (-> archived_or_expired). The record is NEVER
    destroyed — the stage row (and its history) stays stored forever."""
    with get_cursor() as c:
        row = c.execute("SELECT stage FROM student_job_tracker WHERE id=? AND student_id=?",
                        (tracker_id, student_id)).fetchone()
        if row is None:
            raise TrackerError("Tracker entry not found", 404)
        if row["stage"] == "archived_or_expired":
            return _tracker_row(tracker_id, c)
    return update_tracker_entry(student_id, tracker_id, stage="archived_or_expired")


def delete_saved_only(student_id, tracker_id):
    """Delete ONLY a tracker row still in 'saved'. Anything beyond saved must
    keep its history — the caller gets ``TrackedError`` 409 with the reason."""
    with get_cursor() as c:
        row = c.execute("SELECT stage FROM student_job_tracker WHERE id=? AND student_id=?",
                        (tracker_id, student_id)).fetchone()
        if row is None:
            raise TrackerError("Tracker entry not found", 404)
        if row["stage"] != "saved":
            raise TrackerError(
                f"A '{row['stage']}' job keeps its history — archive it instead of deleting", 409)
        c.execute("DELETE FROM student_job_tracker WHERE id=? AND student_id=?",
                  (tracker_id, student_id))
        return True


def report_job_link(student_id, job):
    """Idempotently record a student's report about a job link.

    This deliberately does not mark a provider record dead or hide it for
    anyone else: reports require later manual verification.
    """
    if not (job or {}).get("fingerprint"):
        raise TrackerError("A link report needs a job fingerprint")
    with get_cursor() as c:
        existing = c.execute("SELECT id FROM job_link_reports WHERE student_id=? AND fingerprint=?",
                             (student_id, job["fingerprint"])).fetchone()
        if existing:
            return existing["id"], False
        report_id = c.execute(
            "INSERT INTO job_link_reports (student_id, fingerprint, url, title, provider, reported_at) "
            "VALUES (?,?,?,?,?,?)",
            (student_id, job["fingerprint"], job.get("apply_url") or job.get("url") or "",
             job.get("title") or "", job.get("provider") or job.get("source") or "", _now()),
        ).lastrowid
        return report_id, True


def list_job_link_reports(student_id):
    with get_cursor() as c:
        rows = c.execute("SELECT id, fingerprint, url, title, provider, reported_at "
                         "FROM job_link_reports WHERE student_id=? ORDER BY reported_at DESC, id DESC",
                         (student_id,)).fetchall()
        return [dict(r) for r in rows]


def record_role_view(student_id, role_id):
    """Record a student opening a role's details (Phase L recently-viewed). A
    re-view bumps ``viewed_at`` (moves the role back to the top of the list)
    and never duplicates. Raises ``ValueError`` for an unknown role. The
    per-student list is capped at ``MAX_ROLE_VIEW_EVENTS`` newest rows."""
    with get_cursor() as c:
        exists = c.execute("SELECT id FROM roles WHERE id=?", (role_id,)).fetchone()
        if exists is None:
            raise ValueError(f"Role {role_id} not found")
        now = _now()
        c.execute(
            "INSERT INTO role_view_events (student_id, role_id, viewed_at) VALUES (?,?,?) "
            "ON CONFLICT(student_id, role_id) DO UPDATE SET viewed_at=excluded.viewed_at",
            (student_id, role_id, now))
        c.execute(
            "DELETE FROM role_view_events WHERE student_id=? AND role_id NOT IN ("
            "SELECT role_id FROM role_view_events WHERE student_id=? "
            "ORDER BY viewed_at DESC, role_id DESC LIMIT ?)",
            (student_id, student_id, MAX_ROLE_VIEW_EVENTS))
        return now


def list_recent_role_views(student_id):
    """A student's recently-viewed roles, newest-first (capped at the same
    limit). Only additive, real role columns ride along (never fabricated) and
    the company name comes from the LEFT JOIN — company-authored roles keep
    their author context, ESCO/catalogue roles stay reference rows."""
    with get_cursor() as c:
        rows = c.execute(
            "SELECT v.viewed_at, r.id, r.title, r.description, r.company_id, r.source, "
            "r.external_id, r.is_reference, r.canonical_role_id, r.canonical_mapping_updated_at, "
            "r.family, r.source_version, r.canonical_status, r.role_key, c.name AS company_name "
            "FROM role_view_events v "
            "JOIN roles r ON r.id = v.role_id "
            "LEFT JOIN companies c ON c.id = r.company_id "
            "WHERE v.student_id=? ORDER BY v.viewed_at DESC, v.role_id DESC LIMIT ?",
            (student_id, MAX_ROLE_VIEW_EVENTS)).fetchall()
        return [_row(r) for r in rows]


def roles_catalog_version():
    """Newest ``source_version`` among reference catalogue roles (max over real
    pinned import versions), or ``None`` when no reference row carries one —
    never synthesized. Drives the honest catalogue-version meta line."""
    with get_cursor() as c:
        row = c.execute(
            "SELECT MAX(source_version) AS ver FROM roles "
            "WHERE is_reference=1 AND source_version IS NOT NULL AND source_version != ''"
        ).fetchone()
        ver = (row["ver"] or "").strip() if row else ""
        return ver or None


def create_role(company_id, title, required_skills, description=None, is_reference=0, source="company",
                parent_role_id=None, source_version=None, aliases=(), isco_codes=(), external_id=None,
                fetched_at=None):
    """required_skills: list of {name, category, level}.

    Additive canonical fields: ``parent_role_id`` (only from a real source
    hierarchy), ``source_version`` (a real pinned dataset version, never
    guessed), ``aliases`` (list of ``{alias, type, language}``), and
    ``isco_codes`` (list of ``{code, source, source_ref}``) are only stored
    when a real source supplied them.
    """
    now = _now()
    title = (title or "").strip() or "Untitled role"
    with get_cursor() as c:
        cur = c.execute(
            "INSERT INTO roles (company_id, title, description, is_reference, source, external_id, "
            "role_key, source_version, canonical_status, is_local_authoring, normalized_title, family, "
            "parent_role_id, fetched_at, imported_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,'active',?,?,?,?,?,?,?)",
            (company_id, title, description, int(is_reference), source, external_id,
             _role_key_for(source, title, external_id), source_version,
             int(source != "esco"), _canonical_title(title), _canonical_family(title),
             parent_role_id, fetched_at, now, now))
        role_id = cur.lastrowid
        for rs in required_skills:
            sk = get_or_create_skill(rs["name"], rs.get("category", "General"))
            c.execute("INSERT INTO role_skills (role_id, skill_id, required_level) VALUES (?,?,?)",
                      (role_id, sk["id"], rs["level"]))
            _record_skill_source(c, role_id, sk["id"], source, None, now)
        for a in aliases:
            _insert_alias(c, role_id, a.get("alias"), a.get("type", "alternative"),
                          a.get("language", "en"), now)
        for ic in isco_codes:
            _insert_isco_code(c, role_id, ic.get("code"), ic.get("source", "esco"),
                              ic.get("source_ref"), now)
        return get_role(role_id)


def _insert_alias(cur, role_id, alias, alias_type, language, created_at):
    alias = (alias or "").strip()
    if not alias:
        return
    if alias_type not in ("alternative", "hidden"):
        alias_type = "alternative"
    cur.execute(
        "INSERT OR IGNORE INTO role_aliases (role_id, alias, alias_type, language, created_at) "
        "VALUES (?,?,?,?,?)",
        (role_id, alias, alias_type, language or "en", created_at))


def _insert_isco_code(cur, role_id, code, source, source_ref, created_at):
    code = (code or "").strip()
    if not code:
        return
    cur.execute(
        "INSERT OR IGNORE INTO role_isco_codes (role_id, isco_code, source, source_ref, created_at) "
        "VALUES (?,?,?,?,?)",
        (role_id, code, source or "esco", source_ref, created_at))


def update_role(role_id, title=None, description=None, required_skills=None):
    with get_cursor() as c:
        new_title = (title or "").strip()
        if new_title:
            c.execute(
                "UPDATE roles SET title=?, normalized_title=?, family=?, updated_at=? WHERE id=?",
                (new_title, _canonical_title(new_title), _canonical_family(new_title), _now(), role_id))
        if description is not None:
            c.execute("UPDATE roles SET description=?, updated_at=? WHERE id=?",
                      (description, _now(), role_id))
        if required_skills is not None:
            row = c.execute("SELECT source FROM roles WHERE id=?", (role_id,)).fetchone()
            skill_source = (row["source"] if row else "company") or "company"
            now = _now()
            c.execute("UPDATE roles SET updated_at=? WHERE id=?", (now, role_id))
            c.execute("DELETE FROM role_skills WHERE role_id=?", (role_id,))
            c.execute("DELETE FROM role_skill_sources WHERE role_id=?", (role_id,))
            for rs in required_skills:
                sk = get_or_create_skill(rs["name"], rs.get("category", "General"))
                c.execute("INSERT INTO role_skills (role_id, skill_id, required_level) VALUES (?,?,?)",
                          (role_id, sk["id"], rs["level"]))
                _record_skill_source(c, role_id, sk["id"], skill_source, None, now)
        return get_role(role_id)


def delete_role(role_id):
    with get_cursor() as c:
        c.execute("DELETE FROM roles WHERE id=?", (role_id,))
        # clear students' target roles pointing here
        c.execute("UPDATE students SET target_role_id=NULL WHERE target_role_id=?", (role_id,))
    return 1


def _catalog_company_id(c):
    row = c.execute("SELECT id FROM companies WHERE name=?", (CATALOG_COMPANY_NAME,)).fetchone()
    return row["id"] if row else None


def import_esco_role(uri, title, essential=(), optional=(), required_level="Intermediate",
                     max_total=16, source_version=None, isco_code=None, aliases=(),
                     source_language=None, import_imprint=None, parent_uri=None, conn=None):
    """Import an ESCO occupation as a selectable, per-student target role.

    Idempotent: one ``roles`` row per ESCO ``source``+``external_id`` pair, so
    selecting the same occupation twice never duplicates roles or skills.

    Source honesty is preserved: the row carries ``source='esco'`` and its ESCO
    occupation URI as ``external_id``, and it is excluded from company rosters
    (``list_roles``/``list_feed_roles``) so an ESCO occupation is never shown as
    a company-posted opening.

    ESCO itself supplies no proficiency levels, so required skills use the
    platform's documented neutral level (``required_level``, default
    Intermediate) -- never a level ESCO did not provide. ESCO ``essential``
    skills are imported as ``skill_kind='essential'`` and ``optional`` skills as
    ``'optional'``; noisy tail skills are trimmed via ``max_total``.

    ``source_version``/``isco_code``/``aliases`` are recorded only when the
    import/reference flow received them from a real source (never guessed).
    ``source_language``/``import_imprint`` are the Phase E import-audit trail:
    written only by the ESCO refresh service on a whole-row re-import.
    ``parent_uri`` links to an already-imported managed ESCO occupation when one
    exists. ``conn`` lets the managed refresh service run this inside its single
    apply transaction (backward-compatible; default opens its own cursor).
    """
    uri = (uri or "").strip()
    if not uri:
        return None
    cursor = get_cursor() if conn is None else contextlib.nullcontext(conn)
    with cursor as c:
        existing = c.execute("SELECT id FROM roles WHERE source='esco' AND external_id=?",
                             (uri,)).fetchone()
        if existing:
            return get_role(existing["id"])
        company_id = _catalog_company_id(c)
        essential = [str(s).strip() for s in (essential or []) if str(s).strip()]
        optional = [str(s).strip() for s in (optional or []) if str(s).strip()]
        if not essential and not optional:
            return None
        if len(essential) + len(optional) > max_total:
            optional = optional[:max(0, max_total - len(essential))]
        title = (title or "").strip() or "ESCO occupation"
        now = _now()
        parent_role_id = None
        if parent_uri:
            prow = c.execute("SELECT id FROM roles WHERE source='esco' AND external_id=?",
                             (parent_uri,)).fetchone()
            if prow:
                parent_role_id = prow["id"]
        cur = c.execute(
            "INSERT INTO roles (company_id, title, description, is_reference, source, external_id, "
            "role_key, source_version, canonical_status, is_local_authoring, normalized_title, family, "
            "source_language, import_imprint, parent_role_id, fetched_at, imported_at, updated_at) "
            "VALUES (?,?,?,0,'esco',?,?,?, 'active', 0, ?,?,?,?,?,?,?,?)",
            (company_id, title,
             "Occupation imported from the ESCO labour-market catalogue.", uri,
             _role_key_for("esco", title, uri), source_version,
             _canonical_title(title), _canonical_family(title),
             source_language, import_imprint, parent_role_id, now, now, now))
        role_id = cur.lastrowid
        if isco_code:
            _insert_isco_code(c, role_id, isco_code, "esco", uri, now)
        for a in aliases:
            _insert_alias(c, role_id, a.get("alias"), a.get("type", "alternative"),
                          a.get("language", "en"), now)
        seen = set()
        for name, kind in list((n, "essential") for n in essential) + list((n, "optional") for n in optional):
            key = name.lower().strip()
            if key in seen:
                continue
            seen.add(key)
            sk = get_or_create_skill(name, "Professional Skill")
            c.execute("INSERT INTO role_skills (role_id, skill_id, required_level, skill_kind) "
                      "VALUES (?,?,?,?)",
                      (role_id, sk["id"], required_level, kind))
            _record_skill_source(c, role_id, sk["id"], "esco", None, now)
        return get_role(role_id)


def _record_skill_source(cur, role_id, skill_id, source, source_uri, attested_at=None):
    cur.execute(
        "INSERT OR IGNORE INTO role_skill_sources (role_id, skill_id, source, source_uri, attested_at) "
        "VALUES (?,?,?,?,?)",
        (role_id, skill_id, source, source_uri, attested_at or _now()))


def backfill_role_canonical_metadata():
    """Idempotent startup backfill for rows created before migration 0003.

    Fills only fields that are provably derivable from existing data (title
    normalization, family, role_key, the explicit local-authoring flag) and
    records per-skill provenance copied from each role's own source. Never
    invents versions, URIs, ISCO codes, aliases, or hierarchy edges - those
    stay NULL/absent until a real source supplies them.
    """
    now = _now()
    with get_cursor() as c:
        rows = c.execute(
            "SELECT id, title, source, external_id, role_key, is_local_authoring, "
            "normalized_title, family, imported_at, updated_at FROM roles"
        ).fetchall()
        for r in rows:
            updates = []
            params = []
            if not r["normalized_title"] or not r["family"]:
                updates.append("normalized_title=?, family=?")
                params.extend([_canonical_title(r["title"]), _canonical_family(r["title"])])
            if not r["role_key"]:
                updates.append("role_key=?")
                params.append(_role_key_for(r["source"], r["title"], r["external_id"]))
            if not r["is_local_authoring"] and r["source"] != "esco":
                updates.append("is_local_authoring=1")
            if (r["source"] == "esco" and not r["imported_at"]
                    and not r["updated_at"]):
                # Legacy ESCO row: it exists (so it was imported), but the import
                # time was never recorded. Mark an honest "known since backfill"
                # timestamp rather than claiming a specific import instant.
                updates.append("updated_at=?")
                params.append(now)
            if updates:
                params.append(r["id"])
                c.execute(f"UPDATE roles SET {', '.join(updates)} WHERE id=?", tuple(params))
        # Per-skill provenance: each existing role_skills attestation is declared
        # with the role's own source (company/catalog/esco), URI unknown.
        skill_rows = c.execute("""
            SELECT rs.role_id, rs.skill_id, r.source
            FROM role_skills rs JOIN roles r ON r.id=rs.role_id
            LEFT JOIN role_skill_sources rss
              ON rss.role_id=rs.role_id AND rss.skill_id=rs.skill_id
            WHERE rss.role_id IS NULL""").fetchall()
        attested = _now()
        for s in skill_rows:
            _record_skill_source(c, s["role_id"], s["skill_id"],
                                 s["source"] or "company", None, attested)


def role_aliases(role_id):
    with get_cursor() as c:
        return [_row(r) for r in c.execute(
            "SELECT id, alias, alias_type, language, created_at FROM role_aliases "
            "WHERE role_id=? ORDER BY alias_type, language, alias", (role_id,)).fetchall()]


def add_role_alias(role_id, alias, alias_type="alternative", language="en"):
    with get_cursor() as c:
        _insert_alias(c, role_id, alias, alias_type, language, _now())
        return True


def remove_role_alias(alias_id):
    with get_cursor() as c:
        cur = c.execute("DELETE FROM role_aliases WHERE id=?", (alias_id,))
        return cur.rowcount


def role_isco_codes(role_id):
    with get_cursor() as c:
        return [_row(r) for r in c.execute(
            "SELECT id, isco_code, source, source_ref, created_at FROM role_isco_codes "
            "WHERE role_id=? ORDER BY source, isco_code", (role_id,)).fetchall()]


def role_skill_sources(role_id):
    with get_cursor() as c:
        rows = c.execute(
            "SELECT skill_id, source, source_uri, attested_at FROM role_skill_sources "
            "WHERE role_id=?", (role_id,)).fetchall()
        return {r["skill_id"]: _row(r) for r in rows}


def related_roles(role_id):
    """Roles reachable through a *maintained* relationship ONLY: the real
    parent_role_id / family / superseded_by_role_id links. Never invents career
    transitions; no relationship => None / empty lists. Children, siblings and
    superseded-by links are restricted to active roles (mirrors Phase D status
    gating); the direct parent and the superseded_by target are shown as-is
    because they are the role's own real links."""
    with get_cursor() as c:
        def role_row(rid):
            r = c.execute(
                "SELECT r.*, c.name AS company_name FROM roles r "
                "LEFT JOIN companies c ON c.id=r.company_id WHERE r.id=?",
                (rid,)).fetchone()
            if not r:
                return None
            rd = _row(r)
            rd["required_skills"] = role_skills(c, rid)
            return rd

        self_row = c.execute("SELECT * FROM roles WHERE id=?", (role_id,)).fetchone()
        if not self_row:
            return None
        parent = role_row(self_row["parent_role_id"]) if self_row["parent_role_id"] else None
        children = []
        for r in c.execute(
                "SELECT r.*, c.name AS company_name FROM roles r "
                "LEFT JOIN companies c ON c.id=r.company_id "
                "WHERE r.parent_role_id=? AND " + _ACTIVE_ROLE_CLAUSE +
                " ORDER BY r.title", (role_id,)).fetchall():
            rd = _row(r)
            rd["required_skills"] = role_skills(c, r["id"])
            children.append(rd)
        siblings = []
        fam = (self_row["family"] or "").strip()
        if fam:
            for r in c.execute(
                    "SELECT r.*, c.name AS company_name FROM roles r "
                    "LEFT JOIN companies c ON c.id=r.company_id "
                    "WHERE r.family=? AND r.id <> ? AND "
                    "(r.parent_role_id IS NULL OR r.parent_role_id <> ?) AND "
                    + _ACTIVE_ROLE_CLAUSE +
                    " ORDER BY r.title", (fam, role_id, role_id)).fetchall():
                rd = _row(r)
                rd["required_skills"] = role_skills(c, r["id"])
                siblings.append(rd)
        supersedes = []
        for r in c.execute(
                "SELECT r.*, c.name AS company_name FROM roles r "
                "LEFT JOIN companies c ON c.id=r.company_id "
                "WHERE r.superseded_by_role_id=? AND " + _ACTIVE_ROLE_CLAUSE +
                " ORDER BY r.title", (role_id,)).fetchall():
            rd = _row(r)
            rd["required_skills"] = role_skills(c, r["id"])
            supersedes.append(rd)
        superseded_by = role_row(self_row["superseded_by_role_id"]) if self_row["superseded_by_role_id"] else None
    return {
        "parent": parent,
        "children": children,
        "siblings": siblings,
        "supersedes": supersedes,
        "superseded_by": superseded_by,
    }


def role_provenance(role_id):
    """Full canonical metadata for one role: fields + aliases + ISCO codes +
    per-skill provenance. Mirrors the role's own source - a locally authored
    role is never presented with ESCO labels."""
    role = get_role(role_id)
    if not role:
        return None
    return {
        "role_id": role["id"],
        "title": role["title"],
        "source": role.get("source") or "company",
        "role_key": role.get("role_key"),
        "canonical_status": role.get("canonical_status") or "active",
        "source_version": role.get("source_version"),
        "external_id": role.get("external_id"),
        "is_local_authoring": bool(role.get("is_local_authoring")),
        "family": role.get("family"),
        "parent_role_id": role.get("parent_role_id"),
        "fetched_at": role.get("fetched_at"),
        "imported_at": role.get("imported_at"),
        "updated_at": role.get("updated_at"),
        "aliases": role_aliases(role["id"]),
        "isco_codes": role_isco_codes(role["id"]),
        "skill_sources": role_skill_sources(role["id"]),
        "mapping": mapping_of(role["id"]),
        "related": related_roles(role["id"]),
    }


# ---------------------------------------------------------- role mapping (Phase F)

# Canonical pool a company role can be mapped *to*: reference roles that are
# still active (never deprecated/superseded). Local/company roles and imported
# non-reference rows are excluded by construction.
CANONICAL_POOL_CLAUSE = "r.is_reference=1 AND " + _ACTIVE_ROLE_CLAUSE


def canonical_mapping_pool():
    """Active reference roles eligible as mapping targets (read-only)."""
    with get_cursor() as c:
        rows = c.execute(
            "SELECT r.*, c.name AS company_name FROM roles r "
            "LEFT JOIN companies c ON c.id=r.company_id "
            "WHERE " + CANONICAL_POOL_CLAUSE + " ORDER BY r.title").fetchall()
        out = []
        for r in rows:
            rd = _row(r)
            rd["required_skills"] = role_skills(c, r["id"])
            out.append(rd)
        return out


def mapping_of(role_id):
    """The role's confirmed canonical mapping (dict or None), or None when the
    role/its target no longer exists."""
    with get_cursor() as c:
        row = c.execute(
            "SELECT canonical_role_id, canonical_mapping_updated_at FROM roles WHERE id=?",
            (role_id,)).fetchone()
        if not row or not row["canonical_role_id"]:
            return None
        target = c.execute(
            "SELECT id, title, source, external_id FROM roles WHERE id=?",
            (row["canonical_role_id"],)).fetchone()
        if not target:
            return None
        return {
            "canonical_role_id": target["id"],
            "mapped_title": target["title"],
            "source": target["source"] or "catalog",
            "external_id": target["external_id"],
            "mapped_at": row["canonical_mapping_updated_at"],
        }


def set_mapping(role_id, canonical_role_id, actor):
    """Confirm or clear a company role's canonical mapping. Append-only audit:
    every write records exactly one role_mapping_events row.

    ``canonical_role_id`` None unmaps; anything else must be an active reference
    role and never the role itself - otherwise ValueError. Re-confirming the
    current target is a no-op. Never touches the local role's title, description
    or skills. ``actor`` is the user dict from ``_current_user``.
    """
    now = _now()
    with get_cursor() as c:
        row = c.execute("SELECT canonical_role_id FROM roles WHERE id=?", (role_id,)).fetchone()
        if not row:
            raise ValueError("role not found")
        current = row["canonical_role_id"]
        if canonical_role_id is None:
            target_id = None
            action = None
        else:
            target_id = int(canonical_role_id)
            if target_id == role_id:
                raise ValueError("cannot map a role to itself")
            ref = c.execute(
                "SELECT id FROM roles r WHERE r.id=? AND " + CANONICAL_POOL_CLAUSE,
                (target_id,)).fetchone()
            if not ref:
                raise ValueError("target is not an active reference role")
            if current == target_id:
                return get_role(role_id)
            action = "changed" if current else "mapped"
        c.execute(
            "UPDATE roles SET canonical_role_id=?, canonical_mapping_updated_at=? WHERE id=?",
            (target_id, now, role_id))
        if action is not None:
            c.execute(
                "INSERT INTO role_mapping_events "
                "(role_id, action, from_canonical_role_id, to_canonical_role_id, "
                "actor_user_id, actor_role, created_at) VALUES (?,?,?,?,?,?,?)",
                (role_id, action, current, target_id, actor["id"],
                 actor.get("role") or actor.get("display_name") or "user", now))
        elif current:
            c.execute(
                "INSERT INTO role_mapping_events "
                "(role_id, action, from_canonical_role_id, to_canonical_role_id, "
                "actor_user_id, actor_role, created_at) VALUES (?,?,?,?,?,?,?)",
                (role_id, "unmapped", current, None, actor["id"],
                 actor.get("role") or actor.get("display_name") or "user", now))
        return get_role(role_id)


def mapping_history(role_id):
    """Append-only audit for one role, newest first, with canonical titles
    resolved live for both endpoints of each event."""
    with get_cursor() as c:
        rows = c.execute(
            "SELECT * FROM role_mapping_events WHERE role_id=? ORDER BY id DESC",
            (role_id,)).fetchall()
        out = []
        for r in rows:
            def title_of(rid):
                if rid is None:
                    return None
                t = c.execute("SELECT title FROM roles WHERE id=?", (rid,)).fetchone()
                return t["title"] if t else None
            out.append({
                "event_id": r["id"],
                "action": r["action"],
                "from_canonical_role_id": r["from_canonical_role_id"],
                "from_title": title_of(r["from_canonical_role_id"]),
                "to_canonical_role_id": r["to_canonical_role_id"],
                "to_title": title_of(r["to_canonical_role_id"]),
                "actor_user_id": r["actor_user_id"],
                "actor_role": r["actor_role"],
                "created_at": r["created_at"],
            })
        return out


# ---------------------------------------------------------------- students

def list_students():
    with get_cursor() as c:
        return [_row(r) for r in c.execute("SELECT * FROM students ORDER BY name").fetchall()]


def get_student(student_id):
    with get_cursor() as c:
        r = c.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if not r:
            return None
        sd = _row(r)
        sd["self_reported_skills"] = student_self_reported(c, student_id)
        sd["verified_skills"] = student_verified(c, student_id)
        if sd.get("target_role_id"):
            sd["target_role"] = role_from_id(c, sd["target_role_id"])
        return sd


def get_student_by_user(user_id):
    with get_cursor() as c:
        r = c.execute("SELECT * FROM students WHERE user_id=?", (user_id,)).fetchone()
        if not r:
            return None
        return get_student(r["id"])


def student_self_reported(cur, student_id):
    return [_row(r) for r in cur.execute("""
        SELECT s.id AS skill_id, s.name, s.category, sr.level, sr.source, sr.evidence
        FROM self_reported_skills sr JOIN skills s ON s.id=sr.skill_id
        WHERE sr.student_id=? ORDER BY s.name""", (student_id,)).fetchall()]


def student_verified(cur, student_id):
    return [_row(r) for r in cur.execute("""
        SELECT s.id AS skill_id, s.name, s.category, v.level, v.verified_at
        FROM verified_skills v JOIN skills s ON s.id=v.skill_id
        WHERE v.student_id=? ORDER BY s.name""", (student_id,)).fetchall()]


# ------------------------------------------------------------------ Phase Q: prepare-for-job skill readiness

def _skill_lookup_key(name):
    """Exact-only canonical lookup key for a skill name (never fuzzy)."""
    canon, _ = skill_registry.normalise_name(name)
    return ((canon or "").strip() or (name or "").strip()).lower()


def prepare_job_view(student, job):
    """Readiness view for a surfaced feed job the student is considering.

    Pure data mapping over the student's OWN verified + self-reported skill
    rows and the job's ``required_skills`` names. Resolution is explicit
    canonical-name lookup against the ``skills`` table — ``skill_id`` is a REAL
    skills row id or null, a name with no skills row is honestly ``no_path``
    (never a guessed gap), and student skill rows are never fabricated."""
    required = [str(n).strip() for n in (job.get("required_skills") or []) if str(n).strip()]
    verified = student.get("verified_skills") or []
    reported = student.get("self_reported_skills") or []
    vmap, rmap = {}, {}
    for v in verified:
        vmap.setdefault(_skill_lookup_key(v.get("name")), v)
    for r in reported:
        rmap.setdefault(_skill_lookup_key(r.get("name")), r)

    skills = []
    for name in required:
        canon, _ = skill_registry.normalise_name(name)
        lookup = (canon or name).strip()
        key = lookup.lower()
        db_row = get_skill_by_name(lookup) if lookup else None
        matched = vmap.get(key) or rmap.get(key)
        if key in vmap:
            status = "verified"
        elif key in rmap:
            status = "self_reported"
        elif db_row:
            status = "gap"
        else:
            status = "no_path"
        item = {
            "name": name,
            "skill_id": (db_row["id"] if db_row and db_row.get("id")
                         else matched.get("skill_id") if matched else None),
            "status": status,
        }
        if matched:
            item["student_level"] = matched.get("level")
            if matched.get("verified_at"):
                item["verified_at"] = matched["verified_at"]
        skills.append(item)

    return {
        "job": {
            "title": job.get("title") or "",
            "company": job.get("company") or "",
            "location_label": job.get("location_label"),
            "match_pct": job.get("match_pct"),
            "apply_url": job.get("apply_url") or "",
            "listing_status": job.get("listing_status"),
            "provider": job.get("provider"),
        },
        "skills": skills,
    }


def role_from_id(cur, role_id):
    r = cur.execute("SELECT * FROM roles WHERE id=?", (role_id,)).fetchone()
    if not r:
        return None
    rd = _row(r)
    rd["required_skills"] = role_skills(cur, role_id)
    return rd


def create_student(name, email, university, user_id=None, education_level=None):
    with get_cursor() as c:
        cur = c.execute("INSERT INTO students (name, email, university, user_id, education_level) VALUES (?,?,?,?,?)",
                        (name, email, university, user_id, education_level))
        return get_student(cur.lastrowid)


def update_student(student_id, **fields):
    allowed = {"name", "email", "university", "target_role_id", "cv_filename", "cohort_confirmed", "share_public", "education_level"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed and v is not None:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return get_student(student_id)
    vals.append(student_id)
    with get_cursor() as c:
        c.execute(f"UPDATE students SET {', '.join(sets)} WHERE id=?", vals)
        return get_student(student_id)


def delete_student(student_id):
    with get_cursor() as c:
        c.execute("DELETE FROM students WHERE id=?", (student_id,))
    return 1


def replace_self_reported_skills(student_id, skills):
    """skills: list of {name, level, [category], [evidence]} — replaces the
    student's full self-reported set. Evidence is optional; manual/seed entries
    simply have NULL evidence."""
    with get_cursor() as c:
        c.execute("DELETE FROM self_reported_skills WHERE student_id=?", (student_id,))
        for s in skills:
            sk = get_or_create_skill(s["name"], s.get("category", "General"))
            c.execute("INSERT INTO self_reported_skills (student_id, skill_id, level, source, evidence) "
                      "VALUES (?,?,?,?,?)",
                      (student_id, sk["id"], s["level"], s.get("source", "cv"), s.get("evidence")))
        return get_student(student_id)


def update_verified_skill(student_id, skill_id, level):
    with get_cursor() as c:
        c.execute("""INSERT INTO verified_skills (student_id, skill_id, level, verified_at)
                     VALUES (?,?,?, datetime('now'))
                     ON CONFLICT(student_id, skill_id) DO UPDATE SET level=excluded.level, verified_at=datetime('now')""",
                  (student_id, skill_id, level))
        return get_student(student_id)


# ---------------------------------------------------------------- learning

def list_learning_path(student_id):
    with get_cursor() as c:
        rows = c.execute("""
            SELECT l.id, l.student_id, l.skill_id, s.name AS skill_name, s.category,
                   l.explanation, l.practice_exercise, l.mini_project, l.resources, l.roadmap, l.progress,
                   l.blueprint_version, l.blueprint_competencies, l.plan_modules, l.generated_at
            FROM learning_path_items l JOIN skills s ON s.id=l.skill_id
            WHERE l.student_id=? ORDER BY s.name""", (student_id,)).fetchall()
        out = []
        for r in rows:
            d = _row(r)
            d["resources"] = _json_loads(d.get("resources"))
            d["roadmap"] = _json_loads(d.get("roadmap"))
            d["progress"] = _json_loads(d.get("progress")) or []
            d["plan_modules"] = _json_loads(d.get("plan_modules"))
            d["modules"] = d["plan_modules"]
            d["blueprint_competencies"] = _json_loads(d.get("blueprint_competencies"))
            out.append(d)
        return out


def get_learning_item(student_id, skill_id):
    with get_cursor() as c:
        r = c.execute("""
            SELECT l.id, l.student_id, l.skill_id, s.name AS skill_name, s.category,
                   l.explanation, l.practice_exercise, l.mini_project, l.resources, l.roadmap, l.progress,
                   l.blueprint_version, l.blueprint_competencies, l.plan_modules, l.generated_at
            FROM learning_path_items l JOIN skills s ON s.id=l.skill_id
            WHERE l.student_id=? AND l.skill_id=?""", (student_id, skill_id)).fetchone()
        if not r:
            return None
        d = _row(r)
        d["resources"] = _json_loads(d.get("resources"))
        d["roadmap"] = _json_loads(d.get("roadmap"))
        d["progress"] = _json_loads(d.get("progress")) or []
        d["plan_modules"] = _json_loads(d.get("plan_modules"))
        d["modules"] = d["plan_modules"]
        d["blueprint_competencies"] = _json_loads(d.get("blueprint_competencies"))
        return d


def upsert_learning_item(student_id, skill_id, explanation, practice_exercise, mini_project,
                         resources=None, roadmap=None, modules=None, blueprint_version=None, blueprint_competencies=None):
    with get_cursor() as c:
        c.execute("""INSERT INTO learning_path_items (student_id, skill_id, explanation, practice_exercise, mini_project, resources, roadmap,
                     blueprint_version, blueprint_competencies, plan_modules)
                     VALUES (?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(student_id, skill_id) DO UPDATE SET
                       explanation=excluded.explanation,
                       practice_exercise=excluded.practice_exercise,
                       mini_project=excluded.mini_project,
                       resources=excluded.resources,
                       roadmap=excluded.roadmap,
                       blueprint_version=excluded.blueprint_version,
                       blueprint_competencies=excluded.blueprint_competencies,
                       plan_modules=excluded.plan_modules,
                       generated_at=datetime('now')""",
                  (student_id, skill_id, explanation, practice_exercise, mini_project,
                   _json_dumps(resources), _json_dumps(roadmap),
                   blueprint_version, _json_dumps(blueprint_competencies), _json_dumps(modules)))
        return get_learning_item(student_id, skill_id)


def update_learning_progress(student_id, skill_id, steps):
    """Persist the completed roadmap step numbers for a learning item."""
    with get_cursor() as c:
        c.execute("UPDATE learning_path_items SET progress=? WHERE student_id=? AND skill_id=?",
                  (_json_dumps(sorted(set(steps))), student_id, skill_id))
    return get_learning_item(student_id, skill_id)


def get_career_roadmap(student_id, role_id):
    with get_cursor() as c:
        row = c.execute("SELECT * FROM career_roadmaps WHERE student_id=? AND role_id=?",
                        (student_id, role_id)).fetchone()
        if not row:
            return None
        d = _row(row)
        d["roadmap"] = _json_loads(d["roadmap"])
        return d


def upsert_career_roadmap(student_id, role_id, roadmap):
    with get_cursor() as c:
        c.execute("""INSERT INTO career_roadmaps (student_id, role_id, roadmap)
                     VALUES (?,?,?)
                     ON CONFLICT(student_id, role_id) DO UPDATE SET
                       roadmap=excluded.roadmap,
                       generated_at=datetime('now')""",
                  (student_id, role_id, _json_dumps(roadmap)))
    return get_career_roadmap(student_id, role_id)


# ---------------------------------------------------------------- tutor

VALID_TUTOR_IDS = ("nova", "axel", "sage", "vex")


def _conversation_title(content):
    text = re.sub(r"\s+", " ", (content or "").strip())
    if not text:
        return "New conversation"
    if len(text) <= 56:
        return text
    clipped = text[:56].rsplit(" ", 1)[0].strip()
    return f"{clipped or text[:56].strip()}..."


def _conversation_payload(row, message_count=None, last_message_at=None, preview=None):
    data = _row(row)
    if not data:
        return None
    if message_count is not None:
        data["message_count"] = int(message_count or 0)
    if last_message_at is not None:
        data["last_message_at"] = last_message_at
    if preview is not None:
        data["preview"] = preview
    return data


def create_tutor_conversation(student_id, tutor_id, title=None):
    if tutor_id not in VALID_TUTOR_IDS:
        raise ValueError("invalid_tutor")
    with get_cursor() as c:
        cur = c.execute(
            """
            INSERT INTO tutor_conversations (student_id, tutor_id, title)
            VALUES (?, ?, ?)
            """,
            (student_id, tutor_id, _conversation_title(title)),
        )
        row = c.execute("SELECT * FROM tutor_conversations WHERE id=?", (cur.lastrowid,)).fetchone()
        return _conversation_payload(row, message_count=0, preview="")


def get_tutor_conversation(student_id, conversation_id):
    with get_cursor() as c:
        row = c.execute(
            """
            SELECT
                tc.*,
                COUNT(tm.id) AS message_count,
                MAX(tm.created_at) AS last_message_at,
                (
                    SELECT content
                    FROM tutor_messages tm2
                    WHERE tm2.conversation_id = tc.id
                    ORDER BY tm2.id DESC
                    LIMIT 1
                ) AS preview
            FROM tutor_conversations tc
            LEFT JOIN tutor_messages tm ON tm.conversation_id = tc.id
            WHERE tc.student_id = ? AND tc.id = ?
            GROUP BY tc.id
            """,
            (student_id, conversation_id),
        ).fetchone()
        if not row:
            return None
        return _conversation_payload(
            row,
            message_count=row["message_count"],
            last_message_at=row["last_message_at"],
            preview=row["preview"] or "",
        )


def list_tutor_conversations(student_id, include_empty=False):
    with get_cursor() as c:
        rows = c.execute(
            """
            SELECT
                tc.*,
                COUNT(tm.id) AS message_count,
                MAX(tm.created_at) AS last_message_at,
                (
                    SELECT content
                    FROM tutor_messages tm2
                    WHERE tm2.conversation_id = tc.id
                    ORDER BY tm2.id DESC
                    LIMIT 1
                ) AS preview
            FROM tutor_conversations tc
            LEFT JOIN tutor_messages tm ON tm.conversation_id = tc.id
            WHERE tc.student_id = ?
            GROUP BY tc.id
            HAVING ? = 1 OR COUNT(tm.id) > 0
            ORDER BY COALESCE(MAX(tm.created_at), tc.updated_at) DESC, tc.id DESC
            """,
            (student_id, 1 if include_empty else 0),
        ).fetchall()
        return [
            _conversation_payload(
                r,
                message_count=r["message_count"],
                last_message_at=r["last_message_at"],
                preview=r["preview"] or "",
            )
            for r in rows
        ]


def ensure_tutor_conversation(student_id, tutor_id, conversation_id=None, title_seed=None):
    if conversation_id is not None:
        conversation = get_tutor_conversation(student_id, conversation_id)
        if not conversation:
            return None
        if tutor_id and conversation["tutor_id"] != tutor_id:
            return None
        return conversation
    if tutor_id not in VALID_TUTOR_IDS:
        raise ValueError("invalid_tutor")
    with get_cursor() as c:
        row = c.execute(
            """
            SELECT *
            FROM tutor_conversations
            WHERE student_id = ? AND tutor_id = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (student_id, tutor_id),
        ).fetchone()
        if row:
            return _conversation_payload(row)
    return create_tutor_conversation(student_id, tutor_id, title_seed)


def add_tutor_message(student_id, tutor_id, skill_id, role, content, conversation_id=None):
    conversation = None
    if conversation_id is not None:
        conversation = get_tutor_conversation(student_id, conversation_id)
        if not conversation:
            raise ValueError("conversation_not_found")
        if tutor_id and conversation["tutor_id"] != tutor_id:
            raise ValueError("conversation_tutor_mismatch")
        tutor_id = conversation["tutor_id"]
    elif tutor_id:
        conversation = ensure_tutor_conversation(student_id, tutor_id, title_seed=content if role == "user" else None)
        conversation_id = conversation["id"] if conversation else None

    with get_cursor() as c:
        cur = c.execute(
            """
            INSERT INTO tutor_messages (student_id, tutor_id, skill_id, role, content, conversation_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (student_id, tutor_id, skill_id, role, content, conversation_id),
        )
        if conversation_id is not None:
            if role == "user" and (not conversation or conversation.get("title") == "New conversation"):
                c.execute(
                    """
                    UPDATE tutor_conversations
                    SET title = ?, updated_at = datetime('now')
                    WHERE id = ? AND student_id = ?
                    """,
                    (_conversation_title(content), conversation_id, student_id),
                )
            else:
                c.execute(
                    "UPDATE tutor_conversations SET updated_at = datetime('now') WHERE id = ? AND student_id = ?",
                    (conversation_id, student_id),
                )
        return _row(c.execute("SELECT * FROM tutor_messages WHERE id=?", (cur.lastrowid,)).fetchone())


def list_tutor_messages(student_id, tutor_id=None, skill_id=None, conversation_id=None):
    """Messages for one student, optionally scoped to a real conversation.

    ``conversation_id`` is the Phase 4A primary chat boundary. Without it, the
    older tutor-scoped behavior remains available for legacy callers and tests:
    rows written before tutor separation have ``tutor_id`` NULL and are treated
    as belonging to whichever tutor is viewing them.
    """
    with get_cursor() as c:
        base, params = "SELECT * FROM tutor_messages WHERE student_id=?", [student_id]
        if conversation_id is not None:
            base += " AND conversation_id=?"
            params.append(conversation_id)
        elif tutor_id:
            base += " AND (tutor_id=? OR tutor_id IS NULL)"
            params.append(tutor_id)
        if skill_id:
            base += " AND skill_id=?"
            params.append(skill_id)
        base += " ORDER BY id"
        rows = c.execute(base, params).fetchall()
        return [_row(r) for r in rows]


def clear_tutor_messages(student_id, tutor_id, conversation_id=None):
    """Clear only the requested conversation, with legacy tutor-level fallback."""
    with get_cursor() as c:
        if conversation_id is not None:
            row = c.execute(
                """
                SELECT id
                FROM tutor_conversations
                WHERE student_id = ? AND id = ? AND tutor_id = ?
                """,
                (student_id, conversation_id, tutor_id),
            ).fetchone()
            if not row:
                return False
            c.execute("DELETE FROM tutor_messages WHERE student_id=? AND conversation_id=?",
                      (student_id, conversation_id))
            c.execute("DELETE FROM tutor_conversation_memory_threads WHERE conversation_id=?",
                      (conversation_id,))
            c.execute(
                """
                UPDATE tutor_conversations
                SET title = 'New conversation', updated_at = datetime('now')
                WHERE student_id = ? AND id = ?
                """,
                (student_id, conversation_id),
            )
            return True
        c.execute("DELETE FROM tutor_messages WHERE student_id=? AND (tutor_id=? OR tutor_id IS NULL)",
                  (student_id, tutor_id))
        return True


def get_tutor_preference(student_id):
    """Which global tutor (nova/axel/sage/vex) the student wants. None = default."""
    with get_cursor() as c:
        row = c.execute("SELECT tutor_id FROM tutor_preferences WHERE student_id=?",
                        (student_id,)).fetchone()
        return row["tutor_id"] if row else None


def set_tutor_preference(student_id, tutor_id, mode=None, language=None):
    """Persist the student's tutor persona, working mode and/or language.

    Each argument is optional: ``None`` keeps whatever is currently stored (and
    a brand-new row defaults the tutor to 'nova' and the language to 'auto').
    Returns the new tutor id.
    """
    with get_cursor() as c:
        row = c.execute("SELECT tutor_id, mode, language FROM tutor_preferences WHERE student_id=?",
                        (student_id,)).fetchone()
        cur_tutor = row["tutor_id"] if row else "nova"
        cur_mode = row["mode"] if row else None
        cur_language = row["language"] if row else None
        new_tutor = tutor_id if tutor_id is not None else cur_tutor
        new_mode = mode if mode is not None else cur_mode
        new_language = language if language is not None else (cur_language or "auto")
        c.execute("""INSERT INTO tutor_preferences (student_id, tutor_id, mode, language)
                     VALUES (?,?,?,?)
                     ON CONFLICT(student_id) DO UPDATE SET
                       tutor_id=excluded.tutor_id, mode=excluded.mode,
                       language=excluded.language, updated_at=datetime('now')""",
                  (student_id, new_tutor, new_mode, new_language))
    return new_tutor


def get_tutor_language(student_id):
    """Stored language preference, or None when the student has no row yet."""
    with get_cursor() as c:
        row = c.execute("SELECT language FROM tutor_preferences WHERE student_id=?",
                        (student_id,)).fetchone()
        language = row["language"] if row else None
        return (language or "").strip().lower() or None


def get_tutor_mode(student_id):
    """Stored working mode, or None when the student has no explicit mode yet."""
    with get_cursor() as c:
        row = c.execute("SELECT mode FROM tutor_preferences WHERE student_id=?",
                        (student_id,)).fetchone()
        mode = row["mode"] if row else None
        return (mode or "").strip().lower() or None


_COPILOT_CONFIG_JSON_FIELDS = (("traits_json", "traits", []),
                               ("capabilities_json", "capabilities", {}))


def get_copilot_config(student_id):
    """The student's Build-Your-Copilot configuration, or None.

    Returns the frozen creation snapshot (choice, voice_agent_id, the
    personality fields that compose the dynamic system prompt, and the enabled
    capabilities), with the JSON columns decoded to their friendly ``traits`` /
    ``capabilities`` keys (the same shape as ``copilot.snapshot_for``).
    ``None`` when no copilot has been built yet — the current fixed four-persona
    behavior stays unchanged.
    """
    with get_cursor() as c:
        row = c.execute("SELECT * FROM copilot_config WHERE student_id=?",
                        (student_id,)).fetchone()
    if not row:
        return None
    cfg = dict(row)
    for src, dst, fallback in _COPILOT_CONFIG_JSON_FIELDS:
        raw = cfg.pop(src, None)
        try:
            cfg[dst] = json.loads(raw or ("[]" if isinstance(fallback, list) else "{}"))
        except Exception:
            cfg[dst] = fallback
    return cfg


def set_copilot_config(student_id, cfg):
    """Create/replace the student's copilot configuration from a snapshot dict.

    ``cfg`` must already carry the frozen preset values (choice, voice_agent_id,
    name, title, role, specialty, origin, traits, behavior, style, capabilities)
    — this layer just persists them and never fabricates any field. Upserts the
    single per-student row; returns the stored config (decoded).
    """
    with get_cursor() as c:
        c.execute("""INSERT INTO copilot_config
                     (student_id, choice, voice_agent_id, name, title, role,
                      specialty, origin, traits_json, behavior, style,
                      capabilities_json)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(student_id) DO UPDATE SET
                       choice=excluded.choice,
                       voice_agent_id=excluded.voice_agent_id,
                       name=excluded.name,
                       title=excluded.title,
                       role=excluded.role,
                       specialty=excluded.specialty,
                       origin=excluded.origin,
                       traits_json=excluded.traits_json,
                       behavior=excluded.behavior,
                       style=excluded.style,
                       capabilities_json=excluded.capabilities_json,
                       updated_at=datetime('now')""",
                  (student_id,
                   cfg["choice"], cfg["voice_agent_id"], cfg["name"], cfg["title"],
                   cfg["role"], cfg["specialty"], cfg["origin"],
                   json.dumps(cfg["traits"]), cfg["behavior"], cfg["style"],
                   json.dumps(cfg["capabilities"])))
    return get_copilot_config(student_id)


def clear_copilot_config(student_id):
    """Remove the student's copilot configuration (back to the fixed personas)."""
    with get_cursor() as c:
        c.execute("DELETE FROM copilot_config WHERE student_id=?", (student_id,))
    return True


def get_copilot_onboarding(student_id):
    """The student's first-run copilot-onboarding record, or a synthetic
    not_started row when none exists yet.

    The row is DELIBERATELY independent of copilot_config so the "only ask once"
    rule survives DELETE copilot. ``quiz_answers`` is the decoded raw 3-answer
    set (empty for skip/manual_change); ``answered_at`` is None while the row is
    still not_started.
    """
    with get_cursor() as c:
        row = c.execute("SELECT student_id, state, source, quiz_answers_json, answered_at "
                        "FROM copilot_onboarding WHERE student_id=?", (student_id,)).fetchone()
    if not row:
        return {"student_id": student_id, "state": "not_started", "source": "manual_change",
                "quiz_answers": [], "answered_at": None}
    d = dict(row)
    raw = d.pop("quiz_answers_json", None)
    try:
        d["quiz_answers"] = json.loads(raw or "[]")
    except Exception:
        d["quiz_answers"] = []
    return d


def set_copilot_onboarding(student_id, state, source, answers=None):
    """Record how/when the first-run copilot question was resolved.

    Upserts the single per-student row. ``state``/``source`` must be one of the
    documented vocabularies (callers validate); ``answers`` is the raw 3-answer
    set persisted for audit (empty for skip/manual_change). Sets answered_at to
    now whenever the row is written.
    """
    with get_cursor() as c:
        c.execute("""INSERT INTO copilot_onboarding
                     (student_id, state, source, quiz_answers_json, answered_at)
                     VALUES (?,?,?,?, datetime('now'))
                     ON CONFLICT(student_id) DO UPDATE SET
                       state=excluded.state,
                       source=excluded.source,
                       quiz_answers_json=excluded.quiz_answers_json,
                       answered_at=excluded.answered_at""",
                  (student_id, state, source, json.dumps(answers or [])))
    return get_copilot_onboarding(student_id)


def mark_copilot_manual(student_id):
    """Source bookkeeping when the student builds a copilot via the settings
    picker (PUT copilot) rather than the first-run quiz.

    A manual build MEANS the student decided: if the onboarding row is still
    not_started it is marked completed with source=manual_change (so the
    first-run modal never appears after a manual pick), and an existing
    completed/skipped row just records that the latest decision came from the
    settings. The quiz row itself is never re-opened by this path.
    """
    with get_cursor() as c:
        row = c.execute("SELECT state FROM copilot_onboarding WHERE student_id=?",
                        (student_id,)).fetchone()
        if row is None:
            c.execute("""INSERT INTO copilot_onboarding
                         (student_id, state, source, quiz_answers_json, answered_at)
                         VALUES (?, 'completed', 'manual_change', '[]', datetime('now'))""",
                      (student_id,))
        elif row["state"] == "not_started":
            c.execute("""UPDATE copilot_onboarding
                         SET state='completed', source='manual_change',
                             answered_at=datetime('now')
                         WHERE student_id=?""", (student_id,))
        else:
            c.execute("UPDATE copilot_onboarding SET source='manual_change' WHERE student_id=?",
                      (student_id,))
    return get_copilot_onboarding(student_id)


def start_active_assessment(student_id, skill_id, external_token=None, webcam_gate=None):
    """Mark an in-progress verified assessment so the Tutor is locked out.

    ``webcam_gate`` is the server-side attestation that the pre-assessment
    camera permission gate completed successfully (metadata only: no frames or
    landmarks). It is stored as ``webcam_gate_passed`` / ``webcam_gate_checked_at``
    / ``webcam_gate_meta`` so review can see that the gate requirement was met
    before questions were generated.
    """
    token = str(external_token or "").strip() or None
    gate = _normalise_webcam_gate(webcam_gate)
    with get_cursor() as c:
        c.execute("""INSERT INTO active_assessments
                     (student_id, skill_id, external_token, integrity_events,
                      webcam_gate_passed, webcam_gate_checked_at, webcam_gate_meta)
                     VALUES (?,?,?, '[]',?,?,?)
                     ON CONFLICT(student_id) DO UPDATE SET
                       skill_id=excluded.skill_id,
                       external_token=excluded.external_token,
                       integrity_events='[]',
                       webcam_gate_passed=excluded.webcam_gate_passed,
                       webcam_gate_checked_at=excluded.webcam_gate_checked_at,
                       webcam_gate_meta=excluded.webcam_gate_meta,
                       started_at=datetime('now')""",
                  (student_id, skill_id, token,
                   gate["passed"], gate["checked_at"], gate["meta"]))


# Keys that would smuggle raw media through the webcam-gate metadata channel.
_FORBIDDEN_GATE_KEYS = {
    "frame", "frames", "image", "images", "video", "videos", "blob", "blobs",
    "base64", "embedding", "embeddings", "snapshot", "screenshot", "thumbnail",
}


def _normalise_webcam_gate(webcam_gate):
    """Coerce a client webcam-gate attestation into safe storage values.

    Only metadata survives here: ``passed`` (boolean), ``checked_at`` (ISO
    timestamp string) and a small ``meta`` dict of primitive values. Anything
    unexpected (including any raw-media payload) is dropped, never persisted,
    mirroring the integrity event validator.
    """
    passed = 0
    checked_at = None
    meta = {}
    if isinstance(webcam_gate, dict):
        passed = 1 if webcam_gate.get("passed") in (True, 1, "1", "true") else 0
        raw_at = webcam_gate.get("checked_at")
        if isinstance(raw_at, str) and len(raw_at) <= 64:
            checked_at = raw_at
        raw_meta = webcam_gate.get("meta") or {}
        if isinstance(raw_meta, dict):
            for key, value in raw_meta.items():
                if not isinstance(key, str) or len(key) > 32:
                    continue
                # Never accept media payloads through the gate attestation.
                if _FORBIDDEN_GATE_KEYS.intersection(key.lower().split()):
                    continue
                if isinstance(value, (str, int, float, bool)) and len(str(value)) <= 128:
                    meta[key] = value
    return {"passed": passed, "checked_at": checked_at,
            "meta": json.dumps(meta, sort_keys=True)}


ACTIVE_ASSESSMENT_TTL_SECONDS = 5400


def clear_stale_active_assessments(ttl_seconds=ACTIVE_ASSESSMENT_TTL_SECONDS):
    """Drop any active-assessment lock older than the TTL so a crashed client
    (tab closed, page unloaded, process killed) can never leave a student
    permanently locked out of the Tutor/interview endpoints."""
    with get_cursor() as c:
        c.execute("DELETE FROM active_assessments WHERE started_at < datetime('now', ?)",
                  (f"-{int(ttl_seconds)} seconds",))


def get_active_assessment(student_id):
    clear_stale_active_assessments()
    with get_cursor() as c:
        row = c.execute("SELECT * FROM active_assessments WHERE student_id=?",
                        (student_id,)).fetchone()
        return _row(row) if row else None


def clear_active_assessment(student_id):
    with get_cursor() as c:
        c.execute("DELETE FROM active_assessments WHERE student_id=?", (student_id,))


def list_active_assessment_events(student_id, skill_id=None, external_token=None):
    """Return camera/local integrity events collected for the active attempt.

    The token check ties browser-reported events to the same assessment instance
    that will later submit/finalize, preventing stale events from drifting into a
    different session for the same student and skill.
    """
    active = get_active_assessment(student_id)
    if not active:
        return []
    if skill_id is not None and int(active["skill_id"]) != int(skill_id):
        return []
    active_token = str(active.get("external_token") or "").strip()
    if active_token and str(external_token or "").strip() != active_token:
        return []
    return _json_loads(active.get("integrity_events")) or []


def append_active_assessment_event(student_id, skill_id, external_token, event):
    """Append one metadata-only integrity event to the active assessment.

    Deduplication uses the client incident_id when present, so retries and
    repeated detector frames do not create a pile of identical rows.
    """
    clear_stale_active_assessments()
    token = str(external_token or "").strip()
    with get_cursor() as c:
        row = c.execute("SELECT * FROM active_assessments WHERE student_id=?",
                        (student_id,)).fetchone()
        if not row:
            return None
        active = _row(row)
        if int(active["skill_id"]) != int(skill_id):
            return None
        active_token = str(active.get("external_token") or "").strip()
        if not token or active_token != token:
            return None
        events = _json_loads(active.get("integrity_events")) or []
        incident_id = str(event.get("incident_id") or "").strip()
        if incident_id:
            for stored in events:
                if (stored.get("event_type") == event.get("event_type")
                        and str(stored.get("incident_id") or "").strip() == incident_id):
                    return {"event": stored, "events": events, "appended": False}
        events.append(event)
        c.execute("UPDATE active_assessments SET integrity_events=? WHERE student_id=?",
                  (_json_dumps(events), student_id))
        return {"event": event, "events": events, "appended": True}


# ---------------------------------------------------------------- assessments

def create_assessment_attempt(student_id, skill_id, questions, answers, score, passed,
                              flags, level_before, level_after, per_question=None,
                              external_token=None):
    with get_cursor() as c:
        cur = c.execute("""INSERT INTO assessment_attempts
                           (student_id, skill_id, questions, answers, score, passed, flags, per_question, level_before, level_after, external_token)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (student_id, skill_id, questions, answers, score, passed, flags,
                         per_question, level_before, level_after, external_token))
        return get_assessment_attempt(cur.lastrowid)


def get_assessment_attempt_by_token(student_id, token):
    with get_cursor() as c:
        row = c.execute("""SELECT a.*, s.name AS skill_name
                           FROM assessment_attempts a JOIN skills s ON s.id=a.skill_id
                           WHERE a.student_id=? AND a.external_token=?""",
                        (student_id, token)).fetchone()
        return _row(row) if row else None


def get_assessment_attempt(attempt_id):
    with get_cursor() as c:
        return _row(c.execute("""SELECT a.*, s.name AS skill_name
                                 FROM assessment_attempts a JOIN skills s ON s.id=a.skill_id
                                 WHERE a.id=?""", (attempt_id,)).fetchone())


def list_assessment_attempts(student_id=None, skill_id=None):
    with get_cursor() as c:
        q = "SELECT a.*, s.name AS skill_name FROM assessment_attempts a JOIN skills s ON s.id=a.skill_id"
        clauses, vals = [], []
        if student_id:
            clauses.append("a.student_id=?")
            vals.append(student_id)
        if skill_id:
            clauses.append("a.skill_id=?")
            vals.append(skill_id)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY a.id DESC"
        return [_row(r) for r in c.execute(q, vals).fetchall()]


def delete_assessment_attempt(attempt_id):
    with get_cursor() as c:
        c.execute("DELETE FROM assessment_attempts WHERE id=?", (attempt_id,))
    return 1


# ---------------------------------------------------------------- users / auth

def create_user(email, role, display_name, password=None, auth_provider="local", google_sub=None, verified=0, country=None, university=None, location=None, education_level=None):
    """Create a user. Local accounts hash their password; Google accounts store none.

    Phase C: the legacy NOT NULL ``password`` column is only ever written as an
    empty placeholder - plaintext passwords are never persisted any more."""
    pw_col = ""  # legacy NOT NULL constraint; auth always uses password_hash
    hash_b64 = salt_b64 = None
    if password:
        from .auth import hash_password
        hash_b64, salt_b64 = hash_password(password)
    with get_cursor() as c:
        cur = c.execute(
            """INSERT INTO users (email, password, role, display_name, password_hash, password_salt, auth_provider, google_sub, verified, country, university, location, education_level)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (email, pw_col, role, display_name, hash_b64, salt_b64, auth_provider, google_sub, int(verified), country, university, location, education_level))
        return get_user(cur.lastrowid)


def get_user_by_email(email):
    with get_cursor() as c:
        return _safe_user(c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone())


def get_user(user_id):
    with get_cursor() as c:
        return _safe_user(c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())


def get_user_by_google_sub(google_sub):
    with get_cursor() as c:
        return _safe_user(c.execute("SELECT * FROM users WHERE google_sub=?", (google_sub,)).fetchone())


def get_user_by_email_or_google_sub(email, google_sub=None):
    u = get_user_by_email(email)
    if u:
        return u
    if google_sub:
        return get_user_by_google_sub(google_sub)
    return None


def public_user(user):
    """Role-safe projection of a user record — never includes hash or salt."""
    return {"id": user["id"], "email": user["email"], "role": user["role"],
            "display_name": user["display_name"], "auth_provider": user.get("auth_provider", "local"),
            "verified": bool(user.get("verified")), "country": user.get("country") or "",
            "university": user.get("university") or "", "location": user.get("location") or "",
            "education_level": user.get("education_level") or ""}


def set_user_password(user_id, password):
    from .auth import hash_password
    hash_b64, salt_b64 = hash_password(password)
    with get_cursor() as c:
        c.execute("UPDATE users SET password_hash=?, password_salt=?, auth_provider='local' WHERE id=?",
                  (hash_b64, salt_b64, user_id))


def check_credentials(email, password):
    """Verify email/password. Returns the user row or None. Supports legacy
    plaintext rows so pre-migration accounts keep signing in.

    Phase C: a successful legacy-plaintext login immediately upgrades the row
    to a stored PBKDF2 hash and clears the plaintext column, using only the
    password the caller just supplied (never a stored credential wholesale).
    Reads the raw row (including the legacy 'password' column) for the
    comparison, but only ever returns a sanitized copy without it.
    """
    with get_cursor() as c:
        raw = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not raw:
        return None
    full = dict(raw)
    user = _safe_user(full)
    if user.get("auth_provider") == "google":
        return None
    if user.get("password_hash"):
        from .auth import verify_password
        if verify_password(password, user["password_hash"], user["password_salt"]):
            return user
        return None
    # legacy plaintext (pre-C rows): verify first, then upgrade in place.
    if full.get("password") and hmac_compat(password, full["password"]):
        from .auth import hash_password
        hash_b64, salt_b64 = hash_password(password)
        with get_cursor() as c:
            c.execute(
                "UPDATE users SET password_hash=?, password_salt=?, password='' WHERE id=?",
                (hash_b64, salt_b64, user["id"]))
        return user
    return None


def hmac_compat(a, b):
    import hmac as _hmac
    return _hmac.compare_digest(bytes(a, "utf-8"), bytes(b, "utf-8"))


# ---------------------------------------------------------------- sessions

def create_session(user_id, token=None):
    """Issue a session. New tokens are stored ONLY as their SHA-256 hash in
    auth_sessions (with expiry + last-used metadata); the raw token is returned
    to the caller and never persisted."""
    if token is None:
        from .auth import new_session_token
        token = new_session_token()
    from .auth import hash_token, session_expiry_iso, utcnow_iso
    now = utcnow_iso()
    with get_cursor() as c:
        c.execute(
            """INSERT INTO auth_sessions (user_id, token_hash, created_at, expires_at, last_used_at)
               VALUES (?,?,?,?,?)""",
            (user_id, hash_token(token), now, session_expiry_iso(), now))
    return token


def _session_user(r):
    """Project a joined auth-session/user row down to a plain safe user dict."""
    return _safe_user({k: v for k, v in dict(r).items() if k not in {
        "sid", "expires_at", "revoked_at", "created_at", "last_used_at"}})


def get_session_user(token):
    if not token:
        return None
    from .auth import hash_token, utcnow_iso, heartbeat_cutoff_iso, created_plus_ttl
    now = utcnow_iso()
    with get_cursor() as c:
        # New-format session: hash-only token storage.
        r = c.execute(
            """SELECT a.id AS sid, a.expires_at AS expires_at, a.revoked_at AS revoked_at,
                      u.* FROM auth_sessions a JOIN users u ON u.id = a.user_id
               WHERE a.token_hash = ?""", (hash_token(token),)).fetchone()
        if r:
            if r["revoked_at"] or (r["expires_at"] and r["expires_at"] < now):
                return None
            c.execute(
                "UPDATE auth_sessions SET last_used_at = ? WHERE id = ? "
                "AND (last_used_at IS NULL OR last_used_at < ?)",
                (now, r["sid"], heartbeat_cutoff_iso()))
            return _session_user(r)
        # Legacy-format session: raw token in the pre-C sessions table, still
        # honoured for the compatibility window but aged out by the same TTL.
        r = c.execute(
            """SELECT s.created_at AS created_at, u.* FROM sessions s
               JOIN users u ON u.id = s.user_id WHERE s.token = ?""",
            (token,)).fetchone()
        if not r:
            return None
        if created_plus_ttl(r["created_at"]) < now:
            c.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
        return _session_user(r)


def delete_session(token):
    if not token:
        return
    from .auth import hash_token
    with get_cursor() as c:
        c.execute("DELETE FROM auth_sessions WHERE token_hash=?", (hash_token(token),))
        c.execute("DELETE FROM sessions WHERE token=?", (token,))


def revoke_user_sessions(user_id):
    """Revoke every active session for a user (password change/reset). New-format
    rows are soft-revoked; legacy rows are removed outright."""
    from .auth import utcnow_iso
    with get_cursor() as c:
        c.execute(
            "UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
            (utcnow_iso(), user_id))
        c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))


# ---------------------------------------------------------------- google registrations (role pending)

def upsert_google_registration(google_sub, email, display_name):
    with get_cursor() as c:
        c.execute("""INSERT INTO google_registrations (google_sub, email, display_name) VALUES (?,?,?)
                     ON CONFLICT(google_sub) DO UPDATE SET display_name=excluded.display_name""",
                  (google_sub, email, display_name))
        return _row(c.execute("SELECT * FROM google_registrations WHERE google_sub=?", (google_sub,)).fetchone())


def get_google_registration(google_sub):
    with get_cursor() as c:
        return _row(c.execute("SELECT * FROM google_registrations WHERE google_sub=?", (google_sub,)).fetchone())


def delete_google_registration(google_sub):
    with get_cursor() as c:
        c.execute("DELETE FROM google_registrations WHERE google_sub=?", (google_sub,))


# ---------------------------------------------------------------- password resets

def create_password_reset(user_id):
    from .auth import new_reset_token, reset_expiry_iso
    token = new_reset_token()
    with get_cursor() as c:
        c.execute("INSERT INTO password_resets (token, user_id, expires_at) VALUES (?,?,?)",
                  (token, user_id, reset_expiry_iso()))
        return _row(c.execute("SELECT * FROM password_resets WHERE token=?", (token,)).fetchone())


def get_password_reset(token):
    with get_cursor() as c:
        return _row(c.execute("SELECT * FROM password_resets WHERE token=?", (token,)).fetchone())


def consume_password_reset(token):
    """Mark a reset token used; returns affected user id, or None if unusable."""
    row = get_password_reset(token)
    if not row or row["used"]:
        return None
    from .auth import utcnow_iso
    if row["expires_at"] < utcnow_iso():
        return None
    with get_cursor() as c:
        c.execute("UPDATE password_resets SET used=1 WHERE token=?", (token,))
    return row["user_id"]


# ------------------------------------------------------------------ universities

def list_universities():
    """Countries with their universities, grouped and ordered."""
    groups = {}
    with get_cursor() as c:
        rows = c.execute("SELECT country, name FROM universities ORDER BY country, name").fetchall()
    for r in rows:
        groups.setdefault(r["country"], []).append(r["name"])
    return [{"country": ctry, "universities": names} for ctry, names in groups.items()]


def add_university(country, name):
    with get_cursor() as c:
        c.execute("INSERT OR IGNORE INTO universities (country, name) VALUES (?,?)", (country, name))


def list_locations():
    """Countries with their cities, grouped and ordered (cascading dropdown)."""
    groups = {}
    with get_cursor() as c:
        rows = c.execute("SELECT country, name FROM cities ORDER BY country, name").fetchall()
    for r in rows:
        groups.setdefault(r["country"], []).append(r["name"])
    return [{"country": ctry, "cities": names} for ctry, names in groups.items()]


def add_city(country, name):
    with get_cursor() as c:
        c.execute("INSERT OR IGNORE INTO cities (country, name) VALUES (?,?)", (country, name))


# ------------------------------------------------------------------ email verification

def create_email_verification(user_id):
    from .auth import new_reset_token, reset_expiry_iso
    token = new_reset_token()
    with get_cursor() as c:
        c.execute("INSERT INTO email_verifications (token, user_id, expires_at) VALUES (?,?,?)",
                  (token, user_id, reset_expiry_iso()))
        return _row(c.execute("SELECT * FROM email_verifications WHERE token=?", (token,)).fetchone())


def get_email_verification(token):
    with get_cursor() as c:
        return _row(c.execute("SELECT * FROM email_verifications WHERE token=?", (token,)).fetchone())


def consume_email_verification(token):
    """Mark a verification token used; returns affected user id, or None if unusable."""
    row = get_email_verification(token)
    if not row or row["used"]:
        return None
    from .auth import utcnow_iso
    if row["expires_at"] < utcnow_iso():
        return None
    with get_cursor() as c:
        c.execute("UPDATE email_verifications SET used=1 WHERE token=?", (token,))
    return row["user_id"]


def set_user_verified(user_id):
    with get_cursor() as c:
        c.execute("UPDATE users SET verified=1 WHERE id=?", (user_id,))


# ------------------------------------------------------------------ learning diagnostics

def create_diagnostic(student_id, skill_id, questions):
    """Persist a newly generated (unanswered) diagnostic. Returns the row dict."""
    with get_cursor() as c:
        cur = c.execute(
            "INSERT INTO learning_diagnostics (student_id, skill_id, questions) VALUES (?,?,?)",
            (student_id, skill_id, _json_dumps(questions)))
        return _row(c.execute("SELECT * FROM learning_diagnostics WHERE id=?", (cur.lastrowid,)).fetchone())


def get_diagnostic(diagnostic_id):
    with get_cursor() as c:
        return _row(c.execute("SELECT * FROM learning_diagnostics WHERE id=?", (diagnostic_id,)).fetchone())


def get_latest_diagnostic(student_id, skill_id):
    with get_cursor() as c:
        return _row(c.execute(
            """SELECT * FROM learning_diagnostics
               WHERE student_id=? AND skill_id=? ORDER BY id DESC LIMIT 1""",
            (student_id, skill_id)).fetchone())


def list_diagnostics(student_id, skill_id=None, completed_only=True):
    sql = "SELECT * FROM learning_diagnostics WHERE student_id=?"
    args = [student_id]
    if skill_id is not None:
        sql += " AND skill_id=?"
        args.append(skill_id)
    if completed_only:
        sql += " AND completed_at IS NOT NULL"
    sql += " ORDER BY id DESC"
    with get_cursor() as c:
        return [_row(r) for r in c.execute(sql, args).fetchall()]


def delete_unanswered_diagnostics(student_id, skill_id, exclude_id=None):
    """Remove any generated-but-not-submitted diagnostics for a (student, skill),
    so starting a fresh diagnostic does not accumulate idle rows."""
    sql = "DELETE FROM learning_diagnostics WHERE student_id=? AND skill_id=? AND completed_at IS NULL"
    args = [student_id, skill_id]
    if exclude_id is not None:
        sql += " AND id<>?"
        args.append(exclude_id)
    with get_cursor() as c:
        cur = c.execute(sql, args)
        return cur.rowcount


def complete_diagnostic(diagnostic_id, answers, score, topic_results):
    """Persist answers + computed topic-level results for a diagnostic."""
    with get_cursor() as c:
        c.execute(
            """UPDATE learning_diagnostics
               SET answers=?, score=?, topic_results=?, completed_at=datetime('now')
               WHERE id=?""",
            (_json_dumps(answers), score, _json_dumps(topic_results), diagnostic_id))
    return get_diagnostic(diagnostic_id)


def _diagnostic_dict(d):
    if d is None:
        return None
    stored = _json_loads(d.get("topic_results")) or {}
    topics = stored.get("topics") or []
    return {
        "id": d["id"],
        "student_id": d["student_id"],
        "skill_id": d["skill_id"],
        "questions": _json_loads(d.get("questions")),
        "answers": _json_loads(d.get("answers")),
        "score": d.get("score") if d.get("score") is not None else stored.get("overall_score"),
        "topic_results": topics,
        "weak_topics": stored.get("weak_topics") or [],
        "strong_topics": stored.get("strong_topics") or [],
        "created_at": d.get("created_at"),
        "completed_at": d.get("completed_at"),
    }


def public_diagnostic(d):
    return _diagnostic_dict(d)


# ------------------------------------------------------------------ personalized learning path

def create_personalized_path(student_id, skill_id, diagnostic_id, required_level,
                             items, skipped_mastered, stages):
    with get_cursor() as c:
        cur = c.execute(
            """INSERT INTO personalized_paths
               (student_id, skill_id, diagnostic_id, required_level, items, skipped_mastered, stages)
               VALUES (?,?,?,?,?,?,?)""",
            (student_id, skill_id, diagnostic_id, required_level,
             _json_dumps(items), _json_dumps(skipped_mastered), _json_dumps(stages)))
        return _row(c.execute("SELECT * FROM personalized_paths WHERE id=?", (cur.lastrowid,)).fetchone())


def get_personalized_path_for_diagnostic(student_id, skill_id, diagnostic_id):
    with get_cursor() as c:
        return _row(c.execute(
            """SELECT * FROM personalized_paths
               WHERE student_id=? AND skill_id=? AND diagnostic_id=?
               ORDER BY id DESC LIMIT 1""",
            (student_id, skill_id, diagnostic_id)).fetchone())


def get_personalized_path(student_id, skill_id):
    with get_cursor() as c:
        return _row(c.execute(
            """SELECT * FROM personalized_paths
               WHERE student_id=? AND skill_id=? ORDER BY id DESC LIMIT 1""",
            (student_id, skill_id)).fetchone())


def update_path_progress(student_id, skill_id, progress):
    with get_cursor() as c:
        c.execute("UPDATE personalized_paths SET progress=? WHERE student_id=? AND skill_id=?",
                  (_json_dumps(progress), student_id, skill_id))
    return get_personalized_path(student_id, skill_id)


def _path_dict(d):
    if d is None:
        return None
    items = _json_loads(d.get("items")) or []
    stages = _json_loads(d.get("stages")) or []
    all_rows = list(items) + list(stages)
    progress = _json_loads(d.get("progress")) or []
    for row in all_rows:
        key = row.get("id") or row.get("competency") or row.get("stage")
        row["state"] = "done" if key in progress else (row.get("state") or "not_started")
    return {
        "id": d["id"],
        "student_id": d["student_id"],
        "skill_id": d["skill_id"],
        "diagnostic_id": d["diagnostic_id"],
        "required_level": d.get("required_level"),
        "items": items,
        "stages": stages,
        "skipped_mastered": _json_loads(d.get("skipped_mastered")) or [],
        "progress": progress,
        "created_at": d.get("created_at"),
    }


def public_personalized_path(d):
    return _path_dict(d)


# ------------------------------------------------------------------ path progress (additive)

def add_to_path_progress(student_id, skill_id, item_ids):
    """Add item_ids to the path's progress list (idempotent, preserves existing).
    Used by Mini Check completion — add-only semantics."""
    path = get_personalized_path(student_id, skill_id)
    if not path:
        return None
    current = _json_loads(path.get("progress")) or []
    updated = list(dict.fromkeys(current + list(item_ids)))
    return update_path_progress(student_id, skill_id, updated)


# ------------------------------------------------------------------ learning lessons

def _lesson_dict(d):
    if d is None:
        return None
    return {
        "id": d["id"],
        "student_id": d["student_id"],
        "skill_id": d["skill_id"],
        "personalized_path_id": d["personalized_path_id"],
        "competency": d["competency"],
        "title": d["title"],
        "action": d["action"],
        "content": _json_loads(d.get("content_json")) or {},
        "state": d.get("state") or "not_started",
        "mini_check_result": _json_loads(d.get("mini_check_result_json")),
        "created_at": d.get("created_at"),
        "completed_at": d.get("completed_at"),
    }


def create_lesson(student_id, skill_id, path_id, competency, title, action, content_json):
    with get_cursor() as c:
        cur = c.execute(
            """INSERT INTO learning_lessons
               (student_id, skill_id, personalized_path_id, competency, title, action, content_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (student_id, skill_id, path_id, competency, title, action, _json_dumps(content_json)))
        return _lesson_dict(_row(c.execute(
            "SELECT * FROM learning_lessons WHERE id=?", (cur.lastrowid,)).fetchone()))


def get_lesson(student_id, path_id, competency):
    with get_cursor() as c:
        return _lesson_dict(_row(c.execute(
            """SELECT * FROM learning_lessons
               WHERE student_id=? AND personalized_path_id=? AND competency=?
               ORDER BY id DESC LIMIT 1""",
            (student_id, path_id, competency)).fetchone()))


def update_lesson_state(student_id, path_id, competency, state, result_json=None):
    with get_cursor() as c:
        completed_at = "datetime('now')" if state == "completed" else None
        if state == "completed":
            c.execute(
                """UPDATE learning_lessons SET state=?, mini_check_result_json=?, completed_at=datetime('now')
                   WHERE student_id=? AND personalized_path_id=? AND competency=?""",
                (state, _json_dumps(result_json), student_id, path_id, competency))
        else:
            c.execute(
                """UPDATE learning_lessons SET state=?, mini_check_result_json=?
                   WHERE student_id=? AND personalized_path_id=? AND competency=?""",
                (state, _json_dumps(result_json), student_id, path_id, competency))
    return get_lesson(student_id, path_id, competency)


def public_lesson(lesson):
    return _lesson_dict(lesson)


# ------------------------------------------------------------------ learning practice attempts

def _practice_attempt_dict(d):
    if d is None:
        return None
    return {
        "id": d["id"],
        "student_id": d["student_id"],
        "skill_id": d["skill_id"],
        "personalized_path_id": d["personalized_path_id"],
        "lesson_id": d["lesson_id"],
        "competency": d["competency"],
        "answer": d["answer"],
        "practice_task": _json_loads(d.get("practice_task_json")),
        "score": d["score"],
        "status": d["status"],
        "strengths": _json_loads(d.get("strengths")) or [],
        "missing_points": _json_loads(d.get("missing_points")) or [],
        "feedback": d["feedback"],
        "next_action": d["next_action"],
        "source": d["source"],
        "remediation": _remediation_with_attempt_id(d),
        "created_at": d.get("created_at"),
    }


def _remediation_with_attempt_id(d):
    remediation = _json_loads(d.get("remediation_json"))
    if isinstance(remediation, dict):
        from . import lessons
        remediation = lessons.normalize_remediation_review(remediation)
        remediation["practice_attempt_id"] = d["id"]
        return remediation
    return None


def create_practice_attempt(student_id, skill_id, path_id, lesson_id, competency,
                            answer, result, practice_task=None, remediation=None):
    with get_cursor() as c:
        cur = c.execute(
            """INSERT INTO learning_practice_attempts
               (student_id, skill_id, personalized_path_id, lesson_id, competency,
                answer, practice_task_json, score, status, strengths, missing_points,
                feedback, next_action, source, remediation_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                student_id, skill_id, path_id, lesson_id, competency, answer,
                _json_dumps(practice_task),
                result["score"], result["status"], _json_dumps(result.get("strengths") or []),
                _json_dumps(result.get("missing_points") or []), result["feedback"],
                result["next_action"], result["source"], _json_dumps(remediation),
            ),
        )
        return _practice_attempt_dict(_row(c.execute(
            "SELECT * FROM learning_practice_attempts WHERE id=?",
            (cur.lastrowid,),
        ).fetchone()))


def get_practice_attempt(student_id, lesson_id, attempt_id):
    with get_cursor() as c:
        return _practice_attempt_dict(_row(c.execute(
            """SELECT * FROM learning_practice_attempts
               WHERE student_id=? AND lesson_id=? AND id=?""",
            (student_id, lesson_id, attempt_id),
        ).fetchone()))


def list_practice_attempts(student_id, lesson_id, limit=None):
    sql = """SELECT * FROM learning_practice_attempts
             WHERE student_id=? AND lesson_id=?
             ORDER BY id DESC"""
    params = [student_id, lesson_id]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    with get_cursor() as c:
        rows = c.execute(sql, tuple(params)).fetchall()
        return [_practice_attempt_dict(_row(r)) for r in rows]


# ---------------------------------------------------------------- scenarios

def _scenario_attempt_dict(d):
    if d is None:
        return None
    return {
        "id": d["id"],
        "student_id": d["student_id"],
        "scenario_id": d["scenario_id"],
        "scenario_version": d.get("scenario_version") or 1,
        "status": d["status"],
        "state": _json_loads(d.get("state_json")) or {},
        "decisions": _json_loads(d.get("decisions_json")) or [],
        "evidence_viewed": _json_loads(d.get("evidence_viewed_json")) or [],
        "hints_used": d["hints_used"] or 0,
        "score": d["score"],
        "skill_scores": _json_loads(d.get("skill_scores_json")) or {},
        "skill_deltas": _json_loads(d.get("skill_deltas_json")) or [],
        "strengths": _json_loads(d.get("strengths_json")) or [],
        "improvements": _json_loads(d.get("improvements_json")) or [],
        "feedback": _json_loads(d.get("feedback_json")) or {},
        "started_at": d.get("started_at"),
        "completed_at": d.get("completed_at"),
    }


def create_scenario_attempt(student_id, scenario_id, state_json, scenario_version=1):
    with get_cursor() as c:
        cur = c.execute(
            """INSERT INTO scenario_attempts (student_id, scenario_id, scenario_version, state_json)
               VALUES (?, ?, ?, ?)""",
            (student_id, scenario_id, scenario_version, _json_dumps(state_json)),
        )
        return _scenario_attempt_dict(_row(c.execute(
            "SELECT * FROM scenario_attempts WHERE id=?", (cur.lastrowid,)
        ).fetchone()))


def get_scenario_attempt(student_id, attempt_id):
    with get_cursor() as c:
        return _scenario_attempt_dict(_row(c.execute(
            "SELECT * FROM scenario_attempts WHERE id=? AND student_id=?",
            (attempt_id, student_id),
        ).fetchone()))


def update_scenario_attempt(attempt_id, **fields):
    allowed = {
        "status", "state_json", "decisions_json", "evidence_viewed_json",
        "hints_used", "score", "skill_scores_json", "skill_deltas_json",
        "strengths_json", "improvements_json", "feedback_json", "completed_at",
    }
    json_cols = {
        "state_json", "decisions_json", "evidence_viewed_json",
        "skill_scores_json", "skill_deltas_json",
        "strengths_json", "improvements_json", "feedback_json",
    }
    sets = {}
    for k, v in fields.items():
        if k not in allowed:
            continue
        sets[k] = _json_dumps(v) if k in json_cols else v
    if not sets:
        return
    assignments = ", ".join(f"{col}=?" for col in sets)
    if sets.get("status") == "completed" and "completed_at" not in sets:
        assignments += ", completed_at=datetime('now')"
    with get_cursor() as c:
        c.execute(
            f"UPDATE scenario_attempts SET {assignments} WHERE id=?",
            tuple(sets.values()) + (attempt_id,),
        )


def list_scenario_attempts(student_id, scenario_id=None, limit=None):
    sql = """SELECT * FROM scenario_attempts WHERE student_id=?"""
    params = [student_id]
    if scenario_id is not None:
        sql += " AND scenario_id=?"
        params.append(scenario_id)
    sql += " ORDER BY id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    with get_cursor() as c:
        rows = c.execute(sql, tuple(params)).fetchall()
        return [_scenario_attempt_dict(_row(r)) for r in rows]


def find_in_progress_scenario(student_id, scenario_id):
    with get_cursor() as c:
        row = c.execute(
            """SELECT * FROM scenario_attempts
               WHERE student_id=? AND scenario_id=? AND status='in_progress'
               ORDER BY id DESC LIMIT 1""",
            (student_id, scenario_id),
        ).fetchone()
        return _scenario_attempt_dict(_row(row))


_LEVEL_ORDER = {"Beginner": 1, "Intermediate": 2, "Advanced": 3}


def upgrade_self_reported_level(student_id, skill_name):
    """Practice-performance confidence upgrade: raise the student's SELF-REPORTED
    (never verified) level for a skill by one tier, capped at Advanced. Returns
    the delta dict, or None when nothing changes (skill not claimed, or already
    Advanced). Verified skills are untouchable here by design."""
    name = str(skill_name or "").strip().lower()
    if not name:
        return None
    with get_cursor() as c:
        row = c.execute(
            """SELECT srs.id, srs.level, s.name AS sname
               FROM self_reported_skills srs
               JOIN skills s ON s.id = srs.skill_id
               WHERE srs.student_id=? AND lower(s.name)=?
               LIMIT 1""",
            (student_id, name),
        ).fetchone()
        if not row:
            return None
        cur = _LEVEL_ORDER.get(str(row["level"] or "").strip().title(), 0)
        if cur >= 3:
            return None
        new_level = [k for k, v in _LEVEL_ORDER.items() if v == cur + 1][0]
        c.execute("UPDATE self_reported_skills SET level=? WHERE id=?", (new_level, row["id"]))
        return {"name": row["sname"], "before": row["level"], "after": new_level}
