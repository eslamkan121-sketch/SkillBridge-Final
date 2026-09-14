"""SkillBridge FastAPI application.

Single app serving both the REST API and the built React frontend.

Auth model: opaque session tokens issued on login and carried as
`Authorization: Bearer <token>`. RBAC gates every endpoint â€” students only
access their own records, companies only their own roles/candidates, and the
university view only sees anonymized, aggregated data.
"""
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path


def _sb_logger():
    """skillbridge logger. A handler is attached only outside pytest so the test
    suite stays quiet; under uvicorn the request/error lines are visible."""
    logger = logging.getLogger("skillbridge")
    if sys.modules.get("pytest") is None and not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(handler)
    return logger


def _load_env():
    """Load a repo-root .env if present. Real environment variables win.

    The documented setup is 'copy .env.example to .env and add keys'; without a
    loader here those keys were never read, so every GenAI feature silently ran
    its deterministic fallback.

    Never loads under pytest: the suite must stay byte-for-byte deterministic
    and must never send real provider credentials, even when a developer has a
    populated .env on disk.
    """
    if sys.modules.get("pytest") is not None:
        return
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_env()

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import models, matching, genai, integrity, seed, auth as auth_mod, mailer, activity, jobs, career_roadmap, diagnostics, path_builder, lessons, coverage, skill_blueprint, tts, copilot, escoe, practice, recommendations, scenarios, esco_import, role_mapping, match_explain, tutor_memory
from .resources import _CHECK_CACHE, annotate_resources
from .database import init_db, get_cursor, applied_migrations

FRONTEND_DIST = os.environ.get(
    "SKILLBRIDGE_FRONTEND_DIST",
    str(Path(__file__).resolve().parents[2] / "frontend" / "dist"),
)

app = FastAPI(title="SkillBridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------ request ids
# Every request gets a short id so support can correlate a user-facing error with
# a backend log line. The id travels as a response header and (additively, next
# to the existing `detail`) inside error bodies - no existing field is replaced.


def _attach_request_context(request: Request):
    rid = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:12]
    request.state.request_id = rid
    return rid


def _error_body(request, detail):
    body = {"detail": detail}
    rid = getattr(request.state, "request_id", None)
    if rid:
        body["request_id"] = rid
    return body, rid


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = _attach_request_context(request)
    started = time.time()
    try:
        response = await call_next(request)
    except Exception:
        _sb_logger().exception("[%s] %s %s unhandled", rid, request.method, request.url.path)
        raise
    response.headers["X-Request-Id"] = rid
    response.headers["X-Response-Time-Ms"] = f"{round((time.time() - started) * 1000, 1)}"
    _sb_logger().info(
        "[%s] %s %s -> %s", rid, request.method, request.url.path, response.status_code
    )
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    body, rid = _error_body(request, exc.detail)
    response = JSONResponse(status_code=exc.status_code, content=body)
    if rid:
        response.headers["X-Request-Id"] = rid
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    body, rid = _error_body(request, "Invalid request parameters")
    body["errors"] = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
    response = JSONResponse(status_code=422, content=body)
    if rid:
        response.headers["X-Request-Id"] = rid
    return response


# ------------------------------------------------------------------ input limits
# Bounds for any endpoint this migration touches. Existing endpoints are left
# untouched; new endpoints that accept user text must use these so no unvalidated
# input ever reaches storage or logs.

_FIELD_LIMITS = {
    "display_name": 120,
    "email": 254,
    "location": 200,
    "tutor": 40,
    "message": 20000,
    "text": 20000,
    "reason": 500,
}


def _check_field_lengths(payload: dict, allowed: dict):
    """Reject payload fields whose string length exceeds an allowed bound."""
    for key, limit in allowed.items():
        value = payload.get(key)
        if isinstance(value, str) and len(value) > limit:
            raise HTTPException(
                status_code=400,
                detail=f"{key} exceeds the maximum length of {limit} characters",
            )


PASS_THRESHOLD = 70.0
MIN_COHORT_SIZE = 5  # University stats rule: never compute a stat from fewer students
VALID_SIGNUP_ROLES = ("Student", "Company", "University Admin")
_ENTITY_ROLES = {"Student", "Company"}

LEVELS = ["Beginner", "Intermediate", "Advanced"]


def _assessment_difficulty(student, role, skill_id):
    """Quiz difficulty is driven by the level this skill is required at for the
    student's Target Career (Phase 5: skill-targeted, level-adaptive difficulty)."""
    if not role:
        return "Intermediate"
    for row in matching.categorize(student, role):
        if row["skill_id"] == skill_id:
            return row["required_level"]
    return "Intermediate"


@app.on_event("startup")
def on_startup():
    from .database import DB_PATH
    if not os.path.exists(DB_PATH):
        # seed.seed() creates the schema AND the reference data (universities,
        # roles, catalog, demo accounts) â€” it must run on a truly fresh DB,
        # which means checking BEFORE init_db() ever touches the file.
        seed.seed()
    else:
        # Existing databases are only migrated so their new columns appear.
        init_db()
    seed.ensure_catalog_roles()
    # Phase D: fill canonical metadata for rows created before migration 0003
    # (idempotent; a no-op for fresh databases).
    models.backfill_role_canonical_metadata()


# ------------------------------------------------------------------ auth helpers

