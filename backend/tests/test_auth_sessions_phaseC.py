"""Phase C (approved Slice 1): authentication / session hardening.

Contract verified here:
- new signups store only a PBKDF2 hash; no plaintext in users.password;
- legacy plaintext accounts still sign in AND are upgraded in the same login;
- wrong credentials never upgrade a legacy row;
- sessions live in auth_sessions as a SHA-256 token hash only (raw never saved);
- expiry, logout revocation, cross-user rejection, and reset revocation work;
- legacy sessions table keeps working during the compatibility window;
- login/reset rate limiting trips on the safe per-account/IP dimensions and is
  inert under the test suite by default.
"""
import hashlib
import sqlite3

import pytest

import app.auth as auth_mod
import app.database as database
import app.models as models


def _latest_auth_session():
    with database.get_cursor() as c:
        row = c.execute(
            "SELECT token_hash, expires_at, revoked_at, last_used_at FROM auth_sessions "
            "ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row)


def _insert_legacy_user(email, password, role="Student", display_name="Legacy User"):
    with database.get_cursor() as c:
        c.execute(
            "INSERT INTO users (email, password, role, display_name) VALUES (?,?,?,?)",
            (email, password, role, display_name))
        uid = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
    if role == "Student":
        models.create_student(display_name, email, "Cairo University", user_id=uid)
    return uid


# ---------------------------------------------------------------- passwords

def test_signup_stores_hash_not_plaintext(client):
    r = client.post("/api/auth/signup", json={
        "email": "newc@student.edu", "password": "correct horse battery",
        "display_name": "New C", "role": "Student", "location": "Cairo",
    })
    assert r.status_code == 200, r.text
    with database.get_cursor() as c:
        row = c.execute(
            "SELECT password, password_hash, password_salt FROM users WHERE email=?",
            ("newc@student.edu",)).fetchone()
    assert row["password"] == ""            # never plaintext
    assert row["password_hash"] and row["password_salt"]
    assert row["password_hash"] not in ("", "correct horse battery")


def test_legacy_plaintext_login_upgrades_in_place(client):
    _insert_legacy_user("legacy2@example.com", "sekret123")
    r = client.post("/api/auth/login", json={"email": "legacy2@example.com", "password": "sekret123"})
    assert r.status_code == 200, r.text
    with database.get_cursor() as c:
        row = c.execute(
            "SELECT password, password_hash, password_salt FROM users WHERE email=?",
            ("legacy2@example.com",)).fetchone()
    assert row["password"] == ""            # plaintext cleared
    assert row["password_hash"] and row["password_salt"]
    # second login uses the hash path and still works
    r2 = client.post("/api/auth/login", json={"email": "legacy2@example.com", "password": "sekret123"})
    assert r2.status_code == 200


def test_legacy_wrong_password_does_not_upgrade(client):
    _insert_legacy_user("legacy3@example.com", "sekret123")
    r = client.post("/api/auth/login", json={"email": "legacy3@example.com", "password": "wrong"})
    assert r.status_code == 401
    with database.get_cursor() as c:
        row = c.execute(
            "SELECT password, password_hash FROM users WHERE email=?",
            ("legacy3@example.com",)).fetchone()
    assert row["password"] == "sekret123"   # untouched: no upgrade on failure
    assert not row["password_hash"]


def test_wrong_password_hash_account_returns_401(client):
    r = client.post("/api/auth/login", json={"email": "aisha@student.edu", "password": "not-the-password"})
    assert r.status_code == 401


def test_me_payload_never_exposes_password_material(client, auth_headers):
    h = auth_headers("aisha@student.edu")
    r = client.get("/api/auth/me", headers=h)
    assert r.status_code == 200
    body = r.json()
    for forbidden in ("password", "password_hash", "password_salt", "token"):
        assert forbidden not in body


# ---------------------------------------------------------------- sessions

def test_session_stores_only_token_hash(client, auth_headers):
    token = auth_headers("aisha@student.edu")["Authorization"].split()[-1]
    row = _latest_auth_session()
    assert row["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert row["token_hash"] != token
    assert _latest_auth_session()["expires_at"] and _latest_auth_session()["last_used_at"]
    with database.get_cursor() as c:
        blob = "".join(str(x) for (x,) in c.execute("SELECT token_hash FROM auth_sessions").fetchall())
    assert token not in blob            # the raw bearer token is never persisted


def test_expired_session_rejected(client, auth_headers):
    h = auth_headers("aisha@student.edu")
    assert client.get("/api/auth/me", headers=h).status_code == 200
    with database.get_cursor() as c:
        c.execute("UPDATE auth_sessions SET expires_at='2000-01-01 00:00:00'")
    assert client.get("/api/auth/me", headers=h).status_code == 401
    assert "Session expired" in client.get("/api/auth/me", headers=h).json()["detail"]


def test_logout_revokes_session(client, auth_headers):
    h = auth_headers("aisha@student.edu")
    assert client.get("/api/auth/me", headers=h).status_code == 200
    r = client.post("/api/auth/logout", headers=h)
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_cross_user_token_rejected(client, auth_headers, student_id):
    aisha_h = auth_headers("aisha@student.edu")
    yara = client.post("/api/auth/login", json={"email": "yara@student.edu", "password": "demo1234"})
    yara_id = yara.json()["student"]["id"]
    assert yara_id != student_id
    r = client.get(f"/api/students/{yara_id}/role-recommendations", headers=aisha_h)
    assert r.status_code == 403


def test_legacy_session_table_still_acceptable_during_window(db, client):
    with database.get_cursor() as c:
        uid = c.execute("SELECT id FROM users WHERE email=?", ("aisha@student.edu",)).fetchone()["id"]
        c.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", ("legacy-row-token", uid))
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer legacy-row-token"})
    assert r.status_code == 200


def test_reset_confirm_revokes_all_sessions(client, auth_headers):
    h = auth_headers("aisha@student.edu")
    assert client.get("/api/auth/me", headers=h).status_code == 200
    client.post("/api/auth/reset/request", json={"email": "aisha@student.edu"})
    with database.get_cursor() as c:
        reset = c.execute(
            "SELECT token FROM password_resets WHERE user_id=(SELECT id FROM users WHERE email=?) "
            "ORDER BY id DESC LIMIT 1", ("aisha@student.edu",)).fetchone()
    assert reset is not None
    conf = client.post("/api/auth/reset/confirm", json={
        "token": reset["token"], "new_password": "brand-new-secret-99"})
    assert conf.status_code == 200
    # the old session was revoked by the password change
    assert client.get("/api/auth/me", headers=h).status_code == 401
    # old password no longer works; new one does
    old = client.post("/api/auth/login", json={"email": "aisha@student.edu", "password": "demo1234"})
    new = client.post("/api/auth/login", json={"email": "aisha@student.edu", "password": "brand-new-secret-99"})
    assert old.status_code == 401
    assert new.status_code == 200


# ---------------------------------------------------------------- rate limiting

def test_limiter_inert_under_pytest():
    auth_mod.record_login_failure("someone@example.com", "9.9.9.9")
    assert auth_mod.login_failure_exceeded("someone@example.com") is False
    assert auth_mod.login_ip_exceeded("9.9.9.9") is False


def test_per_account_failure_limit(monkeypatch, client):
    monkeypatch.setattr(auth_mod, "_checks_active", lambda: True)
    monkeypatch.setattr(auth_mod, "LOGIN_FAIL_LIMIT", 2)
    monkeypatch.setattr(auth_mod, "LOGIN_FAIL_WINDOW", 9999)
    email = "ratelimited@example.com"
    auth_mod._limiter.clear("login_fail_email", email)
    for _ in range(2):
        assert client.post("/api/auth/login", json={"email": email, "password": "x"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": "x"}).status_code == 429
    auth_mod._limiter.clear("login_fail_email", email)
    assert client.post("/api/auth/login", json={"email": email, "password": "x"}).status_code == 401


def test_per_ip_burst_limit(monkeypatch, client):
    monkeypatch.setattr(auth_mod, "_checks_active", lambda: True)
    monkeypatch.setattr(auth_mod, "LOGIN_IP_LIMIT", 2)
    monkeypatch.setattr(auth_mod, "LOGIN_IP_WINDOW", 9999)
    auth_mod._limiter.clear("login_fail_ip", "9.9.9.9")
    auth_mod._limiter.clear("login_fail_email", "nobody-a@example.com")
    auth_mod._limiter.clear("login_fail_email", "nobody-b@example.com")
    monkeypatch.setattr("app.main._request_ip", lambda request: "9.9.9.9")
    for email in ("nobody-a@example.com", "nobody-b@example.com"):
        assert client.post("/api/auth/login", json={"email": email, "password": "x"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "nobody-c@example.com", "password": "x"}).status_code == 429
    auth_mod._limiter.clear("login_fail_ip", "9.9.9.9")


def test_reset_request_limit(monkeypatch, client):
    monkeypatch.setattr(auth_mod, "_checks_active", lambda: True)
    monkeypatch.setattr(auth_mod, "RESET_REQUEST_LIMIT", 2)
    monkeypatch.setattr(auth_mod, "RESET_REQUEST_WINDOW", 9999)
    email = "resetlimited@example.com"
    auth_mod._limiter.clear("reset_request_email", email)
    for _ in range(2):
        assert client.post("/api/auth/reset/request", json={"email": email}).status_code == 200
    assert client.post("/api/auth/reset/request", json={"email": email}).status_code == 429
    auth_mod._limiter.clear("reset_request_email", email)


def test_successful_login_clears_failure_bucket(monkeypatch, client):
    monkeypatch.setattr(auth_mod, "_checks_active", lambda: True)
    monkeypatch.setattr(auth_mod, "LOGIN_FAIL_LIMIT", 2)
    monkeypatch.setattr(auth_mod, "LOGIN_FAIL_WINDOW", 9999)
    email = "limit-clear@example.com"
    auth_mod._limiter.clear("login_fail_email", email)
    auth_mod._limiter.clear("login_fail_ip", "testclient")
    for _ in range(2):
        assert client.post("/api/auth/login", json={"email": email, "password": "x"}).status_code == 401
    assert auth_mod.login_failure_exceeded(email) is True
    auth_mod.clear_login_failures(email)
    assert auth_mod.login_failure_exceeded(email) is False
    assert client.post("/api/auth/login", json={"email": email, "password": "x"}).status_code == 401
    auth_mod._limiter.clear("login_fail_ip", "testclient")


# ---------------------------------------------------------------- migration 0002

def test_migration_0002_on_fresh_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "c.db"))
    conn.row_factory = sqlite3.Row
    database.set_db_for_test(conn)
    try:
        database.init_db()
        applied = [m["migration_id"] for m in database.applied_migrations()]
        assert applied == ["0001_baseline_implied_schema", "0002_auth_sessions",
                           "0003_canonical_roles", "0004_esco_import",
                           "0005_company_role_mapping", "0006_saved_jobs_tracker", "0007_role_view_events", "0008_job_link_reports", "0009_copilot_config", "0010_copilot_onboarding", "0011_mentor_keys", "0012_tutor_memory"]
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "auth_sessions" in tables
        assert database.run_migrations() == []
    finally:
        database.set_db_for_test()
        conn.close()


def test_migration_0002_upgrades_pre_0002_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "old.db"))
    conn.row_factory = sqlite3.Row
    database.set_db_for_test(conn)
    try:
        pre_c = [m for m in database.MIGRATIONS
                 if m["id"] not in ("0002_auth_sessions", "0003_canonical_roles",
                                    "0004_esco_import", "0005_company_role_mapping",
                                    "0006_saved_jobs_tracker",
                                    "0007_role_view_events", "0008_job_link_reports", "0009_copilot_config", "0010_copilot_onboarding", "0011_mentor_keys", "0012_tutor_memory")]
        database.run_migrations(conn=conn, migrations=pre_c)
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "auth_sessions" not in tables
        pending = database.run_migrations()          # lockstep set now adds 0002..0011
        assert pending == ["0002_auth_sessions", "0003_canonical_roles",
                           "0004_esco_import", "0005_company_role_mapping",
                           "0006_saved_jobs_tracker", "0007_role_view_events", "0008_job_link_reports", "0009_copilot_config", "0010_copilot_onboarding", "0011_mentor_keys", "0012_tutor_memory"]
        assert "auth_sessions" in {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        database.set_db_for_test()
        conn.close()


def test_migration_0002_backs_out_on_failure(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "c2.db"))
    conn.row_factory = sqlite3.Row
    database.set_db_for_test(conn)
    try:
        def bad(c):
            c.execute("CREATE TABLE IF NOT EXISTS oops (id INTEGER PRIMARY KEY)")
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            database.run_migrations(conn=conn, migrations=database.MIGRATIONS + [
                {"id": "9999_bad", "apply": bad}])
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "oops" not in tables and "auth_sessions" not in tables
        assert database.run_migrations() == ["0001_baseline_implied_schema",
                                             "0002_auth_sessions", "0003_canonical_roles",
                                             "0004_esco_import", "0005_company_role_mapping",
                                             "0006_saved_jobs_tracker",
                                             "0007_role_view_events", "0008_job_link_reports", "0009_copilot_config", "0010_copilot_onboarding", "0011_mentor_keys", "0012_tutor_memory"]
    finally:
        database.set_db_for_test()
        conn.close()
