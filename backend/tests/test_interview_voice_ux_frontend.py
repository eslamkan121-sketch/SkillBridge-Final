"""Frontend source-contract guard for the voice-first Mock Interview UX.

No real TTS is called here. The Node checker inspects the real frontend sources
for the interview-only voice flow while leaving normal Copilot chat untouched.
"""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_mock_interview_voice_first_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-interview-voice-ux.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"Mock Interview voice UX contracts broken:\n{result.stdout}\n{result.stderr}")
