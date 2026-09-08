"""Data access layer — CRUD for the five record types plus supporting lookups.

Pure functions over sqlite3 Row dictionaries. Kept free of framework imports so
they can be unit tested in isolation.
"""
from .database import get_cursor

LEVEL_ORDER = {"Beginner": 1, "Intermediate": 2, "Advanced": 3}
VALID_LEVELS = set(LEVEL_ORDER)


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

def list_roles(company_id=None):
    with get_cursor() as c:
        q = """SELECT r.*, c.name AS company_name, c.location AS company_location
               FROM roles r LEFT JOIN companies c ON c.id=r.company_id"""
        if company_id is not None:
            q += " WHERE r.company_id=?"
        if company_id is None:
            # Company-created openings only: imported ESCO occupations are not
            # company openings (source='esco') and must never leak into rosters.
            q += " WHERE r.is_reference=0 AND (r.source IS NULL OR r.source != 'esco')"
        q += " ORDER BY r.title"
        rows = c.execute(q, (company_id,) if company_id is not None else ()).fetchall()
        out = []
        for r in rows:
            rd = _row(r)
            rd["required_skills"] = role_skills(c, r["id"])
            out.append(rd)
        return out


def list_catalog_roles():
    """Reference roles seeded as the talent catalog (read-only baseline)."""
    with get_cursor() as c:
        rows = c.execute("SELECT r.*, c.name AS company_name FROM roles r "
                         "LEFT JOIN companies c ON c.id=r.company_id WHERE r.is_reference=1 ORDER BY r.title").fetchall()
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
    roles' live feed on the student dashboard."""
    location = (location or "").strip()
    country = (country or "").strip()
    with get_cursor() as c:
        rows = c.execute("""SELECT r.id, r.title, r.description, r.is_reference,
                                   c.name AS company_name, c.location AS company_location
                            FROM roles r LEFT JOIN companies c ON c.id=r.company_id
                            WHERE r.is_reference=0 AND (r.source IS NULL OR r.source != 'esco')
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


def create_role(company_id, title, required_skills, description=None, is_reference=0, source="company"):
    """required_skills: list of {name, category, level}."""
    with get_cursor() as c:
        cur = c.execute("INSERT INTO roles (company_id, title, description, is_reference, source) VALUES (?,?,?,?,?)",
                        (company_id, title, description, int(is_reference), source))
        role_id = cur.lastrowid
        for rs in required_skills:
            sk = get_or_create_skill(rs["name"], rs.get("category", "General"))
            c.execute("INSERT INTO role_skills (role_id, skill_id, required_level) VALUES (?,?,?)",
                      (role_id, sk["id"], rs["level"]))
        return get_role(role_id)


def update_role(role_id, title=None, description=None, required_skills=None):
    with get_cursor() as c:
        c.execute("UPDATE roles SET title=COALESCE(?,title), description=COALESCE(?,description) WHERE id=?",
                  (title, description, role_id))
        if required_skills is not None:
            c.execute("DELETE FROM role_skills WHERE role_id=?", (role_id,))
            for rs in required_skills:
                sk = get_or_create_skill(rs["name"], rs.get("category", "General"))
                c.execute("INSERT INTO role_skills (role_id, skill_id, required_level) VALUES (?,?,?)",
                          (role_id, sk["id"], rs["level"]))
        return get_role(role_id)


def delete_role(role_id):
    with get_cursor() as c:
        c.execute("DELETE FROM roles WHERE id=?", (role_id,))
        # clear students' target roles pointing here
        c.execute("UPDATE students SET target_role_id=NULL WHERE target_role_id=?", (role_id,))
    return 1


_CATALOG_COMPANY_NAME = "SkillBridge Talent Catalog"


def _catalog_company_id(c):
    row = c.execute("SELECT id FROM companies WHERE name=?", (_CATALOG_COMPANY_NAME,)).fetchone()
    return row["id"] if row else None


def import_esco_role(uri, title, essential=(), optional=(), required_level="Intermediate", max_total=16):
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
    """
    uri = (uri or "").strip()
    if not uri:
        return None
    with get_cursor() as c:
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
        cur = c.execute(
            "INSERT INTO roles (company_id, title, description, is_reference, source, external_id) "
            "VALUES (?,?,?,0,'esco',?)",
            (company_id, title,
             "Occupation imported from the ESCO labour-market catalogue.", uri))
        role_id = cur.lastrowid
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
        return get_role(role_id)


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

def add_tutor_message(student_id, tutor_id, skill_id, role, content):
    with get_cursor() as c:
        cur = c.execute("INSERT INTO tutor_messages (student_id, tutor_id, skill_id, role, content) VALUES (?,?,?,?,?)",
                        (student_id, tutor_id, skill_id, role, content))
        return _row(c.execute("SELECT * FROM tutor_messages WHERE id=?", (cur.lastrowid,)).fetchone())


def list_tutor_messages(student_id, tutor_id=None, skill_id=None):
    """Messages for one student, optionally scoped to a conversation owner.

    ``tutor_id`` is the conversation owner (nova/axel/sage/vex). Legacy rows
    written before tutor separation have ``tutor_id`` NULL and are treated as
    belonging to whichever tutor is viewing them, so existing history stays
    readable. ``skill_id`` remains an optional extra scope.
    """
    with get_cursor() as c:
        base, params = "SELECT * FROM tutor_messages WHERE student_id=?", [student_id]
        if tutor_id:
            base += " AND (tutor_id=? OR tutor_id IS NULL)"
            params.append(tutor_id)
        if skill_id:
            base += " AND skill_id=?"
            params.append(skill_id)
        base += " ORDER BY id"
        rows = c.execute(base, params).fetchall()
        return [_row(r) for r in rows]


def clear_tutor_messages(student_id, tutor_id):
    """Start a fresh conversation for ONE tutor only.

    Removes that tutor's messages (and legacy NULL-owner rows, which pre-date
    tutor separation and belong to the single shared conversation) without
    touching any other tutor's history.
    """
    with get_cursor() as c:
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


def start_active_assessment(student_id, skill_id, external_token=None):
    """Mark an in-progress verified assessment so the Tutor is locked out."""
    token = str(external_token or "").strip() or None
    with get_cursor() as c:
        c.execute("""INSERT INTO active_assessments
                     (student_id, skill_id, external_token, integrity_events)
                     VALUES (?,?,?, '[]')
                     ON CONFLICT(student_id) DO UPDATE SET
                       skill_id=excluded.skill_id,
                       external_token=excluded.external_token,
                       integrity_events='[]',
                       started_at=datetime('now')""",
                  (student_id, skill_id, token))


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
    """Create a user. Local accounts hash their password; Google accounts store none."""
    pw_col = password or ""  # legacy NOT NULL constraint; auth always uses password_hash
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
    plaintext rows so pre-upgrade seed accounts keep signing in.

    Reads the raw row (including the legacy 'password' column) for the
    comparison, but only ever returns a sanitized copy without it.
    """
    with get_cursor() as c:
        raw = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not raw:
        return None
    full = dict(raw)
    user = _safe_user(full)
    if user.get("auth_provider") == "google" or (user.get("password_hash") is None and user.get("auth_provider") == "google"):
        return None
    if user.get("password_hash"):
        from .auth import verify_password
        if verify_password(password, user["password_hash"], user["password_salt"]):
            return user
        return None
    # legacy plaintext
    if full.get("password") and hmac_compat(password, full["password"]):
        return user
    return None


def hmac_compat(a, b):
    import hmac as _hmac
    return _hmac.compare_digest(bytes(a, "utf-8"), bytes(b, "utf-8"))


# ---------------------------------------------------------------- sessions

def create_session(user_id, token=None):
    if token is None:
        from .auth import new_session_token
        token = new_session_token()
    with get_cursor() as c:
        c.execute("INSERT INTO sessions (token, user_id) VALUES (?,?)", (token, user_id))
    return token


def get_session_user(token):
    if not token:
        return None
    with get_cursor() as c:
        r = c.execute("""SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
                         WHERE s.token=?""", (token,)).fetchone()
        return _safe_user(r) if r else None


def delete_session(token):
    if not token:
        return
    with get_cursor() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (token,))


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
