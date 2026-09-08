"""Learning Polish pass — frontend source-contract guard.

Covers: human-readable topic labels via one reusable helper, fenced multi-line
example code rendering, practice loading UX + action hierarchy, and the Final
Assessment milestone wording (available anytime, independent of progress).
"""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_learning_polish_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-learning-polish.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"Learning Polish frontend contracts broken:\n"
        f"{result.stdout}\n{result.stderr}")


def test_runtime_learning_phase2_practice_frontend_contracts_still_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-learning-phase2-practice.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"Learning Phase 2 Practice frontend contracts broken:\n"
        f"{result.stdout}\n{result.stderr}")
