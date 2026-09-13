"""Runs the Phase N source-contract checker with the project Node runtime."""
import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_job_board_phaseN_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    result = subprocess.run([node, str(checker_script("check-job-board-phaseN.mjs"))],
                            cwd=WORKSPACE_ROOT, capture_output=True, text=True,
                            timeout=120, env=node_env())
    assert result.returncode == 0, f"Phase N jobs-board contracts broken:\n{result.stdout}\n{result.stderr}"
