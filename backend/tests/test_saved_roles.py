"""Saved Roles: persistent bookmarks on the Skills & Roles catalog/browse.
Bookmarks are real backend persistence (DB-backed), scoped to the owning student."""
import pytest


def _catalog_role_id(client, h, index=0):
    r = client.get("/api/roles/catalog", headers=h)
    assert r.status_code == 200, r.text
    roles = r.json()
    assert roles, "expected a non-empty catalog for the seed student"
    return roles[index]["id"]


def test_save_unsave_roundtrip(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    role_id = _catalog_role_id(client, h)
    r = client.post(f"/api/students/{student_id}/saved-roles/{role_id}", headers=h)
    assert r.status_code == 200, r.text
    assert role_id in r.json()["role_ids"]

    r = client.get(f"/api/students/{student_id}/saved-roles", headers=h)
    assert r.status_code == 200
    assert role_id in r.json()["role_ids"]

    r = client.delete(f"/api/students/{student_id}/saved-roles/{role_id}", headers=h)
    assert r.status_code == 200, r.text
    assert role_id not in r.json()["role_ids"]

    r = client.get(f"/api/students/{student_id}/saved-roles", headers=h)
    assert role_id not in r.json()["role_ids"]


def test_saving_same_role_is_idempotent(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    role_id = _catalog_role_id(client, h)
    r1 = client.post(f"/api/students/{student_id}/saved-roles/{role_id}", headers=h)
    r2 = client.post(f"/api/students/{student_id}/saved-roles/{role_id}", headers=h)
    assert r1.json()["role_ids"].count(role_id) == 1
    assert r2.json()["role_ids"].count(role_id) == 1


def test_guest_cannot_save(client, student_id):
    r = client.post(f"/api/students/{student_id}/saved-roles/1")
    assert r.status_code == 401


def test_saving_unknown_role_404(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    r = client.post(f"/api/students/{student_id}/saved-roles/999999", headers=h)
    assert r.status_code == 404


def test_other_student_cannot_touch_saved_roles(client, student_id, auth_headers):
    """Another student's token cannot read the owning student's bookmarks."""
    aisha = auth_headers("aisha@student.edu")
    omar = auth_headers("omar@student.edu")
    role_id = _catalog_role_id(client, aisha)
    client.post(f"/api/students/{student_id}/saved-roles/{role_id}", headers=aisha)
    r = client.get(f"/api/students/{student_id}/saved-roles", headers=omar)
    assert r.status_code == 403