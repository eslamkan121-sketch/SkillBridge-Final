"""Gamified learning-engagement summary for a student.

Derived entirely from persisted activity records — assessment attempts, learning
path items, tutor messages, and verified skills — so progress is real, never
fabricated. Everything is per-student and shown only to that student on their own
dashboard (the leaderboard is a labelled "coming soon" teaser, so no cohort data
is exposed).
"""
import re
from datetime import date, datetime, timedelta

from . import models

# XP awards for each kind of real activity.
XP_LEARNING_ITEM = 25
XP_TUTOR_MESSAGE = 5
XP_ATTEMPT_PASS = 50
XP_ATTEMPT_FAIL = 15
XP_VERIFIED_SKILL = 100

XP_PER_LEVEL = 250


def _day_of(ts):
    """Extract the UTC date from an ISO-ish 'YYYY-MM-DD HH:MM:SS' timestamp."""
    if not ts:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(ts))
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def _streak_days(day_set, ref_day):
    """Consecutive days of activity ending today (or yesterday — still live).

    An older gap resets the streak to zero.
    """
    if not day_set:
        return 0
    days = sorted(day_set)
    if days[-1] < ref_day - timedelta(days=1):
        return 0
    streak = 0
    day = days[-1]
    while day in day_set:
        streak += 1
        day -= timedelta(days=1)
    return streak


_BADGES = [
    ("first_learning", "First steps", "Generated your first personalized learning item.", "Open any skill gap on the Learning page to begin."),
    ("first_assessment", "Quiz taker", "Attempted your first proctored assessment.", "Take any assessment from the Assessments page."),
    ("assessment_ace", "Assessment ace", "Passed an assessment and levelled a skill up.", "Pass a skill assessment to earn your first pass."),
    ("verified", "Verified", "Earned at least one Verified skill on your profile.", "Pass an assessment to get a skill Verified."),
    ("active_learner", "Active learner", "Asked the AI Tutor five or more questions.", "Chat with the AI Tutor on the Learning page."),
    ("on_a_roll", "On a roll", "Kept a learning streak alive for three or more days.", "Keep learning on consecutive days."),
]


def activity_summary(student_id):
    """Return the engagement summary: streak, XP, level, and earned/locked badges."""
    attempts = models.list_assessment_attempts(student_id=student_id)
    learning = models.list_learning_path(student_id)
    with models.get_cursor() as c:
        tutor_msgs = c.execute(
            "SELECT role, created_at FROM tutor_messages WHERE student_id=? ORDER BY id",
            (student_id,)).fetchall()
        verified = c.execute(
            "SELECT verified_at FROM verified_skills WHERE student_id=? ORDER BY verified_at",
            (student_id,)).fetchall()

    activity_days = set()
    xp = 0

    for a in attempts:
        d = _day_of(a.get("created_at"))
        if d:
            activity_days.add(d)
        xp += XP_ATTEMPT_PASS if a.get("passed") else XP_ATTEMPT_FAIL

    for l in learning:
        d = _day_of(l.get("generated_at"))
        if d:
            activity_days.add(d)
        xp += XP_LEARNING_ITEM

    user_messages = 0
    for r in tutor_msgs:
        d = _day_of(r["created_at"])
        if d:
            activity_days.add(d)
        if r["role"] == "user":
            user_messages += 1
    xp += XP_TUTOR_MESSAGE * user_messages

    for v in verified:
        d = _day_of(v["verified_at"])
        if d:
            activity_days.add(d)
        xp += XP_VERIFIED_SKILL

    passed_count = sum(1 for a in attempts if a.get("passed"))
    verified_count = len(verified)

    count = {
        "first_learning": len(learning) >= 1,
        "first_assessment": len(attempts) >= 1,
        "assessment_ace": passed_count >= 1,
        "verified": verified_count >= 1,
        "active_learner": user_messages >= 5,
    }
    streak = _streak_days(activity_days, date.today())
    count["on_a_roll"] = streak >= 3

    badges = [{"code": code, "name": label, "desc": description, "hint": hint, "earned": bool(count[code])}
              for code, label, description, hint in _BADGES]

    level = xp // XP_PER_LEVEL + 1
    return {
        "streak_days": streak,
        "active_days": len(activity_days),
        "xp": xp,
        "level": min(level, 20),
        "xp_into_level": xp % XP_PER_LEVEL,
        "xp_per_level": XP_PER_LEVEL,
        "assessments_taken": len(attempts),
        "verified_skills": verified_count,
        "badges": badges,
        "leaderboard": {"status": "coming_soon",
                        "message": "Cohort leaderboard — coming soon. Keep learning to earn your place."},
    }