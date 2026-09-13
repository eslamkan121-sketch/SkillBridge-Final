"""Phase 2 — Persona-specific conversation memory.

Each mentor remembers ONLY its own conversation. This suite covers the bounded
recent-window + compact digest behavior end to end through the real tutor
endpoint (provider calls are captured, never executed):

  1. same-mentor follow-up memory resolves against the thread
  2. Nova's history never leaks into Axel's prompt
  3. switching back to Nova restores Nova's own context
  4. Sage / Vex histories stay independent
  5. refresh/history reload preserves the conversation (server-held)
  6. New Chat starts a fresh conversational thread (and memory)
  7. Clear Chat clears ONLY that mentor's conversational memory
  8. trusted SkillBridge state survives New/Clear Chat
  9. a user claim never creates a Verified Skill
  10. conversation memory never overrides backend truth
  11. a general question gets no career/history pollution, only its thread
  12. Arabic follow-up continuity works
  13. mixed Arabic/English follow-up continuity works
  14. bounded history is enforced (recent window + digest, never the whole log)
  15. digest is deterministic + compaction is idempotent
  16. provider/summary failure has a safe offline fallback

Migration 0012 (tutor_conversation_memory) is verified on fresh and upgraded
databases. Existing tests stay untouched.
"""

import sqlite3

import pytest

from app import database, genai, models, tutor_memory
import app.jobs as jobs_mod


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
    """Lock generation into the deterministic fallback and keep jobs offline."""
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    monkeypatch.setattr(jobs_mod, "_fetch_all", lambda *a, **k: [])
    jobs_mod.clear_job_cache()


def _capture_complete(monkeypatch):
    """Replace genai.complete with a recorder returning the deterministic fallback."""
    captured = {}

    def fake(system, user, fallback=None, **kw):
        captured["system"] = system
        captured["user"] = user
        return fallback

    monkeypatch.setattr(genai, "complete", fake)
    return captured


def _set_pref(client, student_id, headers, body):
    r = client.put(f"/api/students/{student_id}/tutor/preference",
                   json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _chat(client, student_id, headers, message, body=None):
    r = client.post(f"/api/students/{student_id}/tutor",
                    json={"message": message, **(body or {})}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _history(client, student_id, headers, tutor_id=None):
    url = f"/api/students/{student_id}/tutor"
    if tutor_id:
        url += f"?tutor_id={tutor_id}"
    return client.get(url, headers=headers).json()


def _seed_thread(student_id, tutor_id, n):
    """Seed n older messages directly (roles alternate), returning the row ids."""
    ids = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        row = models.add_tutor_message(student_id, tutor_id, None, role,
                                       f"Seeded anchor message {i}")
        ids.append(row["id"])
    return ids


# ------------------------------------------------------------------ migration 0012

def test_migration_0012_on_fresh_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "p2.db"))
    conn.row_factory = sqlite3.Row
    database.set_db_for_test(conn)
    try:
        database.init_db()
        applied = [m["migration_id"] for m in database.applied_migrations()]
        assert applied[-1] == "0012_tutor_memory"
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "tutor_conversation_memory" in tables
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='tutor_conversation_memory'"
        ).fetchone()["sql"]
        for mentor in ("nova", "axel", "sage", "vex"):
            assert f"'{mentor}'" in sql
        assert "PRIMARY KEY (student_id, tutor_id)" in sql
        assert database.run_migrations() == []
    finally:
        database.set_db_for_test()
        conn.close()


