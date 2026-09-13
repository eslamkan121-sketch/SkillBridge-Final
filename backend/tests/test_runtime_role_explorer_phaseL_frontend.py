"""Phase L — role explorer UI — frontend source-contract guard.

Runs the node checker that locks the frontend contracts: backend-mirroring
types + API helpers, recents fetch/record wiring (fire-and-forget, never
blocking), family facet derived only from real role data (Unclassified never
invented), debounced + keyboard-navigable All Roles search (highlight ring,
sr-only live region, no focus theft), provenance + catalogue-data-version meta
built only from real data, and the silent hash deep-link state.
"""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_role_explorer_phaseL_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-role-explorer-phaseL.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"Role explorer (Phase L) contracts broken:\n"
        f"{result.stdout}\n{result.stderr}")