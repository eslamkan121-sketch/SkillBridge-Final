"""Safe GenAI provider observability + NIM runtime reliability (Phase 1B / NVIDIA).

Covers, deterministically (never a paid API):
- ``NIM_TIMEOUT_SECONDS`` configuration with bounded clamp
- the configured NIM timeout actually flowing through ``_generate``
- timeout / HTTP failures being reflected in ``provider_status`` (attempted,
  success, error class, HTTP status, timeout flag, latency ms)
- "provider configured but request failed" wording vs "no provider connected"
- zero secret leakage in every status/config payload
- a successful response updating ``last_active_provider``
- reasoning-wrapper artifacts being stripped from visible tutor replies
"""

import json

import httpx
import pytest

from app import genai


@pytest.fixture(autouse=True)
def _clean_slate(monkeypatch):
    """Start every provider-visibility test from a clean, keyless slate."""
    monkeypatch.setattr(genai, "OPENAI_KEY", None)
    monkeypatch.setattr(genai, "ANTHROPIC_KEY", None)
    monkeypatch.setattr(genai, "NIM_KEY", None)
    monkeypatch.setattr(genai, "_LAST_PROVIDER", "")
    monkeypatch.setattr(genai, "_LAST_ATTEMPT", {
        "attempted": False, "provider": None, "success": False,
        "error_class": None, "http_status": None, "timeout": False,
        "elapsed_ms": None,
    })


# ------------------------------------------------------------------ timeout config

def test_nim_timeout_default_and_bounds():
    assert genai.NIM_TIMEOUT_SECONDS == 60
    assert genai._bounded_nim_timeout("999") == 300
    assert genai._bounded_nim_timeout("3") == 15
    assert genai._bounded_nim_timeout("45") == 45
    assert genai._bounded_nim_timeout("oops") == 60
    assert genai._bounded_nim_timeout("") == 60


def test_generate_passes_configured_nim_timeout(monkeypatch):
    monkeypatch.setattr(genai, "NIM_KEY", "k")
    captured = {}

    def fake_nim(system, user, retries=1, max_tokens=1024, timeout=None):
        captured["timeout"] = timeout
        return "nim ok"

    monkeypatch.setattr(genai, "_call_nim", fake_nim)
    assert genai.complete("s", "u") == "nim ok"
    assert captured["timeout"] == genai.NIM_TIMEOUT_SECONDS
    assert genai.complete("s", "u", timeout=25) == "nim ok"
    assert captured["timeout"] == 25


def test_call_nim_defaults_to_configured_timeout(monkeypatch):
    monkeypatch.setattr(genai, "NIM_KEY", "k")
    calls = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "nim reply"}}]}

    def fake_post(url, headers, json, verify, timeout):
        calls["timeout"] = timeout
        calls["verify"] = verify
        return Response()

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(genai, "NIM_BASE_URL", "https://nim.example/v1")
    monkeypatch.setattr(genai, "_nim_circuit", {"failures": 0, "open_until": 0.0})
    monkeypatch.setattr(genai, "_tls_verify_context", lambda: "os-ca-context")
    assert genai._call_nim("s", "u") == "nim reply"
    assert calls["timeout"] == genai.NIM_TIMEOUT_SECONDS
    assert calls["verify"] == "os-ca-context"


def test_nim_visible_content_ignores_reasoning_content():
    data = {
        "choices": [{
            "message": {
                "content": "Final visible answer only.",
                "reasoning_content": "Hidden chain-of-thought must never be used.",
            }
        }]
    }
    assert genai._chat_message_content(data) == "Final visible answer only."


# ------------------------------------------------------------------ failure diagnostics

def test_timeout_failure_reflected_in_status(monkeypatch):
    monkeypatch.setattr(genai, "NIM_KEY", "k")

    def boom(*a, **k):
        raise httpx.ReadTimeout("Request timed out.")

    monkeypatch.setattr(genai, "_call_nim", boom)
    assert genai.complete("s", "u", fallback="fb") == "fb"
    st = genai.provider_status()
    assert st["last_attempted_provider"] == "nvidia"
    assert st["last_success"] is False
    assert st["last_error_type"] == "ReadTimeout"
    assert st["last_timeout"] is True
    assert isinstance(st["last_latency_ms"], int) and st["last_latency_ms"] >= 0
    assert st["active_provider"] == "nvidia"  # configured, even though it failed


def test_http_failure_reflected_in_status(monkeypatch):
    monkeypatch.setattr(genai, "NIM_KEY", "k")

    class FakeResponse:
        status_code = 429

    class FakeHTTPError(Exception):
        response = FakeResponse()

    def boom(*a, **k):
        raise FakeHTTPError("rate limited")

    monkeypatch.setattr(genai, "_call_nim", boom)
    assert genai.complete("s", "u", fallback="fb") == "fb"
    st = genai.provider_status()
    assert st["last_success"] is False
    assert st["last_http_status"] == 429
    assert st["last_timeout"] is False
    assert st["last_error_type"] == "FakeHTTPError"


