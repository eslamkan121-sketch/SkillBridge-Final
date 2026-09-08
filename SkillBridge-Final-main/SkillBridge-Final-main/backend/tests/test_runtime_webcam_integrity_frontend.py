"""Frontend source-contract guard for the webcam assessment integrity MVP."""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_frontend_webcam_integrity_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-webcam-integrity.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"Webcam integrity frontend contracts broken:\n{result.stdout}\n{result.stderr}")
