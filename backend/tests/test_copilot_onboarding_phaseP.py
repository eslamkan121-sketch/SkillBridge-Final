"""Phase P — Copilot onboarding quiz (Mentor Experience Phase 1).

The first-run flow now recommends one of the EXACTLY four real mentors
(nova / axel / sage / vex); the old three archetype names (navigator /
strategist / confidant) no longer exist in the API surface. migration 0011
rebuilds ``copilot_config`` so its CHECK accepts the four mentor keys and
re-keys any legacy rows (navigator→nova, strategist→axel, confidant→sage,
refreshing the display name); ``copilot_onboarding`` needs no schema change so
the "ask once" property survives.

Scoring is a pure tally of the four answered mentor keys (one per question);
ties break deterministically — the Question 4 answer, then the Question 1
answer, then DEFAULT_ARCHETYPE (nova) — and the SERVER's recompute is always
the authority over any client-sent ``choice``. A skip resolves to the default
nova mentor. Completing the quiz snapshots the winner, pins the active tutor's
voice agent, and never touches the working mode: recommending Vex must never
activate Interview mode.
"""
import json
import sqlite3

import pytest

from app import copilot, database, models, seed


# ------------------------------------------------------------------ migration 0011

def test_migration_0011_on_fresh_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "p.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    database.set_db_for_test(conn)
    try:
        database.init_db()
        applied = [m["migration_id"] for m in database.applied_migrations()]
        assert applied[-1] == "0013_tutor_conversations"
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "copilot_onboarding" in tables and "copilot_config" in tables
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='copilot_config'"
        ).fetchone()["sql"]
        # The mentors are the ONLY legal choice values …
        for key in ("nova", "axel", "sage", "vex"):
            assert key in sql
        # … and the old archetype names can never be stored again.
        for old in ("navigator", "strategist", "confidant"):
            assert old not in sql
        assert "CHECK" in sql
        info = {r["name"] for r in conn.execute("PRAGMA table_info(copilot_config)")}
        assert {"student_id", "choice", "voice_agent_id", "name", "traits_json",
                "capabilities_json"} <= info
        ob_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='copilot_onboarding'"
        ).fetchone()["sql"]
        assert "'not_started'" in ob_sql and "'completed'" in ob_sql and "'skipped'" in ob_sql
        assert database.run_migrations() == []
    finally:
        database.set_db_for_test()
        conn.close()


def test_migration_0011_upgrades_pre_0011_db_and_rekeys_rows(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "p-old.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    database.set_db_for_test(conn)
    try:
        pre = [m for m in database.MIGRATIONS
               if m["id"] not in ("0011_mentor_keys", "0012_tutor_memory", "0013_tutor_conversations")]
        database.run_migrations(conn=conn, migrations=pre)
        for i, (choice, voice) in enumerate([
            ("navigator", "nova"),
            ("strategist", "axel"),
            ("confidant", "sage"),
        ]):
            conn.execute("INSERT INTO students (email, name) VALUES (?, 'L')",
                         (f"legacy{i}@student.edu",))
            sid = conn.execute("SELECT id FROM students WHERE email=?", (f"legacy{i}@student.edu",)
                               ).fetchone()["id"]
            conn.execute("INSERT INTO copilot_config (student_id, choice, voice_agent_id, name, "
                         "title, role, specialty, origin, behavior, style) "
                         "VALUES (?, ?, ?, 'Archetype', 't', 'r', 's', 'o', 'b', 's')",
                         (sid, choice, voice))
        conn.execute("INSERT INTO copilot_onboarding (student_id, state, source, quiz_answers_json) "
                     "VALUES (1, 'completed', 'quiz', '[\"navigator\",\"navigator\",\"navigator\"]')")
        conn.commit()

        pending = database.run_migrations()
        assert pending == ["0011_mentor_keys", "0012_tutor_memory", "0013_tutor_conversations"]

        # Legacy rows are re-keyed deterministically AND the display names are
        # refreshed so the old archetype names never surface again.
        rekeyed = {(r["choice"], r["voice_agent_id"], r["name"]) for r in conn.execute(
            "SELECT choice, voice_agent_id, name FROM copilot_config").fetchall()}
        assert rekeyed == {
            ("nova", "nova", "Nova"),
            ("axel", "axel", "Axel"),
            ("sage", "sage", "Sage"),
        }
        # copilot_onboarding needs no schema change — answers are free-text JSON.
        row = conn.execute("SELECT state, source, quiz_answers_json FROM copilot_onboarding "
                           "WHERE student_id=1").fetchone()
        assert row["state"] == "completed" and row["source"] == "quiz"
        assert row["quiz_answers_json"] == '["navigator","navigator","navigator"]'
        # Nothing else was touched.
        assert conn.execute("SELECT COUNT(*) n FROM students").fetchone()["n"] == 3
        assert database.run_migrations() == []
    finally:
        database.set_db_for_test()
        conn.close()


def test_migration_0011_backs_out_on_failure(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "p2.db"))
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
        assert "oops" not in tables and "copilot_onboarding" not in tables
        assert database.run_migrations()[-1] == "0013_tutor_conversations"
    finally:
        database.set_db_for_test()
        conn.close()


