"""Practice Scenarios UX upgrade (Phase 4) — frontend + backend source-contract
guard.

Covers: per-decision consequences with professional reasoning, explicit hint
penalty policy, results -> learning follow-up, save-and-resume, per-attempt
history with date/version/score/role, library status groups + difficulty filter
+ Recommended Next, and 390px-safe styles.
"""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_scenarios_phase4_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-scenarios-phase4.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"Practice Scenarios UX upgrade (Phase 4) contracts broken:\n"
        f"{result.stdout}\n{result.stderr}")