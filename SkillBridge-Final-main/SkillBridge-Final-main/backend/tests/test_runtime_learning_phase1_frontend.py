"""Learning Phase 1 frontend source-contract guard.

Pins the canonical Student Learning journey to the actual frontend code:
Start Learning opens the diagnostic/personalized-path flow, visible progress is
topic-based, manual personalized-path completion is absent, and Final Assessment
stays ungated by Learning completion.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_learning_phase1_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = ROOT / "frontend" / "scripts" / "check-learning-phase1.mjs"
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=ROOT, capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, (
        f"Learning Phase 1 frontend contracts broken:\n{result.stdout}\n{result.stderr}")
