"""Regression tests for reviewed Python Error Handling learning content."""
from urllib.parse import quote

from app import genai, models


def test_error_handling_path_respects_functions_prerequisite(client, student_id, auth_headers, monkeypatch):
    monkeypatch.setattr(genai, "genai_enabled", lambda: False)
    headers = auth_headers("aisha@student.edu")
    python = models.get_skill_by_name("Python")
    generated = client.post(f"/api/students/{student_id}/learning/{python['id']}/diagnostic/generate", json={}, headers=headers).json()
    # All wrong makes Error Handling weak, but the declared Functions prerequisite
    # must still appear first in the generated path.
    client.post(f"/api/students/{student_id}/learning/{python['id']}/diagnostic/submit", json={"diagnostic_id": generated["diagnostic_id"], "answers": ["not sure"] * len(generated["questions"])}, headers=headers)
    path = client.post(f"/api/students/{student_id}/learning/{python['id']}/personalized-path/generate", json={}, headers=headers).json()
    assert [item["competency"] for item in path["items"][:2]] == ["python_functions", "python_error_handling"]
    error_item = path["items"][1]
    base = f"/api/students/{student_id}/learning/{python['id']}/lessons/{quote(error_item['competency'], safe='')}"
    lesson = client.post(base + "/generate", json={}, headers=headers)
    assert lesson.status_code == 200, lesson.text
    content = lesson.json()["content"]
    assert "except ValueError" in content["example"]["content"]
    assert all(q["competency"] == "Python Error Handling" for q in content["mini_check"]["questions"])
    decision = client.get(f"/api/students/{student_id}/learning/{python['id']}/orchestrator/next", headers=headers)
    assert decision.status_code == 200, decision.text
    assert decision.json()["objective"].startswith("Define a Python function")