# ------------------------------------------------------------------ questions & keys

def test_onboarding_questions_well_formed():
    assert copilot.ONBOARDING_QUESTION_COUNT == 4
    assert copilot.DEFAULT_ARCHETYPE == "nova"
    assert list(copilot.COPILOT_KEYS) == ["nova", "axel", "sage", "vex"]
    assert len(copilot.ONBOARDING_QUESTIONS) == 4
    for q in copilot.ONBOARDING_QUESTIONS:
        assert q["question"]
        assert len(q["options"]) == 4
        labels = {o["label"] for o in q["options"]}
        assert len(labels) == 4                      # four distinct options
        for o in q["options"]:
            assert o["vote"] in copilot.COPILOT_KEYS  # every vote is a real mentor


def test_seed_wipe_clears_onboarding_table(db):
    models.set_copilot_onboarding(1, "completed", "quiz", ["nova", "nova", "nova", "nova"])
    assert models.get_copilot_onboarding(1)["state"] == "completed"
    seed.seed()
    assert models.get_copilot_onboarding(1)["state"] == "not_started"
    assert db.execute("SELECT COUNT(*) n FROM copilot_onboarding").fetchone()["n"] == 0


# ------------------------------------------------------------------ scoring (pure)

def test_score_archetype_vote_counts():
    assert copilot.score_archetype(["nova", "nova", "nova", "nova"]) == "nova"
    assert copilot.score_archetype(["axel", "axel", "axel", "axel"]) == "axel"
    assert copilot.score_archetype(["sage", "sage", "sage", "sage"]) == "sage"
    assert copilot.score_archetype(["vex", "vex", "vex", "vex"]) == "vex"
    # Mixed: two votes win (no tie).
    assert copilot.score_archetype(["nova", "nova", "axel", "sage"]) == "nova"
    assert copilot.score_archetype(["sage", "axel", "axel", "sage"]) == "sage"
    assert copilot.score_archetype(["vex", "nova", "nova", "sage"]) == "nova"


def test_score_archetype_tie_break_question4():
    # 2-2 nova/axel tie: the Question 4 answer decides.
    assert copilot.score_archetype(["nova", "nova", "axel", "axel"]) == "axel"
    assert copilot.score_archetype(["axel", "axel", "nova", "nova"]) == "nova"
    # Perfect four-way tie: the Question 4 answer is also a winner → wins.
    assert copilot.score_archetype(["nova", "axel", "sage", "vex"]) == "vex"


def test_score_archetype_tie_never_fabricates_a_mentor():
    # Every tie still resolves to one of the EXACT four mentors.
    for answers in [
        ["nova", "nova", "axel", "axel"],
        ["axel", "axel", "sage", "sage"],
        ["nova", "axel", "sage", "vex"],
    ]:
        winner = copilot.score_archetype(answers)
        assert winner in copilot.COPILOT_KEYS


