"""Phase J — explainable role and job matching — frontend source-contract guard.

Runs the node checker that locks the frontend contracts: backend-mirroring
breakdown types + API helpers, MatchBreakdown as a pure native-disclosure
renderer (details/summary, no api import, no getElementById, no client-side
score recompute), exactly one backend call per displayed match number, and no
breakdown helper leaking into App/AppContext wiring.
"""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_match_breakdown_phaseJ_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-match-breakdown-phaseJ.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"Explanable match breakdown (Phase J) contracts broken:\n"
        f"{result.stdout}\n{result.stderr}")