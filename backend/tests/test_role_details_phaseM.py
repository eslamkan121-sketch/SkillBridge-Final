"""Phase M — Role details, comparison and career transitions data.

related_roles() derives roles reachable through maintained relationships ONLY:
the real parent_role_id / family / superseded_by_role_id links. Children,
siblings and superseded-by groups are restricted to active roles; the direct
parent and the superseded_by target appear as-is because they are the role's
own real links. No relationship => None / empty lists — never invented. The
result rides along additively on the existing provenance endpoint, so no role
listing or match score can change.
"""
import sqlite3

import pytest

from app import database, models, seed

MIGRATION_0007 = "0007_role_view_events"


def _mk(db, title, family=None, parent_role_id=None, canonical_status=None,
        superseded_by_role_id=None):
    company_id = db.execute("SELECT id FROM companies LIMIT 1").fetchone()["id"]
    role = models.create_role(company_id, title, [])
    cols = {}
    if family is not None:
        cols["family"] = family
    if parent_role_id is not None:
        cols["parent_role_id"] = parent_role_id
    if canonical_status is not None:
        cols["canonical_status"] = canonical_status
    if superseded_by_role_id is not None:
        cols["superseded_by_role_id"] = superseded_by_role_id
    if cols:
        sets = ", ".join(f"{k}=?" for k in cols)
        db.execute(f"UPDATE roles SET {sets} WHERE id=?", (*cols.values(), role["id"]))
        db.commit()
    return role


def _catalog_role_id():
    return models.list_catalog_roles()[0]["id"]


def test_related_roles_no_relationships_is_honest_empty(db):
    role = _mk(db, "Standalone Sorters-nothing role xyz", family=None)
    rel = models.related_roles(role["id"])
    assert set(rel) == {"parent", "children", "siblings", "supersedes", "superseded_by"}
    assert rel["parent"] is None
    assert rel["children"] == []
    assert rel["siblings"] == []
    assert rel["supersedes"] == []
    assert rel["superseded_by"] is None


def test_related_roles_parent_children_siblings_supersede_graph(db):
    other = _mk(db, "Some other role gamma", family="otherfam")
    a = _mk(db, "Graph A role omega", family="mfam")
    b = _mk(db, "Graph B child omega", family="mfam", parent_role_id=a["id"])
    d = _mk(db, "Graph D sibling omega", family="mfam")
    f = _mk(db, "Graph F replaced omega", family="mfam", superseded_by_role_id=a["id"])
    g = _mk(db, "Graph G successor omega", family="mfam")
    _mk(db, "Standalone epsilon", family=None)
    db.execute("UPDATE roles SET superseded_by_role_id=? WHERE id=?", (g["id"], a["id"]))
    db.commit()

    rel = models.related_roles(a["id"])
    assert rel["parent"] is None
    assert [r["id"] for r in rel["children"]] == [b["id"]]
    # family peers: same family, active, self AND direct children excluded (a
    # child is already listed under specialisations — never double-listed)
    assert [r["id"] for r in rel["siblings"]] == [d["id"], f["id"], g["id"]]
    assert [r["id"] for r in rel["supersedes"]] == [f["id"]]
    assert rel["superseded_by"]["id"] == g["id"]
    # other family + standalone carbon never leak in
    assert other["id"] not in [r["id"] for r in rel["siblings"]]


def test_related_roles_active_only_and_deprecated_never_suggested(db):
    a = _mk(db, "Active parent zeta", family="dfam")
    _mk(db, "Deprecated child zeta", family="dfam", parent_role_id=a["id"],
        canonical_status="deprecated")
    _mk(db, "Deprecated sibling zeta", family="dfam", canonical_status="deprecated")
    _mk(db, "Deprecated supersede zeta", family="dfam",
        superseded_by_role_id=a["id"], canonical_status="deprecated")

    rel = models.related_roles(a["id"])
    assert rel["children"] == []
    assert rel["siblings"] == []
    assert rel["supersedes"] == []


