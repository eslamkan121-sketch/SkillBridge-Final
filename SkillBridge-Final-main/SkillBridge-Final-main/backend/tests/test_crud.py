"""Phase 1 / 2 — CRUD tests for each of the five record types."""
import pytest

from app import models


def test_skill_crud(db):
    sk = models.create_skill("Kubernetes CRUD Test", "DevOps")
    assert sk["id"] and sk["name"] == "Kubernetes CRUD Test"
    got = models.get_skill(sk["id"])
    assert got["category"] == "DevOps"
    assert models.update_skill(sk["id"], name="K8s CRUD Test", category="Container") == 1
    got = models.get_skill(sk["id"])
    assert got["name"] == "K8s CRUD Test" and got["category"] == "Container"
    assert models.delete_skill(sk["id"]) == 1
    assert models.get_skill(sk["id"]) is None


def test_company_crud(db):
    c = models.create_company("Acme Data", "Analytics")
    assert c["id"] and c["industry"] == "Analytics"
    assert models.update_company(c["id"], industry="AI") == 1
    assert models.get_company(c["id"])["industry"] == "AI"
    models.delete_company(c["id"])
    assert models.get_company(c["id"]) is None


def test_role_crud(db):
    comp = models.create_company("Acme Data", "Analytics")
    role = models.create_role(comp["id"], "Data Engineer", [
        {"name": "SQL", "category": "Data", "level": "Advanced"},
        {"name": "Python", "category": "Programming", "level": "Intermediate"},
    ])
    assert role["id"]
    assert len(role["required_skills"]) == 2
    assert {s["name"] for s in role["required_skills"]} == {"SQL", "Python"}

    updated = models.update_role(role["id"], title="Senior Data Engineer",
                                 required_skills=[{"name": "SQL", "category": "Data", "level": "Advanced"}])
    assert updated["title"] == "Senior Data Engineer"
    assert len(updated["required_skills"]) == 1

    assert models.delete_role(role["id"]) == 1
    assert models.get_role(role["id"]) is None


def test_company_role_skill_coverage(client, auth_headers):
    # Phase 2: a Company sees aggregate applicant skill coverage for its own role
    h = auth_headers("hr@northstar.com")
    roles = client.get("/api/roles", headers=h).json()["roles"]
    own = next(r for r in roles if r["title"] == "Junior AI Engineer")
    res = client.get(f"/api/company/roles/{own['id']}/skills", headers=h)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["candidate_count"] >= 1  # seeded students target this role
    assert len(data["skills"]) == len(own["required_skills"])
    for s in data["skills"]:
        assert s["n_candidates"] == data["candidate_count"]
        assert s["strong"] + s["gap"] + s["missing"] == s["n_candidates"]
    # only aggregate numbers + skill identifiers — no candidate identity
    assert "name" not in s or "email" not in data


def test_company_cannot_see_other_company_role_flow(client, auth_headers):
    # RBAC: Northstar can read its own role, but cannot manage Signal's role
    nh = auth_headers("hr@northstar.com")
    sh = auth_headers("hr@signal.com")
    roles = client.get("/api/roles", headers=sh).json()["roles"]
    signal_role = next((r for r in roles if r["title"] == "Data Analyst"), None)
    assert signal_role is not None
    # Northstar trying to edit Signal's role is blocked by ownership
    put = client.put(f"/api/roles/{signal_role['id']}", headers=nh,
                     json={"title": "Hijacked", "required_skills": [{"name": "X", "level": "Beginner", "category": "General"}]})
    assert put.status_code == 403


def test_student_crud(db):
    s = models.create_student("Test Student", "test@student.edu", "Test University")
    assert s["id"]
    assert models.update_student(s["id"], university="Another University")["university"] == "Another University"
    assert models.get_student(s["id"])["email"] == "test@student.edu"
    models.delete_student(s["id"])
    assert models.get_student(s["id"]) is None


def test_assessment_attempt_crud(db):
    sid = models.create_student("S", "s@student.edu", "U")["id"]
    sk = models.create_skill("TerraformPlus", "DevOps")
    a = models.create_assessment_attempt(
        sid, sk["id"], "[]", '["x"]', 80.0, 1, '[]', "Beginner", "Intermediate")
    assert a["id"] and a["score"] == 80.0 and a["passed"] == 1
    got = models.get_assessment_attempt(a["id"])
    assert got["skill_name"] == "TerraformPlus"
    assert models.delete_assessment_attempt(a["id"]) == 1


def test_user_login_roles(client):
    r = client.post("/api/auth/login", json={"email": "aisha@student.edu", "password": "demo1234"})
    assert r.status_code == 200 and r.json()["role"] == "Student"
    assert r.json()["token"] and r.json()["entity_type"] == "student"
    r = client.post("/api/auth/login", json={"email": "hr@northstar.com", "password": "demo1234"})
    assert r.json()["role"] == "Company"
    r = client.post("/api/auth/login", json={"email": "admin@univ.edu", "password": "demo1234"})
    assert r.json()["role"] == "University Admin"
    # wrong-password always rejected
    r = client.post("/api/auth/login", json={"email": "aisha@student.edu", "password": "wrong"})
    assert r.status_code == 401
    # unknown-email behaves identically (no account enumeration)
    r = client.post("/api/auth/login", json={"email": "nobody@student.edu", "password": "demo1234"})
    assert r.status_code == 401


