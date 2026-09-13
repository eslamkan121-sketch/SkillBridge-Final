"""Phase F — Company Role to Canonical Role mapping — frontend + backend
source-contract guard.

Covers: types carrying the additive mapping fields and backend-mirroring shapes,
the three mapping API helpers, a human-confirmed RoleMappingPanel wired into
every company role row, confirmation flowing only through the single write API
(target or null), and no local-role/student mutation from the panel.
"""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_company_mapping_phaseF_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-company-mapping-phaseF.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"Company Role to Canonical Role mapping (Phase F) contracts broken:\n"
        f"{result.stdout}\n{result.stderr}")