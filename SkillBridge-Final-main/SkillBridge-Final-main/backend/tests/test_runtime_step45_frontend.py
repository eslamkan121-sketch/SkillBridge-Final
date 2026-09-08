"""Step 4.5 — frontend source-contract guard for the Copilot UX changes.

Pins the Step 4.5 FINAL CORRECTION contracts to the actual frontend code (like
the Step 4 language guard): per-tutor conversations, New Chat, interview
isolation, profile Back to Chat, expand/collapse overlay, chat voice via the
shared tutor TTS, microphone input, per-avatar Mock Interview, and the dedicated
assessment exam flow (no readiness gate, Copilot hidden, exit finalization).
Runs the repo's Node checker against the real frontend sources, so any
regression fails the suite.
"""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_frontend_step45_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-step45-copilot.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"Step 4.5 frontend contracts broken:\n{result.stdout}\n{result.stderr}")
