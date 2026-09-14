"""Phase Q — unified learning-to-application journey: prepare-for-job readiness.

A student sees one of THEIR OWN live-feed jobs (owner-gated, cache-only
``jobs.peek_feed_job`` locate with the exact ``_student_feed_profile`` feed
coordinates) and gets an honest readiness view: every required skill is
classified against their own verified / self-reported / ``skills``-table rows
by exact canonical name (verified > self_reported > gap > no_path). ``skill_id``
is a REAL skills row id or null, and a name with no skills row is honestly
``no_path`` — never a guessed gap or a fabricated id. Read-only: no feed build,
no cache fork, no snapshot write, no migration.
"""
import pytest

from app import models

JOB = {
    "title": "Machine Learning Engineer",
    "company": "Northstar Labs",
    "url": "https://jobs.example.com/post/2",
    "apply_url": "https://jobs.example.com/apply/2",
    "location": "Birmingham",
    "country": "GB",
    "provider": "adzuna",
    "match_pct": 88.0,
    "listing_status": "live",
    "location_label": "Birmingham, West Midlands, UK",
    "required_skills": ["Python", "Machine Learning", "Docker", "Kubernetes", "Wireframing", "SQL"],
}


# ------------------------------------------------------------------ model: prepare_job_view

def _aisha(db):
    row = next((s for s in models.list_students() if s["name"] == "Aisha Rahman"), None)
    assert row is not None
    return models.get_student(row["id"])


def test_prepare_view_derives_all_four_statuses(db):
    view = models.prepare_job_view(_aisha(db), JOB)
    assert [s["name"] for s in view["skills"]] == JOB["required_skills"]

    by = {s["name"]: s for s in view["skills"]}
    # verified wins even though Python is ALSO self-reported
    assert by["Python"]["status"] == "verified"
    assert by["SQL"]["status"] == "verified"
    assert by["Machine Learning"]["status"] == "self_reported"
    assert by["Docker"]["status"] == "self_reported"
    assert by["Kubernetes"]["status"] == "gap"        # real skills row -> deep-linkable
    assert by["Kubernetes"]["skill_id"] is not None
    assert by["Wireframing"]["status"] == "no_path"   # no skills row -> honest, never a fake gap
    assert by["Wireframing"]["skill_id"] is None


def test_skill_id_is_a_real_db_row_id_or_null(db):
    view = models.prepare_job_view(_aisha(db), JOB)
    by = {s["name"]: s for s in view["skills"]}
    for name in ("Python", "SQL", "Machine Learning", "Docker", "Kubernetes", "Wireframing"):
        row = models.get_skill_by_name(name)
        if name == "Wireframing":
            assert row is None
            assert by[name]["skill_id"] is None
            continue
        assert row is not None, name
        assert by[name]["skill_id"] == row["id"]


def test_verified_precedence_and_evidence_student_level(db):
    view = models.prepare_job_view(_aisha(db), JOB)
    python = next(s for s in view["skills"] if s["name"] == "Python")
    assert python["student_level"] == "Advanced"
    assert python["verified_at"]  # real DB verified_at string
    ml = next(s for s in view["skills"] if s["name"] == "Machine Learning")
    assert ml["student_level"] == "Intermediate"
    assert "verified_at" not in ml
    kubernetes = next(s for s in view["skills"] if s["name"] == "Kubernetes")
    assert "student_level" not in kubernetes
    assert "verified_at" not in kubernetes


def test_canonical_name_resolution_never_fuzzy(db):
    # SYNONYMS turn "ml" into the canonical "Machine Learning" (trusted synonym,
    # not a guess) -> still resolves against aisha's own row.
    view = models.prepare_job_view(_aisha(db), {**JOB, "required_skills": ["ml", "nodejs"]})
    ml = next(s for s in view["skills"] if s["name"] == "ml")
    assert ml["status"] == "self_reported"
    assert ml["skill_id"] == models.get_skill_by_name("Machine Learning")["id"]
    # "nodejs" canonicalizes to the real "Node.js" skills row -> a deep-linkable gap.
    node = next(s for s in view["skills"] if s["name"] == "nodejs")
    assert node["status"] == "gap"
    assert node["skill_id"] == models.get_skill_by_name("Node.js")["id"]


def test_unresolvable_name_is_honestly_no_path(db):
    view = models.prepare_job_view(_aisha(db), {**JOB, "required_skills": ["Wireframing", "Python"]})
    wire = next(s for s in view["skills"] if s["name"] == "Wireframing")
    assert wire["status"] == "no_path"
    assert wire["skill_id"] is None
    assert "student_level" not in wire and "verified_at" not in wire


