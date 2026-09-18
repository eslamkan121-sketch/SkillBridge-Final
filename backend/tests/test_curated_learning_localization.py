"""Locale contracts for the three curated learning topics."""
import re

from app import knowledge_base


TOPICS = (
    knowledge_base.PYTHON_FUNCTIONS,
    knowledge_base.PYTHON_ERROR_HANDLING,
    knowledge_base.SQL_QUERIES_FILTERING,
)


def test_curated_english_content_is_isolated_and_arabic_copy_is_complete():
    arabic = re.compile(r"[\u0600-\u06ff]")
    for topic in TOPICS:
        assert not arabic.search(topic["learn"]["title"])
        assert not arabic.search(topic["learn"]["explanation"])
        locale = topic["locales"]["ar"]
        assert arabic.search(locale["learn"]["title"])
        assert arabic.search(locale["learn"]["explanation"])
        assert arabic.search(locale["practice"]["task"])
        assert len(locale["mini_check"]["questions"]) == len(topic["mini_check"]["questions"])


def test_translated_options_keep_canonical_scoring_and_hints_do_not_reveal_answers():
    for topic in TOPICS:
        localized = topic["locales"]["ar"]["mini_check"]["questions"]
        for canonical, display in zip(topic["mini_check"]["questions"], localized):
            assert canonical["id"] == display["id"]
            assert len(canonical["options"]) == len(display["options"])
            hint = canonical["misconception_hint"].lower()
            answer = str(canonical["correct_answer"]).lower()
            assert answer not in hint
