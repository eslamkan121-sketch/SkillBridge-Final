"""Phase 1.5 — normal chat shows only the selected mentor — frontend source-contract guard.

Runs the node checker that locks the single-mentor chat header: the normal chat
never embeds the four-mentor avatar strip (TutorSelector) and renders only the
selected mentor's avatar/name/traits; the change-mentor UI (settings picker and
onboarding choose grid) still renders all four; selecting a mentor updates the
active tutor (context setTutorId) and persists server-side, restored on the
next load; Vex never auto-enters Interview mode (default mode chat); and
per-mentor conversations are preserved/restored on switch-back.
"""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_chat_mentor_phase15_frontend_contracts_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-chat-mentor-phase15.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"Chat mentor (Phase 1.5) contracts broken:\n"
        f"{result.stdout}\n{result.stderr}")