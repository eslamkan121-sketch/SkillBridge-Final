"""Phase 4A - first-class tutor conversations.

These tests cover the backend contract that powers the redesigned chat UI:
New Chat creates a new empty conversation, history restores its mentor, Clear
Chat affects only the active conversation, and memory is scoped to that
conversation instead of the whole tutor.
"""

import sqlite3

import pytest

from app import database, genai, tutor_memory
import app.jobs as jobs_mod


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    monkeypatch.setattr(jobs_mod, "_fetch_all", lambda *a, **k: [])
    jobs_mod.clear_job_cache()


def _headers(auth_headers):
    return auth_headers("aisha@student.edu")


def _create_conversation(client, student_id, headers, tutor_id="nova"):
    r = client.post(
        f"/api/students/{student_id}/tutor/conversations",
        json={"tutor_id": tutor_id},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["conversation"]


def _chat(client, student_id, headers, message, conversation_id, tutor_id=None):
    body = {"message": message, "conversation_id": conversation_id}
    if tutor_id:
        body["tutor_id"] = tutor_id
    r = client.post(f"/api/students/{student_id}/tutor", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _conversation_messages(client, student_id, headers, conversation_id):
    r = client.get(
        f"/api/students/{student_id}/tutor?conversation_id={conversation_id}",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _capture_complete(monkeypatch):
    captured = {}

    def fake(system, user, fallback=None, **kw):
        captured["system"] = system
        captured["user"] = user
        return fallback

    monkeypatch.setattr(genai, "complete", fake)
    return captured


def test_migration_0013_on_fresh_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "phase4a.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    database.set_db_for_test(conn)
    try:
        database.init_db()
        applied = [m["migration_id"] for m in database.applied_migrations()]
        assert applied[-1] == "0013_tutor_conversations"
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"tutor_conversations", "tutor_conversation_memory_threads"} <= tables
        message_cols = {r["name"] for r in conn.execute("PRAGMA table_info(tutor_messages)")}
        assert "conversation_id" in message_cols
        assert database.run_migrations() == []
    finally:
        database.set_db_for_test()
        conn.close()


def test_migration_0013_upgrades_legacy_messages_and_memory(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "phase4a-old.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    database.set_db_for_test(conn)
    try:
        pre = [m for m in database.MIGRATIONS if m["id"] != "0013_tutor_conversations"]
        database.run_migrations(conn=conn, migrations=pre)
        conn.execute("INSERT INTO students (email, name) VALUES ('phase4a@student.edu', 'Phase')")
        sid = conn.execute("SELECT id FROM students WHERE email='phase4a@student.edu'").fetchone()["id"]
        conn.execute("INSERT INTO tutor_preferences (student_id, tutor_id) VALUES (?, 'axel')", (sid,))
        conn.execute(
            "INSERT INTO tutor_messages (student_id, tutor_id, role, content) "
            "VALUES (?, NULL, 'user', 'legacy ownerless chat')",
            (sid,),
        )
        conn.execute(
            "INSERT INTO tutor_messages (student_id, tutor_id, role, content) "
            "VALUES (?, 'nova', 'user', 'legacy nova chat')",
            (sid,),
        )
        conn.execute(
            """
            INSERT INTO tutor_conversation_memory
                (student_id, tutor_id, summary, last_compacted_id)
            VALUES (?, 'nova', 'Legacy memory summary', 7)
            """,
            (sid,),
        )
        conn.commit()

        pending = database.run_migrations()
        assert pending == ["0013_tutor_conversations"]
        conversations = conn.execute(
            "SELECT tutor_id, title FROM tutor_conversations WHERE student_id=? ORDER BY tutor_id",
            (sid,),
        ).fetchall()
        assert [(r["tutor_id"], r["title"]) for r in conversations] == [
            ("axel", "legacy ownerless chat"),
            ("nova", "legacy nova chat"),
        ]
        messages = conn.execute(
            "SELECT tutor_id, conversation_id FROM tutor_messages WHERE student_id=? ORDER BY id",
            (sid,),
        ).fetchall()
        assert messages[0]["tutor_id"] == "axel" and messages[0]["conversation_id"]
        assert messages[1]["tutor_id"] == "nova" and messages[1]["conversation_id"]
        copied = conn.execute(
            """
            SELECT summary, last_compacted_id
            FROM tutor_conversation_memory_threads
            WHERE student_id=? AND tutor_id='nova'
            """,
            (sid,),
        ).fetchone()
        assert copied["summary"] == "Legacy memory summary"
        assert copied["last_compacted_id"] == 7
    finally:
        database.set_db_for_test()
        conn.close()


def test_new_chat_creates_empty_conversation_and_keeps_previous_history(client, student_id, auth_headers):
    h = _headers(auth_headers)
    first = _create_conversation(client, student_id, h, "nova")
    _chat(client, student_id, h, "Explain Docker volumes.", first["id"], tutor_id="nova")

    second = _create_conversation(client, student_id, h, "nova")

    old_messages = _conversation_messages(client, student_id, h, first["id"])
    new_messages = _conversation_messages(client, student_id, h, second["id"])
    assert len(old_messages) == 2
    assert new_messages == []

    visible = client.get(f"/api/students/{student_id}/tutor/conversations", headers=h).json()
    visible_ids = [c["id"] for c in visible["conversations"]]
    assert first["id"] in visible_ids
    assert second["id"] not in visible_ids

    all_history = client.get(
        f"/api/students/{student_id}/tutor/conversations?include_empty=true",
        headers=h,
    ).json()
    assert {c["id"] for c in all_history["conversations"]} >= {first["id"], second["id"]}


def test_clear_chat_only_clears_current_conversation_and_keeps_trusted_state(client, student_id, auth_headers, db):
    h = _headers(auth_headers)
    first = _create_conversation(client, student_id, h, "nova")
    second = _create_conversation(client, student_id, h, "nova")
    _chat(client, student_id, h, "Explain SQL indexes.", first["id"], tutor_id="nova")
    _chat(client, student_id, h, "Explain Docker images.", second["id"], tutor_id="nova")
    db.execute(
        """
        INSERT INTO tutor_conversation_memory_threads
            (conversation_id, student_id, tutor_id, summary, last_compacted_id)
        VALUES (?, ?, 'nova', 'Clear me', 1)
        """,
        (first["id"], student_id),
    )
    db.execute(
        """
        INSERT INTO tutor_conversation_memory_threads
            (conversation_id, student_id, tutor_id, summary, last_compacted_id)
        VALUES (?, ?, 'nova', 'Keep me', 1)
        """,
        (second["id"], student_id),
    )
    db.commit()
    verified_before = db.execute(
        "SELECT COUNT(*) n FROM verified_skills WHERE student_id=?",
        (student_id,),
    ).fetchone()["n"]

    r = client.request(
        "DELETE",
        f"/api/students/{student_id}/tutor",
        json={"tutor_id": "nova", "conversation_id": first["id"]},
        headers=h,
    )

    assert r.status_code == 200, r.text
    assert _conversation_messages(client, student_id, h, first["id"]) == []
    assert len(_conversation_messages(client, student_id, h, second["id"])) == 2
    assert tutor_memory.memory_summary(student_id, "nova", conversation_id=first["id"]) == ""
    assert tutor_memory.memory_summary(student_id, "nova", conversation_id=second["id"]) == "Keep me"
    verified_after = db.execute(
        "SELECT COUNT(*) n FROM verified_skills WHERE student_id=?",
        (student_id,),
    ).fetchone()["n"]
    assert verified_after == verified_before


def test_history_send_restores_the_conversations_mentor(client, student_id, auth_headers):
    h = _headers(auth_headers)
    nova = _create_conversation(client, student_id, h, "nova")
    axel = _create_conversation(client, student_id, h, "axel")
    _chat(client, student_id, h, "Explain model training.", nova["id"], tutor_id="nova")
    _chat(client, student_id, h, "Give me a build task.", axel["id"], tutor_id="axel")
    client.put(f"/api/students/{student_id}/tutor/preference",
               json={"tutor_id": "axel"}, headers=h)

    restored = _chat(client, student_id, h, "What did we cover here?", nova["id"])

    assert restored["tutor_id"] == "nova"
    messages = _conversation_messages(client, student_id, h, nova["id"])
    assert messages
    assert all(m["tutor_id"] == "nova" for m in messages)


def test_memory_is_scoped_to_the_selected_conversation(client, student_id, auth_headers, db, monkeypatch):
    h = _headers(auth_headers)
    first = _create_conversation(client, student_id, h, "nova")
    second = _create_conversation(client, student_id, h, "nova")
    db.execute(
        """
        INSERT INTO tutor_conversation_memory_threads
            (conversation_id, student_id, tutor_id, summary, last_compacted_id)
        VALUES (?, ?, 'nova', 'Private Needle Memory', 99)
        """,
        (first["id"], student_id),
    )
    db.commit()

    captured = _capture_complete(monkeypatch)
    _chat(client, student_id, h, "Can you make that easier?", second["id"], tutor_id="nova")

    assert "Private Needle Memory" not in captured["user"]
    assert "Recent conversation with this mentor" not in captured["user"]
