"""Minimal, dependency-free loader for the repository-root .env file.

None of the documented single-command launchers (scripts/start.mjs, start.sh,
start.ps1) load the root .env into the backend's environment, so an app
started on a fresh checkout never sees the ELEVENLABS_* values that live in
that file — and the Chat / Mock Interview voice buttons report "Voice
unavailable" even though the file contains a key. This helper imports the TTS
variables at import time so the documented single command actually configures
ElevenLabs.

Only the ELEVENLABS_* variables are applied, and only when the process is NOT
running under pytest, so:

- a developer's exported shell variables always win (never overwritten),
- the automated test suite stays byte-for-byte deterministic (no .env keys),
- provider keys (ANTHROPIC / OPENAI / NVIDIA / NIM_*) are intentionally left
  alone — they keep their existing behavior and are not affected by this file.
"""
import os
import sys
from pathlib import Path

_ROOT_ENV = Path(__file__).resolve().parent.parent.parent / ".env"
_PREFIXES = ("ELEVENLABS_",)
_loaded = False


def load_root_env():
    """Apply the TTS-related root .env variables to the process env once."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    # Never touch the environment under pytest: the test suite must stay
    # deterministic and is written to run without any paid keys configured.
    if sys.modules.get("pytest") is not None:
        return
    try:
        if not _ROOT_ENV.is_file():
            return
        with open(_ROOT_ENV, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if not key.startswith(_PREFIXES) or key in os.environ:
                    continue
                os.environ[key] = value.strip().strip('"').strip("'")
    except OSError:
        return