def test_score_archetype_degenerate_input_never_crashes():
    assert copilot.score_archetype(None) == copilot.DEFAULT_ARCHETYPE
    assert copilot.score_archetype([]) == copilot.DEFAULT_ARCHETYPE
    assert copilot.score_archetype(["nova", "axel", "sage"]) == copilot.DEFAULT_ARCHETYPE
    assert copilot.score_archetype(["navigator", "nova", "axel", "sage"]) == copilot.DEFAULT_ARCHETYPE


@pytest.mark.parametrize("answers", [
    ["nova", "axel", "sage", "vex"],
    ("nova", "axel", "sage", "vex"),
    [" NOVA ", "AXEL", "sage", " vex"],              # normalized keys accepted
])
def test_validate_onboarding_answers_accepts_exactly_four(answers):
    out = copilot.validate_onboarding_answers(answers)
    assert out == [a.strip().lower() for a in answers]


@pytest.mark.parametrize("answers", [
    None,
    "nova",
    [],
    ["nova"],
    ["nova", "axel"],
    ["nova", "axel", "sage"],
    ["nova", "axel", "sage", "vex", "nova"],
    ["nova", "axel", "sage", "navigator"],           # old archetype never accepted
    ["nova", "axel", "sage", 7],
    [None, None, None, None],
    ["vex", "vex", "vex", []],
])
def test_validate_onboarding_answers_rejects_shape_mismatches(answers):
    assert copilot.validate_onboarding_answers(answers) is None


# ------------------------------------------------------------------ models CRUD

def test_onboarding_crud_roundtrip(db):
    assert models.get_copilot_onboarding(1) == {
        "student_id": 1, "state": "not_started", "source": "manual_change",
        "quiz_answers": [], "answered_at": None}
    written = models.set_copilot_onboarding(1, "completed", "quiz",
                                            ["sage", "sage", "sage", "sage"])
    assert written["state"] == "completed"
    assert written["source"] == "quiz"
    assert written["quiz_answers"] == ["sage", "sage", "sage", "sage"]
    assert written["answered_at"]
    row = db.execute("SELECT * FROM copilot_onboarding WHERE student_id=1").fetchone()
    assert json.loads(row["quiz_answers_json"]) == ["sage", "sage", "sage", "sage"]
    # Upsert keeps a single row per student; only the last outcome persists.
    overwritten = models.set_copilot_onboarding(1, "skipped", "skip")
    assert db.execute("SELECT COUNT(*) n FROM copilot_onboarding WHERE student_id=1"
                      ).fetchone()["n"] == 1
    assert overwritten["state"] == "skipped"
    assert overwritten["quiz_answers"] == []


def test_onboarding_cascades_with_student_delete(db):
    db.execute("INSERT INTO students (email, name) VALUES ('gone@student.edu', 'Gone')")
    sid = db.execute("SELECT id FROM students WHERE email='gone@student.edu'").fetchone()["id"]
    models.set_copilot_onboarding(sid, "completed", "quiz", ["nova", "nova", "nova", "nova"])
    db.execute("DELETE FROM students WHERE id=?", (sid,))
    db.commit()
    assert models.get_copilot_onboarding(sid)["state"] == "not_started"


def test_mark_copilot_manual_freezes_not_started(db):
    # No row yet: a settings build means the student decided — never re-ask.
    rec = models.mark_copilot_manual(1)
    assert rec["state"] == "completed"
    assert rec["source"] == "manual_change"
    assert rec["answered_at"]
    assert rec["quiz_answers"] == []


def test_mark_copilot_manual_updates_source_but_keeps_state(db):
    models.set_copilot_onboarding(1, "skipped", "skip")
    rec = models.mark_copilot_manual(1)
    assert rec["state"] == "skipped"          # quiz outcome is never re-opened
    assert rec["source"] == "manual_change"   # the latest decision is recorded


