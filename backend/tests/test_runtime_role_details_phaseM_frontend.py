"""Phase M — role details, comparison & career transitions — frontend source guard.

Runs the node checker that locks the frontend contracts: backend-mirroring
types + api.roleProvenance route; the drawer federates ONLY sourced data
(essential/optional via the real skill_kind column, verified/self/none from the
student payload, hidden aliases never shown, honest deprecation banner), related
roles come ONLY from api.roleProvenance and render as a list/table (no graph, no
salaries/probabilities/timing invented), available jobs come ONLY from the
once-per-mount api.recentJobs feed, and the compare modal adds shared/unique
skills, an evidence-based covered split, and a live-jobs row without ever
recomputing a score or mutating profile or role data.
"""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_role_details_phaseM_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-role-details-phaseM.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"Role details & comparison (Phase M) contracts broken:\n"
        f"{result.stdout}\n{result.stderr}")