"""Phase K — saved jobs + private application tracker — frontend source-contract guard.

Runs the node checker that locks the frontend contracts: backend-mirroring
tracker types + API helpers, the per-row save control passing the row's own
fingerprint and feed coordinates, a tracker panel that calls ONLY tracker
helpers (no student/role writes, no email/calendar/external sync), a
confirm-guarded delete, and archive-as-a-stage (never a destroy).
"""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_job_tracker_phaseK_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-job-tracker-phaseK.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"Job tracker (Phase K) contracts broken:\n"
        f"{result.stdout}\n{result.stderr}")