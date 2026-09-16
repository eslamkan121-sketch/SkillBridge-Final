"""Live-language runtime regression for Phase 5.5 Step 4.

Reproduces, over the real HTTP API, the exact reported case:

    Language = العربية
    "اشرحلي Docker containers بطريقة بسيطة"
    -> the Copilot replied in English

Root cause traced end-to-end: the frontend ``api.tutorSend`` did NOT include
``language`` in the POST body, so each tutor reply depended on whatever language
preference happened to be stored. When the stored preference did not match the
UI selection (e.g. an earlier English session, a silently failed PUT, a stale
row), the backend correctly served the stored language — English — and the
student saw an English reply despite العربية being selected.

These tests pin the fixed contract:
1. the real frontend request now carries ``language`` (Node checker + runtime),
2. the backend resolves that body language without replacing it (never auto/en),
3. ``tutor_reply`` receives lang="ar" and the Arabic directive reaches the
   provider call boundary (genai.complete system prompt),
4. the provider/fallback result is returned as-is (no re-translation to English),
5. the deterministic fallback replies Arabic for this exact message,
6. Auto still detects this exact message as Arabic,
7. English pins English,
8. the request language never rewrites the stored preference,
9. prior English conversation state cannot override the selected Arabic.

Never calls a paid API (deterministic fixture below).
"""

import re
import shutil
import subprocess

import pytest

from app import genai
import app.jobs as jobs_mod
from contract_paths import WORKSPACE_ROOT, checker_script, node_env

ARABIC_EXACT_MESSAGE = "اشرحلي Docker containers بطريقة بسيطة"

_ARABIC_RANGES = (
    (0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF), (0xFE70, 0xFEFF),
)

_ARABIC_INSTRUCTION_MARK = "Reply in clear, natural Arabic"


def has_arabic(text):
    return any(lo <= ord(ch) <= hi for ch in str(text or "")
               for lo, hi in _ARABIC_RANGES)


def arabic_ratio(text):
    letters = [ch for ch in str(text or "") if ch.isalpha()]
    if not letters:
        return 0.0
    arabic = sum(1 for ch in letters
                 if any(lo <= ord(ch) <= hi for lo, hi in _ARABIC_RANGES))
    return arabic / len(letters)


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
        captured["fallback"] = fallback
        return fallback

    monkeypatch.setattr(genai, "complete", fake)
    return captured


def _set_stored_language(client, student_id, headers, language):
    r = client.put(f"/api/students/{student_id}/tutor/preference",
                   json={"language": language}, headers=headers)
    assert r.status_code == 200, r.text


def _tutor(client, student_id, headers, message, body=None):
    """Mirror api.tutorSend's exact payload (post-fix shape incl. language)."""
    base = {
        "message": message,
        "skill_id": None,
        "page": "dashboard",
        "competency": None,
        "job_title": None,
        "job_url": None,
        "mode": "chat",
    }
    base.update(body or {})
    return client.post(f"/api/students/{student_id}/tutor", json=base, headers=headers)


# ------------------------------------------------------------------ exact live bug reproduction

def test_runtime_arabic_pins_reply_even_against_stored_english(client, student_id, auth_headers, monkeypatch):
    """THE reported case: العربية selected + Arabic message must yield Arabic.

    Stored preference is deliberately English (stale/earlier session). Before
    the fix the frontend dropped ``language`` from the request, so this same
    POST would have resolved to English. The fixed frontend sends language:"ar"
    and the backend must honor it.
    """
    h = auth_headers("aisha@student.edu")
    _set_stored_language(client, student_id, h, "en")
    captured = _capture_complete(monkeypatch)

    r = _tutor(client, student_id, h, ARABIC_EXACT_MESSAGE,
               body={"language": "ar"})

    assert r.status_code == 200, r.text
    data = r.json()
    # 2. backend resolves the pinned body language: never auto, never en.
    assert data.get("language") == "ar"
    # 3a. tutor_reply received lang="ar": the Arabic directive is in the system prompt.
    assert _ARABIC_INSTRUCTION_MARK in captured["system"]
    assert "Language: Arabic" in captured["user"]
    # 4. the route returns the provider (here: deterministic) output as-is.
    assert data.get("reply") == captured["fallback"]
    # the reply itself is genuinely Arabic, not an English stub.
    reply = data.get("reply") or ""
    assert has_arabic(reply)
    assert arabic_ratio(reply) > 0.3
    # 8. the request language never rewrites the stored preference.
    pref = client.get(f"/api/students/{student_id}/tutor/preference",
                      headers=h).json()
    assert pref.get("language") == "en"


