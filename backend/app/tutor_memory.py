"""Persona-specific conversation memory (Phase 2).

Each mentor keeps its OWN bounded conversation memory. Storage of the actual
messages stays in ``tutor_messages`` (already keyed by ``student_id`` +
``tutor_id``); this module adds a rolling, DETERMINISTIC digest of the older
messages that have dropped out of the bounded recent window, persisted in the
per-(student, mentor) ``tutor_conversation_memory`` row:

    summary           .. compact text the LLM sees instead of the full history
    last_compacted_id .. watermark id of the newest message already folded,
                         so compaction is idempotent and never rescans a tail

Everything here is conversation context ONLY — never authoritative SkillBridge
state. The memory carries the student's own chat claims verbatim (labelled as
claims) and can never create or override verified skills, assessment scores,
completion, readiness, CV evidence, or the target role. Trusted facts travel
only through the separate copilot context paths; on any conflict, trusted state
wins. Summary generation is fully deterministic and offline: a provider failure
or missing LLM can never break chat, and the bounded recent window always works
on its own.
"""

import re

from .database import get_cursor
from . import models

# Number of the most recent messages sent verbatim to the LLM. Anything older
# is folded into the compact digest. 16 messages ~ 8 mentor/student turns.
RECENT_WINDOW = 16

# Hard cap on the stored digest so prompt memory stays bounded forever.
SUMMARY_CHAR_CAP = 1600

# Per-message excerpt length shown in the prompt blocks.
EXCERPT_CHARS = 160

# Max topic tokens kept in one folded digest chunk.
TOPIC_CAP = 14

# Max messages folded in a single compaction step (each compaction is bounded,
# so a multi-thousand-message thread cannot spray the digest in one turn).
CHUNK_CAP = 20

_TOPIC_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "it", "at", "by", "on", "in",
    "for", "to", "of", "top", "all", "how", "what", "why", "when", "where",
    "does", "do", "not", "now", "you", "your", "my", "me", "our", "we", "this",
    "that", "these", "those", "is", "are", "was", "were", "be", "been", "being",
    "about", "with", "from", "into", "than", "then", "there", "here", "can",
    "could", "should", "would", "will", "just", "like", "say", "said", "says",
    "ok", "okay", "yes", "have", "has", "had", "more", "most", "as", "so",
    "explain", "give", "gave", "think", "remember", "understand", "let", "make",
    "take", "show", "tell", "know", "need", "want", "use", "using", "used",
}

# Quoted phrases ("..." / '...' / «…» / “…” / ‘…’) are the strongest topic
# signal because they keep the exact naming (English or Arabic).
_QUOTED_PHRASE = re.compile(
    r'["“"«]([^"”"»]{2,60})["”"»]' + r"|'([^']{2,60})'|\u2018([^\u2019]{2,60})\u2019",
)

# Capitalised n-gram (e.g. "Docker volumes") — the strongest cue in English
# text for a named topic. Lowers and keeps the trailing lowercase tail.
_CAP_SEQ = re.compile(r"\b([A-Z][A-Za-z0-9&'\-]*)((?:[ \t]+[a-z][A-Za-z0-9&'\-]*){0,2})\b")


def _one_line(text, limit=EXCERPT_CHARS):
    """Collapse whitespace and truncate a message for the prompt/digest."""
    line = re.sub(r"\s+", " ", str(text or "")).strip()
    if not line:
        return ""
    if len(line) > limit:
        return line[:limit].rstrip() + "…"
    return line


