from app import genai


def test_genai_enabled_accepts_nvidia_key(monkeypatch):
    monkeypatch.setattr(genai, "OPENAI_KEY", None)
    monkeypatch.setattr(genai, "ANTHROPIC_KEY", None)
    monkeypatch.setattr(genai, "NIM_KEY", "nv-test")

    assert genai.genai_enabled() is True


def test_nim_uses_openai_compatible_chat_payload(monkeypatch):
    calls = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "nim reply"}}]}

    def fake_post(url, headers, json, verify, timeout):
        calls.update({"url": url, "headers": headers, "json": json,
                      "verify": verify, "timeout": timeout})
        return Response()

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(genai, "OPENAI_KEY", None)
    monkeypatch.setattr(genai, "ANTHROPIC_KEY", None)
    monkeypatch.setattr(genai, "NIM_KEY", "nv-test")
    monkeypatch.setattr(genai, "NIM_BASE_URL", "https://nim.example/v1")
    monkeypatch.setattr(genai, "NIM_MODEL", "nvidia/test-model")
    monkeypatch.setattr(genai, "_nim_circuit", {"failures": 0, "open_until": 0.0})
    monkeypatch.setattr(genai, "_tls_verify_context", lambda: "os-ca-context")

    assert genai.complete("system prompt", "user prompt", timeout=3) == "nim reply"
    assert calls["url"] == "https://nim.example/v1/chat/completions"
    assert calls["headers"]["Authorization"] == "Bearer nv-test"
    assert calls["json"]["model"] == "nvidia/test-model"
    assert calls["json"]["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]
    assert calls["verify"] == "os-ca-context"
    assert calls["timeout"] == 3


def test_nim_failure_uses_existing_fallback(monkeypatch):
    monkeypatch.setattr(genai, "OPENAI_KEY", None)
    monkeypatch.setattr(genai, "ANTHROPIC_KEY", None)
    monkeypatch.setattr(genai, "NIM_KEY", "nv-test")
    monkeypatch.setattr(genai, "_call_nim", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))

    assert genai.complete("system", "user", fallback="deterministic") == "deterministic"
