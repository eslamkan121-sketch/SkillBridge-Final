"""Phase 5 — Proctored assessment: scoring, flag logic, verified-profile update."""
from app import integrity, models, genai


def test_timing_anomaly_flag():
    flags = integrity.evaluate_attempt(question_count=4, total_seconds=30,
                                       free_text_answers=[], local_tab_switches=0)
    codes = {f["code"] for f in flags}
    assert "timing_anomaly" in codes


def test_tab_switch_flag():
    flags = integrity.evaluate_attempt(4, 300, [], local_tab_switches=2)
    assert sum(1 for f in flags if f["code"] == "tab_switch") == 2


def test_ai_text_detection():
    polished = ("In conclusion, the comprehensive approach leverages robust infrastructure "
                "to streamline operations. Furthermore, it is essential to harness state-of-the-art "
                "methodologies. Moreover, we utilize cutting-edge techniques.")
    flagged, flag = integrity.detect_ai_text(polished)
    assert flagged and any(f["code"] == "ai_text" for f in flag)

    plain = "I set up docker and ran the container. It worked."
    flagged, flag = integrity.detect_ai_text(plain)
    assert not flagged


def test_evaluate_merges_client_and_server_flags():
    flags = integrity.evaluate_attempt(4, 60, ["In conclusion, robust and comprehensive work"],
                                       local_tab_switches=1)
    codes = {f["code"] for f in flags}
    assert "tab_switch" in codes and "ai_text" in codes


def test_high_severity_flag_forces_fail(client, student_id, auth_headers):
    # Generate a quiz, answer everything with the model answer (would otherwise pass),
    # but include a clearly AI-styled free-text answer which is a high-severity flag.
    headers = auth_headers("aisha@student.edu")
    docker = models.get_skill_by_name("Docker")
    r = client.post(f"/api/students/{student_id}/assessments/generate",
                    json={"skill_id": docker["id"]}, headers=headers)
    assert r.status_code == 200
    questions = r.json()["questions"]
    answers = [q["answer"] for q in questions]
    poisoned = "In conclusion, we leverage a robust and comprehensive framework. Furthermore, it is essential to utilize cutting-edge and seamless approaches. Moreover, this streamlines and harnesses state-of-the-art methodologies for overall improvement."
    res = client.post(f"/api/students/{student_id}/assessments", json={
        "skill_id": docker["id"], "questions": questions, "answers": answers,
        "total_seconds": 300, "tab_switches": 0,
        "free_text_answers": [poisoned],
    }, headers=headers)
    data = res.json()
    assert data["score"] >= 70  # semantically answered correctly
    assert data["passed"] is False  # but high-severity ai_text flag forces fail
    assert any(f["code"] == "ai_text" for f in data["flags"])