def test_onboarding_table_independent_of_copilot_config(db):
    # "only ask once" survives DELETE copilot: the two tables never share a row.
    models.set_copilot_config(1, copilot.snapshot_for("nova"))
    models.set_copilot_onboarding(1, "completed", "quiz", ["nova", "nova", "nova", "nova"])
    assert models.get_copilot_config(1) is not None
    assert models.clear_copilot_config(1) is True
    assert models.get_copilot_config(1) is None
    assert models.get_copilot_onboarding(1)["state"] == "completed"


# ------------------------------------------------------------------ endpoints

def test_onboarding_state_endpoint_roundtrip(client, auth_headers, student_id):
    headers = auth_headers("aisha@student.edu")
    initial = client.get(f"/api/students/{student_id}/copilot/onboarding-state",
                         headers=headers).json()
    assert initial["state"] == "not_started"
    assert initial["source"] == "manual_change"
    assert initial["answered_at"] is None
    assert initial["configured"] is False
    assert initial["copilot"] is None
    assert [o["key"] for o in initial["options"]] == list(copilot.COPILOT_KEYS)

    posted = client.post(f"/api/students/{student_id}/copilot/onboarding",
                         json={"answers": ["sage", "sage", "sage", "sage"]},
                         headers=headers)
    assert posted.status_code == 200
    body = posted.json()
    assert body["state"] == "completed"
    assert body["source"] == "quiz"
    assert body["assigned"] == "sage"
    assert body["copilot"]["name"] == "Sage"
    assert body["answered_at"]

    state = client.get(f"/api/students/{student_id}/copilot/onboarding-state",
                       headers=headers).json()
    assert state["state"] == "completed"
    assert state["source"] == "quiz"
    assert state["configured"] is True
    assert state["copilot"]["choice"] == "sage"


def test_onboarding_complete_builds_config_and_pins_tutor_voice(client, auth_headers, student_id):
    headers = auth_headers("aisha@student.edu")
    posted = client.post(f"/api/students/{student_id}/copilot/onboarding",
                         json={"answers": ["axel", "axel", "axel", "axel"]},
                         headers=headers)
    assert posted.status_code == 200
    config = client.get(f"/api/students/{student_id}/copilot", headers=headers).json()
    assert config["configured"] is True
    assert config["copilot"]["choice"] == "axel"
    assert config["copilot"]["voice_agent_id"] == "axel"
    pref = client.get(f"/api/students/{student_id}/tutor/preference", headers=headers).json()
    assert pref["tutor_id"] == "axel"
    assert pref["copilot"]["voice_agent_id"] == "axel"


def test_onboarding_selected_mentor_persists(client, auth_headers, student_id):
    """Reopening the flow after completion still shows the stored mentor."""
    headers = auth_headers("aisha@student.edu")
    posted = client.post(f"/api/students/{student_id}/copilot/onboarding",
                         json={"answers": ["nova", "nova", "sage", "vex"]},
                         headers=headers)
    assert posted.status_code == 200
    assert posted.json()["assigned"] == "nova"
    # A later session (fresh requests) reports the same completed mentor.
    state = client.get(f"/api/students/{student_id}/copilot/onboarding-state",
                       headers=headers).json()
    assert state["state"] == "completed"
    assert state["copilot"]["choice"] == "nova"
    config = client.get(f"/api/students/{student_id}/copilot", headers=headers).json()
    assert config["copilot"]["name"] == "Nova"


def test_onboarding_skip_builds_default_nova(client, auth_headers, student_id):
    headers = auth_headers("aisha@student.edu")
    posted = client.post(f"/api/students/{student_id}/copilot/onboarding",
                         json={"skipped": True}, headers=headers)
    assert posted.status_code == 200
    body = posted.json()
    assert body["state"] == "skipped"
    assert body["source"] == "skip"
    assert body["assigned"] == copilot.DEFAULT_ARCHETYPE
    assert body["copilot"]["voice_agent_id"] == "nova"
    config = client.get(f"/api/students/{student_id}/copilot", headers=headers).json()
    assert config["configured"] is True
    assert config["copilot"]["choice"] == "nova"


