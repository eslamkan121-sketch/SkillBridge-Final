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

_PBKDF2_ITERATIONS = 160_000

GOOGLE_CLIENT_ID = os.environ.get("SKILLBRIDGE_GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("SKILLBRIDGE_GOOGLE_CLIENT_SECRET", "")
# When real Google credentials are absent, a clearly-labelled demo identity
# provider can stand in so the flow stays demoable. Real OAuth uses Authlib.
DEMO_GOOGLE = os.environ.get("SKILLBRIDGE_GOOGLE_DEMO", "1" if not GOOGLE_CLIENT_ID else "0") == "1"

RESET_TTL_HOURS = int(os.environ.get("SKILLBRIDGE_RESET_TTL_HOURS", "1"))


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


def utcnow_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def reset_expiry_iso():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=RESET_TTL_HOURS)).strftime("%Y-%m-%d %H:%M:%S")


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