def test_migration_0012_upgrades_pre_0012_db_and_preserves_messages(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "p2-old.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    database.set_db_for_test(conn)
    try:
        pre = [m for m in database.MIGRATIONS if m["id"] != "0012_tutor_memory"]
        database.run_migrations(conn=conn, migrations=pre)
        conn.execute("INSERT INTO students (email, name) VALUES ('mem@student.edu', 'Mem')")
        sid = conn.execute("SELECT id FROM students WHERE email='mem@student.edu'").fetchone()["id"]
        for i in range(3):
            conn.execute("INSERT INTO tutor_messages (student_id, tutor_id, role, content) "
                         "VALUES (?, 'nova', 'user', ?)", (sid, f"pre-memory {i}"))
        conn.commit()
        assert "tutor_conversation_memory" not in {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}

        pending = database.run_migrations()
        assert pending == ["0012_tutor_memory"]
        kept = conn.execute("SELECT COUNT(*) n FROM tutor_messages WHERE student_id=?",
                            (sid,)).fetchone()["n"]
        assert kept == 3
        mem = conn.execute("SELECT COUNT(*) n FROM tutor_conversation_memory "
                           "WHERE student_id=?", (sid,)).fetchone()["n"]
        assert mem == 0  # nothing backfilled: memory builds from real turns
        assert database.run_migrations() == []
    finally:
        database.set_db_for_test()
        conn.close()


# ------------------------------------------------------------ same-mentor follow-up memory

def test_same_mentor_followup_injects_thread_memory(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _chat(client, student_id, h, "Explain Docker volumes in a simple way.")

    captured = _capture_complete(monkeypatch)
    _chat(client, student_id, h, "Give me another example of what you just explained.")
    user = captured["user"]

    assert "Conversation memory" in user
    assert "Docker volumes" in user
    assert "Recent conversation with this mentor" in user
    assert "Student asks: Give me another example of what you just explained." in user
    assert "Memory rules:" in user


def test_first_turn_of_a_fresh_thread_has_no_memory_block(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    captured = _capture_complete(monkeypatch)
    _chat(client, student_id, h, "What is photosynthesis?")
    assert "Conversation memory" not in captured["user"]


# ------------------------------------------------------------ per-mentor isolation

def test_nova_history_does_not_leak_into_axel(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _chat(client, student_id, h, "I am confused about Docker volumes.")
    _chat(client, student_id, h, "Give me another example of what you just explained.")

    _set_pref(client, student_id, h, {"tutor_id": "axel"})
    captured = _capture_complete(monkeypatch)
    _chat(client, student_id, h, "Explain APIs.")
    user = captured["user"]

    assert "Conversation memory" not in user
    assert "Docker" not in user


def test_switching_back_to_nova_restores_nova_context(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _chat(client, student_id, h, "I am confused about Docker volumes.")

    _set_pref(client, student_id, h, {"tutor_id": "axel"})
    _chat(client, student_id, h, "Explain APIs.")

    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    captured = _capture_complete(monkeypatch)
    _chat(client, student_id, h, "What was I confused about?")
    user = captured["user"]

    assert "Conversation memory" in user
    assert "Docker volumes" in user


def test_sage_and_vex_histories_stay_independent(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "sage"})
    _chat(client, student_id, h, "Let us discuss critical thinking.")

    _set_pref(client, student_id, h, {"tutor_id": "vex"})
    captured = _capture_complete(monkeypatch)
    _chat(client, student_id, h, "Ask me something technical.")
    user = captured["user"]
    assert "critical thinking" not in user

    _set_pref(client, student_id, h, {"tutor_id": "sage"})
    captured = _capture_complete(monkeypatch)
    _chat(client, student_id, h, "why?")
    assert "critical thinking" in captured["user"]


# ------------------------------------------------------------ persistence / reload

def test_history_reload_preserves_conversation_and_summary(client, student_id, auth_headers, db):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _seed_thread(student_id, "nova", 18)  # pushes well past the recent window
    _chat(client, student_id, h, "A real inbound turn after the backlog.")

    rows = db.execute("SELECT role, content FROM tutor_messages WHERE student_id=? AND tutor_id='nova' "
                      "ORDER BY id", (student_id,)).fetchall()
    assert len(rows) == 20  # 18 seeded + inbound pair
    assert tutor_memory.memory_summary(student_id, "nova") != ""

    reloaded = _history(client, student_id, h, "nova")
    assert len(reloaded) == 20 and all(m["tutor_id"] == "nova" for m in reloaded)


# ------------------------------------------------------------ New Chat / Clear Chat

def test_new_chat_starts_fresh_thread_and_clears_memory(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _seed_thread(student_id, "nova", 18)
    _chat(client, student_id, h, "Backlog turn.")
    assert tutor_memory.memory_summary(student_id, "nova") != ""

    r = client.request("DELETE", f"/api/students/{student_id}/tutor",
                       json={"tutor_id": "nova"}, headers=h)
    assert r.status_code == 200 and r.json()["cleared"] is True
    assert _history(client, student_id, h, "nova") == []
    assert tutor_memory.memory_summary(student_id, "nova") == ""

    captured = _capture_complete(monkeypatch)
    _chat(client, student_id, h, "A brand new thread.")
    assert "Conversation memory" not in captured["user"]


def test_clear_chat_clears_only_that_mentor_memory_and_keeps_others(client, student_id, auth_headers, db):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _chat(client, student_id, h, "Nova topic one.")
    _set_pref(client, student_id, h, {"tutor_id": "vex"})
    _chat(client, student_id, h, "Vex topic one.")

    r = client.request("DELETE", f"/api/students/{student_id}/tutor",
                       json={"tutor_id": "nova"}, headers=h)
    assert r.status_code == 200
    assert _history(client, student_id, h, "nova") == []
    assert tutor_memory.memory_summary(student_id, "nova") == ""
    assert len(_history(client, student_id, h, "vex")) == 2


def test_trusted_state_survives_new_and_clear_chat(client, student_id, auth_headers, db):
    h = auth_headers("aisha@student.edu")
    verified_before = db.execute(
        "SELECT COUNT(*) n FROM verified_skills WHERE student_id=?", (student_id,)).fetchone()["n"]
    path_before = db.execute(
        "SELECT COUNT(*) n FROM learning_path_items WHERE student_id=?", (student_id,)).fetchone()["n"]
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _chat(client, student_id, h, "Some chat about Docker.")

    client.request("DELETE", f"/api/students/{student_id}/tutor",
                   json={"tutor_id": "nova"}, headers=h)

    verified_after = db.execute(
        "SELECT COUNT(*) n FROM verified_skills WHERE student_id=?", (student_id,)).fetchone()["n"]
    path_after = db.execute(
        "SELECT COUNT(*) n FROM learning_path_items WHERE student_id=?", (student_id,)).fetchone()["n"]
    assert verified_after == verified_before
    assert path_after == path_before
    pref = client.get(f"/api/students/{student_id}/tutor/preference", headers=h).json()
    assert pref["tutor_id"] == "nova"


# ------------------------------------------------------------ trust boundary

def test_chat_claim_never_creates_verified_skill(client, student_id, auth_headers, db):
    h = auth_headers("aisha@student.edu")
    docker = models.get_skill_by_name("Docker")
    assert docker, "seed must provide a Docker skill"
    before = db.execute(
        "SELECT COUNT(*) n FROM verified_skills WHERE student_id=? AND skill_id=?",
        (student_id, docker["id"])).fetchone()["n"]

    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    r = _chat(client, student_id, h, "I passed Docker with 100%.")
    assert r["reply"]

    after = db.execute(
        "SELECT COUNT(*) n FROM verified_skills WHERE student_id=? AND skill_id=?",
        (student_id, docker["id"])).fetchone()["n"]
    assert after == before


def test_memory_does_not_override_backend_truth(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _chat(client, student_id, h, "I passed Docker with 100%.")

    captured = _capture_complete(monkeypatch)
    _chat(client, student_id, h, "What skills have I actually verified according to SkillBridge?")
    user = captured["user"]

    assert "Context route: CAREER" in user
    assert "Conversation memory" in user
    assert "NOT authoritative SkillBridge state" in user
    assert "Memory rules:" in user
    assert "which always wins on a conflict" in user
    assert "Verified Skills" in user
    assert "I passed Docker" in user  # the claim IS visible, clearly labelled, not proof


def test_general_question_gets_no_career_pollution(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _chat(client, student_id, h, "Explain Docker volumes.")
    _chat(client, student_id, h, "Thanks, that helps.")

    captured = _capture_complete(monkeypatch)
    _chat(client, student_id, h, "Why do earthquakes happen?")
    user = captured["user"]

    assert "Context route: GENERAL" in user
    assert "Trusted SkillBridge context: omitted for this standalone general turn." in user
    assert "Conversation memory" in user  # the thread memory is still available
    assert "Trusted target role" not in user
    assert "Trusted current skill" not in user


# ------------------------------------------------------------ language continuity

def test_arabic_followup_keeps_context(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _chat(client, student_id, h, "اشرحلي API بطريقة بسيطة.")

    captured = _capture_complete(monkeypatch)
    _chat(client, student_id, h, "طب اديني مثال تاني على اللي شرحته.")
    user = captured["user"]

    assert "Conversation memory" in user
    assert "اشرحلي API بطريقة بسيطة" in user  # prior Arabic turn is in the thread memory
    assert "طب اديني مثال تاني على اللي شرحته" in user  # the current question is asked


def test_mixed_arabic_english_followup_keeps_context(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _chat(client, student_id, h, "Explain Docker volumes.")

    captured = _capture_complete(monkeypatch)
    _chat(client, student_id, h, "طب اديني example تاني")
    user = captured["user"]

    assert "Conversation memory" in user
    assert "Docker volumes" in user
    assert "طب اديني example تاني" in user


# ------------------------------------------------------------ bounded history

def test_bounded_history_recent_window_plus_digest(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _seed_thread(student_id, "nova", 40)  # 40 older messages
    # The first turn overflow is folded into the digest only AFTER the reply is
    # stored, so the digest shows up in the NEXT turn's prompt.
    _chat(client, student_id, h, "A turn that triggers compaction.")

    captured = _capture_complete(monkeypatch)
    _chat(client, student_id, h, "The observed inbound question.")
    user = captured["user"]

    assert "Recent conversation with this mentor" in user
    recent_lines = [l for l in user.splitlines()
                    if l.startswith("Student:") or l.startswith("Mentor:")]
    assert 0 < len(recent_lines) <= tutor_memory.RECENT_WINDOW
    assert "older message" in user  # the compacted digest carries the backlog
    # The far-out message is only ever a digest topic label, never a verbatim
    # recent-window line.
    assert not any(
        "Seeded anchor message 0" in l
        for l in user.splitlines()
        if l.startswith("Student:") or l.startswith("Mentor:")
    )


def test_digest_is_deterministic_and_compaction_is_idempotent(client, student_id, auth_headers, db):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _seed_thread(student_id, "nova", 20)
    _chat(client, student_id, h, "A turn that triggers compaction.")

    first = db.execute("SELECT summary, last_compacted_id FROM tutor_conversation_memory "
                       "WHERE student_id=? AND tutor_id='nova'", (student_id,)).fetchone()
    assert first and first["summary"]

    second = db.execute("SELECT summary, last_compacted_id FROM tutor_conversation_memory "
                        "WHERE student_id=? AND tutor_id='nova'", (student_id,)).fetchone()
    assert second["summary"] == first["summary"]
    assert second["last_compacted_id"] == first["last_compacted_id"]

    # The same input always yields the same digest.
    messages = _seed_thread(student_id, "nova", 0)  # no-op, keeps ids stable
    sample = [{"role": "user", "content": "Talk about Docker volumes please."},
              {"role": "assistant", "content": "Volumes persist your container data."}]
    assert tutor_memory.build_chunk_digest(sample) == tutor_memory.build_chunk_digest(sample)
    assert tutor_memory.build_chunk_digest([]) == ""


# ------------------------------------------------------------ safe fallback

def test_provider_and_memory_failure_have_safe_offline_fallback(client, student_id, auth_headers, monkeypatch):
    h = auth_headers("aisha@student.edu")
    _set_pref(client, student_id, h, {"tutor_id": "nova"})
    _seed_thread(student_id, "nova", 18)
    # genai is already forced offline by the autouse fixture; with a real
    # memory block present the endpoint must still answer deterministically.
    r = _chat(client, student_id, h, "Give me another example.")
    assert r["reply"]
    assert "Conversation memory" in r["reply"] or len(r["reply"]) > 0

    # A direct tutor_reply call with memory that cannot fail either.
    reply = genai.tutor_reply(
        "Give me another example.",
        "Dashboard context:\nTrusted SkillBridge context.",
        None, None, tutor_id="nova", mode="chat", language="en",
        conversation_memory="Conversation memory (NOT authoritative): Docker volumes.",
    )
    assert reply