@pytest.mark.parametrize("payload", [
    {"skipped": True, "answers": ["nova", "nova", "nova", "nova"]},
    {},
    {"skipped": False},
    {"answers": ["nova", "axel"]},
    {"answers": ["nova", "axel", "sage", "vex", "nova"]},
    {"answers": ["nova", "axel", "sage", "navigator"]},
    {"answers": "nova"},
    {"answers": None},
])
def test_onboarding_rejects_malformed_payloads(client, auth_headers, student_id, payload):
    headers = auth_headers("aisha@student.edu")
    r = client.post(f"/api/students/{student_id}/copilot/onboarding",
                    json=payload, headers=headers)
    assert r.status_code == 400
    assert r.json()["detail"]


def test_onboarding_rejects_invalid_choice(client, auth_headers, student_id):
    headers = auth_headers("aisha@student.edu")
    # "strategist" is an OLD archetype name — never a valid copilot choice now.
    r = client.post(f"/api/students/{student_id}/copilot/onboarding",
                    json={"answers": ["nova", "nova", "nova", "nova"],
                          "choice": "strategist"}, headers=headers)
    assert r.status_code == 400
    assert "sage" in r.json()["detail"]      # error lists the four mentors


def test_onboarding_server_recomputation_overrides_mismatched_choice(client, auth_headers, student_id):
    headers = auth_headers("aisha@student.edu")
    # Answers vote Nova two-to-one, but the client claims Vex.
    posted = client.post(f"/api/students/{student_id}/copilot/onboarding",
                         json={"answers": ["nova", "nova", "axel", "sage"],
                               "choice": "vex"}, headers=headers)
    assert posted.status_code == 200
    body = posted.json()
    assert body["assigned"] == "nova"     # server recompute wins
    config = client.get(f"/api/students/{student_id}/copilot", headers=headers).json()
    assert config["copilot"]["choice"] == "nova"
    pref = client.get(f"/api/students/{student_id}/tutor/preference", headers=headers).json()
    assert pref["tutor_id"] == "nova"


def test_onboarding_retake_replaces_config_and_records_source_quiz(client, auth_headers, student_id):
    headers = auth_headers("aisha@student.edu")
    first = client.post(f"/api/students/{student_id}/copilot/onboarding",
                        json={"answers": ["nova", "nova", "nova", "nova"]},
                        headers=headers)
    assert first.status_code == 200
    second = client.post(f"/api/students/{student_id}/copilot/onboarding",
                         json={"answers": ["vex", "vex", "vex", "vex"]},
                         headers=headers)
    assert second.status_code == 200
    body = second.json()
    assert body["assigned"] == "vex"
    assert body["source"] == "quiz"
    state = client.get(f"/api/students/{student_id}/copilot/onboarding-state",
                       headers=headers).json()
    assert state["state"] == "completed"
    assert state["source"] == "quiz"
    assert state["copilot"]["choice"] == "vex"
    assert client.get(f"/api/students/{student_id}/copilot", headers=headers
                      ).json()["copilot"]["name"] == "Vex"


def test_onboarding_state_visible_from_quiz_and_skipped(client, auth_headers, student_id):
    headers = auth_headers("aisha@student.edu")
    client.post(f"/api/students/{student_id}/copilot/onboarding",
                json={"skipped": True}, headers=headers)
    state = client.get(f"/api/students/{student_id}/copilot/onboarding-state",
                       headers=headers).json()
    assert state["state"] == "skipped" and state["source"] == "skip"


def test_put_copilot_marks_manual_and_never_reopens_modal(client, auth_headers, student_id):
    headers = auth_headers("aisha@student.edu")
    # A settings build before any quiz: state becomes completed / manual_change.
    r = client.put(f"/api/students/{student_id}/copilot",
                   json={"choice": "axel"}, headers=headers)
    assert r.status_code == 200
    state = client.get(f"/api/students/{student_id}/copilot/onboarding-state",
                       headers=headers).json()
    assert state["state"] == "completed"
    assert state["source"] == "manual_change"

    # Skipped-then-manual: the skip outcome stays skipped, source is updated.
    second = client.post(f"/api/students/{student_id}/copilot/onboarding",
                         json={"skipped": True}, headers=headers)
    assert second.json()["state"] == "skipped"
    r = client.put(f"/api/students/{student_id}/copilot",
                   json={"choice": "vex"}, headers=headers)
    assert r.status_code == 200
    state = client.get(f"/api/students/{student_id}/copilot/onboarding-state",
                       headers=headers).json()
    assert state["state"] == "skipped"
    assert state["source"] == "manual_change"


