"""Phase 5.5 Step 3 — Tutor Identity Profiles.

The single canonical source of tutor identity metadata lives in the frontend
(``frontend/src/lib/tutorProfiles.ts``, verified by TypeScript at build time and
by ``scripts/check-tutor-profiles.mjs`` here). The backend keeps the *personality*
engine (``genai.TUTOR_PERSONAS``) describing the same four identities by id.

These tests pin:
- the canonical identity contract (ids, names, origins, specialties, non-empty
  traits/bestFor, English+Arabic languages, avatar mapping) by running the Node
  checker against the actual single-source file;
- backend personality alignment (same four ids, canonical names, non-empty styles);
- regressions the step must not break: tutor persistence, mode switching, and
  the mock interview. Never calls a paid API.
"""

import shutil
import subprocess

import pytest

from app import copilot, genai, models
from contract_paths import FRONTEND_ROOT, WORKSPACE_ROOT, checker_script, node_env


def _node():
    return shutil.which("node")


# ------------------------------------------------------------------ canonical profile contract (single source of truth)

COMPLETE = {
    "nova": {"name": "Nova", "origin": "London, United Kingdom", "specialty": "Learn & Explain"},
    "axel": {"name": "Axel", "origin": "California, United States", "specialty": "Practice & Build"},
    "sage": {"name": "Sage", "origin": "Alexandria, Egypt", "specialty": "Discuss & Think"},
    "vex": {"name": "Vex", "origin": "Paris, France", "specialty": "Test & Interview"},
}


def test_every_tutor_id_has_exactly_one_canonical_profile():
    """1+2: all four Tutor profiles exist and each Tutor ID maps to one profile."""
    checks = (FRONTEND_ROOT / "src" / "lib" / "tutorProfiles.ts").read_text(encoding="utf-8")
    assert "export const TUTOR_PROFILES" in checks
    for tid in copilot.ALLOWED_TUTOR_IDS:
        assert f"id: '{tid}'" in checks or f"id: \"{tid}\"" in checks, tid


def test_canonical_profile_contract_via_node_checker():
    """3-8: origins, specialties, non-empty traits/bestFor, languages, avatars.

    Runs the repo's own checker against the actual single-source file.
    """
    node = _node()
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-tutor-profiles.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, f"node profile check failed:\n{result.stdout}\n{result.stderr}"


# ------------------------------------------------------------------ backend personality alignment

def test_backend_personas_cover_the_same_four_ids():
    ids = set(genai.TUTOR_PERSONAS)
    assert ids == set(COMPLETE) == set(copilot.ALLOWED_TUTOR_IDS)


def test_backend_persona_names_match_canonical_identity():
    for tid, meta in COMPLETE.items():
        persona = genai.TUTOR_PERSONAS[tid]
        assert persona["name"] == meta["name"], tid
        assert persona["style"].strip(), tid


# ------------------------------------------------------------------ the step must not break existing tutor behavior

def test_tutor_persistence_still_works(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    client.put(f"/api/students/{student_id}/tutor/preference", json={"tutor_id": "sage"}, headers=h)
    got = client.get(f"/api/students/{student_id}/tutor/preference", headers=h).json()
    assert got["tutor_id"] == "sage" and got["mode"] == "discuss"  # default mode follows tutor


def test_mode_switching_still_works(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    client.put(f"/api/students/{student_id}/tutor/preference", json={"tutor_id": "nova"}, headers=h)
    assert client.put(f"/api/students/{student_id}/tutor/preference",
                      json={"mode": "practice"}, headers=h).json()["mode"] == "practice"
    got = client.get(f"/api/students/{student_id}/tutor/preference", headers=h).json()
    assert got["tutor_id"] == "nova" and got["mode"] == "practice"
    # origin must never restrict modes: Nova can still pick interview
    assert client.put(f"/api/students/{student_id}/tutor/preference",
                      json={"mode": "interview"}, headers=h).json()["mode"] == "interview"


def test_mock_interview_still_works(client, student_id, auth_headers):
    h = auth_headers("aisha@student.edu")
    r = client.post(f"/api/students/{student_id}/interview",
                    json={"message": "", "turn": 1, "tutor": "vex"}, headers=h)
    assert r.status_code == 200 and r.json()["reply"] and r.json()["turn"] == 2
