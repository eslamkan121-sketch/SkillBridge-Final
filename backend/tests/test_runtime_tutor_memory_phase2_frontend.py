"""Runtime wrapper for the Phase 2 per-tutor conversation memory frontend contract checker.

Verifies that the real frontend source enforces per-tutor history, per-tutor
send, and per-tutor Clear Chat so the backend's own per-mentor memory row is
always populated and cleared by the right mentor's activity.  Never calls a paid
provider.
"""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_tutor_memory_phase2_frontend_contract():
    """Per-tutor history/send/clear stays wired to the per-mentor backend memory."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-tutor-memory-phase2.mjs")
    assert script.exists()
    result = subprocess.run(
        [node, str(script)],
        cwd=WORKSPACE_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env=node_env(),
    )
    assert result.returncode == 0, (
        f"frontend tutor-memory-phase2 contract broken:\n{result.stdout}\n{result.stderr}"
    )