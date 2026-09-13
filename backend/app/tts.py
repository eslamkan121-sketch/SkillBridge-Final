"""ElevenLabs text-to-speech for the mock-interview tutors.

Each tutor (nova/axel/sage/vex) maps to a voice ID from the environment. Audio
is fetched from the ElevenLabs streaming endpoint and cached in-process keyed
by (tutor, text) so repeated lines don't burn quota.
"""
import os
import ssl

import httpx
import truststore

from app.dotenv_local import load_root_env

load_root_env()

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")

TUTOR_VOICES = {
    "nova": os.environ.get("ELEVENLABS_NOVA_VOICE_ID", ""),
    "axel": os.environ.get("ELEVENLABS_AXEL_VOICE_ID", ""),
    "sage": os.environ.get("ELEVENLABS_SAGE_VOICE_ID", ""),
    "vex": os.environ.get("ELEVENLABS_VEX_VOICE_ID", ""),
}

MAX_TEXT_CHARS = 2000  # interview replies are short; guard the payload
_CACHE = {}
_CACHE_LIMIT = 200
_TLS_VERIFY_CONTEXT = None


def _tls_verify_context():
    """Use the operating-system CA store for ElevenLabs HTTPS verification.

    On Windows this picks up local enterprise/antivirus root CAs that are
    trusted by the OS but absent from certifi. Verification remains enabled.
    """
    global _TLS_VERIFY_CONTEXT
    if _TLS_VERIFY_CONTEXT is None:
        _TLS_VERIFY_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return _TLS_VERIFY_CONTEXT


def tts_available():
    return bool(ELEVENLABS_API_KEY and all(TUTOR_VOICES.values()))


def tutor_voice_status():
    """Safe public voice configuration status: booleans only, never IDs."""
    return {tutor: bool(voice_id) for tutor, voice_id in TUTOR_VOICES.items()}


def config_status():
    """Safe TTS diagnostic payload for the UI/API.

    The API key and voice IDs are secrets, so only loaded/not-loaded booleans are
    exposed. The synthesis endpoint still validates the exact selected tutor.
    """
    return {
        "available": tts_available(),
        "api_key_loaded": bool(ELEVENLABS_API_KEY),
        "tutor_voices_loaded": tutor_voice_status(),
        "tts_configured": tts_available(),
    }


def _log_startup_status():
    import logging
    log = logging.getLogger("skillbridge.tts")
    if tts_available():
        log.info("TTS provider configured: ElevenLabs (api_key_loaded=%s, voices=%s)",
                 bool(ELEVENLABS_API_KEY), {k: bool(v) for k, v in TUTOR_VOICES.items()})
    else:
        log.warning("TTS provider NOT configured: missing ElevenLabs API key or voice IDs")


_log_startup_status()


def synthesize(tutor, text):
    """Return MP3 bytes for ``text`` spoken by ``tutor``.

    Raises ValueError for bad input, RuntimeError when ElevenLabs is not
    configured or the upstream call fails.
    """
    tutor = (tutor or "").strip().lower()
    if tutor not in TUTOR_VOICES:
        raise ValueError(f"Unknown tutor voice: {tutor!r}")
    voice_id = TUTOR_VOICES[tutor]
    if not voice_id:
        raise RuntimeError(f"No ElevenLabs voice configured for {tutor}")
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")

    text = (text or "").strip()
    if not text:
        raise ValueError("No text to speak")
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]

    cache_key = (tutor, text)
    cached = _CACHE.get(cache_key)
    if cached:
        return cached

    try:
        resp = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": ELEVENLABS_MODEL,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
            verify=_tls_verify_context(),
            timeout=60,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"ElevenLabs request failed: {exc.__class__.__name__}") from exc
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs returned {resp.status_code}")

    audio = resp.content
    content_type = (resp.headers.get("content-type") or "").lower()
    if not audio:
        raise RuntimeError("ElevenLabs returned empty audio")
    if content_type and not (content_type.startswith("audio/") or "octet-stream" in content_type):
        raise RuntimeError(f"ElevenLabs returned non-audio content type: {content_type.split(';', 1)[0]}")
    if len(_CACHE) >= _CACHE_LIMIT:
        oldest = next(iter(_CACHE))
        _CACHE.pop(oldest, None)
    _CACHE[cache_key] = audio
    return audio
