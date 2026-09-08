"""Learning Phase 4 Recommended Resources frontend source-contract guard."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_learning_phase4_resources_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = ROOT / "frontend" / "scripts" / "check-learning-phase4-resources.mjs"
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=ROOT, capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, (
        f"Learning Phase 4 resource frontend contracts broken:\n"
        f"{result.stdout}\n{result.stderr}")