def _extract_topics(text):
    """Deterministic topic hints from a chunk of older conversation.

    Returns a de-duplicated, ordered list of compact topic labels. Only named
    signals are used (quoted phrases, then capitalised n-grams with common
    sentence-opening words filtered) so noise stays low; Arabic naming survives
    through quoted phrases.
    """
    raw = str(text or "")
    topics = []
    for m in re.finditer(_QUOTED_PHRASE, raw):
        phrase = next((g for g in m.groups() if g), None)
        if phrase:
            phrase = re.sub(r"\s+", " ", phrase).strip()
            if 2 <= len(phrase) <= 60:
                topics.append(phrase)
    for m in _CAP_SEQ.finditer(raw):
        head, tail = m.group(1), (m.group(2) or "").strip()
        # Trim trailing stopwords from the lowercase tail ("Docker volumes in"
        # -> "Docker volumes").
        tail_words = tail.split() if tail else []
        while tail_words and tail_words[-1].lower() in _TOPIC_STOPWORDS:
            tail_words.pop()
        tail = (" " + " ".join(tail_words)) if tail_words else ""
        label = (head + tail).strip()
        first = head.lower()
        if len(label) < 3 or first in _TOPIC_STOPWORDS:
            continue
        topics.append(label)
    seen = set()
    out = []
    for t in topics:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
        if len(out) >= TOPIC_CAP:
            break
    return out


def build_chunk_digest(messages):
    """Deterministic compact digest of a chunk of older messages.

    ``messages`` must be chronological rows (dicts with ``role`` and
    ``content``). Returns a small labelled block covering: how many messages
    were folded, the topic hints, the student's first request and the mentor's
    last reply. Never stores reasoning, system prompts, or provider identity.
    """
    messages = [m for m in (messages or []) if m]
    if not messages:
        return ""
    chunk = messages[:CHUNK_CAP]
    users = [m for m in chunk if m.get("role") == "user"]
    assistants = [m for m in chunk if m.get("role") == "assistant"]
    covered = len(messages)
    topics = _extract_topics("\n".join(str(m.get("content") or "") for m in chunk))
    lines = [f"[{covered} older message{'s' if covered != 1 else ''} compacted into conversation memory]"]
    if topics:
        lines.append("Topics discussed: " + ", ".join(topics))
    if users:
        lines.append('Student asked: "' + _one_line(users[0]["content"]) + '"')
    if assistants:
        lines.append('Mentor replied: "' + _one_line(assistants[-1]["content"]) + '"')
    return "\n".join(lines)


def memory_summary(student_id, tutor_id, conversation_id=None):
    """Stored digest for one chat boundary, or '' when none exists yet.

    Phase 4A callers pass ``conversation_id`` so memory follows exactly one
    conversation. Older Phase 2 callers omit it and continue to use the
    per-(student, mentor) compatibility row.
    """
    with get_cursor() as c:
        if conversation_id is not None:
            row = c.execute(
                """
                SELECT summary
                FROM tutor_conversation_memory_threads
                WHERE conversation_id=? AND student_id=? AND tutor_id=?
                """,
                (conversation_id, student_id, tutor_id),
            ).fetchone()
        else:
            row = c.execute(
                "SELECT summary FROM tutor_conversation_memory WHERE student_id=? AND tutor_id=?",
                (student_id, tutor_id),
            ).fetchone()
    return row["summary"] if row else ""


def _write_memory(student_id, tutor_id, summary, last_compacted_id, conversation_id=None):
    with get_cursor() as c:
        if conversation_id is not None:
            c.execute(
                """INSERT INTO tutor_conversation_memory_threads
                   (conversation_id, student_id, tutor_id, summary, last_compacted_id)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(conversation_id) DO UPDATE SET
                     summary=excluded.summary,
                     last_compacted_id=excluded.last_compacted_id,
                     updated_at=datetime('now')""",
                (conversation_id, student_id, tutor_id, summary, last_compacted_id),
            )
        else:
            c.execute(
                """INSERT INTO tutor_conversation_memory
                   (student_id, tutor_id, summary, last_compacted_id)
                   VALUES (?,?,?,?)
                   ON CONFLICT(student_id, tutor_id) DO UPDATE SET
                     summary=excluded.summary,
                     last_compacted_id=excluded.last_compacted_id,
                     updated_at=datetime('now')""",
                (student_id, tutor_id, summary, last_compacted_id),
            )


