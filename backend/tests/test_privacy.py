"""Privacy hardening + new features:
- /api/students is an anonymized, university-only cohort index
- individual student records are scoped: university admin cannot read one,
  a company only a student targeting its own role
- /api/roles/{id} only serves the catalog or a company's own roles
- shareable verified-skills public profile (opt-in only)
- persisted learning-path progress
"""


def _h(login, email):
    return {"Authorization": f"Bearer {login(email)['token']}"}


def test_students_list_is_anonymized_and_university_only(client, auth_headers, login):
    headers = _h(login, "admin@univ.edu")
    r = client.get("/api/students", headers=headers)
    assert r.status_code == 200
    blob = str(r.json())
    assert "@" not in blob and "aisha" not in blob.lower()
    assert all(set(s.keys()) == {"id", "university", "target_role_id", "cohort_confirmed"} for s in r.json())
    # students and companies are blocked from the index entirely
    assert client.get("/api/students", headers=_h(login, "aisha@student.edu")).status_code == 403
    assert client.get("/api/students", headers=_h(login, "hr@northstar.com")).status_code == 403
    assert client.get("/api/students").status_code == 401


def test_university_admin_cannot_read_individual_student(client, login):
    headers = _h(login, "admin@univ.edu")
    aisha = login("aisha@student.edu")["student"]["id"]
    assert client.get(f"/api/students/{aisha}", headers=headers).status_code == 403


def test_company_reads_only_students_targeting_own_role(client, login):
    aisha = login("aisha@student.edu")["student"]["id"]
    # Northstar owns Junior AI Engineer, which Aisha targets -> allowed
    north = _h(login, "hr@northstar.com")
    assert client.get(f"/api/students/{aisha}", headers=north).status_code == 200
    # Signal Works does not own that role -> blocked
    signal = _h(login, "hr@signal.com")
    assert client.get(f"/api/students/{aisha}", headers=signal).status_code == 403


def test_role_get_is_scoped_to_catalog_or_own(client, login):
    catalog = client.get("/api/roles/catalog", headers=_h(login, "aisha@student.edu")).json()
    catalog_id = catalog[0]["id"]
    assert catalog_id
    # any student can read catalog (reference) roles
    assert client.get(f"/api/roles/{catalog_id}", headers=_h(login, "aisha@student.edu")).status_code == 200
    # a company's own role is readable by that company
    roles = client.get("/api/roles", headers=_h(login, "hr@northstar.com")).json()["roles"]
    own = next(r for r in roles if r["title"] == "Junior AI Engineer")
    assert client.get(f"/api/roles/{own['id']}", headers=_h(login, "hr@northstar.com")).status_code == 200
    # ... but not by a different company or a student
    assert client.get(f"/api/roles/{own['id']}", headers=_h(login, "hr@signal.com")).status_code == 403
    assert client.get(f"/api/roles/{own['id']}", headers=_h(login, "aisha@student.edu")).status_code == 403


def test_public_profile_is_opt_in_and_verified_only(client, auth_headers, login):
    payload = login("aisha@student.edu")
    sid = payload["student"]["id"]
    headers = {"Authorization": f"Bearer {payload['token']}"}
    # not shared by default
    assert client.get(f"/api/public/verified/{sid}").status_code == 404
    # toggle sharing on, then read the public artifact (no auth header)
    r = client.put(f"/api/students/{sid}", json={"share_public": 1}, headers=headers)
    assert r.status_code == 200 and r.json()["share_public"] == 1
    pub = client.get(f"/api/public/verified/{sid}")
    assert pub.status_code == 200
    data = pub.json()
    assert data["name"] == "Aisha Rahman"
    assert data["university"] == "Aston University"
    assert data["target_role"]["title"] == "Junior AI Engineer"
    assert len(data["verified_skills"]) >= 1
    names = {s["name"] for s in data["verified_skills"]}
    assert "Python" in names and "SQL" in names
    # only evidence-backed verifications appear, never self-reported claims
    blob = str(data)
    assert "Kaggle" not in blob
    # turning it off hides it again
    client.put(f"/api/students/{sid}", json={"share_public": 0}, headers=headers)
    assert client.get(f"/api/public/verified/{sid}").status_code == 404
    # unknown student id -> 404, never a guessable existence leak
    assert client.get("/api/public/verified/9999").status_code == 404


def test_learning_progress_persists(client, student_id, auth_headers, login):
    from app import models, matching
    headers = _h(login, "aisha@student.edu")
    student = models.get_student(student_id)
    gap = matching.gap_skills(student, student["target_role"])[0]
    r = client.post(f"/api/students/{student_id}/learning/generate",
                    json={"skill_id": gap["skill_id"]}, headers=headers)
    assert r.status_code == 200
    n_steps = len((r.json() or {}).get("roadmap", {}).get("steps", []))
    assert n_steps >= 3
    done = [1, 2]
    r = client.post(f"/api/students/{student_id}/learning/{gap['skill_id']}/progress",
                    json={"steps": done + ["bogus", 2]}, headers=headers)
    assert r.status_code == 200
    item = r.json()
    assert item["progress"] == [1, 2]  # deduped, ints only, sorted
    # persisted for future reads
    again = client.get(f"/api/students/{student_id}/learning/{gap['skill_id']}", headers=headers)
    assert again.status_code == 200 and again.json()["progress"] == [1, 2]