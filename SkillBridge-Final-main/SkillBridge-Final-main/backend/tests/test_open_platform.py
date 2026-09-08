"""Req 1 — Open platform: university is optional for Students (independent
learners), an Education Level field is collected, and independent learners are
excluded from university (institution) views."""
from app import models


def test_student_can_signup_without_university(client):
    """A Student may sign up with no university (independent learner) and must
    provide an education level. University is no longer mandatory for Students."""
    r = client.post("/api/auth/signup", json={
        "email": "indie@student.edu", "password": "supersecret1",
        "display_name": "Indie Learner", "role": "Student",
        "education_level": "Self-taught/Independent", "location": "London"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["role"] == "Student"
    assert not (data.get("university") or "").strip()
    assert data.get("education_level") == "Self-taught/Independent"


def test_independent_learner_has_no_university_on_record(client):
    """The stored Student record for an independent learner has no university,
    so the UI can render 'Independent learner' instead of a blank line."""
    r = client.post("/api/auth/signup", json={
        "email": "indie2@student.edu", "password": "supersecret1",
        "display_name": "Indie Two", "role": "Student",
        "education_level": "Undergraduate", "location": "Manchester"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["role"] == "Student"
    assert not (me.get("university") or "").strip()
    assert me.get("education_level") == "Undergraduate"
    # resolve to the student record so the UI can render 'Independent learner'
    student = models.get_student_by_user(me["id"])
    assert student is not None
    assert not (student.get("university") or "").strip()
    assert student.get("education_level") == "Undergraduate"


def test_undergrad_vs_grad_field_is_distinct(client):
    """Two students with different education levels keep distinct values — the
    field genuinely differentiates undergrad and graduate students."""
    for email, lvl in [("ug@student.edu", "Undergraduate"), ("pg@student.edu", "Graduate")]:
        r = client.post("/api/auth/signup", json={
            "email": email, "password": "supersecret1",
            "display_name": email.split("@")[0], "role": "Student",
            "education_level": lvl, "location": "Leeds"})
        assert r.status_code == 200, r.text
        token = r.json()["token"]
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert me.get("education_level") == lvl


def test_university_admin_still_requires_university(client):
    """Making university optional for Students must not loosen it for University
    Admin accounts, which remain institution-scoped."""
    r = client.post("/api/auth/signup", json={
        "email": "no-dept@univ.edu", "password": "supersecret1",
        "display_name": "No Dept", "role": "University Admin",
        "education_level": "Graduate", "location": "Dubai"})
    assert r.status_code == 400


def test_company_signup_ignores_student_fields(client):
    """Company signup is unaffected by the new student-only fields."""
    r = client.post("/api/auth/signup", json={
        "email": "acme@company.com", "password": "supersecret1",
        "display_name": "Acme", "role": "Company", "industry": "AI / Software",
        "location": "London"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "Company"
