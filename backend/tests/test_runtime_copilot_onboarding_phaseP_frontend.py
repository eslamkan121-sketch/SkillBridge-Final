"""Phase P — copilot onboarding quiz + settings picker — frontend source-contract guard.

Runs the node checker that locks the frontend contracts: onboarding modal and
settings picker read archetype/quiz data ONLY from lib/copilotArchetypes.ts;
each component calls ONLY its own pair of api.* helpers (never provider /
tutor / learning / jobs / student-write helpers, no localStorage, no
window.open); skip and in-flow "Skip for now" resolve through the same
{skipped:true} POST; finish submits the answer set (server recompute is the
assignment authority); settings "Retake the quiz" bridges to the onboarding
forceOpen; App wires both modals to Students only with the "Change your
copilot" menu entry; required a11y + CSS classes exist.
"""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_copilot_onboarding_phaseP_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-copilot-onboarding-phaseP.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"Copilot onboarding + settings (Phase P) contracts broken:\n"
        f"{result.stdout}\n{result.stderr}")