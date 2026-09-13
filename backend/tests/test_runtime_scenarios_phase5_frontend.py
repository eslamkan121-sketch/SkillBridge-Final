"""Connected journey (Phase 5) — frontend + backend source-contract guard.

Covers: Role Detail -> Learning / Practice / Assessments actions, scenario
results -> gated Take Assessment with skill focus, Learning surface for
role-specific scenarios of the current skill, Dashboard Recommended Next Step
with a navigable deterministic-priority rule, breadcrumbs/back context, and the
no-auto verdict/no-target-role-change invariants.
"""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_scenarios_phase5_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-scenarios-phase5.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"Connected journey (Phase 5) contracts broken:\n"
        f"{result.stdout}\n{result.stderr}")