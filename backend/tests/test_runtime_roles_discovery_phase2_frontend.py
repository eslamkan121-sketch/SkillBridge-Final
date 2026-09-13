"""Skills & Roles discovery redesign (Phase 2) — frontend source-contract guard.

Covers: four top-level views (Recommended / All / Saved / Market Search),
stable display-only deduplication, one shared match source, role-detail drawer,
compare mode (max 3, no salary), deliberate target-change confirmation,
pagination, match-range facet, and honest empty/unavailable states.
"""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_roles_discovery_phase2_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-roles-discovery-phase2.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"Skills & Roles discovery (Phase 2) frontend contracts broken:\n"
        f"{result.stdout}\n{result.stderr}")