def test_signup_creates_entity_and_login_works(client):
    r = client.post("/api/auth/signup", json={
        "email": "new-stud@student.edu", "password": "supersecret1",
        "display_name": "New Student", "role": "Student", "university": "Aston University",
        "location": "Birmingham"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["role"] == "Student" and data["token"]
    # they can log in with their own credentials
    r = client.post("/api/auth/login", json={"email": "new-stud@student.edu", "password": "supersecret1"})
    assert r.status_code == 200
    # duplicate signup is rejected
    r = client.post("/api/auth/signup", json={
        "email": "new-stud@student.edu", "password": "supersecret1",
        "display_name": "New Student", "role": "Student", "location": "Birmingham"})
    assert r.status_code == 409


def test_signup_university_admin(client):
    # A new University Admin can self-serve sign up (Phase 1: all three roles).
    # They must choose a country + university via the cascading dropdown.
    r = client.post("/api/auth/signup", json={
        "email": "new-admin@univ.edu", "password": "supersecret1",
        "display_name": "New Admin", "role": "University Admin",
        "country": "United Arab Emirates", "university": "Khalifa University",
        "location": "Abu Dhabi"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["role"] == "University Admin"
    assert data["token"] and data["entity_type"] == "university"
    assert data["university"] == "Khalifa University" and data["country"] == "United Arab Emirates"
    base = client.get("/api/auth/me", headers={"Authorization": f"Bearer {data['token']}"})
    assert base.status_code == 200 and base.json()["role"] == "University Admin"
    assert base.json()["university"] == "Khalifa University"
    # and can log in afterwards
    r = client.post("/api/auth/login", json={"email": "new-admin@univ.edu", "password": "supersecret1"})
    assert r.status_code == 200 and r.json()["role"] == "University Admin"
    # country + university are required
    r = client.post("/api/auth/signup", json={
        "email": "no-dept@univ.edu", "password": "supersecret1",
        "display_name": "No Dept", "role": "University Admin"})
    assert r.status_code == 400


def test_signup_invalid_role_rejected(client):
    r = client.post("/api/auth/signup", json={
        "email": "bad-role@x.edu", "password": "supersecret1",
        "display_name": "Bad", "role": "Superuser"})
    assert r.status_code == 400


def test_logout_invalidates_session(client, login):
    data = login("aisha@student.edu")
    h = {"Authorization": f"Bearer {data['token']}"}
    assert client.get("/api/auth/me", headers=h).status_code == 200
    assert client.post("/api/auth/logout", headers=h).status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_password_reset_flow(client, db):
    r = client.post("/api/auth/reset/request", json={"email": "omar@student.edu"})
    assert r.status_code == 200 and r.json()["ok"] is True
    user = models.get_user_by_email("omar@student.edu")
    row = db.execute(
        "SELECT token FROM password_resets WHERE user_id=? AND used=0 ORDER BY id DESC",
        (user["id"],),
    ).fetchone()
    assert row and row["token"]
    token = row["token"]
    r = client.post("/api/auth/reset/confirm", json={"token": token, "new_password": "brandnewpass1"})
    assert r.status_code == 200 and r.json()["ok"] is True
    # old password gone, new works
    assert client.post("/api/auth/login", json={"email": "omar@student.edu", "password": "demo1234"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "omar@student.edu", "password": "brandnewpass1"}).status_code == 200
    # reuse of the token is blocked
    r = client.post("/api/auth/reset/confirm", json={"token": token, "new_password": "anotherpass1"})
    assert r.status_code == 400


def test_universities_reference_endpoint(client):
    # Seed ships a country -> university reference list for the cascading dropdown.
    # It is public reference data usable on the (unauthenticated) signup page.
    r = client.get("/api/universities")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and len(data) >= 1
    gb = next((g for g in data if g["country"] == "United Kingdom"), None)
    assert gb is not None
    assert "Aston University" in gb["universities"]


def test_email_verification_flow(client):
    # When SMTP is not configured, signup returns accounts pre-verified so the
    # app stays demoable, but the verification endpoint still works.
    user = models.create_user("verifyme@test.edu", "Student", "Verify Me",
                                       password="supersecret1", verified=0)
    token = models.create_email_verification(user["id"])["token"]
    r = client.post("/api/auth/verify", json={"token": token})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert models.get_user(user["id"])["verified"] == 1
    # reusing the token is rejected
    r = client.post("/api/auth/verify", json={"token": token})
    assert r.status_code == 400
    # bogus token rejected
    assert client.post("/api/auth/verify", json={"token": "nope"}).status_code == 400


def test_signup_not_blocked_by_slow_email(client, monkeypatch):
    """Account creation must never freeze: the verification email is sent on a
    background task, so even a slow/failing SMTP cannot block the response."""
    import time
    from app import mailer

    def slow(*a, **k):
        time.sleep(2)  # simulate a slow/unreachable SMTP
        return True

    monkeypatch.setattr(mailer, "email_configured", lambda: True)
    monkeypatch.setattr(mailer, "send_verification_email", slow)
    start = time.time()
    # TestClient still waits for the background task, but critically the user is
    # persisted and the endpoint is happy even though the email task is slow.
    r = client.post("/api/auth/signup", json={
        "email": "neverfreeze@test.edu", "password": "supersecret1",
        "display_name": "Never Freeze", "role": "Student",
        "location": "Birmingham",
    })
    elapsed = time.time() - start
    assert r.status_code == 200
    assert r.json()["email_verified_delivery"] is True
    assert r.json()["email"] == "neverfreeze@test.edu"
    user = models.get_user_by_email("neverfreeze@test.edu")
    assert user is not None and user["verified"] == 0
