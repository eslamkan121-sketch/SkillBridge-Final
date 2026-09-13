"""Practice Scenarios family generalization (Phase 3) — frontend + backend
source-contract guard.

Covers: per-family scenario isolation, deterministic role-blueprints for
out-of-family roles, family-honest scenario cards (family + version), and
versioned attempts surviving target changes.
"""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_scenarios_phase3_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-scenarios-family-phase3.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"Scenario family generalization (Phase 3) contracts broken:\n"
        f"{result.stdout}\n{result.stderr}")