def test_clean_pass_updates_verified_profile(client, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    student = models.get_student(student_id)
    docker = models.get_skill_by_name("Docker")
    before_verified = {v["name"] for v in student["verified_skills"]}

    r = client.post(f"/api/students/{student_id}/assessments/generate",
                    json={"skill_id": docker["id"], "num_questions": 10}, headers=headers)
    questions = r.json()["questions"]
    assert len(questions) == 10  # real 10-question assessment
    answers = [q["answer"] for q in questions]

    res = client.post(f"/api/students/{student_id}/assessments", json={
        "skill_id": docker["id"], "questions": questions, "answers": answers,
        "total_seconds": 300, "tab_switches": 0, "free_text_answers": [],
    }, headers=headers)
    data = res.json()
    assert data["passed"] is True
    assert data["score"] >= 70
    assert len(data.get("per_question") or []) == len(questions)

    updated = models.get_student(student_id)
    assert "Docker" in {v["name"] for v in updated["verified_skills"]}
    # skill moved into verified profile
    assert "Docker" in {v["name"] for v in updated["verified_skills"]}


def test_fail_does_not_verify(client, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    # Wrong answers -> score below threshold -> no verification
    skill = models.create_skill("K8s", "DevOps")
    r = client.post(f"/api/students/{student_id}/assessments/generate",
                    json={"skill_id": skill["id"]}, headers=headers)
    questions = r.json()["questions"]
    answers = ["definitely wrong" for _ in questions]
    res = client.post(f"/api/students/{student_id}/assessments", json={
        "skill_id": skill["id"], "questions": questions, "answers": answers,
        "total_seconds": 300, "tab_switches": 0, "free_text_answers": [],
    }, headers=headers)
    data = res.json()
    assert data["passed"] is False
    assert "K8s" not in {v["name"] for v in models.get_student(student_id)["verified_skills"]}


def test_practice_mode_reuses_prior_attempt(client, student_id, auth_headers):
    headers = auth_headers("aisha@student.edu")
    docker = models.get_skill_by_name("Docker")
    # first attempt -> 10 questions
    r = client.post(f"/api/students/{student_id}/assessments/generate",
                    json={"skill_id": docker["id"], "num_questions": 10}, headers=headers)
    questions = r.json()["questions"]
    answers = [q["answer"] for q in questions]
    res = client.post(f"/api/students/{student_id}/assessments", json={
        "skill_id": docker["id"], "questions": questions, "answers": answers,
        "total_seconds": 300, "tab_switches": 0, "free_text_answers": [],
    }, headers=headers)
    assert res.json()["passed"] is True

    # practice mode returns the SAME questions plus previous per-question results
    r = client.post(f"/api/students/{student_id}/assessments/generate",
                    json={"skill_id": docker["id"], "num_questions": 10, "practice": True}, headers=headers)
    data = r.json()
    assert data["practice"] is True
    assert data["previous_score"] is not None
    assert len(data["questions"]) == 10
    assert len(data["previous_results"]) == 10


def test_free_text_grader_marks_paraphrase_correct():
    """A genuine paraphrase of the model answer must be graded correct — the
    regression that the old word-overlap (>=0.4 of model words) failed."""
    model_ans = ("A generator yields items lazily one at a time, so it uses constant "
                 "memory for large or infinite sequences, e.g. streaming a huge log file line by line.")
    paraphrase = ("Generators produce values lazily instead of building a whole list up front, "
                  "which means memory stays fixed even for huge or endless sequences like "
                  "processing a massive log one line at a time.")
    assert genai.grade_free_text(model_ans, paraphrase) is True


def test_free_text_grader_accepts_low_overlap_but_correct_paraphrases():
    """Real answers use different vocabulary to the model answer. These four were
    all flagged incorrect by the old exact-word-overlap fallback even though each
    is a technically-correct paraphrase — they must pass."""
    cases = [
        # (model answer, correct low-overlap student answer)
        ("Generators trade a little overhead for lazy evaluation — essential for large data streams.",
         "processing large files line by line to save memory, or when you can stop early after finding the first match"),
        ("Tracebacks tell you the failing line; confirm the key truly exists before changing logic.",
         "print the dictionary's keys to see what's available, then check spelling and verify the data source"),
        ("Resilience = timeouts + bounded retries + explicit error handling.",
         "implement retry logic with exponential backoff and a timeout using tenacity or requests with urllib3.Retry"),
        ("Dataclasses encode a fixed schema; dicts are flexible but untyped.",
         "when you have a fixed schema, need type hints and autocomplete, or want to attach methods and default values"),
    ]
    for model_ans, student_ans in cases:
        assert genai.grade_free_text(model_ans, student_ans) is True, (
            f"correct paraphrase wrongly failed:\n  model: {model_ans}\n  answer: {student_ans}")


def test_free_text_grader_rejects_off_topic_and_empty():
    model_ans = ("Use docker logs to inspect the output, run the container in the foreground "
                 "to see errors live, and check the entrypoint command — often the process exits "
                 "immediately.")
    assert genai.grade_free_text(model_ans, "I like pizza and football.") is False
    assert genai.grade_free_text(model_ans, "") is False
    assert genai.grade_free_text(model_ans, "ok") is False
    # a substantively wordy but completely off-topic answer (zero concept overlap)
    assert genai.grade_free_text(model_ans,
        "In conclusion, we leverage a robust and comprehensive framework. Furthermore, "
        "it is essential to utilize cutting-edge and seamless approaches for overwhelmand.") is False
    # exact/verbatim model answer always correct
    assert genai.grade_free_text(model_ans, model_ans) is True


def test_free_text_grader_is_independent_of_ai_text_flag():
    """Grading is about substance; the AI-text integrity flag is separate. A
    polished but on-topic answer should still grade correct, while remaining
    something the flag detector can flag."""
    model_ans = ("Docker images are immutable build-time templates; containers are the running, "
                 "isolated instances created from them.")
    polished = ("In conclusion, docker images serve as immutable build-time templates while "
                "containers are the comprehensive, running instances that leverage those templates.")
    assert genai.grade_free_text(model_ans, polished) is True
    flagged, flags = integrity.detect_ai_text(polished)
    assert flagged and any(f["code"] == "ai_text" for f in flags)


def test_activity_endpoint_is_per_student_gamified_summary(client, student_id, auth_headers):
    """The dashboard's gamification summary derives from real persisted activity:
    XP, level, backwards-fill streak and badges — all per student."""
    headers = auth_headers("aisha@student.edu")
    r = client.get(f"/api/students/{student_id}/activity", headers=headers)
    assert r.status_code == 200
    data = r.json()
    # never exposes cohort or other students' data
    assert "leaderboard" in data and data["leaderboard"]["status"] == "coming_soon"
    # derived from real records on a seeded student
    assert data["xp"] > 0
    assert data["level"] >= 1
    assert data["assessments_taken"] >= 1
    assert data["verified_skills"] >= 1
    for b in data["badges"]:
        assert {"code", "name", "desc", "hint", "earned"} <= set(b)
    # another student cannot read this one's activity
    other = auth_headers("omar@student.edu")
    r2 = client.get(f"/api/students/{student_id}/activity", headers=other)
    assert r2.status_code == 403
