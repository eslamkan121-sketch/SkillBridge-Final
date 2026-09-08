"""Learning Phase 1 frontend source-contract guard.

Pins the canonical Student Learning journey to the actual frontend code:
Start Learning opens the diagnostic/personalized-path flow, visible progress is
topic-based, manual personalized-path completion is absent, and Final Assessment
stays ungated by Learning completion.
"""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_learning_phase1_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-learning-phase1.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"Learning Phase 1 frontend contracts broken:\n{result.stdout}\n{result.stderr}")
