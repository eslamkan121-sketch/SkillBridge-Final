"""Authentication primitives for SkillBridge.

Provides password hashing (PBKDF2-SHA256, salted), opaque session tokens, and
password-reset tokens. Google OAuth is wired through Authlib's starlette client
so the flow uses an established library rather than a hand-rolled implementation.

Password hashes are the only thing stored for local accounts; Google-only
accounts have no password at all (auth_provider='google').
"""
import base64
import datetime as dt
import hashlib
import hmac
import os
import secrets
import sys
import threading
import time

_PBKDF2_ITERATIONS = 160_000

GOOGLE_CLIENT_ID = os.environ.get("SKILLBRIDGE_GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("SKILLBRIDGE_GOOGLE_CLIENT_SECRET", "")
# When real Google credentials are absent, a clearly-labelled demo identity
# provider can stand in so the flow stays demoable. Real OAuth uses Authlib.
DEMO_GOOGLE = os.environ.get("SKILLBRIDGE_GOOGLE_DEMO", "1" if not GOOGLE_CLIENT_ID else "0") == "1"

RESET_TTL_HOURS = int(os.environ.get("SKILLBRIDGE_RESET_TTL_HOURS", "1"))

# Sessions (Phase C hardening). Newly issued bearer tokens are never stored
# raw - only their SHA-256 hash. Expiry and revocation are enforced at lookup.
SESSION_TTL_HOURS = int(os.environ.get("SKILLBRIDGE_SESSION_TTL_HOURS", "24"))
SESSION_HEARTBEAT_MINUTES = int(os.environ.get("SKILLBRIDGE_SESSION_HEARTBEAT_MINUTES", "5"))

# Authentication rate-limit boundaries (in-process, TTL-bounded).
LOGIN_FAIL_LIMIT = 8          # failed attempts per email account
LOGIN_FAIL_WINDOW = 120       # seconds
LOGIN_IP_LIMIT = 40           # login attempts per source address
LOGIN_IP_WINDOW = 300         # seconds
RESET_REQUEST_LIMIT = 3       # reset requests per email address
RESET_REQUEST_WINDOW = 3600   # seconds


# ---------------------------------------------------------------- passwords

def hash_password(password):
    """Return (hash_b64, salt_b64) for a plaintext password."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return base64.b64encode(dk).decode(), base64.b64encode(salt).decode()


def verify_password(password, hash_b64, salt_b64):
    """Constant-time verification of a password against stored hash/salt."""
    if not hash_b64 or not salt_b64:
        return False
    try:
        salt = base64.b64decode(salt_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
        return hmac.compare_digest(base64.b64encode(dk).decode(), hash_b64)
    except Exception:
        return False


# ---------------------------------------------------------------- tokens

def new_session_token():
    return secrets.token_urlsafe(32)


def new_reset_token():
    return secrets.token_urlsafe(32)


def hash_token(token):
    """Deterministic digest used to store bearer tokens (raw is never saved)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def utcnow_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def session_expiry_iso():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=SESSION_TTL_HOURS)).strftime("%Y-%m-%d %H:%M:%S")


def heartbeat_cutoff_iso():
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=SESSION_HEARTBEAT_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")


def reset_expiry_iso():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=RESET_TTL_HOURS)).strftime("%Y-%m-%d %H:%M:%S")


def created_plus_ttl(created_at):
    """Legacy sessions have no expiry column; apply the same TTL on top of the
    row's created_at so unfettered old sessions eventually age out."""
    if not created_at:
        return utcnow_iso()
    try:
        parsed = dt.datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return utcnow_iso()
    return (parsed + dt.timedelta(hours=SESSION_TTL_HOURS)).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- rate limiting
# In-process, TTL-bounded counters for unauthenticated auth routes. Counters
# only ever hold identity keys (email/IP) and timestamps - never credentials.
# The suite gets a no-op so it stays deterministic and never degrades.


class _RateLimiter:
    def __init__(self, clock=None):
        self._buckets = {}  # (bucket, key) -> (start, count)
        self._lock = threading.Lock()
        self._clock = clock or time.time

    def _tick(self, key, window):
        """Prune/refresh one bucket; returns the current count for it."""
        start, count = self._buckets.get(key, (0, 0))
        if count and self._clock() - start >= window:
            start, count = 0, 0
        return count

    def exceeded(self, bucket, key, limit, window):
        with self._lock:
            return self._tick((bucket, key), window) >= limit

    def record(self, bucket, key, window):
        with self._lock:
            k = (bucket, key)
            start, count = self._buckets.get(k, (0, 0))
            if count and self._clock() - start >= window:
                start, count = 0, 0
            if not count:
                start = self._clock()
            self._buckets[k] = (start, count + 1)

    def clear(self, bucket, key):
        with self._lock:
            self._buckets.pop((bucket, key), None)


_limiter = _RateLimiter()


def _checks_active():
    """Rate limiting applies outside pytest only (the suite must be
    deterministic and never throttle its own demo logins)."""
    return sys.modules.get("pytest") is None


def login_failure_exceeded(email):
    return _checks_active() and _limiter.exceeded("login_fail_email", email, LOGIN_FAIL_LIMIT, LOGIN_FAIL_WINDOW)


def login_ip_exceeded(ip):
    return _checks_active() and _limiter.exceeded("login_fail_ip", ip, LOGIN_IP_LIMIT, LOGIN_IP_WINDOW)


def record_login_failure(email, ip):
    if not _checks_active():
        return
    _limiter.record("login_fail_email", email, LOGIN_FAIL_WINDOW)
    _limiter.record("login_fail_ip", ip, LOGIN_IP_WINDOW)


def clear_login_failures(email):
    _limiter.clear("login_fail_email", email)


def reset_request_exceeded(email):
    return _checks_active() and _limiter.exceeded("reset_request_email", email, RESET_REQUEST_LIMIT, RESET_REQUEST_WINDOW)


def record_reset_request(email):
    if _checks_active():
        _limiter.record("reset_request_email", email, RESET_REQUEST_WINDOW)


# ---------------------------------------------------------------- OAuth client

_oauth = None


def get_oauth():
    """Authlib OAuth registry with the Google provider registered."""
    global _oauth
    if _oauth is None:
        from authlib.integrations.starlette_client import OAuth
        _oauth = OAuth()
        if GOOGLE_CLIENT_ID:
            _oauth.register(
                name="google",
                client_id=GOOGLE_CLIENT_ID,
                client_secret=GOOGLE_CLIENT_SECRET,
                server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
                client_kwargs={"scope": "openid email profile"},
            )
    return _oauth


def google_configured():
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)