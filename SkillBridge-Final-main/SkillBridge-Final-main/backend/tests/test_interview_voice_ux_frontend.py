"""Frontend source-contract guard for the voice-first Mock Interview UX.

No real TTS is called here. The Node checker inspects the real frontend sources
for the interview-only voice flow while leaving normal Copilot chat untouched.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_mock_interview_voice_first_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = ROOT / "frontend" / "scripts" / "check-interview-voice-ux.mjs"
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=ROOT, capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, (
        f"Mock Interview voice UX contracts broken:\n{result.stdout}\n{result.stderr}")