def _bearer_token(request: Request):
    auth = request.headers.get("Authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return token.strip()


def _current_user(request: Request):
    user = models.get_session_user(_bearer_token(request))
    if not user:
        raise HTTPException(status_code=401, detail="Session expired, please sign in again")
    return user


def _require_roles(user, *roles):
    if user["role"] not in roles:
        raise HTTPException(status_code=403, detail=f"Requires {' or '.join(roles)} role")


def _resolve_role_context(user):
    """Return (entity_type, entity) for a logged-in user."""
    if user["role"] == "Student":
        return "student", models.get_student_by_user(user["id"])
    if user["role"] == "Company":
        return "company", models.get_company_by_user(user["id"])
    return "university", None


def _entity_bundle(user):
    """Full public identity payload attached to login/me responses."""
    entity_type, entity = _resolve_role_context(user)
    payload = models.public_user(user)
    payload["entity_type"] = entity_type
    if entity_type == "student":
        payload["student"] = entity
        payload["analysis"] = matching.analyze_student(entity["id"]) if entity.get("target_role_id") else None
        payload["learning"] = models.list_learning_path(entity["id"])
    elif entity_type == "company":
        payload["company"] = entity
        payload["roles"] = models.get_roles_by_company(entity["id"])
    return payload


def _upsert_university(country, university):
    """Record a chosen university in the reference list (idempotent)."""
    if country and university:
        models.add_university(country, university)


def _own_student(user, student_id):
    """Student endpoints are scoped to the owning student. A company may read a
    student only when that student targets one of the company's own roles; the
    university view stays aggregate-only, so no individual records are reachable."""
    if user["role"] == "Student":
        student = models.get_student_by_user(user["id"])
        if not student or student["id"] != student_id:
            raise HTTPException(status_code=403, detail="Not allowed to access another student's data")
        return
    if user["role"] == "Company":
        student = models.get_student(student_id)
        if not student or not student.get("target_role"):
            raise HTTPException(status_code=403, detail="Not allowed to access this student's data")
        company = models.get_company_by_user(user["id"])
        role = student["target_role"]
        if not company or not role or role.get("company_id") != company["id"]:
            raise HTTPException(status_code=403, detail="Not allowed to access this student's data")
        return
    raise HTTPException(status_code=403, detail="Not allowed")


def _own_company_role(user, role_id):
    """Company may manage only roles owned by its own company record (never the catalog)."""
    role = models.get_role(role_id)
    if user["role"] != "Company":
        raise HTTPException(status_code=403, detail="Only companies manage roles")
    if role is None or role.get("is_reference"):
        raise HTTPException(status_code=404, detail="Role not found")
    company = models.get_company_by_user(user["id"])
    if not company or role["company_id"] != company["id"]:
        raise HTTPException(status_code=403, detail="Not allowed to manage this role")
    return role


# ------------------------------------------------------------------ auth endpoints

@app.post("/api/auth/signup")
def signup(body: dict, background_tasks: BackgroundTasks):
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    display_name = (body.get("display_name") or "").strip()
    role = body.get("role")
    country = (body.get("country") or "").strip()
    university = (body.get("university") or "").strip()
    location = (body.get("location") or "").strip()
    education_level = (body.get("education_level") or "").strip()
    if not email or not password or not display_name:
        raise HTTPException(status_code=400, detail="Email, password and display name are required")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if role not in VALID_SIGNUP_ROLES:
        raise HTTPException(status_code=400, detail="You can create a Student, Company or University Admin account here")
    if models.get_user_by_email(email):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    if not location:
        raise HTTPException(status_code=400, detail="Please tell us your location (city) so we can show you roles near you")
    if role == "University Admin" and not (country and university):
        raise HTTPException(status_code=400, detail="University Admins must choose a country and university")

    # Email verification: local accounts must verify their email before they are
    # marked verified. When SMTP is not configured (demo), accounts start verified
    # so the app stays demoable but the verification flow remains available.
    verify = mailer.email_configured()
    user = models.create_user(email, role, display_name, password=password,
                              verified=0 if verify else 1, country=country,
                              university=university, location=location,
                              education_level=education_level)
    if role == "Student":
        models.create_student(display_name, email, university, user_id=user["id"],
                              education_level=education_level)
    elif role == "Company":
        models.create_company(display_name, (body.get("industry") or "").strip(),
                              user_id=user["id"], location=location)
    elif role == "University Admin":
        _upsert_university(country, university)
    if verify:
        token = models.create_email_verification(user["id"])["token"]
        # Send asynchronously so a slow/unreachable SMTP can never block (and
        # appear to "freeze") the create-account request.
        background_tasks.add_task(mailer.send_verification_email, user, token)
    token = models.create_session(user["id"])
    return {"token": token, **models.public_user(user), "entity_type": _resolve_role_context(user)[0],
            "email_verified_delivery": verify}


@app.post("/api/auth/login")
def login(body: dict, request: Request):
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    ip = _request_ip(request)
    if auth_mod.login_failure_exceeded(email) or auth_mod.login_ip_exceeded(ip):
        raise HTTPException(status_code=429, detail="Too many login attempts. Please try again later.")
    user = models.check_credentials(email, password)
    if not user:
        auth_mod.record_login_failure(email, ip)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    auth_mod.clear_login_failures(email)
    token = models.create_session(user["id"])
    return {"token": token, **_entity_bundle(user)}


def _request_ip(request: Request):
    return (request.client.host if request.client else "unknown") or "unknown"


@app.post("/api/auth/logout")
def logout(request: Request):
    models.delete_session(_bearer_token(request))
    return {"ok": True}


@app.get("/api/auth/me")
def me(request: Request):
    user = _current_user(request)
    return _entity_bundle(user)


@app.get("/api/auth/google/config")
def google_config():
    return {"configured": auth_mod.google_configured(), "demo": auth_mod.DEMO_GOOGLE}


@app.get("/api/auth/google/login")
async def google_login():
    """Real OAuth redirect (via Authlib). Demo mode uses /api/auth/google/demo."""
    if not auth_mod.google_configured():
        return RedirectResponse(url="/login", status_code=302)
    oauth = auth_mod.get_oauth()
    return await oauth.google.authorize_redirect(
        request_uri="http://localhost:8000/api/auth/google/callback")


@app.post("/api/auth/google/demo")
def google_demo(body: dict):
    """Demo Google identity, used only when real OAuth credentials are absent."""
    email = (body.get("email") or "").strip().lower()
    display_name = (body.get("display_name") or "").strip()
    if not email or not display_name:
        raise HTTPException(status_code=400, detail="Email and display name are required")
    user = models.get_user_by_email(email)
    if user:
        token = models.create_session(user["id"])
        return {"token": token, "registered": True, **_entity_bundle(user)}
    sub = f"demo-{email}"
    models.upsert_google_registration(sub, email, display_name)
    return {"registered": False, "google_sub": sub, "email": email, "display_name": display_name}


@app.get("/api/auth/google/callback")
async def google_callback(request: Request):
    if not auth_mod.google_configured():
        raise HTTPException(status_code=400, detail="Google not configured")
    oauth = auth_mod.get_oauth()
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo") or token
    sub = userinfo.get("sub")
    email = (userinfo.get("email") or "").lower()
    name = userinfo.get("name") or (email.split("@")[0] if email else "Google User")
    existing = models.get_user_by_google_sub(sub) or models.get_user_by_email(email) if sub else None
    if existing:
        sess = models.create_session(existing["id"])
        return {"token": sess, "registered": True, **_entity_bundle(existing)}
    if sub:
        models.upsert_google_registration(sub, email, name)
        return {"registered": False, "google_sub": sub, "email": email, "display_name": name}
    raise HTTPException(status_code=400, detail="Could not identify the Google account")


@app.post("/api/auth/google/complete")
def google_complete(body: dict):
    """Second step of Google signup: pick a role; the backend creates the account."""
    sub = (body.get("google_sub") or "").strip()
    role = body.get("role")
    country = (body.get("country") or "").strip()
    university = (body.get("university") or "").strip()
    industry = (body.get("industry") or "").strip()
    location = (body.get("location") or "").strip()
    education_level = (body.get("education_level") or "").strip()
    if not sub or role not in VALID_SIGNUP_ROLES:
        raise HTTPException(status_code=400, detail="google_sub and a valid role are required")
    if not location:
        raise HTTPException(status_code=400, detail="Please tell us your location (city) so we can show you roles near you")
    if role == "University Admin" and not (country and university):
        raise HTTPException(status_code=400, detail="University Admins must choose a country and university")
    reg = models.get_google_registration(sub)
    if not reg:
        raise HTTPException(status_code=404, detail="No pending Google registration")
    user = models.create_user(reg["email"], role, reg["display_name"],
                              auth_provider="google", google_sub=sub, verified=1,
                              country=country, university=university, location=location,
                              education_level=education_level)
    if role == "Student":
        models.create_student(reg["display_name"], reg["email"], university, user_id=user["id"],
                              education_level=education_level)
    elif role == "Company":
        models.create_company(reg["display_name"], industry, user_id=user["id"], location=location)
    if country and university:
        _upsert_university(country, university)
    models.delete_google_registration(sub)
    sess = models.create_session(user["id"])
    return {"token": sess, **_entity_bundle(user)}


@app.post("/api/auth/reset/request")
def reset_request(body: dict, background_tasks: BackgroundTasks):
    email = (body.get("email") or "").strip().lower()
    # Rate limit by email so an attacker cannot spam reset emails for one account.
    if auth_mod.reset_request_exceeded(email):
        raise HTTPException(status_code=429, detail="Too many password reset requests. Please try again later.")
    auth_mod.record_reset_request(email)
    user = models.get_user_by_email(email)
    if not user or user.get("auth_provider") == "google":
        # Do not leak whether an account exists.
        return {"ok": True, "message": "If that email has an account, a reset link has been created."}
    created = models.create_password_reset(user["id"])
    if mailer.email_configured():
        # Send asynchronously so a slow/unreachable SMTP can't block the request.
        background_tasks.add_task(mailer.send_reset_email, user, created["token"])
        return {"ok": True, "message": "A password reset link has been sent to your email."}
    # No SMTP configured (demo): never return the raw token â€” it is a live
    # credential that can reset any account.  Instead, auto-confirm the reset
    # so the flow stays demoable without exposing secrets.
    return {"ok": True, "message": "Demo mode: no email is sent. Check the demo-mode banner for next steps."}


@app.post("/api/auth/reset/confirm")
def reset_confirm(body: dict):
    token = (body.get("token") or "").strip()
    new_password = body.get("new_password") or ""
    if not token or len(new_password) < 8:
        raise HTTPException(status_code=400, detail="A valid token and a password of 8+ characters are required")
    user_id = models.consume_password_reset(token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Reset token is invalid or expired")
    models.set_user_password(user_id, new_password)
    models.revoke_user_sessions(user_id)
    return {"ok": True}


# ------------------------------------------------------------------ email verification

@app.post("/api/auth/verify")
def verify_email(body: dict):
    """Verify a user's email using the token emailed at signup."""
    token = (body.get("token") or "").strip()
    user_id = models.consume_email_verification(token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Verification link is invalid or expired")
    models.set_user_verified(user_id)
    return {"ok": True}


@app.post("/api/auth/verify/status")
def verify_status(body: dict):
    """Lightweight helper: report verification state for a new signup."""
    email = (body.get("email") or "").strip().lower()
    user = models.get_user_by_email(email)
    if not user:
        return {"exists": False}
    return {"exists": True, "verified": bool(user.get("verified"))}


# ------------------------------------------------------------------ universities reference

@app.get("/api/config/demo-mode")
def api_demo_mode():
    """Report whether the app is running without a real GenAI provider (demo /
    deterministic-fallback mode) and whether email delivery (SMTP) is configured.
    Lets the frontend show a visible banner explaining why AI output is generic
    and why reset links are not emailed.

    Also exposes safe (secret-free) GenAI provider observability: which providers
    are configured, the priority order, and which provider handled the last reply.
    API keys are never included, so no credentials can leak through this config.
    """
    return {
        "genai_enabled": genai.genai_enabled(),
        "email_configured": mailer.email_configured(),
        "provider": genai.provider_status(),
        "jobs": jobs.provider_status(),
    }


@app.get("/api/system/db-status")
def api_db_status(limit: int = 200):
    """Read-only database health: engine, honest applied-migration ledger, and a
    bounded listing of the last N migrations (clamped to 1..200). No auth, no
    secrets, no data rows - only schema-level observability."""
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    migrations = applied_migrations()
    return {
        "database": {"engine": "sqlite", "ok": True},
        "migrations": {
            "applied_count": len(migrations),
            "applied": migrations[-limit:],
        },
    }


@app.get("/api/system/esco/status")
def api_esco_status(request: Request):
    """Read-only ESCO import/refresh observability for University Admins:
    configured version/language (the operator pin), the esco-market cache age,
    catalogue scores of ESCO/managed rows, and the most recent run. No network.
    """
    user = _current_user(request)
    _require_roles(user, "University Admin")
    with get_cursor() as conn:
        total_esco = conn.execute(
            "SELECT COUNT(*) AS c FROM roles WHERE source='esco'").fetchone()["c"]
        managed = conn.execute(
            "SELECT canonical_status, COUNT(*) AS c FROM roles "
            "WHERE source='esco' AND import_imprint IS NOT NULL "
            "GROUP BY canonical_status").fetchall()
    cache_age = None
    at = getattr(escoe, "_cache", {}).get("at")
    if at:
        cache_age = max(0, int(time.time() - at))
    last = esco_import.latest_import_runs(1)
    return {
        "configured": {"version": esco_import.configured_version(),
                       "language": esco_import.configured_language()},
        "esco_market_cache_age_seconds": cache_age,
        "roles": {
            "total_esco": total_esco,
            "managed_by_status": {r["canonical_status"]: r["c"] for r in managed},
        },
        "last_run": last[0] if last else None,
    }


@app.post("/api/system/esco/preview")
def api_esco_preview(request: Request, body: dict):
    """Dry-run preview of a managed ESCO import/refresh. Persists the dry-run
    run + change ledger; never mutates any role. University Admins only.
    """
    user = _current_user(request)
    _require_roles(user, "University Admin")
    uris = [u for u in (body.get("uris") or []) if str(u).strip()]
    query = body.get("query") or ""
    if isinstance(query, str):
        query = query.strip()
    language = (body.get("language") or "").strip() or None
    if not uris and not query:
        raise HTTPException(status_code=400, detail="provide uris or query")
    result = esco_import.preview(
        esco_import.build_default_transport(),
        esco_import.configured_version(), language or esco_import.configured_language(),
        uris=uris, query=query,
        max_occupations=esco_import.configured_max_occupations(),
        triggered_by_user_id=user.get("id"))
    return result


@app.post("/api/system/esco/apply")
def api_esco_apply(request: Request, body: dict):
    """Apply a previously previewed dry-run set (the only managed write path).
    Refuses when the previewed version/language no longer match the current
    configuration. University Admins only.
    """
    user = _current_user(request)
    _require_roles(user, "University Admin")
    preview_run_id = body.get("preview_run_id")
    if not isinstance(preview_run_id, int) or preview_run_id <= 0:
        raise HTTPException(status_code=400, detail="preview_run_id required")
    try:
        result = esco_import.apply_refresh(
            esco_import.build_default_transport(), preview_run_id,
            esco_import.configured_version(), esco_import.configured_language(),
            triggered_by_user_id=user.get("id"))
    except esco_import.EscoApplyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return result


@app.get("/api/universities")
def api_list_universities():
    """Countries with their universities (public reference data for the
    cascading signup dropdown â€” no auth required)."""
    return models.list_universities()


@app.get("/api/locations")
def api_list_locations():
    """Countries with their cities (public reference data for the cascading
    country â†’ city signup dropdown â€” no auth required)."""
    return models.list_locations()


# ------------------------------------------------------------------ skills catalog

@app.get("/api/skills")
def api_list_skills(request: Request):
    _current_user(request)
    return models.list_skills()


@app.post("/api/skills")
def api_create_skill(request: Request, body: dict):
    _current_user(request)
    name, category = body["name"], body.get("category", "General")
    existing = models.get_skill_by_name(name)
    if existing:
        return existing
    return models.create_skill(name, category)


# ------------------------------------------------------------------ companies

@app.get("/api/companies")
def api_list_companies(request: Request):
    _current_user(request)
    return models.list_companies()


# ------------------------------------------------------------------ roles

@app.get("/api/roles")
def api_list_roles(request: Request, search: str = ""):
    user = _current_user(request)
    search = (search or "").strip()
    roles = models.list_roles(search=search)
    catalog = models.list_catalog_roles(search=search)
    user_location = (user.get("location") or "").strip()
    user_country = (user.get("country") or "").strip()
    if user["role"] == "Company":
        company = models.get_company_by_user(user["id"])
        company_id = company["id"] if company else None
        roles = [r for r in roles if r.get("company_id") == company_id and not r.get("is_reference")]
    else:
        # Live roster first: roles posted by companies in the user's location/country,
        # then remote (no location) openings, then the rest.
        def loc_rank(r):
            loc = (r.get("company_location") or "").strip()
            if not loc:
                return 1
            if user_location and loc.lower() == user_location.lower():
                return 0
            if user_country and (user_country.lower() in loc.lower() or loc.lower() in user_country.lower()):
                return 0
            return 2
        roles.sort(key=lambda r: (loc_rank(r), r["title"].lower()))
    return {"roles": roles, "catalog": catalog,
            "location": user_location,
            "is_company": user["role"] == "Company",
            "company_id": (models.get_company_by_user(user["id"]) or {}).get("id") if user["role"] == "Company" else None,
            "role_data_version": models.roles_catalog_version()}


@app.get("/api/roles/catalog")
def api_catalog_roles(request: Request, search: str = ""):
    _current_user(request)
    search = (search or "").strip()
    return models.list_catalog_roles(search=search)


@app.get("/api/roles/esco-market")
def api_esco_market(q: str = "software", target_role: str = "", limit: int = 8, request: Request = None):
    """Real occupations that exist in the labour market (ESCO taxonomy), each
    with the essential skills it requires. Used by Skills & Roles so students
    can aim at a role that actually exists, not only company-defined ones.

    When ``target_role`` is supplied, title-variant resolution and ranking are
    driven by the student's chosen career intent. Otherwise the query text is
    searched verbatim (general free-text box).
    """
    _current_user(request)
    limit = min(max(int(limit), 1), 15)
    role_title = (target_role or "").strip()
    try:
        if role_title:
            occupations = escoe.market_occupations_for_role(role_title, limit=limit)
            text = role_title
        else:
            text = (q or "").strip()[:80]
            occupations = escoe.market_occupations(text, limit=limit)
    except Exception:
        # Never let a live-API failure surface to the browser as a dropped
        # request / "Failed to fetch": degrade to an honest unavailable state.
        occupations = []
        return {"source": "ESCO", "query": role_title or text, "occupations": [],
                "status": "unavailable",
                "message": "Live market (ESCO) lookup is unavailable right now. Try again in a moment."}
    return {"source": "ESCO", "query": role_title or text, "occupations": occupations, "status": "ok"}


@app.get("/api/roles/{role_id}")
def api_get_role(role_id: int, request: Request):
    """Catalog roles are public reference data; a company may read only its own
    role definitions, never another company's."""
    user = _current_user(request)
    role = models.get_role(role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.get("is_reference"):
        return role
    if user["role"] == "Company":
        company = models.get_company_by_user(user["id"])
        if company and role.get("company_id") == company["id"]:
            return role
    raise HTTPException(status_code=403, detail="Not allowed to view this role")


@app.get("/api/roles/{role_id}/provenance")
def api_role_provenance(role_id: int, request: Request):
    """Canonical metadata for one role: aliases, ISCO mappings, per-skill
    provenance and source fields, under the same ownership/visibility rules as
    GET /api/roles/{role_id}. A locally authored role is never shown with ESCO
    labels."""
    user = _current_user(request)
    role = models.get_role(role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if not role.get("is_reference"):
        if user["role"] != "Company":
            raise HTTPException(status_code=403, detail="Not allowed to view this role")
        company = models.get_company_by_user(user["id"])
        if not company or role.get("company_id") != company["id"]:
            raise HTTPException(status_code=403, detail="Not allowed to view this role")
    return models.role_provenance(role_id)


@app.post("/api/roles")
def api_create_role(request: Request, body: dict):
    user = _current_user(request)
    _require_roles(user, "Company")
    company = models.get_company_by_user(user["id"]) or {}
    if not company.get("id"):
        raise HTTPException(status_code=403, detail="No company linked to this account")
    return models.create_role(company["id"], body["title"],
                              body.get("required_skills", []), body.get("description"))


@app.put("/api/roles/{role_id}")
def api_update_role(role_id: int, request: Request, body: dict):
    user = _current_user(request)
    role = _own_company_role(user, role_id)
    return models.update_role(role_id, body.get("title") or role["title"],
                              body.get("description"), body.get("required_skills"))


@app.delete("/api/roles/{role_id}")
def api_delete_role(role_id: int, request: Request):
    user = _current_user(request)
    _own_company_role(user, role_id)
    models.delete_role(role_id)
    return {"deleted": True}


@app.get("/api/company/roles/{role_id}/candidates")
def api_role_candidates(role_id: int, request: Request):
    user = _current_user(request)
    _own_company_role(user, role_id)
    rows = []
    for student in models.list_students():
        full = models.get_student(student["id"])
        if full.get("target_role_id") != role_id:
            continue
        analysis = matching.analyze_student(full["id"])
        if not analysis:
            continue
        rows.append({
            "student_id": full["id"], "name": full["name"], "email": full["email"],
            "university": full["university"], "match_score": analysis["match_score"],
            "gap_count": analysis["gap_count"],
            "verified_count": len(full["verified_skills"]),
        })
    rows.sort(key=lambda r: r["match_score"], reverse=True)
    return rows


@app.get("/api/company/roles/{role_id}/canonical-matches")
def api_role_canonical_matches(role_id: int, request: Request):
    """Ranked canonical-role suggestions for a company's own role, with a real
    confidence score and a literal explanation. Suggestions are computed on
    demand and never persisted; roles below the confidence floor simply stay
    unmapped."""
    user = _current_user(request)
    _own_company_role(user, role_id)
    result = role_mapping.suggest_matches(role_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return result


@app.post("/api/company/roles/{role_id}/canonical-mapping")
def api_role_canonical_mapping(role_id: int, request: Request, body: dict):
    """Confirm (or clear) a company role's canonical mapping. ``body`` carries
    ``canonical_role_id`` (int) or ``null`` to unmap. Server-side only: the
    target must be an active reference role. Append-only audit; the local
    role's title, description and skills are never touched."""
    user = _current_user(request)
    _own_company_role(user, role_id)
    canonical_role_id = body.get("canonical_role_id") if body else None
    if canonical_role_id is not None:
        try:
            canonical_role_id = int(canonical_role_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid canonical_role_id")
    try:
        role = models.set_mapping(role_id, canonical_role_id, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "role_id": role["id"],
        "canonical_role_id": role.get("canonical_role_id"),
        "mapped": models.mapping_of(role_id),
        "mapping_updated_at": role.get("canonical_mapping_updated_at"),
    }


@app.get("/api/company/roles/{role_id}/mapping-history")
def api_role_mapping_history(role_id: int, request: Request):
    """Append-only mapping audit for a company's own role, newest first."""
    user = _current_user(request)
    _own_company_role(user, role_id)
    return models.mapping_history(role_id)



# ------------------------------------------------------------------ company analytics

@app.get("/api/company/roles/{role_id}/skills")
def api_role_skill_coverage(role_id: int, request: Request):
    """Aggregate applicant skill coverage for a company's own role.

    For every required skill of the role, report how many matched candidates are
    strong (meets/exceeds requirement), in a gap (has it below requirement), or
    missing it entirely â€” plus a coverage percentage. Only aggregate numbers and
    skill identifiers are exposed, never an individual candidate's raw skills.
    """
    user = _current_user(request)
    role = _own_company_role(user, role_id)
    matched = []
    for student in models.list_students():
        full = models.get_student(student["id"])
        if full.get("target_role_id") != role_id:
            continue
        analysis = matching.analyze_student(full["id"])
        if analysis:
            matched.append(analysis)

    coverage = []
    for rs in role.get("required_skills", []):
        strong = gap = missing = 0
        for a in matched:
            row = next((g for g in a["skill_gaps"] if g["skill_id"] == rs["skill_id"]), None)
            if row is None:
                missing += 1
            elif row["status"] == "strong":
                strong += 1
            else:
                gap += 1
        n = len(matched)
        coverage.append({
            "skill_id": rs["skill_id"],
            "skill_name": rs["name"],
            "category": rs.get("category"),
            "required_level": rs["required_level"],
            "strong": strong,
            "gap": gap,
            "missing": missing,
            "coverage_pct": round(strong / n * 100, 1) if n else 0.0,
            "n_candidates": n,
        })
    coverage.sort(key=lambda c: c["coverage_pct"])
    return {"role_id": role_id, "role_title": role["title"],
            "candidate_count": len(matched), "skills": coverage}


# ------------------------------------------------------------------ students

@app.get("/api/students")
def api_list_students(request: Request):
    """Anonymized cohort index for the university dashboard only â€” never names
    or emails, and no access for students/companies."""
    user = _current_user(request)
    _require_roles(user, "University Admin")
    return [{"id": s["id"], "university": s["university"],
             "target_role_id": s.get("target_role_id"),
             "cohort_confirmed": bool(s.get("cohort_confirmed"))}
            for s in models.list_students()]


@app.get("/api/students/{student_id}")
def api_get_student(student_id: int, request: Request):
    user = _current_user(request)
    _own_student(user, student_id)
    student = models.get_student(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


@app.get("/api/students/{student_id}/role-recommendations")
def api_role_recommendations(student_id: int, request: Request):
    """Universal target-role recommendations for a student's trusted profile.

    Mixes company roles, catalog roles and ESCO market occupations, ranked by a
    deterministic evidence formula (see recommendations module). Always returns
    200 with local results even when the live ESCO lookup fails.
    """
    user = _current_user(request)
    _own_student(user, student_id)
    student = models.get_student(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return recommendations.recommend(student)


@app.post("/api/students/{student_id}/target-role/esco")
def api_select_esco_target(student_id: int, request: Request, body: dict):
    """Select an ESCO occupation as the student's Target Role.

    Idempotently imports the occupation (source='esco' + its external_id) and
    points the student's target_role_id at it, so the existing Gap Analysis and
    learning flows can consume the occupation's essential skills. The role is a
    real ESCO occupation -- never pretended to be a company posting. This only
    sets a target; it never creates or modifies Verified Skills.
    """
    user = _current_user(request)
    _own_student(user, student_id)
    student = models.get_student(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    uri = (body.get("uri") or "").strip()
    if not uri:
        raise HTTPException(status_code=400, detail="An ESCO occupation uri is required")
    role = recommendations.select_esco_role(
        uri, body.get("title"), fallback_skills=body.get("skills") or [])
    if not role:
        raise HTTPException(status_code=502,
                            detail="Could not import this occupation (ESCO unavailable and no skill data found)")
    models.update_student(student_id, target_role_id=role["id"])
    return models.get_student(student_id)


@app.put("/api/students/{student_id}")
def api_update_student(student_id: int, request: Request, body: dict):
    user = _current_user(request)
    _own_student(user, student_id)
    fields = {k: v for k, v in body.items() if k in
              ("name", "email", "university", "target_role_id", "cv_filename", "share_public")}
    return models.update_student(student_id, **fields)


@app.delete("/api/students/{student_id}")
def api_delete_student(student_id: int, request: Request):
    user = _current_user(request)
    _own_student(user, student_id)
    models.delete_student(student_id)
    return {"deleted": True}


# ------------------------------------------------------------------ CV upload + extraction

def _pdf_to_text(content_bytes):
    """Best-effort text extraction from an uploaded PDF. Returns '' on any
    failure so callers can fall back instead of crashing."""
    try:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(content_bytes))
        parts = []
        for page in reader.pages:
            try:
                text = page.extract_text() or ""
            except Exception:
                continue
            parts.append(text)
        return "\n".join(parts).strip()
    except Exception:
        return ""


@app.post("/api/students/{student_id}/cv")
def upload_cv(student_id: int, file: UploadFile = File(...), request: Request = None):
    user = _current_user(request)
    _own_student(user, student_id)
    content_bytes = file.file.read()
    is_pdf = content_bytes.startswith(b"%PDF")
    cv_text = ""
    scanned = False
    no_text = False
    if is_pdf:
        cv_text = _pdf_to_text(content_bytes)
        if not cv_text.strip():
            scanned = True
    if not cv_text.strip():
        try:
            cv_text = content_bytes.decode("utf-8", errors="replace")
        except Exception:
            cv_text = ""
    if not cv_text.strip():
        no_text = True
    extracted = genai.extract_skills_from_cv(cv_text) if cv_text.strip() else []
    warning = None
    if no_text or scanned:
        warning = ("We couldn't read any text in the uploaded document — it looks "
                   "like a scanned image. Upload a text-based PDF or enter your "
                   "skills manually; your existing profile was kept.")
    elif not extracted:
        warning = ("No recognizable skills were found in the uploaded document. "
                   "Your existing skills were kept.")
    # A CV that yields nothing readable/recognizable must NOT wipe the student's
    # current self-reported profile (the old code clobbered skills on every
    # upload, silently erasing a good profile on a scanned/empty upload).
    if extracted:
        models.update_student(student_id, cv_filename=file.filename)
        models.replace_self_reported_skills(student_id, extracted)
    student = models.get_student(student_id)
    return {"extracted": extracted, "student": student,
            "genai_provider": "real" if genai.genai_enabled() else "deterministic-fallback",
            "warning": warning, "skills_kept": not extracted}


# ------------------------------------------------------------------ matching

@app.get("/api/students/{student_id}/analysis")
def api_student_analysis(student_id: int, request: Request):
    user = _current_user(request)
    _own_student(user, student_id)
    analysis = matching.analyze_student(student_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Student has no target role")
    return analysis


@app.get("/api/students/{student_id}/activity")
def api_student_activity(student_id: int, request: Request):
    user = _current_user(request)
    _own_student(user, student_id)
    return activity.activity_summary(student_id)


# ------------------------------------------------------------------ learning

def _maybe_refresh_learning(item):
    """Deterministic on-read resource upgrade for stored learning items.

    Legacy items whose roadmap cites channel homepages / search pages / bare
    vendor roots are quietly re-attached to the current direct, on-topic
    resources and persisted — no LLM, no network calls involved."""
    if not item:
        return None
    refreshed = genai.refresh_learning_item_resources(item, "")
    if not refreshed:
        return item
    models.upsert_learning_item(
        refreshed["student_id"], refreshed["skill_id"],
        refreshed["explanation"], refreshed["practice_exercise"], refreshed["mini_project"],
        refreshed.get("resources") or [], refreshed["roadmap"],
        modules=refreshed.get("modules") or refreshed.get("plan_modules"),
        blueprint_version=refreshed.get("blueprint_version"),
        blueprint_competencies=refreshed.get("blueprint_competencies"))
    return refreshed


@app.post("/api/students/{student_id}/learning/generate")
def api_generate_learning(student_id: int, request: Request, body: dict):
    user = _current_user(request)
    _own_student(user, student_id)
    skill_id = body["skill_id"]
    student = models.get_student(student_id)
    role = student.get("target_role")
    if not role:
        raise HTTPException(status_code=400, detail="Student has no target role")
    skill = models.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    studying = f"Studying at {student['university']}" if student.get("university") else "Independent learner"
    ctx = f"{studying}, building a career as a {role['title']}."
    item = genai.generate_learning_item(skill["name"], skill["category"], role["title"], ctx)
    return models.upsert_learning_item(student_id, skill_id, item["explanation"],
                                       item["practice_exercise"], item["mini_project"],
                                       item.get("resources") or [], item.get("roadmap") or None,
                                       modules=item.get("modules"),
                                       blueprint_version=item.get("blueprint_version"),
                                       blueprint_competencies=item.get("blueprint_competencies"))


@app.get("/api/students/{student_id}/learning")
def api_list_learning(student_id: int, request: Request):
    user = _current_user(request)
    _own_student(user, student_id)
    return [_maybe_refresh_learning(item) for item in models.list_learning_path(student_id)]


@app.get("/api/students/{student_id}/learning/{skill_id}")
def api_get_learning(student_id: int, skill_id: int, request: Request):
    user = _current_user(request)
    _own_student(user, student_id)
    item = models.get_learning_item(student_id, skill_id)
    if not item:
        raise HTTPException(status_code=404, detail="Learning item not found")
    return _maybe_refresh_learning(item)


@app.post("/api/students/{student_id}/learning/{skill_id}/progress")
def api_save_learning_progress(student_id: int, skill_id: int, request: Request, body: dict):
    """Persist which roadmap steps a student has completed for one skill."""
    user = _current_user(request)
    _own_student(user, student_id)
    steps = []
    for s in body.get("steps") or []:
        try:
            num = int(s)
        except (TypeError, ValueError):
            continue
        if num > 0:
            steps.append(num)
    return models.update_learning_progress(student_id, skill_id, steps)


@app.post("/api/students/{student_id}/learning/{skill_id}/check-links")
def api_recheck_learning_links(student_id: int, skill_id: int, request: Request):
    """Re-validate all resource links for a learning item and return annotated results.
    
    Forces a fresh check (bypasses cache) and returns resources with availability status.
    Useful when a student suspects links have rotted or wants to refresh after fixes.
    """
    user = _current_user(request)
    _own_student(user, student_id)
    item = models.get_learning_item(student_id, skill_id)
    if not item:
        raise HTTPException(status_code=404, detail="Learning item not found")
    
    resources = item.get("resources") or []
    if not resources:
        return {"resources": [], "message": "No resources to check"}
    
    # Force fresh check by clearing cache for these URLs
    for r in resources:
        _CHECK_CACHE.pop(r["url"], None)
    
    annotated = annotate_resources(resources)
    # Return both annotated list and summary
    available = sum(1 for r in annotated if r.get("available") is True)
    dead = sum(1 for r in annotated if r.get("available") is False)
    unknown = sum(1 for r in annotated if r.get("available") is None)
    
    return {
        "resources": annotated,
        "summary": {"available": available, "dead": dead, "unknown": unknown, "total": len(annotated)}
    }


@app.get("/api/students/{student_id}/career-roadmap")
def api_get_career_roadmap(student_id: int, request: Request):
    """Full start-to-finish career roadmap for the student's target role.
    Stored per (student, role); regenerated if the role changed."""
    user = _current_user(request)
    _own_student(user, student_id)
    student = models.get_student(student_id)
    role = student.get("target_role") if student else None
    if not role:
        return {"role_title": None, "phases": [], "phase_count": 0,
                "summary": "Choose a target role on the Skills & Roles page first."}
    saved = models.get_career_roadmap(student_id, role["id"])
    if saved and int(saved["roadmap"].get("resources_version") or 0) >= 4:
        roadmap = career_roadmap.normalize_roadmap(saved["roadmap"])
        return roadmap
    roadmap = career_roadmap.normalize_roadmap(career_roadmap.build_career_roadmap(student, role))
    models.upsert_career_roadmap(student_id, role["id"], roadmap)
    return roadmap


# ------------------------------------------------------------------ AI tutor

def _conversation_id_from(body: dict | None):
    if not body or body.get("conversation_id") in (None, ""):
        return None
    try:
        conversation_id = int(body.get("conversation_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="conversation_id must be an integer")
    if conversation_id <= 0:
        raise HTTPException(status_code=400, detail="conversation_id must be positive")
    return conversation_id


def _validate_tutor_id(raw, *, field="tutor"):
    if raw is None:
        return None
    tutor_id = str(raw).strip().lower()
    if tutor_id not in copilot.ALLOWED_TUTOR_IDS:
        raise HTTPException(status_code=400,
                            detail=f"Unknown {field} (allowed: nova, axel, sage, vex)")
    return tutor_id


@app.get("/api/students/{student_id}/tutor")
def api_tutor_history(student_id: int, request: Request, skill_id: int = None,
                      tutor_id: str = None, conversation_id: int = None):
    """Conversation history for a student.

    Phase 4A callers should pass ``conversation_id``. The older tutor-scoped
    path remains available for compatibility.
    """
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    tutor_id = _validate_tutor_id(tutor_id, field="tutor") if tutor_id is not None else None
    if conversation_id is not None:
        conversation = models.get_tutor_conversation(student_id, conversation_id)
        if not conversation or (tutor_id and conversation["tutor_id"] != tutor_id):
            raise HTTPException(status_code=404, detail="Conversation not found")
        tutor_id = conversation["tutor_id"]
    return models.list_tutor_messages(
        student_id,
        tutor_id=tutor_id,
        skill_id=skill_id,
        conversation_id=conversation_id,
    )


@app.get("/api/students/{student_id}/tutor/conversations")
def api_tutor_conversations(student_id: int, request: Request, include_empty: bool = False):
    """Conversation history list for the chat sidebar/history drawer."""
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    return {"conversations": models.list_tutor_conversations(student_id, include_empty=include_empty)}


@app.post("/api/students/{student_id}/tutor/conversations")
def api_create_tutor_conversation(student_id: int, request: Request, body: dict = None):
    """Create an empty conversation without clearing any existing history."""
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    tutor_id = _validate_tutor_id((body or {}).get("tutor_id"), field="tutor")
    copilot_config = models.get_copilot_config(student_id)
    tutor_id = tutor_id or (
        copilot_config["voice_agent_id"] if copilot_config
        else models.get_tutor_preference(student_id) or "nova"
    )
    conversation = models.create_tutor_conversation(student_id, tutor_id)
    return {"conversation": conversation}


@app.delete("/api/students/{student_id}/tutor")
def api_tutor_new_chat(student_id: int, request: Request, body: dict = None):
    """Clear messages from the selected conversation only.

    Older clients may omit ``conversation_id`` and still clear the selected
    tutor's legacy thread. Tutor preference, mode, language and trusted
    SkillBridge state are untouched.
    """
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    tutor_id = _validate_tutor_id((body or {}).get("tutor_id"), field="tutor")
    conversation_id = _conversation_id_from(body)
    if conversation_id is not None:
        conversation = models.get_tutor_conversation(student_id, conversation_id)
        if not conversation or (tutor_id and conversation["tutor_id"] != tutor_id):
            raise HTTPException(status_code=404, detail="Conversation not found")
        tutor_id = conversation["tutor_id"]
    tutor_id = tutor_id or models.get_tutor_preference(student_id) or "nova"
    cleared = models.clear_tutor_messages(student_id, tutor_id, conversation_id=conversation_id)
    if not cleared:
        raise HTTPException(status_code=404, detail="Conversation not found")
    tutor_memory.clear_memory(student_id, tutor_id, conversation_id=conversation_id)
    return {"cleared": True, "tutor_id": tutor_id, "conversation_id": conversation_id}


@app.post("/api/students/{student_id}/tutor")
def api_tutor_chat(student_id: int, request: Request, body: dict):
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    if models.get_active_assessment(student_id):
        raise HTTPException(status_code=423, detail=(
            "The AI Tutor is locked during an active Verified Final Assessment to "
            "protect its integrity. Submit the assessment to resume."))
    student = models.get_student(student_id)
    question = body.get("message", "")
    if not isinstance(question, str) or not question.strip():
        raise HTTPException(status_code=400, detail="Message must not be empty")
    skill_id = body.get("skill_id")
    skill = models.get_skill(skill_id) if skill_id else None
    if not skill:
        skill_id = None
    page = str(body.get("page") or "dashboard").strip().lower()
    competency = body.get("competency")
    job_title = body.get("job_title")
    job_url = body.get("job_url")
    ctx = copilot.build_context(
        student, page=page, skill_id=skill_id, competency=competency,
        job_title=job_title, job_url=job_url,
        country=user.get("country") or "", location=user.get("location") or "",
    )
    skill_name = skill["name"] if skill else None
    role = student.get("target_role") if student else None
    body_tutor = _validate_tutor_id(body.get("tutor_id"), field="tutor persona")
    conversation_id = _conversation_id_from(body)
    conversation = None
    if conversation_id is not None:
        conversation = models.get_tutor_conversation(student_id, conversation_id)
        if not conversation or (body_tutor and conversation["tutor_id"] != body_tutor):
            raise HTTPException(status_code=404, detail="Conversation not found")
        body_tutor = conversation["tutor_id"]
    # A built copilot (Build-Your-Copilot) pins the voice agent that speaks it and
    # carries the per-user personality/capability config. The personality composes
    # the system prompt; the voice stays a shared agent reference.
    copilot_config = models.get_copilot_config(student_id)
    personality = copilot.personality_for_config(copilot_config)
    tutor_id = body_tutor or models.get_tutor_preference(student_id) or "nova"
    if copilot_config and conversation_id is None:
        tutor_id = copilot_config["voice_agent_id"]
    elif copilot_config and copilot_config["voice_agent_id"] != tutor_id:
        personality = None
    conversation = conversation or models.ensure_tutor_conversation(
        student_id,
        tutor_id,
        conversation_id=conversation_id,
        title_seed=question,
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation_id = conversation["id"]
    raw_mode = body.get("mode")
    if raw_mode is not None:
        mode = copilot.validate_mode(raw_mode)
        if mode is None:
            raise HTTPException(status_code=400,
                                detail="Unknown tutor mode (allowed: chat, practice, discuss, interview)")
    else:
        mode = models.get_tutor_mode(student_id) or copilot.default_mode_for(tutor_id)
        # 'interview' is a request-driven session mode, never a standing
        # preference: a stored 'interview' must not hijack a fresh chat into
        # interview framing. Only an explicit body mode can enter interview.
        if mode == "interview":
            mode = copilot.default_mode_for(tutor_id)
    # Language: the backend makes the final call. An optional validated body
    # value pins the reply (used by the interview session to stay stable); the
    # stored preference is used otherwise, and 'auto' decides per message.
    body_lang = body.get("language")
    if body_lang is not None:
        body_lang = copilot.validate_language(body_lang)
        if body_lang is None:
            raise HTTPException(status_code=400,
                                detail="Unknown tutor language (allowed: auto, en, ar)")
    language = copilot.resolve_language(
        body_lang or models.get_tutor_language(student_id) or "auto",
        question,
    )
    ctx_text = f"{ctx['label']} context:\n{ctx['context']}\nLanguage: {copilot.language_label(language)}"
    # Bounded memory for THIS mentor conversation, built from the pre-turn
    # history so the inbound message is never double-shown.
    pre_turn = models.list_tutor_messages(
        student_id,
        tutor_id=tutor_id,
        conversation_id=conversation_id,
    )
    memory_block = tutor_memory.memory_block_for(
        student_id,
        tutor_id,
        messages=pre_turn,
        conversation_id=conversation_id,
    )
    models.add_tutor_message(student_id, tutor_id, skill_id, "user", question,
                             conversation_id=conversation_id)
    if mode == "interview":
        reply = genai.interview_reply(
            question,
            ctx_text,
            skill_name,
            role["title"] if role else None,
            turn=int(body.get("turn") or 1),
            tutor_id=tutor_id,
            language=language,
        )
    else:
        reply = genai.tutor_reply(
            question,
            ctx_text,
            skill_name,
            role["title"] if role else None,
            tutor_id=tutor_id,
            mode=mode,
            language=language,
            personality=personality,
            conversation_memory=memory_block,
        )
    msg = models.add_tutor_message(student_id, tutor_id, skill_id, "assistant", reply,
                                   conversation_id=conversation_id)
    tutor_memory.after_turn(student_id, tutor_id, conversation_id=conversation_id)
    return {
        **msg,
        "reply": reply,
        "tutor_id": tutor_id,
        "mode": mode,
        "language": language,
        "conversation_id": conversation_id,
        "conversation": models.get_tutor_conversation(student_id, conversation_id),
    }


@app.get("/api/students/{student_id}/tutor/preference")
def api_get_tutor_preference(student_id: int, request: Request):
    """Which global tutor persona, working mode and reply language the student prefers."""
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    copilot_config = models.get_copilot_config(student_id)
    tutor_id = (copilot_config["voice_agent_id"] if copilot_config
                else models.get_tutor_preference(student_id) or "nova")
    mode = models.get_tutor_mode(student_id) or copilot.default_mode_for(tutor_id)
    language = models.get_tutor_language(student_id) or copilot.TUTOR_DEFAULT_LANGUAGE
    payload = {"tutor_id": tutor_id, "mode": mode, "language": language}
    if copilot_config:
        payload["copilot"] = {
            "configured": True,
            "choice": copilot_config["choice"],
            "name": copilot_config["name"],
            "voice_agent_id": copilot_config["voice_agent_id"],
        }
    return payload


@app.put("/api/students/{student_id}/tutor/preference")
def api_set_tutor_preference(student_id: int, request: Request, body: dict):
    """Persist the student's chosen tutor persona, working mode and/or language.

    Accepts ``tutor_id``, ``mode``, ``language`` or any combination. Each field
    is independently optional, so updating one never resets the others.
    Arbitrary values are rejected, and a request that sets nothing valid is a
    400.
    """
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    has_tutor = "tutor_id" in body
    has_mode = "mode" in body
    has_language = "language" in body
    if not has_tutor and not has_mode and not has_language:
        raise HTTPException(status_code=400,
                            detail="Provide tutor_id, mode and/or language")
    tutor = None
    if has_tutor:
        raw = body.get("tutor_id")
        tutor = str(raw).strip().lower() if isinstance(raw, str) and raw.strip() else None
        if tutor not in copilot.ALLOWED_TUTOR_IDS:
            raise HTTPException(status_code=400,
                                detail="Unknown tutor persona (allowed: nova, axel, sage, vex)")
    mode = None
    if has_mode:
        mode = copilot.validate_mode(body.get("mode"))
        if mode is None:
            raise HTTPException(status_code=400,
                                detail="Unknown tutor mode (allowed: chat, practice, discuss, interview)")
    language = None
    if has_language:
        language = copilot.validate_language(body.get("language"))
        if language is None:
            raise HTTPException(status_code=400,
                                detail="Unknown tutor language (allowed: auto, en, ar)")
    if tutor is None and mode is None and language is None:
        raise HTTPException(status_code=400,
                            detail="tutor_id, mode and/or language must be valid")
    models.set_tutor_preference(student_id, tutor, mode, language)
    current_tutor = models.get_tutor_preference(student_id) or "nova"
    current_mode = models.get_tutor_mode(student_id) or copilot.default_mode_for(current_tutor)
    current_language = models.get_tutor_language(student_id) or copilot.TUTOR_DEFAULT_LANGUAGE
    return {"tutor_id": current_tutor, "mode": current_mode, "language": current_language}


@app.get("/api/students/{student_id}/copilot")
def api_get_copilot(student_id: int, request: Request):
    """The student's Build-Your-Copilot configuration, or None + the options.

    ``options`` are the EXACT four current mentors (never more). ``copilot`` is
    the frozen per-user snapshot when one has been built, else None.
    """
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    config = models.get_copilot_config(student_id)
    return {"configured": config is not None,
            "copilot": config,
            "options": copilot.copilot_options()}


@app.put("/api/students/{student_id}/copilot")
def api_set_copilot(student_id: int, request: Request, body: dict):
    """Build (or rebuild) the student's copilot from exactly one of the 4 mentors.

    Snapshotting the chosen preset per-student (personality/capability config
    + the one shared voice agent it speaks through). The voice agent also
    becomes the active tutor so the SPA chat and TTS follow the copilot's voice.
    """
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    choice = copilot.validate_choice(body.get("choice"))
    if choice is None:
        raise HTTPException(status_code=400,
                            detail="Unknown copilot (allowed: nova, axel, sage, vex)")
    snapshot = copilot.snapshot_for(choice)
    config = models.set_copilot_config(student_id, snapshot)
    models.set_tutor_preference(student_id, snapshot["voice_agent_id"])
    models.mark_copilot_manual(student_id)
    return {"configured": True,
            "copilot": config,
            "options": copilot.copilot_options()}


@app.delete("/api/students/{student_id}/copilot")
def api_clear_copilot(student_id: int, request: Request):
    """Remove the student's copilot and return to the fixed persona picker."""
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    models.clear_copilot_config(student_id)
    return {"configured": False,
            "copilot": None,
            "options": copilot.copilot_options()}


@app.get("/api/students/{student_id}/copilot/onboarding-state")
def api_copilot_onboarding_state(student_id: int, request: Request):
    """Where the student stands on the first-run copilot quiz (read-only).

    ``state`` is not_started/completed/skipped, ``source`` records how the last
    outcome was reached (quiz/skip/manual_change), and ``configured`` tells the
    SPA whether a copilot is built, so the modal can show "already built → open
    the picker instead" on a retake. A row that has never been written is
    honestly reported as not_started. Lives on its own table so DELETE copilot
    never resets the only-ask-once flag.
    """
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    onboarding = models.get_copilot_onboarding(student_id)
    config = models.get_copilot_config(student_id)
    return {
        "state": onboarding["state"],
        "source": onboarding["source"],
        "answered_at": onboarding["answered_at"],
        "configured": config is not None,
        "copilot": config,
        "options": copilot.copilot_options(),
    }


@app.post("/api/students/{student_id}/copilot/onboarding")
def api_copilot_onboarding(student_id: int, request: Request, body: dict):
    """Resolve the first-run copilot quiz (complete or skip).

    Exactly one resolution must be provided: ``skipped=true`` (builds the
    default nova mentor, state=skipped/source=skip) OR ``answers`` — a
    list of exactly four valid mentor keys. The winner is ALWAYS the
    server's recompute from ``answers`` (pure tally; ties break on Question 4,
    then Question 1, then the default nova); an
    optional ``choice`` field is validated but recomputed over, so a
    mismatched client-submitted mentor can never win (spec: server is the
    source of truth; the result screen's "choose this instead" is encoded by
    the client substituting the desired key into the answer set). Completing
    snapshots the winning mentor, pins the active tutor's voice agent, and
    records state=completed/source=quiz with the raw answers persisted for
    audit.
    """
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")
    skipped = body.get("skipped")
    answers = body.get("answers")
    choice = body.get("choice")

    if skipped is True and answers not in (None, []):
        raise HTTPException(
            status_code=400,
            detail="skipped and answers are mutually exclusive (choose one resolution)")

    if skipped is True:
        winner = copilot.DEFAULT_ARCHETYPE
        state, source = "skipped", "skip"
        stored_answers = []
    else:
        validated = copilot.validate_onboarding_answers(answers)
        if validated is None:
            raise HTTPException(
                status_code=400,
                detail=(f"answers must be a list of exactly {copilot.ONBOARDING_QUESTION_COUNT} "
                        "valid mentors (nova, axel, sage, vex)"))
        if choice not in (None, ""):
            if copilot.validate_choice(choice) is None:
                raise HTTPException(
                    status_code=400,
                    detail="Unknown copilot (allowed: nova, axel, sage, vex)")
        winner = copilot.score_archetype(validated)
        state, source = "completed", "quiz"
        stored_answers = validated

    snapshot = copilot.snapshot_for(winner)
    config = models.set_copilot_config(student_id, snapshot)
    models.set_tutor_preference(student_id, snapshot["voice_agent_id"])
    onboarding = models.set_copilot_onboarding(student_id, state, source, stored_answers)
    return {
        "state": onboarding["state"],
        "source": onboarding["source"],
        "assigned": winner,
        "answered_at": onboarding["answered_at"],
        "copilot": config,
        "options": copilot.copilot_options(),
    }


@app.post("/api/students/{student_id}/assessments/session")
def api_start_assessment_session(student_id: int, request: Request, body: dict):
    """Mark a verified final assessment as in progress so the Tutor is locked.

    The pre-assessment webcam permission gate is enforced HERE, server-side:
    the Final Assessment cannot start unless the client forwards ``webcam_gate
    = {passed: true, checked_at, meta}`` produced by the local camera pre-check.
    This is a metadata attestation (no frames, no landmarks); it guarantees a
    bypassing client cannot skip the gate silently, and review can see the
    attestation persisted with the active session.
    """
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    skill_id = body.get("skill_id")
    if not skill_id or not models.get_skill(skill_id):
        raise HTTPException(status_code=404, detail="Skill not found")
    webcam_gate = body.get("webcam_gate")
    if not isinstance(webcam_gate, dict) or not webcam_gate.get("passed") in (True, 1, "1", "true"):
        raise HTTPException(
            status_code=400,
            detail=("The camera integrity gate must be passed before the Final "
                    "Assessment session can start (webcam_gate.passed=true)."))
    external_token = str(body.get("external_token") or "").strip() or None
    if external_token and models.get_assessment_attempt_by_token(student_id, external_token):
        raise HTTPException(status_code=409, detail="Assessment attempt is already finalized")
    models.start_active_assessment(student_id, skill_id, external_token=external_token,
                                   webcam_gate=webcam_gate)
    return {"active": True, "skill_id": skill_id, "webcam_gate": {"required": True, "passed": True}}


@app.delete("/api/students/{student_id}/assessments/session")
def api_end_assessment_session(student_id: int, request: Request):
    """Resume the Tutor after a verified assessment ends (submit or abandon)."""
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    models.clear_active_assessment(student_id)
    return {"active": False}


@app.post("/api/students/{student_id}/assessments/integrity-events")
def api_create_assessment_integrity_event(student_id: int, request: Request, body: dict):
    """Accept metadata-only local integrity events for the active assessment.

    Browser frames and landmarks stay local; this endpoint persists only
    validated event metadata and ties it to the active assessment token.
    """
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    skill_id = body.get("skill_id")
    if not skill_id or not models.get_skill(skill_id):
        raise HTTPException(status_code=404, detail="Skill not found")
    external_token = str(body.get("external_token") or "").strip()
    if external_token and models.get_assessment_attempt_by_token(student_id, external_token):
        raise HTTPException(status_code=409, detail="Assessment attempt is already finalized")
    active = models.get_active_assessment(student_id)
    if not active:
        raise HTTPException(status_code=409, detail="No active assessment session")
    if int(active["skill_id"]) != int(skill_id):
        raise HTTPException(status_code=409, detail="Camera event does not match the active assessment skill")
    if not external_token or str(active.get("external_token") or "").strip() != external_token:
        raise HTTPException(status_code=403, detail="Camera event does not match the active assessment session")
    try:
        event = integrity.validate_assessment_integrity_event(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    saved = models.append_active_assessment_event(student_id, skill_id, external_token, event)
    if not saved:
        raise HTTPException(status_code=409, detail="Camera event could not be attached to this assessment")
    return {"accepted": bool(saved.get("appended")), "event": saved["event"],
            "events_count": len(saved.get("events") or [])}


# ------------------------------------------------------------------ mock interview

@app.post("/api/students/{student_id}/interview")
def api_interview(student_id: int, request: Request, body: dict):
    user = _current_user(request)
    if user["role"] != "Student":
        raise HTTPException(status_code=403, detail="Only students can start a mock interview")
    _own_student(user, student_id)
    if models.get_active_assessment(student_id):
        raise HTTPException(status_code=423, detail=(
            "The AI Tutor is locked during an active Verified Final Assessment to "
            "protect its integrity. Submit the assessment to resume."))

    last_answer = (body.get("message") or "").strip()
    if len(last_answer) > 4000:
        raise HTTPException(status_code=400, detail="Interview answer is too long")
    try:
        turn = int(body.get("turn") or 1)
    except (TypeError, ValueError):
        turn = 1
    turn = min(max(turn, 1), 50)

    skill_id = body.get("skill_id")
    skill_row = None
    if skill_id:
        skill_row = models.get_skill(skill_id)
        if not skill_row:
            raise HTTPException(status_code=404, detail="Skill not found")

    student = models.get_student(student_id)
    role = student.get("target_role")
    studying = f"Studying at {student['university']}" if student.get("university") else "Independent learner"
    ctx = f"{studying}; current profile: " \
          + ", ".join(f"{s['name']} ({s['level']})" for s in student.get("self_reported_skills") or []) \
          + "; target role: " + (role["title"] if role else "none")
    # The interview language is pinned per session: a validated body value wins
    # (the frontend resolves it once at start), otherwise the stored preference,
    # with 'auto' falling back to English so the interview never flips language
    # between turns.
    body_lang = body.get("language")
    if body_lang is not None:
        body_lang = copilot.validate_language(body_lang)
        if body_lang is None:
            raise HTTPException(status_code=400,
                                detail="Unknown tutor language (allowed: auto, en, ar)")
    language = copilot.resolve_language(
        body_lang or models.get_tutor_language(student_id) or "auto",
        last_answer,
    )
    ctx = f"{ctx}\nLanguage: {copilot.language_label(language)}"
    reply = genai.interview_reply(
        last_answer,
        ctx,
        skill_row["name"] if skill_row else None,
        role["title"] if role else None,
        turn,
        tutor_id=body.get("tutor"),
        language=language,
    )
    return {"reply": reply, "turn": turn + 1, "language": language}


@app.get("/api/students/{student_id}/interview/voice")
def api_interview_voice(student_id: int, request: Request):
    """Which ElevenLabs voices are configured, without exposing secret IDs."""
    user = _current_user(request)
    _own_student(user, student_id)
    return tts.config_status()


@app.post("/api/students/{student_id}/interview/tts")
def api_interview_tts(student_id: int, request: Request, body: dict):
    """Synthesize an interviewer line with the selected tutor's ElevenLabs voice."""
    user = _current_user(request)
    _own_student(user, student_id)
    if models.get_active_assessment(student_id):
        raise HTTPException(status_code=423, detail=(
            "The AI Tutor is locked during an active Verified Final Assessment to "
            "protect its integrity. Submit the assessment to resume."))
    tutor = body.get("tutor")
    text = body.get("text")
    try:
        audio = tts.synthesize(tutor, text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return StreamingResponse(iter([audio]), media_type="audio/mpeg",
                             headers={"Cache-Control": "max-age=3600"})


@app.post("/api/students/{student_id}/tutor/tts")
def api_tutor_tts(student_id: int, request: Request, body: dict):
    """Speak any tutor reply aloud using the SAME ElevenLabs TTS pipeline.

    This is the chat voice path â€” one shared TTS implementation, one tutor voice
    per persona. Subject to the same Verified Final Assessment integrity lock.
    """
    user = _current_user(request)
    _own_student(user, student_id)
    if models.get_active_assessment(student_id):
        raise HTTPException(status_code=423, detail=(
            "The AI Tutor is locked during an active Verified Final Assessment to "
            "protect its integrity. Submit the assessment to resume."))
    tutor = body.get("tutor")
    text = body.get("text")
    try:
        audio = tts.synthesize(tutor, text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return StreamingResponse(iter([audio]), media_type="audio/mpeg",
                             headers={"Cache-Control": "max-age=3600"})


# ------------------------------------------------------------------ assessments

@app.post("/api/students/{student_id}/assessments/generate")
def api_generate_assessment(student_id: int, request: Request, body: dict):
    user = _current_user(request)
    _own_student(user, student_id)
    skill_id = body["skill_id"]
    num_questions = min(max(int(body.get("num_questions") or 10), 3), 20)
    practice = bool(body.get("practice"))
    student = models.get_student(student_id)
    role = student.get("target_role")
    skill = models.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    if practice:
        prior = next(iter([a for a in models.list_assessment_attempts(student_id, skill_id)
                           if a.get("per_question")]), None)
        if prior:
            questions = json.loads(prior["questions"]) if isinstance(prior.get("questions"), str) else prior["questions"]
            previous_results = json.loads(prior["per_question"]) if isinstance(prior.get("per_question"), str) else (prior.get("per_question") or [])
            return {"skill": skill, "questions": questions, "practice": True,
                    "previous_score": prior["score"], "previous_passed": bool(prior["passed"]),
                    "previous_results": previous_results}

    questions, coverage_info = _generate_assessment_questions(skill, student, role, num_questions)
    return {"skill": skill, "questions": questions, "practice": bool(practice),
            "competency_coverage": coverage_info,
            "previous_results": None, "previous_score": None, "previous_passed": None}


def _generate_assessment_questions(skill, student, role, num_questions):
    """Generate a competency-tagged assessment for a skill.

    When the skill has a blueprint, generation uses a CLOSED set of competency slugs
    (derived from the skill's required proficiency in the student's target career),
    every question is competency-tagged, and coverage (each required competency
    represented) is guaranteed by `coverage` helpers. Skills without a blueprint fall
    back to the legacy generic quiz (unchanged behaviour).
    """
    difficulty = _assessment_difficulty(student, role, skill["id"])
    if not skill_blueprint.has_blueprint(skill["name"]):
        questions = genai.generate_quiz(
            skill["name"], role["title"] if role else "", num_questions=num_questions,
            difficulty=difficulty)
        return questions, None
    required_level = _path_required_level(student, role, skill["id"])
    req = coverage.required_slugs(skill["name"], required_level)
    labels = [skill_blueprint.competency_label(s) for s in req]
    questions = genai.generate_final_assessment(
        skill["name"], (role["title"] if role else ""),
        competency_slugs=req, competency_labels=labels, num_questions=num_questions)
    covered, missing = coverage.coverage_for_questions(questions, req)
    return questions, {
        "required_level": required_level,
        "required": req,
        "labels": labels,
        "covered": covered,
        "missing": missing,
        "valid": all((q.get("competency") or "").strip() in set(req) for q in questions
                     if q.get("competency")),
    }


@app.post("/api/students/{student_id}/assessments")
def api_submit_assessment(student_id: int, request: Request, body: dict):
    user = _current_user(request)
    _own_student(user, student_id)
    skill_id = body["skill_id"]
    questions = body.get("questions", [])
    answers = body.get("answers", [])
    total_seconds = body.get("total_seconds")
    tab_switches = int(body.get("tab_switches") or 0)
    free_text_answers = body.get("free_text_answers") or []
    external_token = str(body.get("external_token") or "").strip() or None

    if external_token:
        existing = models.get_assessment_attempt_by_token(student_id, external_token)
        if existing:
            payload = _stored_attempt_payload(student_id, existing)
            payload["already"] = True
            payload["analysis"] = matching.analyze_student(student_id)
            return payload

    camera_flags = _local_integrity_flags_for_submission(student_id, skill_id, external_token, body)
    payload = _compute_assessment_result(
        student_id, skill_id, questions, answers, total_seconds, tab_switches,
        free_text_answers, extra_flags=camera_flags)
    _store_assessment_result(student_id, skill_id, payload, external_token=external_token)
    payload["analysis"] = matching.analyze_student(student_id)
    return payload


def _current_user_flex(request: Request, body=None):
    """Bearer-token auth from the Authorization header, falling back to a token
    in the request body (`auth_token`). Used by the exit-finalize endpoint so a
    `navigator.sendBeacon` (which cannot set headers) can still authenticate."""
    try:
        return _current_user(request)
    except HTTPException:
        token = ""
        if body and isinstance(body, dict):
            token = str(body.get("auth_token") or "").strip()
        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        user = models.get_session_user(token)
        if not user:
            raise HTTPException(status_code=401, detail="Session expired, please sign in again")
        return user


def _local_integrity_flags_for_submission(student_id, skill_id, external_token, body,
                                          termination_event=None):
    """Collect validated browser/camera event metadata for the active attempt.

    Events may arrive ahead of time through /integrity-events, and the final
    submit/finalize body may include the same local event list as a reliability
    fallback for page-unload cases. Both paths are token-bound and deduped.
    """
    body_events = body.get("camera_events") or []
    if body_events and not isinstance(body_events, list):
        raise HTTPException(status_code=400, detail="Camera events must be a list")

    events_to_append = []
    if termination_event:
        events_to_append.append(termination_event)
    if body_events:
        events_to_append.extend(body_events[:integrity.MAX_CAMERA_EVENTS_PER_SUBMISSION])

    if events_to_append:
        active = models.get_active_assessment(student_id)
        if not active:
            raise HTTPException(status_code=409, detail="No active assessment session for integrity events")
        if int(active["skill_id"]) != int(skill_id):
            raise HTTPException(status_code=409, detail="Integrity events do not match the active assessment skill")
        if not external_token or str(active.get("external_token") or "").strip() != external_token:
            raise HTTPException(status_code=403, detail="Integrity events do not match the active assessment session")
        for raw in events_to_append:
            try:
                event = integrity.validate_assessment_integrity_event(raw)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            models.append_active_assessment_event(student_id, skill_id, external_token, event)

    stored = models.list_active_assessment_events(student_id, skill_id, external_token)
    try:
        return integrity.assessment_events_to_flags(stored)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _validated_termination_event(body):
    raw = body.get("termination_event")
    if not raw:
        return None
    try:
        event = integrity.validate_assessment_integrity_event(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not integrity.is_hard_termination_event(event):
        raise HTTPException(status_code=400, detail="Termination event must be a hard integrity event")
    return event


def _compute_assessment_result(student_id, skill_id, questions, answers,
                               total_seconds, tab_switches, free_text_answers,
                               extra_flags=None, ended=None):
    """Deterministic grading shared by the normal submit and the exit-finalize
    endpoints. Answers shorter than the question list are unanswered and simply
    never count toward the score (unanswered == 0 marks)."""
    skill = models.get_skill(skill_id)
    student = models.get_student(student_id)

    flags = integrity.evaluate_attempt(len(questions), total_seconds, free_text_answers, tab_switches)
    if extra_flags:
        flags = list(flags) + list(extra_flags)

    # grade free-text answers as a batch (real GenAI call when a key is set,
    # deterministic semantic-overlap heuristic otherwise)
    ft_indexes = [i for i, q in enumerate(questions) if q and q.get("type") == "free_text"]
    ft_pairs = [(q.get("answer") or "", str(answers[i]) if i < len(answers) else "")
                for i, q in enumerate(questions) if i in ft_indexes]
    ft_results = genai.grade_free_text_batch(
        ft_pairs, skill["name"], (student.get("target_role") or {}).get("title"))
    ft_cursor = 0

    # per-question results drive an objective, transparent score
    per_question = []
    correct = 0
    for i, q in enumerate(questions):
        ans = str(answers[i]) if i < len(answers) else ""
        model_ans = (q.get("answer") or "") if q else ""
        is_correct = False
        if model_ans:
            if q.get("type") == "multiple_choice":
                is_correct = ans.strip().lower() == model_ans.strip().lower()
            else:
                is_correct = bool(ft_results[ft_cursor]) if ft_cursor < len(ft_results) else False
                ft_cursor += 1
        if is_correct:
            correct += 1
        per_question.append({"index": i, "type": q.get("type", "multiple_choice"),
                             "correct": is_correct, "answer": ans,
                             "competency": (q.get("competency") or "") if q else ""})
    score = round((correct / max(len(questions), 1)) * 100, 1)

    # Competency-aware pass rule (Phase 4.5): for a FULL-COVERAGE assessment of a
    # skill with a blueprint, passing requires the overall threshold AND every
    # required competency to itself pass (>= 70). Legacy/partial/untagged attempts
    # keep the original rule so existing history is never rewritten.
    role = student.get("target_role") or {}
    required = (coverage.required_slugs(skill["name"], _path_required_level(student, role, skill_id))
                if skill_blueprint.has_blueprint(skill["name"]) else [])
    _, _pq, competencies = coverage.score_assessment(
        questions, answers, [p["correct"] for p in per_question])
    full_coverage = bool(required) and coverage.coverage_for_questions(questions, required)[0]
    high_flag = any(integrity.is_score_blocking_flag(f) for f in flags)
    passed = score >= PASS_THRESHOLD and not high_flag
    if full_coverage:
        missing = coverage.coverage_for_questions(questions, required)[1]
        comps_all_pass = all(c["passed"] for c in competencies if c["competency"] in required)
        if missing or not comps_all_pass:
            passed = False

    level, _ = matching.effective_skill_level(student, skill_id)
    before = level or "Beginner"
    after = before
    if passed:
        after = LEVELS[min(LEVELS.index(before) + 1, 2)] if before != "Advanced" else "Advanced"

    payload = {
        "score": score,
        "passed": passed,
        "flags": flags,
        "questions": questions,
        "answers": answers,
        "per_question": per_question,
        "competencies": competencies,
        "full_coverage": full_coverage,
        "level_before": before,
        "level_after": after,
        "unanswered": sum(1 for i, _q in enumerate(questions)
                          if i >= len(answers) or not str(answers[i] or "").strip()),
        "integrity_status": integrity.result_integrity_status(flags),
    }
    if ended:
        payload["ended"] = ended
    return payload


def _store_assessment_result(student_id, skill_id, payload, external_token=None):
    """Persist a computed result, release the active-assessment lock, and update
    the verified skill profile on a pass."""
    models.create_assessment_attempt(
        student_id, skill_id, json.dumps(payload["questions"]),
        json.dumps(payload["answers"]), payload["score"], int(payload["passed"]),
        json.dumps(payload["flags"]), payload["level_before"], payload["level_after"],
        per_question=json.dumps(payload["per_question"]), external_token=external_token)
    models.clear_active_assessment(student_id)
    if payload["passed"]:
        models.update_verified_skill(student_id, skill_id, payload["level_after"])


def _stored_attempt_payload(student_id, attempt, ended=None):
    """Rebuild the submit/finalize response shape from a stored attempt row so an
    idempotent duplicate exit/submit returns an identical result (no double-grade)."""
    questions = (json.loads(attempt["questions"]) if isinstance(attempt.get("questions"), str)
                 else attempt["questions"])
    answers = (json.loads(attempt["answers"]) if isinstance(attempt.get("answers"), str)
               else attempt["answers"])
    flags = (json.loads(attempt["flags"]) if isinstance(attempt.get("flags"), str)
             else attempt["flags"])
    per_question = (json.loads(attempt["per_question"])
                    if isinstance(attempt.get("per_question"), str)
                    else (attempt.get("per_question") or []))
    skill_id = attempt["skill_id"]
    skill = models.get_skill(skill_id)
    student = models.get_student(student_id)
    role = student.get("target_role") or {}
    required = (coverage.required_slugs(skill["name"], _path_required_level(student, role, skill_id))
                if skill_blueprint.has_blueprint(skill["name"]) else [])
    _, _comp, competencies = coverage.score_assessment(
        questions, answers, [p["correct"] for p in per_question])
    full_coverage = bool(required) and coverage.coverage_for_questions(questions, required)[0]
    hard_flags = [f for f in flags or [] if integrity.is_hard_termination_event(f.get("code"))]
    payload = {
        "score": attempt["score"],
        "passed": bool(attempt["passed"]),
        "flags": flags,
        "questions": questions,
        "answers": answers,
        "per_question": per_question,
        "competencies": competencies,
        "full_coverage": full_coverage,
        "level_before": attempt["level_before"],
        "level_after": attempt["level_after"],
        "unanswered": sum(1 for i, _q in enumerate(questions)
                          if i >= len(answers) or not str(answers[i] or "").strip()),
        "integrity_status": integrity.result_integrity_status(flags),
    }
    if hard_flags:
        if ended == "exit":
            ended = "integrity_violation"
        payload["termination_reason"] = integrity.event_reason(hard_flags[0].get("code"))
    if ended:
        payload["ended"] = ended
    return payload


@app.post("/api/students/{student_id}/assessments/finalize")
def api_finalize_assessment(student_id: int, request: Request, body: dict):
    """Immediately finalize an in-progress verified assessment (page unload,
    tab/section leave, refresh or close). Every unanswered question is scored as
    zero, the active-assessment lock is cleared, and the Tutor/interview/TTS
    endpoints unlock right away. Idempotent per attempt token: duplicate exit
    events (route-leave + pagehide + beacon) never double-submit or double-count.

    A session token supplied as `auth_token` in the body authenticates
    `navigator.sendBeacon` calls (which cannot set Authorization headers), and
    the per-attempt `external_token` makes the finalize idempotent."""
    user = _current_user_flex(request, body)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    skill_id = body["skill_id"]
    questions = body.get("questions", [])
    answers = body.get("answers", [])
    total_seconds = body.get("total_seconds")
    tab_switches = int(body.get("tab_switches") or 0)
    free_text_answers = body.get("free_text_answers") or []
    external_token = str(body.get("external_token") or "").strip() or None

    if external_token:
        existing = models.get_assessment_attempt_by_token(student_id, external_token)
        if existing:
            payload = _stored_attempt_payload(student_id, existing, ended="exit")
            payload["already"] = True
            payload["analysis"] = matching.analyze_student(student_id)
            return payload

    termination_event = _validated_termination_event(body)
    camera_flags = _local_integrity_flags_for_submission(
        student_id, skill_id, external_token, body, termination_event=termination_event)
    payload = _compute_assessment_result(
        student_id, skill_id, questions, answers, total_seconds, tab_switches,
        free_text_answers, extra_flags=camera_flags,
        ended=("integrity_violation" if termination_event else "exit"))
    if termination_event:
        payload["termination_event"] = termination_event
        payload["termination_reason"] = integrity.event_reason(termination_event)
    if questions:
        payload["flags"] = list(payload["flags"]) + [{
            "code": "assessment_exited",
            "label": "Assessment ended early",
            "severity": "warning",
            "detail": "The assessment was exited before submit; unanswered questions were scored as zero.",
        }]
        payload["integrity_status"] = integrity.result_integrity_status(payload["flags"])
    _store_assessment_result(student_id, skill_id, payload, external_token=external_token)
    payload["analysis"] = matching.analyze_student(student_id)
    return payload


@app.get("/api/students/{student_id}/assessments")
def api_list_assessments(student_id: int, request: Request):
    user = _current_user(request)
    _own_student(user, student_id)
    return models.list_assessment_attempts(student_id=student_id)


@app.get("/api/students/{student_id}/skills/{skill_id}/verification")
def api_skill_verification(student_id: int, skill_id: int, request: Request):
    """Evidence-backed verification view for one skill (self-service, owner only).

    Explains WHY a skill is (or is not) Verified from the persisted record:
    the attempt history, per-competency breakdown of the most recent
    competency-tagged attempt, and any integrity flags raised. Built entirely
    from existing rows â€” no duplicate skill system, nothing invented.
    """
    user = _current_user(request)
    _own_student(user, student_id)
    student = models.get_student(student_id)
    skill = models.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    verified = next((v for v in (student.get("verified_skills") or [])
                     if v.get("skill_id") == skill_id), None)
    attempts = models.list_assessment_attempts(student_id=student_id, skill_id=skill_id)

    def _flags(raw):
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except Exception:
            parsed = []
        safe = []
        for f in parsed if isinstance(parsed, list) else []:
            if isinstance(f, dict):
                safe.append({k: f.get(k) for k in ("code", "label", "severity", "detail")})
            else:
                safe.append({"code": str(f), "label": str(f), "severity": "warning", "detail": ""})
        return safe

    def _pq(attempt):
        try:
            raw = attempt.get("per_question")
            parsed = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except Exception:
            parsed = []
        return [p for p in parsed if isinstance(p, dict) and (p.get("competency") or "").strip()]

    def _competencies(attempt):
        by = {}
        for p in _pq(attempt):
            comp = p["competency"].strip()
            b = by.setdefault(comp, {"count": 0, "correct": 0})
            b["count"] += 1
            if p.get("correct"):
                b["correct"] += 1
        out = []
        for comp, agg in sorted(by.items()):
            score = round((agg["correct"] / max(agg["count"], 1)) * 100, 1)
            out.append({
                "competency": comp,
                "label": skill_blueprint.competency_label(comp) or comp,
                "count": agg["count"],
                "correct": agg["correct"],
                "score": score,
                "passed": score >= PASS_THRESHOLD,
            })
        return out

    tagged = [a for a in attempts if _pq(a)]
    source = next((a for a in tagged if a.get("passed")), None) or (tagged[0] if tagged else None)

    return {
        "skill": {"id": skill["id"], "name": skill["name"], "category": skill.get("category")},
        "verified": bool(verified),
        "verified_level": (verified or {}).get("level"),
        "verified_at": (verified or {}).get("verified_at"),
        "attempt_count": len(attempts),
        "attempts": [
            {
                "id": a["id"],
                "score": a.get("score"),
                "passed": bool(a.get("passed")),
                "level_before": a.get("level_before"),
                "level_after": a.get("level_after"),
                "created_at": a.get("created_at"),
                "flags": _flags(a.get("flags")),
                "high_flags": any(f.get("severity") == "high" for f in _flags(a.get("flags"))),
            }
            for a in attempts
        ],
        "competencies": _competencies(source) if source else [],
        "source_attempt_id": source["id"] if source else None,
    }


# ---------------------------------------------------------------- learning diagnostics

def _own_diagnostic(user, student_id):
    """Learning diagnostics carry the student's own answers/results, so access is
    strictly limited to the owning student (never companies or the university view)."""
    if user["role"] != "Student":
        raise HTTPException(status_code=403, detail="Only the owning student may access learning diagnostics")
    student = models.get_student_by_user(user["id"])
    if not student or student["id"] != student_id:
        raise HTTPException(status_code=403, detail="Not allowed to access another student's data")


def _diagnostic_questions(diag):
    raw = diag.get("questions")
    return json.loads(raw) if isinstance(raw, str) else raw or []


@app.post("/api/students/{student_id}/learning/{skill_id}/diagnostic/generate")
def api_generate_diagnostic(student_id: int, skill_id: int, request: Request, body: dict):
    """Generate a topic-level diagnostic for a (student, skill). Determines which
    competencies inside the skill the student is strong/developing/weak at. This
    NEVER verifies a skill."""
    user = _current_user(request)
    _own_diagnostic(user, student_id)
    skill = models.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    student = models.get_student(student_id)
    role = student.get("target_role") or {}
    learning_item = models.get_learning_item(student_id, skill_id)
    topics = diagnostics.resolve_topics(skill["name"], learning_item)
    try:
        num = max(0, min(int(body.get("num_questions") or 0), 20))
    except (TypeError, ValueError):
        num = 0
    questions = genai.generate_diagnostic(
        skill["name"], topics, role.get("title") if role else None,
        num_questions=num or None)
    models.delete_unanswered_diagnostics(student_id, skill_id)
    diag = models.create_diagnostic(student_id, skill_id, questions)
    return {"skill": skill, "topics": topics, "questions": questions,
            "diagnostic_id": diag["id"]}


@app.post("/api/students/{student_id}/learning/{skill_id}/diagnostic/submit")
def api_submit_diagnostic(student_id: int, skill_id: int, request: Request, body: dict):
    """Submit answers to a generated diagnostic, deterministically score per
    competency, and persist the topic-level results + weak/strong topics."""
    user = _current_user(request)
    _own_diagnostic(user, student_id)
    skill = models.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    diagnostic_id = body.get("diagnostic_id")
    diag = models.get_diagnostic(diagnostic_id) if diagnostic_id else None
    if not diag or diag["student_id"] != student_id or diag["skill_id"] != skill_id:
        raise HTTPException(status_code=404, detail="Diagnostic not found")
    if diag.get("completed_at"):
        raise HTTPException(status_code=400, detail="Diagnostic already completed")

    questions = _diagnostic_questions(diag)
    answers = body.get("answers", [])

    # grade free-text answers as a batch (real GenAI call when a key is set,
    # deterministic semantic-overlap heuristic otherwise) â€” same infra as assessments
    ft_indexes = [i for i, q in enumerate(questions) if q and q.get("type") == "free_text"]
    ft_pairs = [(q.get("correct_answer") or "", str(answers[i]) if i < len(answers) else "")
                for i, q in enumerate(questions) if i in ft_indexes]
    student = models.get_student(student_id)
    role = student.get("target_role") or {}
    ft_results = genai.grade_free_text_batch(
        ft_pairs, skill["name"], role.get("title") if role else None)

    correct_flags = [False] * len(questions)
    ft_cursor = 0
    for i, q in enumerate(questions):
        model_ans = (q.get("correct_answer") or "") if q else ""
        ans = str(answers[i]) if i < len(answers) else ""
        if not model_ans:
            continue
        if q.get("type") == "mcq":
            correct_flags[i] = ans.strip().lower() == str(model_ans).strip().lower()
        else:
            correct_flags[i] = bool(ft_results[ft_cursor]) if ft_cursor < len(ft_results) else False
            ft_cursor += 1

    result = diagnostics.score_topics(questions, answers, lambda i, q, a: correct_flags[i])

    saved = models.complete_diagnostic(diag["id"], answers, result["overall_score"], result)
    return models.public_diagnostic(saved)


@app.get("/api/students/{student_id}/learning/{skill_id}/diagnostic/latest")
def api_latest_diagnostic(student_id: int, skill_id: int, request: Request):
    """Return the most recent diagnostic (generated or completed) for a (student, skill)."""
    user = _current_user(request)
    _own_diagnostic(user, student_id)
    diag = models.get_latest_diagnostic(student_id, skill_id)
    if not diag:
        raise HTTPException(status_code=404, detail="No diagnostic found")
    return models.public_diagnostic(diag)


# ---------------------------------------------------------------- personalized learning path

def _path_required_level(student, role, skill_id):
    """Required proficiency for this skill in the student's target role (used only
    as a hint for path building; Intermediate when unknown)."""
    if not role:
        return "Intermediate"
    for row in matching.categorize(student, role):
        if row["skill_id"] == skill_id:
            return row.get("required_level") or "Intermediate"
    return "Intermediate"


@app.post("/api/students/{student_id}/learning/{skill_id}/personalized-path/generate")
def api_generate_personalized_path(student_id: int, skill_id: int, request: Request, body: dict):
    """Build (or reuse) a personalized learning path from the student's latest
    COMPLETED diagnostic for this skill. Never regenerates for the same diagnostic;
    a newer completed diagnostic may produce a new path."""
    user = _current_user(request)
    _own_diagnostic(user, student_id)
    skill = models.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    diag = models.get_latest_diagnostic(student_id, skill_id)
    if not diag or not diag.get("completed_at"):
        return {"diagnostic_required": True, "path": None}

    existing = models.get_personalized_path_for_diagnostic(student_id, skill_id, diag["id"])
    if existing:
        return models.public_personalized_path(existing)

    student = models.get_student(student_id)
    role = student.get("target_role") or {}
    required_level = _path_required_level(student, role, skill_id)
    public_diag = models.public_diagnostic(diag)
    built = path_builder.build_personalized_path(skill, public_diag, required_level)
    saved = models.create_personalized_path(
        student_id, skill_id, diag["id"], required_level,
        built["path"], built["skipped_mastered"], built["stages"])
    return models.public_personalized_path(saved)


@app.get("/api/students/{student_id}/learning/{skill_id}/personalized-path")
def api_get_personalized_path(student_id: int, skill_id: int, request: Request):
    user = _current_user(request)
    _own_diagnostic(user, student_id)
    path = models.get_personalized_path(student_id, skill_id)
    if not path:
        return {"diagnostic_required": True, "path": None}
    return models.public_personalized_path(path)


@app.post("/api/students/{student_id}/learning/{skill_id}/personalized-path/progress")
def api_save_personalized_path_progress(student_id: int, skill_id: int, request: Request, body: dict):
    """Persist which path items/stages a student has completed (order-independent)."""
    user = _current_user(request)
    _own_diagnostic(user, student_id)
    progress = []
    for s in body.get("progress") or []:
        if isinstance(s, str) and s:
            progress.append(s)
    return models.update_path_progress(student_id, skill_id, list(dict.fromkeys(progress)))


@app.get("/api/students/{student_id}/learning/{skill_id}/final-assessment/status")
def api_final_assessment_status(student_id: int, skill_id: int, request: Request):
    """Deterministic readiness for the Final Assessment (Reqs 5-8).

    A required competency (blueprint slug) is satisfied if it was MASTERED in the
    student's latest diagnostic OR is a completed (progressed) item on the current
    personalized path. The Final Assessment stays locked until every requirement is
    satisfied. No LLM involved.
    """
    user = _current_user(request)
    _own_diagnostic(user, student_id)
    skill = models.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    student = models.get_student(student_id)
    role = student.get("target_role") or {}
    required_level = _path_required_level(student, role, skill_id)

    diag = models.get_latest_diagnostic(student_id, skill_id)
    diag_ready = False
    topics = []
    if diag and diag.get("completed_at"):
        topics = (models.public_diagnostic(diag).get("topic_results") or [])
        diag_ready = True

    path = models.get_personalized_path(student_id, skill_id)
    path_items = []
    path_progress = []
    skipped = []
    path_ready = False
    if path:
        items = json.loads(path.get("items")) if isinstance(path.get("items"), str) else path.get("items") or []
        path_items = items
        path_progress = json.loads(path.get("progress")) if isinstance(path.get("progress"), str) else path.get("progress") or []
        skipped = json.loads(path.get("skipped_mastered")) if isinstance(path.get("skipped_mastered"), str) else path.get("skipped_mastered") or []
        path_ready = True

    readiness = coverage.final_assessment_ready(
        skill["name"], required_level, topics, path_items, path_progress, skipped)

    return {
        "skill": {"id": skill["id"], "name": skill["name"]},
        "required_level": required_level,
        "diagnostic_completed": diag_ready,
        "path_exists": path_ready,
        "has_blueprint": skill_blueprint.has_blueprint(skill["name"]),
        "readiness": readiness,
    }


# ---------------------------------------------------------------- topic lessons

def _own_lesson_topic(user, student_id, skill_id, competency):
    """Authorize access to a lesson and return (path, path_item).

    Verifies: Student role, student ownership, personalized path exists for
    student+skill, competency is an active (non-mastered) topic in that path.
    """
    if user["role"] != "Student":
        raise HTTPException(status_code=403, detail="Only students may access lessons")
    student = models.get_student_by_user(user["id"])
    if not student or student["id"] != student_id:
        raise HTTPException(status_code=403, detail="Not allowed to access another student's data")
    path = models.get_personalized_path(student_id, skill_id)
    if not path:
        raise HTTPException(status_code=404, detail="No personalized path found for this skill")
    items = json.loads(path.get("items")) or [] if isinstance(path.get("items"), str) else path.get("items") or []
    path_item = next((it for it in items if it.get("competency") == competency), None)
    if not path_item:
        raise HTTPException(status_code=404, detail=f"Competency '{competency}' not found in this path")
    mastered_raw = path.get("skipped_mastered")
    mastered = set(json.loads(mastered_raw) if isinstance(mastered_raw, str) else mastered_raw or [])
    if competency in mastered:
        raise HTTPException(status_code=400, detail="Cannot create lesson for a mastered topic")
    return path, path_item


def _resolve_lesson_action(path_item):
    """Derive 'learn' vs 'review' from the path item's diagnostic data."""
    topic_status = path_item.get("topic_status") or "weak"
    return "review" if topic_status == diagnostics.DEVELOPING else "learn"


def _lesson_response(student_id, skill_id, path, path_item, lesson):
    skill = models.get_skill(skill_id) or {}
    student = models.get_student(student_id) or {}
    target_role = (student.get("target_role") or {}).get("title")
    return lessons.normalize_lesson(
        lesson,
        path_item["competency"],
        skill_name=skill.get("name"),
        skill_category=skill.get("category"),
        target_role=target_role,
        required_level=path.get("required_level"),
    )


@app.post("/api/students/{student_id}/learning/{skill_id}/lessons/{competency}/generate")
def api_generate_lesson(student_id: int, skill_id: int, competency: str, request: Request, body: dict):
    """Generate (or return existing) lesson for a topic. Reuses existing lesson if one
    already exists for this student + current path + competency."""
    user = _current_user(request)
    path, path_item = _own_lesson_topic(user, student_id, skill_id, competency)
    existing = models.get_lesson(student_id, path["id"], competency)
    if existing:
        return _lesson_response(student_id, skill_id, path, path_item, existing)
    skill = models.get_skill(skill_id)
    skill_name = (skill.get("name") if skill else None) or f"Skill {skill_id}"
    action = body.get("action") or _resolve_lesson_action(path_item)
    target_role = None
    student_profile = models.get_student(student_id)
    if student_profile:
        target_role = (student_profile.get("target_role") or {}).get("title")
    content = lessons.generate_lesson(
        skill_name=skill_name,
        competency=competency,
        action=action,
        topic_status=path_item.get("topic_status"),
        diagnostic_score=path_item.get("diagnostic_score"),
        target_role=target_role,
        required_level=path.get("required_level"),
        skill_category=skill.get("category"),
    )
    lesson = models.create_lesson(
        student_id=student_id,
        skill_id=skill_id,
        path_id=path["id"],
        competency=competency,
        title=f"{skill_name} > {competency}",
        action=action,
        content_json=content,
    )
    return _lesson_response(student_id, skill_id, path, path_item, lesson)


@app.get("/api/students/{student_id}/learning/{skill_id}/lessons/{competency}")
def api_get_lesson(student_id: int, skill_id: int, competency: str, request: Request):
    """Get an existing lesson for a topic. Returns 404 if not yet generated."""
    user = _current_user(request)
    path, path_item = _own_lesson_topic(user, student_id, skill_id, competency)
    lesson = models.get_lesson(student_id, path["id"], competency)
    if not lesson:
        raise HTTPException(status_code=404, detail="No lesson found. Generate it first.")
    return _lesson_response(student_id, skill_id, path, path_item, lesson)


@app.post("/api/students/{student_id}/learning/{skill_id}/lessons/{competency}/start")
def api_start_lesson(student_id: int, skill_id: int, competency: str, request: Request, body: dict):
    """Mark a lesson as in_progress."""
    user = _current_user(request)
    path, path_item = _own_lesson_topic(user, student_id, skill_id, competency)
    lesson = models.get_lesson(student_id, path["id"], competency)
    if not lesson:
        raise HTTPException(status_code=404, detail="No lesson found. Generate it first.")
    if lesson["state"] == "completed":
        return _lesson_response(student_id, skill_id, path, path_item, lesson)
    lesson = models.update_lesson_state(student_id, path["id"], competency, "in_progress")
    return _lesson_response(student_id, skill_id, path, path_item, lesson)


def _current_practice_lesson(student_id, skill_id, competency, request):
    user = _current_user(request)
    path, path_item = _own_lesson_topic(user, student_id, skill_id, competency)
    lesson = models.get_lesson(student_id, path["id"], competency)
    if not lesson:
        raise HTTPException(status_code=404, detail="No lesson found. Generate it first.")
    return path, path_item, lesson


def _practice_task_for_submission(student_id, lesson, body):
    source_raw = body.get("practice_task_source_attempt_id")
    if source_raw in (None, ""):
        return practice.lesson_practice_task(lesson)
    try:
        source_attempt_id = int(source_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid practice task source")
    source_attempt = models.get_practice_attempt(student_id, lesson["id"], source_attempt_id)
    if not source_attempt:
        raise HTTPException(status_code=404, detail="Practice task source not found")
    remediation = source_attempt.get("remediation") or {}
    if not remediation.get("follow_up_task"):
        raise HTTPException(status_code=400, detail="Practice task source has no follow-up task")
    return practice.remediation_practice_task(source_attempt)


@app.get("/api/students/{student_id}/learning/{skill_id}/lessons/{competency}/practice")
def api_get_practice_attempts(student_id: int, skill_id: int, competency: str, request: Request):
    """Return persisted practice attempts for this lesson, latest first."""
    path, path_item, lesson = _current_practice_lesson(student_id, skill_id, competency, request)
    attempts = models.list_practice_attempts(student_id, lesson["id"])
    return {
        "latest": attempts[0] if attempts else None,
        "attempts": attempts,
        "count": len(attempts),
    }


@app.post("/api/students/{student_id}/learning/{skill_id}/lessons/{competency}/practice")
def api_submit_practice(student_id: int, skill_id: int, competency: str,
                        request: Request, body: dict):
    """Evaluate and persist a Practice answer.

    Practice feedback is informational. It does not complete the lesson, update
    personalized path progress, create verified skills, or affect assessment access.
    """
    path, path_item, lesson = _current_practice_lesson(student_id, skill_id, competency, request)
    answer = str(body.get("answer") or "").strip()
    if not answer:
        raise HTTPException(status_code=400, detail="Practice answer is required")
    if len(answer) > 8000:
        raise HTTPException(status_code=400, detail="Practice answer is too long")
    skill = models.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    student = models.get_student(student_id)
    previous_attempts = models.list_practice_attempts(student_id, lesson["id"], limit=3)
    practice_task = _practice_task_for_submission(student_id, lesson, body)
    context = practice.build_evaluation_context(
        student=student,
        skill=skill,
        path=path,
        path_item=path_item,
        lesson=lesson,
        previous_attempts=previous_attempts,
        practice_task=practice_task,
    )
    result = practice.evaluate_practice(context, answer)
    remediation = practice.generate_remediation(context, result, answer)
    attempt = models.create_practice_attempt(
        student_id=student_id,
        skill_id=skill_id,
        path_id=path["id"],
        lesson_id=lesson["id"],
        competency=competency,
        answer=answer,
        result=result,
        practice_task=practice_task,
        remediation=remediation,
    )
    return {
        "attempt": attempt,
        "attempts_count": len(previous_attempts) + 1,
    }


# ---------------------------------------------------------------- practice scenarios

def _require_scenario_attempt(student_id, attempt_id, request):
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    attempt = models.get_scenario_attempt(student_id, attempt_id)
    if not attempt:
        raise HTTPException(status_code=404, detail="Scenario attempt not found")
    return user, attempt


def _scenario_for_attempt(attempt):
    scenario = scenarios._scenario(attempt["scenario_id"])
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return scenario


@app.get("/api/students/{student_id}/scenarios")
def api_list_scenarios(student_id: int, request: Request):
    """Scenario library: catalog, per-scenario progress, practice stats."""
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    student = models.get_student(student_id)
    return scenarios.list_scenarios(student)


@app.get("/api/students/{student_id}/scenarios/history")
def api_scenario_history(student_id: int, request: Request):
    """Per-attempt scenario history: date, version, score, role, status."""
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    student = models.get_student(student_id)
    return scenarios.scenario_history(student)


@app.post("/api/students/{student_id}/scenarios/{scenario_id}/start")
def api_start_scenario(student_id: int, scenario_id: str, request: Request):
    """Start (or resume) a scenario; returns the interactive player payload."""
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    student = models.get_student(student_id)
    scenario = scenarios.lookup_scenario(student, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if not scenarios.scenario_eligible(student, scenario) and not scenarios.has_attempt(student_id, scenario_id):
        raise HTTPException(status_code=403, detail="Scenario is not available for your profile and target role yet.")
    try:
        attempt, scenario = scenarios.start_scenario(student_id, scenario_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return scenarios.player_view(attempt, scenario, student=student)


@app.get("/api/students/{student_id}/scenarios/attempts/{attempt_id}")
def api_get_scenario_attempt(student_id: int, attempt_id: int, request: Request):
    """Resume an attempt: player view while in progress, results once done."""
    user, attempt = _require_scenario_attempt(student_id, attempt_id, request)
    scenario = _scenario_for_attempt(attempt)
    if attempt["status"] == "completed":
        fb = attempt.get("feedback") or {}
        return scenarios.result_payload(
            attempt, scenario,
            match_before=(fb.get("_match_before")),
            match_after=(fb.get("_match_after")),
            deltas=attempt.get("skill_deltas") or [],
            student=models.get_student(student_id),
        )
    return scenarios.player_view(attempt, scenario, student=models.get_student(student_id))


@app.post("/api/students/{student_id}/scenarios/attempts/{attempt_id}/decide")
def api_decide_scenario(student_id: int, attempt_id: int, body: dict, request: Request):
    """Advance a scenario by one decision. Branches the story, scores, and
    completes the attempt when the decision leads to an outcome."""
    user, attempt = _require_scenario_attempt(student_id, attempt_id, request)
    scenario = _scenario_for_attempt(attempt)
    try:
        updated, completed = scenarios.decide(attempt, scenario, body or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not completed:
        return scenarios.player_view(updated, scenario, student=models.get_student(student_id))

    match_before = (matching.analyze_student(student_id) or {}).get("match_score")
    deltas = scenarios.improve_skill_confidence(student_id, scenario)
    match_after = (matching.analyze_student(student_id) or {}).get("match_score")
    payload = scenarios.result_payload(updated, scenario, match_before=match_before, match_after=match_after, deltas=deltas)
    # keep the before/after numbers durable so a resumed results view stays honest
    fb = dict(updated.get("feedback") or {})
    fb["_match_before"] = match_before
    fb["_match_after"] = match_after
    models.update_scenario_attempt(attempt_id, feedback_json=fb)
    return payload


@app.post("/api/students/{student_id}/scenarios/attempts/{attempt_id}/hint")
def api_scenario_hint(student_id: int, attempt_id: int, body: dict, request: Request):
    """Curated, non-answer nudge for the current step."""
    user, attempt = _require_scenario_attempt(student_id, attempt_id, request)
    scenario = _scenario_for_attempt(attempt)
    if attempt["status"] == "completed":
        raise HTTPException(status_code=400, detail="This scenario is already complete")
    hint = scenarios.hint_for(attempt, scenario, step_id=(body or {}).get("step_id"), question=(body or {}).get("question"))
    if not (body or {}).get("question"):
        attempt = scenarios.mark_hint(attempt, scenario)
    hint["hints_used"] = attempt.get("hints_used") or 0
    hint["hint_policy"] = scenarios._hint_policy(attempt.get("hints_used") or 0)
    return hint


# ---------------------------------------------------------------- saved roles

@app.get("/api/students/{student_id}/saved-roles")
def api_list_saved_roles(student_id: int, request: Request):
    """Role ids the student bookmarked from the Skills & Roles catalog/browse."""
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    return {"role_ids": models.list_saved_roles(student_id)}


@app.post("/api/students/{student_id}/saved-roles/{role_id}")
def api_save_role(student_id: int, role_id: int, request: Request):
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    role = models.get_role(role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    models.create_saved_role(student_id, role_id)
    return {"role_ids": models.list_saved_roles(student_id)}


@app.delete("/api/students/{student_id}/saved-roles/{role_id}")
def api_unsave_role(student_id: int, role_id: int, request: Request):
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    models.remove_saved_role(student_id, role_id)
    return {"role_ids": models.list_saved_roles(student_id)}


@app.get("/api/students/{student_id}/recent-roles")
def api_list_recent_roles(student_id: int, request: Request):
    """Roles this student opened most recently (Phase L recently-viewed). The
    list is private to the student, newest-first, capped in the data layer."""
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    return {"roles": models.list_recent_role_views(student_id)}


@app.post("/api/students/{student_id}/recent-roles")
def api_record_role_view(student_id: int, request: Request, body: dict):
    """Record a student opening a role's details so the explorer can surface it
    under Recently viewed. Unknown role -> 404; a re-view just refreshes the
    timestamp (upsert, never duplicates)."""
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    role_id = (body or {}).get("role_id")
    if not isinstance(role_id, int) or role_id <= 0:
        raise HTTPException(status_code=400, detail="role_id must be a positive integer")
    try:
        viewed_at = models.record_role_view(student_id, role_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"viewed_at": viewed_at}


@app.post("/api/students/{student_id}/learning/{skill_id}/lessons/{competency}/mini-check")
def api_submit_mini_check(student_id: int, skill_id: int, competency: str,
                          request: Request, body: dict):
    """Submit Mini Check answers. Pass >= 70% completes the lesson and adds the topic
    to the personalized path progress. Fail leaves everything in_progress."""
    user = _current_user(request)
    path, path_item = _own_lesson_topic(user, student_id, skill_id, competency)
    lesson = models.get_lesson(student_id, path["id"], competency)
    if not lesson:
        raise HTTPException(status_code=404, detail="No lesson found. Generate it first.")
    content = lesson.get("content") or {}
    mc_questions = (content.get("mini_check") or {}).get("questions") or []
    answers = body.get("answers") or []
    if not mc_questions:
        raise HTTPException(status_code=400, detail="Lesson has no mini check questions")
    correct, total, passed = lessons.score_mini_check(mc_questions, answers)
    result = {"score": round((correct / total) if total else 0.0, 3), "correct": correct,
              "total": total, "passed": passed}
    new_state = "completed" if passed else "in_progress"
    lesson = models.update_lesson_state(student_id, path["id"], competency, new_state, result)
    if passed:
        models.add_to_path_progress(student_id, skill_id, [path_item["id"]])
    refreshed_path = models.get_personalized_path(student_id, skill_id)
    prog_raw = refreshed_path.get("progress") if refreshed_path else None
    path_progress = json.loads(prog_raw) if isinstance(prog_raw, str) else (prog_raw or [])
    return {"lesson": _lesson_response(student_id, skill_id, path, path_item, lesson),
            "path_progress": path_progress}


# ------------------------------------------------------------------ recent jobs

def _student_feed_profile(user, location="", country="", market=""):
    """Feed coordinates for the current user: student profile, skills, role
    title, country, location, and role requisites — the EXACT inputs both the
    recent-jobs feed and the Phase K job saver run on, so a saved snapshot
    always matches what the student actually saw."""
    loc = location or user.get("location") or ""
    cty = country or user.get("country") or ""
    skills = []
    requisites = []
    role = ""
    student = None
    if user["role"] == "Student":
        student = models.get_student_by_user(user["id"])
        if student:
            for s in student.get("self_reported_skills") or []:
                skills.append((s["name"], s.get("level") or "Beginner", False))
            for v in student.get("verified_skills") or []:
                skills.append((v["name"], v.get("level") or "Intermediate", True))
            role = (student.get("target_role") or {}).get("title") or ""
            for rs in (student.get("target_role") or {}).get("required_skills") or []:
                if rs.get("name"):
                    requisites.append(rs["name"])
    return student, skills, role, cty, loc, requisites


@app.get("/api/jobs/recent")
def api_recent_jobs(request: Request, limit: int = 10, location: str = "", country: str = "", market: str = ""):
    """Real, recent job postings matched + ranked (most → least fitting) to the
    signed-in student's skills, target role, and country. Live multi-source feed
    with a short cache; when feeds are unreachable the response is an honest
    ``unavailable`` empty state (never curated/demo jobs).

    ``market`` is an optional remote/relocation search country (e.g. ``gb`` for
    a Cairo student) that widens reach via location-scoped feeds like Adzuna —
    clearly surfaced as a relocation search, never implied to be local."""
    user = _current_user(request)
    student, skills, role, cty, loc, requisites = _student_feed_profile(
        user, location=location, country=country, market=market)
    # Students only search AFTER their CV is uploaded: the role feed is matched
    # to their CV-derived profile, so we never fetch before an upload populates
    # self-reported skills.
    if user["role"] == "Student" and not student.get("self_reported_skills"):
        return {"source": "no-cv", "jobs": [], "groups": {
            "local_count": 0, "broader_count": 0, "other_count": 0}}
    return jobs.recent_jobs(skills=skills, role=role,
                            country=cty,
                            location=loc,
                            limit=min(max(int(limit), 1), 16),
                            role_requisites=requisites,
                            market_country=market,
                            request_id=getattr(request.state, "request_id", "") or "")


# ------------------------------------------------------------------ Phase K: saved jobs + private tracker

def _tracker_or_http(e):
    if isinstance(e, models.TrackerError):
        return HTTPException(status_code=e.code, detail=e.message)
    raise e


@app.get("/api/students/{student_id}/jobs/tracker")
def api_job_tracker_list(student_id: int, request: Request):
    """The student's private application tracker (saved/preparing/applied/...).
    Student-only and ownership-gated; companies and universities never see it."""
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    items = models.list_job_tracker(student_id)
    return {
        "items": items,
        "counts": {stage: sum(1 for i in items if i["stage"] == stage)
                   for stage in models.JOB_TRACKER_STAGES},
    }


@app.get("/api/students/{student_id}/jobs/tracker/{tracker_id}")
def api_job_tracker_get(student_id: int, tracker_id: int, request: Request):
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    entry = models.get_tracker_entry(student_id, tracker_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Tracker entry not found")
    return entry


@app.post("/api/students/{student_id}/jobs/saved")
def api_save_job(student_id: int, request: Request, body: dict):
    """Save a currently-surfaced feed job into the tracker (idempotent).

    The snapshot is taken from the student's own live feed at save time via the
    same machinery that rendered the number they saw (locate_feed_job); a job
    that is not in the current feed is a 404 — a snapshot is never fabricated.
    """
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    fingerprint = (body or {}).get("fingerprint")
    if not fingerprint:
        raise HTTPException(status_code=400, detail="fingerprint is required")
    student, skills, role, cty, loc, requisites = _student_feed_profile(
        user, location=(body or {}).get("location") or "",
        country=(body or {}).get("country") or "")
    market = (body or {}).get("market") or ""
    if not student or not student.get("self_reported_skills"):
        raise HTTPException(status_code=404, detail="No CV yet — nothing to save")
    job = jobs.locate_feed_job(skills, role, cty, loc, requisites, market, fingerprint)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found in the current feed")
    tracker_id, created = models.save_job_snapshot(student_id, job)
    return {"tracker_id": tracker_id, "created": created,
            "item": models.get_tracker_entry(student_id, tracker_id)}


@app.patch("/api/students/{student_id}/jobs/tracker/{tracker_id}")
def api_update_tracker_item(student_id: int, tracker_id: int, request: Request, body: dict):
    """Update note/optional dates, or move the job across the stage allow-list.
    Every stage change is appended to the tracker_stage_history audit table;
    re-applying the same stage is a no-op. Invalid transitions -> 409/400."""
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    try:
        return models.update_tracker_entry(
            student_id, tracker_id,
            stage=body.get("stage"), note=body.get("note"),
            interview_date=body.get("interview_date"),
            application_deadline=body.get("application_deadline"))
    except models.TrackerError as e:
        raise _tracker_or_http(e)


@app.delete("/api/students/{student_id}/jobs/tracker/{tracker_id}")
def api_delete_tracker_item(student_id: int, tracker_id: int, request: Request):
    """Delete ONLY a still-'saved' tracker row (the frontend asks for
    confirmation). Anything beyond saved keeps its history — 409 with a reason."""
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    try:
        models.delete_saved_only(student_id, tracker_id)
    except models.TrackerError as e:
        raise _tracker_or_http(e)
    return {"deleted": True}


# ------------------------------------------------------------------ Phase N: job-link reports

@app.get("/api/students/{student_id}/jobs/link-reports")
def api_job_link_reports(student_id: int, request: Request):
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    return {"reports": models.list_job_link_reports(student_id)}


@app.post("/api/students/{student_id}/jobs/recent/{fingerprint}/report-dead-link")
def api_report_job_link(student_id: int, fingerprint: str, request: Request, body: dict | None = None):
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    student, skills, role, cty, loc, requisites = _student_feed_profile(
        user, location=(body or {}).get("location") or "", country=(body or {}).get("country") or "")
    market = (body or {}).get("market") or ""
    job = jobs.locate_feed_job(skills, role, cty, loc, requisites, market, fingerprint)
    if job is None:
        # A previously saved snapshot is a valid report target even if it has
        # disappeared from the short-lived live feed.
        job = next((x for x in models.list_job_tracker(student_id) if x["fingerprint"] == fingerprint), None)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found in your feed or tracker")
    report_id, created = models.report_job_link(student_id, job)
    return {"report_id": report_id, "created": created, "fingerprint": fingerprint}


# ------------------------------------------------------------------ Phase Q: prepare-for-job readiness

@app.get("/api/students/{student_id}/jobs/recent/{fingerprint}/prepare")
def api_job_prepare(student_id: int, fingerprint: str, request: Request,
                    location: str = "", country: str = "", market: str = ""):
    """Read-only readiness view for a job the student is actually seeing.

    Uses the SAME feed coordinates as the recent-jobs feed (``_student_feed_profile``)
    and a cache-only ``peek_feed_job`` lookup — it never triggers a feed build.
    Each required skill resolves against the student's own verified/self-reported
    records by exact canonical name; ``skill_id`` is a real skills row id or null
    and unresolvable names are honestly ``no_path``."""
    user = _current_user(request)
    _require_roles(user, "Student")
    _own_student(user, student_id)
    student, skills, role, cty, loc, requisites = _student_feed_profile(
        user, location=location, country=country, market=market)
    if not student or not student.get("self_reported_skills"):
        raise HTTPException(status_code=404, detail="No CV yet — nothing to prepare")
    hit = jobs.peek_feed_job(skills, role, cty, loc, requisites, market, fingerprint)
    if not hit or not hit.get("found") or hit.get("job") is None:
        raise HTTPException(status_code=404, detail="Job not found in the current feed")
    return models.prepare_job_view(student, hit["job"])


# ------------------------------------------------------------------ Phase J: explainable role and job matching

def _breakdown_or_http(e):
    if isinstance(e, match_explain.MatchExplainError):
        return HTTPException(status_code=e.status_code, detail=e.message)
    raise e


@app.get("/api/students/{student_id}/target-role-match/breakdown")
def api_target_role_match_breakdown(student_id: int, request: Request):
    """Read-only decomposition of the student's Dashboard role-match score
    (the ``analysis.match_score`` ring) into per-required-skill contributions
    plus labelled rounding adjustments that sum EXACTLY to the displayed
    number. Self-reported evidence is never shown as verified; a missing skill
    contributes zero and is labelled missing, never a penalty."""
    user = _current_user(request)
    _own_student(user, student_id)
    student = models.get_student(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    try:
        return match_explain.target_role_match_breakdown(student)
    except match_explain.MatchExplainError as e:
        raise _breakdown_or_http(e)


@app.get("/api/students/{student_id}/role-match/breakdown")
def api_role_match_breakdown(student_id: int, request: Request,
                             role_id: int | None = None, external_id: str = ""):
    """Read-only decomposition of one recommendation card's match_score ring
    (role_id for local/catalog roles, external_id for ESCO occupations)."""
    user = _current_user(request)
    _own_student(user, student_id)
    student = models.get_student(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    query = str(role_id) if role_id is not None else (external_id.strip() or None)
    if not query:
        raise HTTPException(status_code=400, detail="Provide role_id or external_id")
    try:
        return match_explain.role_match_breakdown(student, query)
    except match_explain.MatchExplainError as e:
        raise _breakdown_or_http(e)


@app.get("/api/students/{student_id}/jobs/recent/{fingerprint}/breakdown")
def api_job_match_breakdown(student_id: int, fingerprint: str, request: Request,
                            location: str = "", country: str = "", market: str = "",
                            limit: int = 10):
    """Read-only decomposition of one jobs-feed row's match_pct badge, rebuilt
    from the exact normalized record the student saw (same feed cache key, same
    scoring context), with components + labelled cap/rounding lines summing
    EXACTLY to the stored match_pct. Missing external data stays unknown."""
    user = _current_user(request)
    _own_student(user, student_id)
    student = models.get_student(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    try:
        return match_explain.job_match_breakdown(
            student, fingerprint, location=location, country=country, market=market,
            limit=max(1, min(int(limit), 16)))
    except match_explain.MatchExplainError as e:
        raise _breakdown_or_http(e)


# ------------------------------------------------------------------ public verified-skills profile

@app.get("/api/public/verified/{student_id}")
def api_public_verified(student_id: int):
    """Read-only, no-auth snapshot of a student's VERIFIED skills. Only served
    when the student has explicitly enabled sharing; verification evidence is
    the assessment-pass date, never self-reported claims."""
    student = models.get_student(student_id)
    if not student or not student.get("share_public"):
        raise HTTPException(status_code=404, detail="Profile not shared")
    role = student.get("target_role")
    return {
        "student_id": student["id"],
        "name": student["name"],
        "university": student["university"],
        "target_role": {"title": role["title"], "company": role.get("company_name")} if role else None,
        "verified_skills": [
            {"skill_id": v["skill_id"], "name": v["name"], "category": v.get("category"),
             "level": v["level"], "verified_at": v.get("verified_at")}
            for v in student["verified_skills"]
        ],
    }


# ------------------------------------------------------------------ university

def _admin_cohort_students(user):
    """Students belonging to the University Admin's own cohort.

    Scoped to the admin's university (case-insensitive) so one admin never sees
    another institution's students â€” and never individual records. Students with an
    empty/NULL university (independent learners) are excluded from the cohort.
    """
    mine = (user.get("university") or "").strip().lower()
    out = []
    for s in models.list_students():
        uni = (s.get("university") or "").strip()
        if not uni:
            continue
        if mine and uni.strip().lower() != mine:
            continue
        out.append(s)
    return out


@app.get("/api/university/cohort")
def api_university_cohort(request: Request):
    user = _current_user(request)
    _require_roles(user, "University Admin")
    students = _admin_cohort_students(user)
    return {
        "university": user.get("university") or "",
        "student_count": len(students),
        "confirmed_count": sum(1 for s in students if s.get("cohort_confirmed")),
        "min_cohort_size": MIN_COHORT_SIZE,
        # anonymized â€” never names/emails; only index + confirmation status
        "students": [{"index": i + 1, "confirmed": bool(s.get("cohort_confirmed"))}
                     for i, s in enumerate(students)],
    }


@app.post("/api/university/cohort/confirm")
def api_university_confirm(request: Request):
    user = _current_user(request)
    _require_roles(user, "University Admin")
    mine = (user.get("university") or "").strip().lower()
    with get_cursor() as conn:
        if mine:
            conn.execute(
                "UPDATE students SET cohort_confirmed=1 WHERE university IS NOT NULL "
                "AND LOWER(TRIM(university))=?", (mine,))
        else:
            conn.execute(
                "UPDATE students SET cohort_confirmed=1 WHERE university IS NOT NULL "
                "AND LENGTH(TRIM(university))>0")
    return api_university_cohort(request)


@app.get("/api/university/stats")
def api_university_stats(request: Request):
    user = _current_user(request)
    _require_roles(user, "University Admin")
    students = _admin_cohort_students(user)
    confirmed = sum(1 for s in students if s.get("cohort_confirmed"))
    if confirmed < MIN_COHORT_SIZE:
        return {"rule": {"min_cohort_size": MIN_COHORT_SIZE, "satisfied": False,
                         "student_count": len(students), "confirmed_count": confirmed},
                "stats": None,
                "message": f"Not enough confirmed students to compute statistics (need at least {MIN_COHORT_SIZE})."}
    analysis_rows = []
    for s in students:
        if not s.get("cohort_confirmed"):
            continue
        a = matching.analyze_student(s["id"])
        if a:
            analysis_rows.append(a)

    skill_stats = {}
    for a in analysis_rows:
        for gap in a["skill_gaps"]:
            key = gap["skill_name"]
            entry = skill_stats.setdefault(key, {"skill_name": key, "category": gap.get("category"),
                                                 "count": 0, "strong": 0, "gap": 0, "missing": 0})
            entry["count"] += 1
            entry[gap["status"]] += 1

    ordered = list(skill_stats.values())
    for e in ordered:
        e["need_improvement_pct"] = round((e["gap"] + e["missing"]) / e["count"] * 100, 1) if e["count"] else 0
    ordered = sorted(ordered, key=lambda e: -e["need_improvement_pct"])

    avg_scores = [a["match_score"] for a in analysis_rows]
    cohort_ids = [s["id"] for s in students if s.get("cohort_confirmed")]
    return {
        "rule": {"min_cohort_size": MIN_COHORT_SIZE, "satisfied": True,
                 "student_count": len(students), "confirmed_count": confirmed},
        "university": user.get("university") or "",
        "student_count": len(students),
        "with_target_role": len(analysis_rows),
        "average_match_score": round(sum(avg_scores) / len(avg_scores), 1) if avg_scores else 0,
        "skill_stats": ordered,
        "verified_skills_total": _count_verified(cohort_ids),
        "assessments_total": _count_assessments(cohort_ids),
    }


def _count_verified(student_ids=None):
    from .database import get_cursor
    with get_cursor() as c:
        if student_ids:
            marks = ",".join("?" for _ in student_ids)
            return c.execute(f"SELECT COUNT(*) AS n FROM verified_skills WHERE student_id IN ({marks})",
                             list(student_ids)).fetchone()["n"]
        return c.execute("SELECT COUNT(*) AS n FROM verified_skills").fetchone()["n"]


def _count_assessments(student_ids=None):
    if not student_ids:
        return len(models.list_assessment_attempts())
    return sum(len(models.list_assessment_attempts(student_id=sid)) for sid in student_ids)


# ------------------------------------------------------------------ static frontend

def _mount_frontend():
    dist = Path(FRONTEND_DIST)
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and str(candidate).startswith(str(dist.resolve())):
            return FileResponse(str(candidate))
        index = dist / "index.html"
        if index.is_file():
            return FileResponse(str(index))
        return {"service": "SkillBridge API",
                "frontend": "run `npm run build` in frontend/ or use start.sh"}


_mount_frontend()