def test_no_secret_leakage_after_failure(monkeypatch):
    monkeypatch.setattr(genai, "NIM_KEY", "nvapi-SUPER-SECRET-KEY")
    monkeypatch.setattr(genai, "OPENAI_KEY", "sk-proj-SUPER-SECRET-OPENAI")
    monkeypatch.setattr(genai, "_call_nim", lambda *a, **k: (_ for _ in ()).throw(
        httpx.ConnectTimeout("connect abort or timeout with a long description")))

    genai.complete("s", "u", fallback="fb")
    blob = json.dumps(genai.provider_status())
    for marker in ("nvapi-SUPER-SECRET-KEY", "sk-proj-SUPER-SECRET-OPENAI",
                   "connect abort", "Authorization", "Bearer"):
        assert marker not in blob
    assert genai.provider_status()["last_error_type"] == "ConnectTimeout"


# ------------------------------------------------------------------ wording + success

def test_configured_but_failed_fallback_wording(monkeypatch):
    """A configured-but-failing provider must say "temporarily unavailable /
    limited fallback mode", never the misleading "no GenAI provider is connected"."""
    monkeypatch.setattr(genai, "genai_enabled", lambda: True)
    captured = {}

    def fake(system, user, fallback=None, **kw):
        captured["fallback"] = fallback
        return fallback

    monkeypatch.setattr(genai, "complete", fake)
    reply = genai.tutor_reply("Why is the ocean salty?", "ctx", None, None,
                              tutor_id="nova", mode="chat", language="en")
    low = reply.lower()
    assert "temporarily unavailable" in low or "limited fallback" in low
    assert "no genai provider is connected" not in low
    assert "practical skill" not in low


def test_success_updates_last_active_provider(monkeypatch):
    monkeypatch.setattr(genai, "NIM_KEY", "k")
    monkeypatch.setattr(genai, "_call_nim", lambda s, u, **k: "nim answered")
    assert genai.complete("s", "u") == "nim answered"
    st = genai.provider_status()
    assert st["preferred_provider"] == "nvidia"
    assert st["last_active_provider"] == "nvidia"
    assert st["active_provider"] == "nvidia"
    assert st["last_attempted_provider"] == "nvidia"
    assert st["last_success"] is True
    assert st["last_error_type"] is None
    assert isinstance(st["last_latency_ms"], int) and st["last_latency_ms"] >= 0


# ------------------------------------------------------------------ status shape + config endpoint

def test_provider_status_keyless_slate():
    st = genai.provider_status()
    assert st["enabled"] is False
    assert st["preferred_provider"] == "none"
    assert st["active_provider"] == "none"
    assert st["last_active_provider"] is None
    assert st["last_attempted_provider"] is None
    assert st["last_success"] is None
    assert st["last_error_type"] is None
    assert st["priority"] == ["openai", "anthropic", "nvidia"]
    assert st["providers"]["openai"]["configured"] is False
    assert st["providers"]["anthropic"]["configured"] is False
    assert st["providers"]["nvidia"]["configured"] is False


def test_provider_status_never_leaks_keys(monkeypatch):
    monkeypatch.setattr(genai, "OPENAI_KEY", "sk-proj-supersecret-openai")
    monkeypatch.setattr(genai, "ANTHROPIC_KEY", "ant-000-supersecret-anthropic")
    monkeypatch.setattr(genai, "NIM_KEY", "nvapi-supersecret-nim")
    st = genai.provider_status()
    assert st["enabled"] is True
    blob = json.dumps(st)
    assert "sk-proj-supersecret-openai" not in blob
    assert "ant-000-supersecret-anthropic" not in blob
    assert "nvapi-supersecret-nim" not in blob
    assert st["providers"]["openai"]["configured"] is True
    assert st["providers"]["anthropic"]["configured"] is True
    assert st["providers"]["nvidia"]["configured"] is True


def test_provider_preferred_follows_priority(monkeypatch):
    monkeypatch.setattr(genai, "OPENAI_KEY", "o")
    monkeypatch.setattr(genai, "ANTHROPIC_KEY", "a")
    monkeypatch.setattr(genai, "NIM_KEY", "n")
    assert genai.provider_status()["preferred_provider"] == "openai"
    monkeypatch.setattr(genai, "OPENAI_KEY", None)
    assert genai.provider_status()["preferred_provider"] == "anthropic"
    monkeypatch.setattr(genai, "ANTHROPIC_KEY", None)
    assert genai.provider_status()["preferred_provider"] == "nvidia"


