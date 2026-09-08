"""Frontend source-contract guard for the webcam assessment integrity MVP."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_frontend_webcam_integrity_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = ROOT / "frontend" / "scripts" / "check-webcam-integrity.mjs"
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=ROOT, capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, (
        f"Webcam integrity frontend contracts broken:\n{result.stdout}\n{result.stderr}")