def test_runtime_missing_language_reproduces_the_live_bug(client, student_id, auth_headers):
    """Negative control: exactly what the buggy frontend sent.

    Stored 'en' + NO language in the body reproduces the live English reply and
    pins the root cause — the language decision fell back to the stored value.
    The fixed frontend no longer sends this shape for an Arabic selection
    (see the Node checker test), so this stays a documenting regression lane.
    """
    h = auth_headers("aisha@student.edu")
    _set_stored_language(client, student_id, h, "en")
    r = _tutor(client, student_id, h, ARABIC_EXACT_MESSAGE)
    data = r.json()
    assert data.get("language") == "en"
    reply = data.get("reply") or ""
    assert not has_arabic(reply)
    assert "[Nova's voice]" not in reply


def test_runtime_auto_detects_this_exact_message_as_arabic(client, student_id, auth_headers):
    """Auto + the exact reported message -> Arabic (backend detection)."""
    h = auth_headers("aisha@student.edu")
    _set_stored_language(client, student_id, h, "auto")
    r = _tutor(client, student_id, h, ARABIC_EXACT_MESSAGE)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("language") == "ar"
    assert has_arabic(data.get("reply") or "")


def test_runtime_english_pins_english(client, student_id, auth_headers):
    """Language = English + the same Arabic message -> English (preference wins)."""
    h = auth_headers("aisha@student.edu")
    _set_stored_language(client, student_id, h, "en")
    r = _tutor(client, student_id, h, ARABIC_EXACT_MESSAGE,
               body={"language": "en"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("language") == "en"
    assert not has_arabic(data.get("reply") or "")


def test_runtime_prior_english_thread_never_overrides_arabic(client, student_id, auth_headers):
    """9. History doesn't matter: an English turn then an Arabic-selected turn.

    The backend only ever looks at the stored preference + the current request's
    language (Auto detection reads the current message), never at prior replies.
    """
    h = auth_headers("aisha@student.edu")
    _set_stored_language(client, student_id, h, "en")
    r1 = _tutor(client, student_id, h, "Please explain Docker now")
    assert r1.json().get("language") == "en"

    # Student now selects العربية; new request pins ar -> Arabic regardless of
    # the English conversation just seen.
    r2 = _tutor(client, student_id, h, ARABIC_EXACT_MESSAGE,
                body={"language": "ar"})
    assert r2.json().get("language") == "ar"
    assert has_arabic(r2.json().get("reply") or "")


# ------------------------------------------------------------------ frontend contract guard

def test_runtime_frontend_sends_language_on_every_tutor_request():
    """1. The actual browser request must carry the selected language.

    Runs the repo's Node checker against the real frontend source. This test is
    RED whenever someone removes `language` from api.tutorSend / CopilotPanel.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-tutor-language.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"frontend tutor-language contract broken:\n{result.stdout}\n{result.stderr}")


def test_runtime_detection_unit_matches_spec_example():
    """Raw detection sanity for the exact message (backend-owned decision)."""
    from app import copilot
    assert copilot.detect_language(ARABIC_EXACT_MESSAGE) == "ar"
    assert copilot.detect_language("Please explain Docker containers simply") == "en"
    assert copilot.resolve_language("ar", ARABIC_EXACT_MESSAGE) == "ar"
    assert copilot.resolve_language("auto", ARABIC_EXACT_MESSAGE) == "ar"
    # 2. explicit pins are never replaced by auto/en.
    assert copilot.resolve_language("en", "اشرحلي Docker") == "en"


# ------------------------------------------------------------------ live Arabizi mirroring (T1-T4)

_ARABIZI_GREETING = "ezayek ya nova 3amla eh"
_ARABIZI_DOCKER = "ana msh fahm el docker ports"
_ARABIC_SCRIPT_GREETING = "إزيك يا نوفا"


def test_live_arabizi_greeting_mirrors_arabic(client, student_id, auth_headers):
    """T1 — auto + "ezayek ya nova 3amla eh" -> Arabic reply, no meta-commentary."""
    h = auth_headers("aisha@student.edu")
    _set_stored_language(client, student_id, h, "auto")
    r = _tutor(client, student_id, h, _ARABIZI_GREETING)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("language") == "ar"
    reply = data.get("reply") or ""
    assert has_arabic(reply)
    low = reply.lower()
    assert "i'll respond" not in low
    assert "it looks like" not in low


def test_live_arabizi_docker_question_mirrors_arabic(client, student_id, auth_headers):
    """T2 — auto + mixed Arabizi/English "docker ports" -> Arabic reply."""
    h = auth_headers("aisha@student.edu")
    _set_stored_language(client, student_id, h, "auto")
    r = _tutor(client, student_id, h, _ARABIZI_DOCKER)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("language") == "ar"
    assert has_arabic(data.get("reply") or "")


def test_live_english_query_stays_english(client, student_id, auth_headers):
    """T3 — "how are you" must still resolve English (regression guard)."""
    h = auth_headers("aisha@student.edu")
    _set_stored_language(client, student_id, h, "auto")
    r = _tutor(client, student_id, h, "how are you")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("language") == "en"
    assert not has_arabic(data.get("reply") or "")


def test_live_arabic_script_greeting_ends_in_arabic(client, student_id, auth_headers):
    """T4 — an Arabic reply must not close on an English sentence."""
    h = auth_headers("aisha@student.edu")
    _set_stored_language(client, student_id, h, "auto")
    r = _tutor(client, student_id, h, _ARABIC_SCRIPT_GREETING)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("language") == "ar"
    reply = (data.get("reply") or "").strip()
    assert has_arabic(reply)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?؟])\s+", reply) if s.strip()]
    assert sentences, "reply must contain at least one sentence"
    assert has_arabic(sentences[-1]), f"last sentence must be Arabic: {sentences[-1]!r}"


def test_live_arabizi_negative_no_translation_narration(client, student_id, auth_headers):
    """T5 — negative: "3amla eh" (auto) must not narrate translation decisions.

    Catches model invention on the live provider: the reply must never contain
    "in English", "translate", "I'll respond", or "Since you wrote".
    """
    h = auth_headers("aisha@student.edu")
    _set_stored_language(client, student_id, h, "auto")
    r = _tutor(client, student_id, h, "3amla eh")
    assert r.status_code == 200, r.text
    reply = (r.json().get("reply") or "").strip()
    low = reply.lower()
    assert "in english" not in low
    assert "translate" not in low
    assert "i'll respond" not in low
    assert "since you wrote" not in low
    assert has_arabic(reply)


def test_live_longer_arabizi_docker_volumes_question(client, student_id, auth_headers):
    """T6 — longer, specific Arabizi must mirror Arabic without degenerating.

    "momken tshar7ly docker volumes bel3araby law samaht" is a normal long
    Arabizi request (no Arabic script). Auto must resolve it ar and the reply
    must be Arabic or Arabic+English technical — never a degenerate stub or an
    English-only response.
    """
    from app import copilot
    msg = "momken tshar7ly docker volumes bel3araby law samaht"
    assert copilot.detect_language(msg) == "ar"
    assert copilot.resolve_language("auto", msg) == "ar"
    h = auth_headers("aisha@student.edu")
    _set_stored_language(client, student_id, h, "auto")
    r = _tutor(client, student_id, h, msg)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("language") == "ar"
    reply = (data.get("reply") or "").strip()
    assert has_arabic(reply)
    low = reply.lower()
    assert "in english" not in low
    assert "translate" not in low
    assert "i'll respond" not in low