def test_delete_copilot_keeps_onboarding_state(client, auth_headers, student_id):
    headers = auth_headers("aisha@student.edu")
    client.post(f"/api/students/{student_id}/copilot/onboarding",
                json={"answers": ["nova", "nova", "nova", "nova"]}, headers=headers)
    assert client.delete(f"/api/students/{student_id}/copilot", headers=headers).status_code == 200
    state = client.get(f"/api/students/{student_id}/copilot/onboarding-state",
                       headers=headers).json()
    assert state["state"] == "completed"      # only-ask-once survives DELETE copilot
    assert state["source"] == "quiz"
    assert state["configured"] is False


def test_onboarding_vex_never_activates_interview_mode(client, auth_headers, student_id):
    """Recommending Vex must not auto-start Interview mode (persona ≠ mode)."""
    headers = auth_headers("aisha@student.edu")
    posted = client.post(f"/api/students/{student_id}/copilot/onboarding",
                         json={"answers": ["vex", "vex", "vex", "vex"]}, headers=headers)
    assert posted.status_code == 200
    assert posted.json()["assigned"] == "vex"
    # The trainer mode is untouched and independent of the mentor persona.
    assert copilot.default_mode_for("vex") == "chat"
    assert copilot.default_mode_for(posted.json()["assigned"]) != "interview"
    pref = client.get(f"/api/students/{student_id}/tutor/preference", headers=headers).json()
    assert pref["tutor_id"] == "vex"


def test_onboarding_surface_exposes_only_the_four_mentors(client, auth_headers, student_id):
    """Old archetype names never surface in the onboarding flow/payloads."""
    headers = auth_headers("aisha@student.edu")
    state = client.get(f"/api/students/{student_id}/copilot/onboarding-state",
                       headers=headers).json()
    for opt in state["options"]:
        assert opt["key"] not in ("navigator", "strategist", "confidant")
    assert [o["key"] for o in state["options"]] == ["nova", "axel", "sage", "vex"]
    posted = client.post(f"/api/students/{student_id}/copilot/onboarding",
                         json={"answers": ["nova", "nova", "nova", "nova"]},
                         headers=headers).json()
    assert posted["copilot"]["name"] == "Nova"


def test_onboarding_endpoints_authz_matrix(client, auth_headers, student_id):
    guest_state = client.get(f"/api/students/{student_id}/copilot/onboarding-state")
    assert guest_state.status_code == 401
    guest_post = client.post(f"/api/students/{student_id}/copilot/onboarding",
                             json={"answers": ["nova", "nova", "nova", "nova"]})
    assert guest_post.status_code == 401

    company = auth_headers("hr@northstar.com")
    assert client.get(f"/api/students/{student_id}/copilot/onboarding-state",
                      headers=company).status_code == 403
    assert client.post(f"/api/students/{student_id}/copilot/onboarding",
                       json={"answers": ["nova", "nova", "nova", "nova"]},
                       headers=company).status_code == 403

    university = auth_headers("admin@univ.edu")
    assert client.get(f"/api/students/{student_id}/copilot/onboarding-state",
                      headers=university).status_code == 403

    omar = auth_headers("omar@student.edu")
    assert client.get(f"/api/students/{student_id}/copilot/onboarding-state",
                      headers=omar).status_code == 403
    assert client.post(f"/api/students/{student_id}/copilot/onboarding",
                       json={"answers": ["nova", "nova", "nova", "nova"]},
                       headers=omar).status_code == 403
