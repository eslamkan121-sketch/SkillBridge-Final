"""Learning Phase 3 Adaptive Remediation frontend source-contract guard."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_learning_phase3_remediation_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = ROOT / "frontend" / "scripts" / "check-learning-phase3-remediation.mjs"
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=ROOT, capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, (
        f"Learning Phase 3 Adaptive Remediation frontend contracts broken:\n"
        f"{result.stdout}\n{result.stderr}")