def test_related_roles_deprecated_parent_and_target_resolve_as_is(db):
    parent = _mk(db, "Deprecated parent eta", canonical_status="deprecated")
    child = _mk(db, "Active child eta", family="efam", parent_role_id=parent["id"])
    successor = _mk(db, "Deprecated successor eta", canonical_status="deprecated")
    subject = _mk(db, "Subject eta", family="efam")
    db.execute("UPDATE roles SET superseded_by_role_id=? WHERE id=?", (successor["id"], subject["id"]))
    db.commit()

    rel_parent = models.related_roles(child["id"])
    assert rel_parent["parent"]["id"] == parent["id"]
    assert rel_parent["parent"]["canonical_status"] == "deprecated"

    rel_subject = models.related_roles(subject["id"])
    assert rel_subject["superseded_by"]["id"] == successor["id"]
    assert rel_subject["superseded_by"]["canonical_status"] == "deprecated"


def test_related_roles_deprecated_role_still_resolvable_and_unlisted(db):
    a = _mk(db, "Parent theta", family="tfam")
    dep = _mk(db, "Deprecated subject theta", family="tfam", parent_role_id=a["id"],
              canonical_status="deprecated")

    rel = models.related_roles(dep["id"])
    assert rel["parent"]["id"] == a["id"]  # deprecated subject still sees its parent
    others = models.related_roles(a["id"])
    assert all(r["id"] != dep["id"] for r in others["children"])  # but is never suggested


def test_related_roles_unknown_role_is_none(db):
    assert models.related_roles(999999) is None


def test_related_rows_carry_openable_role_shape(db):
    a = _mk(db, "Parent kappa", family="kfam")
    _mk(db, "Child kappa", family="kfam", parent_role_id=a["id"])
    rel = models.related_roles(a["id"])
    for group in ("children", "siblings", "supersedes"):
        for r in rel[group]:
            assert "required_skills" in r and "family" in r and "source_version" in r
            assert "canonical_status" in r


def test_related_siblings_requires_nonempty_family(db):
    role = _mk(db, "No-family lambda", family=None)
    rel = models.related_roles(role["id"])
    assert rel["siblings"] == []


# ------------------------------------------------- provenance endpoint (additive)

def test_provenance_is_strictly_additive_with_related(db):
    role = models.list_catalog_roles()[0]
    prov = models.role_provenance(role["id"])
    assert prov is not None
    assert set(prov["related"]) == {"parent", "children", "siblings", "supersedes", "superseded_by"}
    # get_role / list payloads are untouched by the additive key
    assert "related" not in models.get_role(role["id"])
    assert all("related" not in r for r in models.list_roles())
    assert all("related" not in r for r in models.list_catalog_roles())


def test_provenance_endpoint_returns_related_for_catalog(db, client, auth_headers):
    h = auth_headers("aisha@student.edu")
    r = client.get(f"/api/roles/{_catalog_role_id()}/provenance", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert "aliases" in body and "isco_codes" in body and "skill_sources" in body
    assert "related" in body
    assert set(body["related"]) == {"parent", "children", "siblings", "supersedes", "superseded_by"}


def test_provenance_endpoint_ownership_unchanged(db, client, auth_headers):
    northstar = [r for r in models.list_roles() if r.get("company_name") == "Northstar Labs"]
    assert northstar
    role_id = northstar[0]["id"]

    owner = auth_headers("hr@northstar.com")
    own = client.get(f"/api/roles/{role_id}/provenance", headers=owner)
    assert own.status_code == 200
    assert "related" in own.json() and own.json()["source"] == "company"

    outsider = auth_headers("hr@signal.com")
    assert client.get(f"/api/roles/{role_id}/provenance", headers=outsider).status_code == 403
    assert client.get(f"/api/roles/{role_id}/provenance").status_code == 401
    assert client.get("/api/roles/9999999/provenance", headers=owner).status_code == 404


def test_provenance_related_never_reaches_roles_listing(db):
    """The listing endpoints must not gain the related graph (payload creep is
    exactly what the additive contract forbids)."""
    _mk(db, "Graph mu", family="mufam")
    rows = models.list_roles()
    assert all("related" not in r for r in rows)
    cats = models.list_catalog_roles()
    assert all("related" not in r for r in cats)