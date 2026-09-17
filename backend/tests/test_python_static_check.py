from app import lessons, practice


def _lesson():
    return {"content": lessons.generate_lesson("Python", "Python Functions", "learn")}


def test_static_check_accepts_equivalent_supported_conversion_forms_without_execution():
    result = practice.python_functions_static_check(_lesson(), """def celsius_to_fahrenheit(value):
    return value * 1.8 + 32
""")
    assert result["status"] == "looks_structurally_sound"
    assert "not executed" in result["note"]


def test_static_check_identifies_incorrect_print_only_submission_without_execution():
    result = practice.python_functions_static_check(_lesson(), """def celsius_to_fahrenheit(celsius):
    print(celsius)
""")
    assert result["status"] == "needs_fix"
    assert any("return" in check.lower() for check in result["checks"])


def test_static_check_is_not_applied_to_untrusted_or_other_topics():
    assert practice.python_functions_static_check({"content": {"practice": {}}}, "def anything(): pass") is None