def clear_memory(student_id, tutor_id, conversation_id=None):
    """Delete conversation memory for one chat boundary.

    Clears only the selected conversation when ``conversation_id`` is supplied.
    The old per-mentor path remains for legacy New/Clear Chat behavior. Trusted
    SkillBridge state is never touched.
    """
    with get_cursor() as c:
        if conversation_id is not None:
            c.execute(
                """
                DELETE FROM tutor_conversation_memory_threads
                WHERE conversation_id=? AND student_id=? AND tutor_id=?
                """,
                (conversation_id, student_id, tutor_id),
            )
        else:
            c.execute(
                "DELETE FROM tutor_conversation_memory WHERE student_id=? AND tutor_id=?",
                (student_id, tutor_id),
            )
    return True


def after_turn(student_id, tutor_id, conversation_id=None):
    """Fold any messages that just dropped out of the recent window.

    Called AFTER the assistant reply is stored. Messages newer than the stored
    ``last_compacted_id`` (but older than the recent window) are folded into
    the digest once; the watermark is advanced so compaction is idempotent.
    A deterministic fallback is guaranteed — no provider is ever required.
    """
    messages = models.list_tutor_messages(
        student_id,
        tutor_id=tutor_id,
        conversation_id=conversation_id,
    )
    if len(messages) <= RECENT_WINDOW:
        return None
    overflow = messages[: len(messages) - RECENT_WINDOW]
    with get_cursor() as c:
        if conversation_id is not None:
            row = c.execute(
                """
                SELECT summary, last_compacted_id
                FROM tutor_conversation_memory_threads
                WHERE conversation_id=? AND student_id=? AND tutor_id=?
                """,
                (conversation_id, student_id, tutor_id),
            ).fetchone()
        else:
            row = c.execute(
                "SELECT summary, last_compacted_id FROM tutor_conversation_memory "
                "WHERE student_id=? AND tutor_id=?",
                (student_id, tutor_id),
            ).fetchone()
    previous = row["summary"] if row else ""
    watermark = row["last_compacted_id"] if row else 0
    to_fold = [m for m in overflow if m["id"] > watermark]
    if not to_fold:
        return None
    digest = build_chunk_digest(to_fold)
    if not digest:
        return None
    combined = (previous.strip() + "\n" + digest).strip() if previous.strip() else digest
    if len(combined) > SUMMARY_CHAR_CAP:
        combined = "…earlier details truncated to keep memory bounded…\n" + combined[-SUMMARY_CHAR_CAP:]
    _write_memory(student_id, tutor_id, combined, to_fold[-1]["id"], conversation_id=conversation_id)
    if conversation_id is not None:
        _write_memory(student_id, tutor_id, combined, to_fold[-1]["id"])
    return combined


def memory_block_for(student_id, tutor_id, messages=None, conversation_id=None):
    """The bounded memory block for one mentor's next prompt turn, or None.

    ``messages`` is the thread BEFORE the inbound turn (main passes the current
    history; when omitted it is read from the DB). Combines the compact digest
    of older conversation with the most recent ``RECENT_WINDOW`` messages. The
    block is explicitly labelled non-authoritative so it can never masquerade
    as trusted SkillBridge state. Returns None on a fresh thread so a first
    turn's prompt stays byte-identical to the pre-memory behavior.
    """
    if messages is None:
        messages = models.list_tutor_messages(
            student_id,
            tutor_id=tutor_id,
            conversation_id=conversation_id,
        )
    summary = memory_summary(student_id, tutor_id, conversation_id=conversation_id)
    recent = messages[-RECENT_WINDOW:]
    if not summary and not recent:
        return None
    lines = [
        "Conversation memory (this mentor's own earlier chat with this student — "
        "NOT authoritative SkillBridge state):"
    ]
    if summary:
        lines.append(summary)
    if recent:
        lines.append("Recent conversation with this mentor (earliest to latest):")
        for m in recent:
            speaker = "Student" if m.get("role") == "user" else "Mentor"
            content = _one_line(m.get("content"), limit=EXCERPT_CHARS)
            lines.append(f"{speaker}: {content}")
    return "\n".join(lines)
