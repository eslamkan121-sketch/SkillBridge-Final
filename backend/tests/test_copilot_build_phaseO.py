"""Phase O — Build Your Copilot: per-user copilot config + dynamic persona.

A single ``copilot_config`` row per student freezes the chosen copilot at
creation time (exactly one of the four mentors — nova / axel / sage / vex —
each mapped ONE-TO-ONE to its own working voice agent) plus the
personality/capability block that composes the dynamic system prompt.
Personality/capability is CONFIGURATION (snapshotted per user); the voice is
a SCARCE shared ElevenLabs reference, never duplicated. Chat keeps
``tutor_id`` selecting the voice agent while ``personality`` replaces the fixed
persona in the system prompt, and a configured copilot pins the active tutor
preference to its voice agent. No config ⇒ behavior byte-identical to the
fixed personas.

The old Navigator / Strategist / Confidant archetypes no longer exist: the
copilot choices ARE the mentors, and migration 0011 re-keys any legacy rows
and tightens the DB CHECK to the four mentor keys.

Never requires provider keys; the capture helper records the composed prompt.
"""
import json
import sqlite3

import pytest

from app import database, models, copilot, genai
import app.jobs as jobs_mod


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
    """Lock generation into the deterministic fallback and keep jobs offline."""
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    monkeypatch.setattr(jobs_mod, "_fetch_all", lambda *a, **k: [])
    jobs_mod.clear_job_cache()


def _file_db(tmp_path, name="phaseo.db"):
    conn = sqlite3.connect(str(tmp_path / name))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ------------------------------------------------------------------ migration 0009/0011

def test_migration_0009_on_fresh_db(tmp_path):
    conn = _file_db(tmp_path)
    database.set_db_for_test(conn)
    try:
        database.init_db()
        applied = [m["migration_id"] for m in database.applied_migrations()]
        assert applied[-1] == "0013_tutor_conversations"
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "copilot_config" in tables
        assert "copilot_onboarding" in tables
        info = {r["name"] for r in conn.execute("PRAGMA table_info(copilot_config)")}
        assert {"student_id", "choice", "voice_agent_id", "name", "title", "role",
                "specialty", "origin", "traits_json", "behavior", "style",
                "capabilities_json", "updated_at"} <= info
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='copilot_config'"
        ).fetchone()["sql"]
        # Only the four mentor keys are legal choice/voice values, never the
        # old archetype names.
        for key in ("nova", "axel", "sage", "vex"):
            assert key in sql and f"'{key}'" in sql
        for old in ("navigator", "strategist", "confidant"):
            assert old not in sql
        ob_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='copilot_onboarding'"
        ).fetchone()["sql"]
        assert "'not_started'" in ob_sql and "'completed'" in ob_sql and "'skipped'" in ob_sql
        assert "'quiz'" in ob_sql and "'skip'" in ob_sql and "'manual_change'" in ob_sql
        assert database.run_migrations() == []
    finally:
        database.set_db_for_test()
        conn.close()