def test_provider_status_reports_last_active_after_fallthrough(monkeypatch):
    monkeypatch.setattr(genai, "OPENAI_KEY", "o")
    monkeypatch.setattr(genai, "_LAST_PROVIDER", "nvidia")
    st = genai.provider_status()
    assert st["preferred_provider"] == "openai"
    assert st["active_provider"] == "nvidia"
    assert st["last_active_provider"] == "nvidia"


def test_config_endpoint_exposes_status_without_keys(client):
    r = client.get("/api/config/demo-mode")
    assert r.status_code == 200
    payload = r.json()
    assert payload["genai_enabled"] is False
    provider = payload["provider"]
    assert provider["enabled"] is False
    assert provider["preferred_provider"] == "none"
    assert provider["last_attempted_provider"] is None
    assert provider["priority"] == ["openai", "anthropic", "nvidia"]
    assert "providers" in provider
    blob = json.dumps(payload)
    for marker in ("sk-", "sk-proj-", "ant-", "nvapi-", "Bearer"):
        assert marker not in blob


# ------------------------------------------------------------------ reasoning sanitization

def test_reasoning_wrappers_never_leak():
    sample = (
        "Here's a thinking process:\n"
        "The user is a beginner asking about earthquakes.\n\n"
        "<thinking>Let me be careful to simplify fault mechanics.</thinking>\n\n"
        "```thinking\nstep one: keep it simple\n```\n\n"
        "Analyze User Input: beginner wants a simple explanation.\n\n"
        "An earthquake happens when built-up stress along a fault releases as ground shaking."
    )
    cleaned = genai._strip_reasoning(sample)
    low = cleaned.lower()
    assert "thinking process" not in low
    assert "<thinking>" not in cleaned
    assert "```thinking" not in cleaned
    assert "analyze user input" not in low
    assert "An earthquake happens" in cleaned
    # normal explanation text survives
    assert "ground shaking" in cleaned
    assert genai._clean_visible_reply(sample) == cleaned.strip()


def test_nemotron_numbered_plan_never_leaks():
    """The Nemotron visible chain-of-thought (numbered bold plan) must not reach
    students; only the final answer paragraphs stay. Deterministic offline."""
    sample = (
        "1.  **Analyze User Input:**\n"
        "   - **Student context provided:** University, target role.\n"
        "   - **Student asks:** \"Explain how a refrigerator works.\"\n"
        "   - **Required reply language:** English\n\n"
        "2.  **Determine Topic & Source:**\n"
        "   - This is a general science question.\n"
        "3.  **Draft - Step-by-Step (Mental Rehearsal):**\n"
        "   - *Explanation:* A refrigerator moves heat outside.\n"
        "\n"
        "A refrigerator works on a simple principle: it does not create cold, it "
        "moves heat from inside to outside. Practical example: the back of the fridge "
        "feels warm because that is where the heat is dumped."
    )
    cleaned = genai._strip_reasoning(sample)
    low = cleaned.lower()
    for artifact in ("analyze user input", "mental rehearsal",
                     "determine topic & source", "identify key elements",
                     "**draft - step-by-step", "student context provided"):
        assert artifact not in low, f"{artifact!r} leaked"
    assert "refrigerator works on a simple principle" in low
    assert "practical example" in low
    assert cleaned.startswith("A refrigerator works")


def test_context_reasoning_and_arithmetic_artifacts_never_leak():
    sample = (
        "反思考\n"
        "The student context shows:\n"
        "- University: Aston University\n"
        "- Target role: Junior AI Engineer\n"
        "- Current skill gap: Docker\n"
        "5 - 28 - 2 = -25\n\n"
        "البراكين تثور عندما تتراكم الصهارة والغازات تحت سطح الأرض ثم تجد منفذاً للخروج."
    )
    cleaned = genai._clean_visible_reply(sample, persona_id="nova", language="ar")
    low = cleaned.lower()
    for artifact in ("反思考", "student context shows", "junior ai engineer",
                     "current skill gap", "docker", "5 - 28 - 2"):
        assert artifact not in low
    assert "البراكين" in cleaned


def test_provider_self_identity_is_repaired_without_stripping_educational_mentions():
    leaked = "أهلاً بك! أنا نيموترون، نموذج لغوي من NVIDIA.\n\nأنت حالياً تتعلم Docker حسب SkillBridge."
    cleaned = genai._clean_visible_reply(leaked, persona_id="sage", language="ar")
    assert cleaned.startswith("أنا Sage")
    assert "نيموترون" not in cleaned
    assert "NVIDIA" not in cleaned
    educational = "NVIDIA GPUs are often used to accelerate model training."
    assert genai._clean_visible_reply(educational, persona_id="nova", language="en") == educational
