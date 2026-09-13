"""Runtime regression for the live Vex chat-framing failures (FAIL 1 + FAIL 2).

The user reproduced, in the real browser:
- opening a fresh Vex chat and typing "hello" produced the interview framing
  ("Acceptable start. Now go deeper...", "Vex here — your mock interviewer
  for the Cybersecurity Analyst role...");
- Vex answering "Explain DNS, then ask me one question about what you just
  explained." flipped it around and asked the STUDENT to explain
  ("Let's start with the fundamentals. Explain DNS to me...").

Root cause: the frontend's Vex default working mode was 'interview' and every
tutor-select persisted it, so every fresh Vex chat POSTed mode:'interview' on
/api/.../tutor — the backend correctly routed that to the interview engine.
This test runs the Node source-contract checker over the real frontend so the
fix (Vex chat default + never persisting the live session mode + restoring the
working mode after finishing an interview) can never silently regress.

Never calls a paid API.
"""

import shutil
import subprocess

import pytest

from contract_paths import WORKSPACE_ROOT, checker_script, node_env


def test_runtime_copilot_vex_mode_frontend_contract():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to run SkillBridge but was not found")
    script = checker_script("check-copilot-vex-mode.mjs")
    assert script.exists()
    result = subprocess.run([node, str(script)], cwd=WORKSPACE_ROOT, capture_output=True,
                            text=True, timeout=120, env=node_env())
    assert result.returncode == 0, (
        f"frontend Copilot Vex chat-mode contract broken:\n{result.stdout}\n{result.stderr}")