def test_empty_and_blank_required_skills_yield_empty_list(db):
    assert models.prepare_job_view(_aisha(db), {**JOB, "required_skills": []})["skills"] == []
    assert models.prepare_job_view(_aisha(db), {**JOB, "required_skills": None})["skills"] == []
    view = models.prepare_job_view(_aisha(db), {**JOB, "required_skills": ["", "  "]})
    assert view["skills"] == []


def test_job_block_shape(db):
    view = models.prepare_job_view(_aisha(db), JOB)
    assert view["job"] == {
        "title": "Machine Learning Engineer",
        "company": "Northstar Labs",
        "location_label": "Birmingham, West Midlands, UK",
        "match_pct": 88.0,
        "apply_url": "https://jobs.example.com/apply/2",
        "listing_status": "live",
        "provider": "adzuna",
    }


# ------------------------------------------------------------------ endpoint (monkeypatch the live feed)

def _fake_peek(skills, role, country, location, requisites, market, fingerprint, limit=10, seen=None):
    if seen is not None:
        seen["skills"] = skills
        seen["role"] = role
        seen["country"] = country
        seen["location"] = location
        seen["requisites"] = requisites
        seen["market"] = market
        seen["fingerprint"] = fingerprint
    if fingerprint == "fp-missing":
        return {"found": False, "job": None}
    return {"found": True, "job": {**JOB, "fingerprint": fingerprint}}


@pytest.fixture()
def mock_peek(monkeypatch, client):
    seen = {}
    monkeypatch.setattr("app.main.jobs.peek_feed_job",
                        lambda *a, **k: _fake_peek(*a, seen=seen, **k))
    yield client, seen


@pytest.fixture()
def block_feed_build(monkeypatch, client):
    """The prepare endpoint must NEVER trigger a feed build (locate would warm
    the cache + fetch providers); a locate call here is a contract violation."""
    def boom(*a, **k):
        raise AssertionError("prepare must be cache-only (peek_feed_job), never locate_feed_job")
    monkeypatch.setattr("app.main.jobs.locate_feed_job", boom)
    yield client


def test_prepare_endpoint_reads_own_feed_coordinates(mock_peek, student_id, auth_headers):
    client, seen = mock_peek
    h = auth_headers("aisha@student.edu")
    r = client.get(f"/api/students/{student_id}/jobs/recent/fp-abc/prepare",
                   params={"location": "Birmingham", "country": "GB", "market": "gb"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert seen["fingerprint"] == "fp-abc"
    assert seen["country"] == "GB" and seen["location"] == "Birmingham" and seen["market"] == "gb"
    assert seen["role"] == "Junior AI Engineer"
    assert seen["skills"] == [
        ("Docker", "Beginner", False), ("Git", "Intermediate", False),
        ("Machine Learning", "Intermediate", False), ("Python", "Advanced", False),
        ("SQL", "Advanced", False),
        ("Python", "Advanced", True), ("SQL", "Advanced", True),
    ]
    by = {s["name"]: s for s in body["skills"]}
    assert by["Python"]["status"] == "verified" and by["Kubernetes"]["status"] == "gap"


def test_prepare_endpoint_is_cache_only_never_builds_feed(block_feed_build, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    r = block_feed_build.get(f"/api/students/{student_id}/jobs/recent/fp-abc/prepare", headers=h)
    # Fresh empty feed cache + locate blocked = honest 404; a feed build would
    # have warmed the cache via locate_feed_job and returned 200 here.
    assert r.status_code == 404
    assert "current feed" in r.json()["detail"]


def test_prepare_endpoint_writes_no_snapshot(mock_peek, student_id, auth_headers):
    client, _seen = mock_peek
    h = auth_headers("aisha@student.edu")
    client.get(f"/api/students/{student_id}/jobs/recent/fp-abc/prepare", headers=h)
    client.get(f"/api/students/{student_id}/jobs/recent/fp-abc/prepare", headers=h)
    assert models.list_job_tracker(student_id) == []
    assert models.get_student(student_id)["verified_skills"]  # profile untouched


def test_prepare_unknown_fingerprint_is_404(mock_peek, student_id, auth_headers):
    client, _seen = mock_peek
    r = client.get(f"/api/students/{student_id}/jobs/recent/fp-missing/prepare",
                   headers=auth_headers("aisha@student.edu"))
    assert r.status_code == 404


def test_prepare_owner_matrix(mock_peek, student_id, auth_headers):
    client, _seen = mock_peek
    url = f"/api/students/{student_id}/jobs/recent/fp-abc/prepare"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=auth_headers("omar@student.edu")).status_code == 403
    assert client.get(url, headers=auth_headers("hr@northstar.com")).status_code == 403
    assert client.get(url, headers=auth_headers("admin@univ.edu")).status_code == 403