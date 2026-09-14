"""Copilot voice mode (ChatGPT-style) — engine unit-test runner.

Runs ``frontend/scripts/check-copilot-voice-unit.mjs`` (Node 24 native TS
type-stripping imports ``src/lib/voiceSession.ts``) which proves the exact
state machine offline: happy path idle -> listening -> processing -> speaking ->
idle, barge-in during speaking (interrupted -> 400 ms -> listening, playback
stopped), barge-in while /tutor is in flight (fetch aborted, partial transcript
kept, stale reply dropped), the 65 s sentry timeout, /tutor and /tutor/tts error
surfaces, mic errors, stop/clear semantics, lang mapping (en-US/ar-EG), and the
invariant that the user transcript is never sent to /tutor/tts.

The React wiring (useVoiceSession/useTTSPlayer/VoiceMode/VoiceOrb) is
source-guarded by CopilotPanel keeping the Step 4.5 / Interview voice-ux
literals, and by tsc + vite build in the harness flow.
"""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_copilot_voice_unit_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-copilot-voice-unit.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"Copilot voice engine unit tests broken:\n"
        f"{result.stdout}\n{result.stderr}")