def test_migration_0009_upgrades_pre_0009_db_and_keeps_rows(tmp_path):
    conn = _file_db(tmp_path)
    database.set_db_for_test(conn)
    try:
        pre = [m for m in database.MIGRATIONS
               if m["id"] not in ("0009_copilot_config", "0010_copilot_onboarding",
                                  "0011_mentor_keys", "0012_tutor_memory", "0013_tutor_conversations")]
        database.run_migrations(conn=conn, migrations=pre)
        conn.execute("INSERT INTO students (email, name, university, education_level) "
                     "VALUES ('legacy@student.edu', 'Legacy', 'Old U', 'Undergraduate')")
        conn.commit()
        assert "copilot_config" not in {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        pending = database.run_migrations()
        assert pending == ["0009_copilot_config", "0010_copilot_onboarding",
                           "0011_mentor_keys", "0012_tutor_memory", "0013_tutor_conversations"]
        kept = conn.execute("SELECT email FROM students WHERE email='legacy@student.edu'").fetchone()
        assert kept is not None
        assert database.run_migrations() == []
    finally:
        database.set_db_for_test()
        conn.close()


def test_migration_0009_backs_out_on_failure(tmp_path):
    conn = _file_db(tmp_path)
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
        assert "oops" not in tables and "copilot_config" not in tables
        assert "copilot_onboarding" not in tables
        assert database.run_migrations()[-1] == "0013_tutor_conversations"
    finally:
        database.set_db_for_test()
        conn.close()


# ------------------------------------------------------------------ options & presets

def test_copilot_options_exactly_four_mentors_each_with_its_own_voice():
    options = copilot.copilot_options()
    assert [o["key"] for o in options] == ["nova", "axel", "sage", "vex"]
    voices = [o["voice_agent_id"] for o in options]
    assert voices == ["nova", "axel", "sage", "vex"]     # one-to-one, vex included
    assert len(set(voices)) == 4
    assert set(voices) == set(copilot.ALLOWED_TUTOR_IDS)
    for o in options:
        assert all(o["capabilities"][c] is True for c in copilot.COPILOT_CAPABILITIES)
        assert o["name"] and o["title"]


@pytest.mark.parametrize("choice", ["nova", "axel", "sage", "vex"])
def test_validate_choice_accepts_four_mentors(choice):
    assert copilot.validate_choice(choice) == choice
    assert copilot.validate_choice(" " + choice.upper() + " ") == choice


@pytest.mark.parametrize("choice", [None, "", "navigator", "strategist", "confidant",
                                    "strategistly", 0, "brigadier", "Nope"])
def test_validate_choice_rejects_unknown(choice):
    assert copilot.validate_choice(choice) is None


@pytest.mark.parametrize("choice,voice,name", [
    ("nova", "nova", "Nova"),
    ("axel", "axel", "Axel"),
    ("sage", "sage", "Sage"),
    ("vex", "vex", "Vex"),
])
def test_snapshot_for_frozen_and_well_formed(choice, voice, name):
    snap = copilot.snapshot_for(choice)
    assert set(snap) == {"choice", "voice_agent_id", "name", "title", "role",
                         "specialty", "origin", "traits", "behavior", "style",
                         "capabilities"}
    assert snap["voice_agent_id"] == voice
    assert snap["name"] == name
    assert isinstance(snap["traits"], list) and snap["traits"]
    assert isinstance(snap["capabilities"], dict)
    json.dumps(snap)                       # fully JSON-encodable
    assert copilot.snapshot_for(choice) == snap   # reproducible / frozen


# ------------------------------------------------------------------ models CRUD

def test_copilot_config_crud_roundtrip(db):
    assert models.get_copilot_config(1) is None
    stored = models.set_copilot_config(1, copilot.snapshot_for("nova"))
    assert stored["choice"] == "nova"
    assert stored["voice_agent_id"] == "nova"
    assert stored["name"] == "Nova"
    assert stored["updated_at"]
    assert stored["capabilities"]["learning"] is True
    loaded = models.get_copilot_config(1)
    assert loaded == stored
    assert db.execute("SELECT COUNT(*) n FROM copilot_config").fetchone()["n"] == 1

    overwritten = models.set_copilot_config(1, copilot.snapshot_for("vex"))
    assert overwritten["choice"] == "vex"
    assert overwritten["voice_agent_id"] == "vex"
    assert db.execute("SELECT COUNT(*) n FROM copilot_config").fetchone()["n"] == 1

    assert models.clear_copilot_config(1) is True
    assert models.get_copilot_config(1) is None
    assert db.execute("SELECT COUNT(*) n FROM copilot_config").fetchone()["n"] == 0


def test_copilot_config_cascade_with_student_delete(db):
    models.set_copilot_config(1, copilot.snapshot_for("nova"))
    db.execute("INSERT INTO students (email, name) VALUES ('gone@student.edu', 'Gone')")
    sid = db.execute("SELECT id FROM students WHERE email='gone@student.edu'").fetchone()["id"]
    models.set_copilot_config(sid, copilot.snapshot_for("sage"))
    assert db.execute("SELECT COUNT(*) n FROM copilot_config").fetchone()["n"] == 2
    db.execute("DELETE FROM students WHERE id=?", (sid,))
    db.commit()
    assert models.get_copilot_config(sid) is None
    assert db.execute("SELECT COUNT(*) n FROM copilot_config").fetchone()["n"] == 1


def test_personality_for_config_shapes(db):
    assert copilot.personality_for_config(None) is None
    config = models.set_copilot_config(1, copilot.snapshot_for("sage"))
    persona = copilot.personality_for_config(config)
    assert persona["name"] == "Sage"
    assert set(persona) == {"name", "role", "origin", "specialty",
                            "traits", "behavior", "style"}
    assert persona["traits"] == ["Calm", "Analytical", "Thoughtful", "Reflective"]
    assert copilot.personality_for_config({"voice_agent_id": "nova"})["name"] == "the copilot"


# ------------------------------------------------------------------ endpoints

def _capture_complete(monkeypatch):
    captured = {}

    def fake(system, user, fallback=None, **kw):
        captured["system"] = system
        captured["user"] = user
        return fallback

    monkeypatch.setattr(genai, "complete", fake)
    return captured


def test_copilot_endpoints_authz_matrix(client, auth_headers, student_id):
    guest = client.get(f"/api/students/{student_id}/copilot")
    assert guest.status_code == 401
    assert client.put(f"/api/students/{student_id}/copilot",
                      json={"choice": "nova"}).status_code == 401
    assert client.delete(f"/api/students/{student_id}/copilot").status_code == 401

    company = auth_headers("hr@northstar.com")
    assert client.get(f"/api/students/{student_id}/copilot",
                      headers=company).status_code == 403
    assert client.put(f"/api/students/{student_id}/copilot",
                      json={"choice": "nova"},
                      headers=company).status_code == 403

    university = auth_headers("admin@univ.edu")
    assert client.get(f"/api/students/{student_id}/copilot",
                      headers=university).status_code == 403

    omar = auth_headers("omar@student.edu")
    assert client.get(f"/api/students/{student_id}/copilot",
                      headers=omar).status_code == 403
    assert client.delete(f"/api/students/{student_id}/copilot",
                         headers=omar).status_code == 403


def test_copilot_get_put_delete_roundtrip(client, auth_headers, student_id):
    headers = auth_headers("aisha@student.edu")
    initial = client.get(f"/api/students/{student_id}/copilot", headers=headers).json()
    assert initial["configured"] is False
    assert initial["copilot"] is None
    assert [o["key"] for o in initial["options"]] == ["nova", "axel", "sage", "vex"]

    put = client.put(f"/api/students/{student_id}/copilot",
                     json={"choice": "nova"}, headers=headers)
    assert put.status_code == 200
    body = put.json()
    assert body["configured"] is True
    assert body["copilot"]["choice"] == "nova"
    assert body["copilot"]["voice_agent_id"] == "nova"
    assert body["copilot"]["name"] == "Nova"
    assert body["copilot"]["capabilities"]["practice"] is True

    got = client.get(f"/api/students/{student_id}/copilot", headers=headers).json()
    assert got["configured"] is True
    assert got["copilot"]["name"] == "Nova"

    put2 = client.put(f"/api/students/{student_id}/copilot",
                      json={"choice": "axel"}, headers=headers)
    assert put2.status_code == 200
    assert put2.json()["copilot"]["voice_agent_id"] == "axel"
    assert put2.json()["copilot"]["name"] == "Axel"

    bad = client.put(f"/api/students/{student_id}/copilot",
                     json={"choice": "confidant"}, headers=headers)
    assert bad.status_code == 400
    assert "sage" in bad.json()["detail"]            # the allowed list is the 4 mentors

    deleted = client.delete(f"/api/students/{student_id}/copilot", headers=headers)
    assert deleted.status_code == 200
    body = deleted.json()
    assert body["configured"] is False and body["copilot"] is None


def test_copilot_put_syncs_tutor_preference_and_preference_reports_copilot(client, auth_headers, student_id):
    headers = auth_headers("aisha@student.edu")
    assert client.put(f"/api/students/{student_id}/copilot",
                      json={"choice": "sage"}, headers=headers).status_code == 200
    pref = client.get(f"/api/students/{student_id}/tutor/preference",
                      headers=headers).json()
    assert pref["tutor_id"] == "sage"                          # voice agent won
    assert pref["copilot"]["configured"] is True
    assert pref["copilot"]["choice"] == "sage"
    assert pref["copilot"]["voice_agent_id"] == "sage"
    assert pref["copilot"]["name"] == "Sage"

    client.delete(f"/api/students/{student_id}/copilot", headers=headers)
    pref = client.get(f"/api/students/{student_id}/tutor/preference",
                      headers=headers).json()
    assert "copilot" not in pref
    assert pref["tutor_id"] in copilot.ALLOWED_TUTOR_IDS


def test_copilot_no_config_chat_unchanged(client, auth_headers, student_id, monkeypatch):
    captured = _capture_complete(monkeypatch)
    headers = auth_headers("aisha@student.edu")
    r = client.post(f"/api/students/{student_id}/tutor",
                    json={"message": "What is your name?"}, headers=headers)
    assert r.status_code == 200
    assert "You are Nova" in captured["system"]
    assert "The Navigator" not in captured["system"]
    assert "The Strategist" not in captured["system"]


def test_copilot_chat_applies_personality_and_voice(client, auth_headers, student_id, monkeypatch):
    captured = _capture_complete(monkeypatch)
    headers = auth_headers("aisha@student.edu")
    assert client.put(f"/api/students/{student_id}/copilot",
                      json={"choice": "sage"}, headers=headers).status_code == 200

    r = client.post(f"/api/students/{student_id}/tutor",
                    json={"message": "What is your name?"}, headers=headers)
    assert r.status_code == 200
    # The composed system prompt describes the mentor, not a generic persona —
    # and no other mentor leaks into it.
    assert "You are Sage" in captured["system"]
    assert "Alexandria, Egypt" in captured["system"]
    assert "You are Nova" not in captured["system"]
    assert "You are Axel" not in captured["system"]
    # tutor_id kept its voice-agent semantics: the personality override still
    # composes the prompt even when a different voice agent is requested.
    raw = client.post(f"/api/students/{student_id}/tutor",
                      json={"message": "What is your name?", "tutor_id": "axel"},
                      headers=headers)
    assert raw.status_code == 200
    assert "You are Sage" in captured["system"]
    assert "You are Axel" not in captured["system"]
