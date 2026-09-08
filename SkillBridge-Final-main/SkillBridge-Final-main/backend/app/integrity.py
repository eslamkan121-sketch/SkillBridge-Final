"""Integrity monitoring heuristics for proctored assessments.

Uses non-identifying integrity signals:
  - tab-switch / focus-loss events
  - metadata-only webcam events from browser-local analysis
  - timing anomalies (attempt too fast to be plausible for the question count)
  - suspected pasted-AI-text on free-text answers (heuristic classifier)

Each detection function returns an integrity flag dict with a stable code,
a label, and a severity. The frontend both reports local events (tab switches)
and submits free-text answers / timing for server-side checks.
"""
import re

UNUSUAL_FILL_SPEED_SECS = 8.0  # faster than this per question = suspicious
UNUSUAL_TOTAL_SECS_PER_Q = 12.0  # whole attempt finished faster than this = timing anomaly

ASSESSMENT_EVENT_TYPES = {
    "tab_switch": {
        "label": "Tab switch detected",
        "detail": "The assessment window lost focus during the attempt.",
        "reason": "The assessment window lost focus.",
        "severity": "high",
        "source": "browser",
        "hard": True,
    },
    "browser_hidden": {
        "label": "Assessment tab hidden",
        "detail": "The assessment browser tab was hidden during the attempt.",
        "reason": "The assessment browser tab was hidden.",
        "severity": "high",
        "source": "browser",
        "hard": True,
    },
    "window_blur": {
        "label": "Assessment window lost focus",
        "detail": "The assessment window lost focus during the attempt.",
        "reason": "The assessment window lost focus.",
        "severity": "high",
        "source": "browser",
        "hard": True,
    },
    "fullscreen_exit": {
        "label": "Fullscreen exited",
        "detail": "Fullscreen assessment mode was exited during the attempt.",
        "reason": "Fullscreen assessment mode was exited.",
        "severity": "high",
        "source": "browser",
        "hard": True,
    },
    "camera_disabled": {
        "label": "Camera connection lost",
        "detail": "The camera track stopped or became unavailable during the assessment.",
        "reason": "Camera connection was lost during the assessment.",
        "severity": "high",
        "source": "camera",
        "hard": True,
    },
    "camera_subject_missing": {
        "label": "No person visible",
        "detail": "No person was visible for a sustained period during the assessment.",
        "reason": "No person was visible for more than 10 seconds.",
        "severity": "high",
        "source": "camera",
        "hard": True,
    },
    "multiple_people": {
        "label": "Multiple people detected",
        "detail": "More than one person was visible for a sustained period during the assessment.",
        "reason": "Multiple people were visible for more than 8 seconds.",
        "severity": "high",
        "source": "camera",
        "hard": True,
    },
    "phone_detected": {
        "label": "Phone detected",
        "detail": "A phone-like object was visible for a sustained period during the assessment.",
        "reason": "Phone detected during assessment.",
        "severity": "high",
        "source": "camera",
        "hard": True,
    },
    "attention_away": {
        "label": "Attention away",
        "detail": "Head direction appeared away from the assessment for a sustained period.",
        "reason": "Attention appeared away from the assessment for a sustained period.",
        "severity": "warning",
        "source": "camera",
        "hard": False,
    },
}

CAMERA_EVENT_TYPES = {
    code: meta for code, meta in ASSESSMENT_EVENT_TYPES.items()
    if meta.get("source") == "camera"
}
HARD_TERMINATION_EVENT_CODES = {
    code for code, meta in ASSESSMENT_EVENT_TYPES.items() if meta.get("hard")
}
SOFT_INTEGRITY_EVENT_CODES = {
    code for code, meta in ASSESSMENT_EVENT_TYPES.items() if not meta.get("hard")
}
CAMERA_SEVERITIES = {"info", "warning", "high"}
CAMERA_SCORE_NEUTRAL_CODES = set(CAMERA_EVENT_TYPES)
SCORE_BLOCKING_FLAG_CODES = {"ai_text", "ai_text_pattern"} | HARD_TERMINATION_EVENT_CODES
MAX_CAMERA_EVENT_DURATION_MS = 2 * 60 * 60 * 1000
MAX_CAMERA_EVENTS_PER_SUBMISSION = 40
_FORBIDDEN_CAMERA_PAYLOAD_KEYS = {
    "image", "images", "frame", "frames", "video", "blob", "payload",
    "data_url", "base64", "embedding", "face_embedding", "landmarks",
    "keypoints", "faces", "face_landmarks",
}


def flag_tab_switch():
    return {
        "code": "tab_switch",
        "label": "Tab switch detected",
        "severity": "high",
        "detail": "The assessment window lost focus during the attempt, which can indicate navigating away from the test.",
    }


def flag_timing_anomaly(total_seconds, question_count):
    per_q = total_seconds / max(question_count, 1)
    return {
        "code": "timing_anomaly",
        "label": "Timing anomaly",
        "severity": "warning",
        "detail": f"Attempt completed in {total_seconds:.0f}s ({per_q:.1f}s per question), which is implausibly fast for {question_count} questions.",
    }


def _duration_label(ms):
    try:
        seconds = max(0, int(ms)) / 1000
    except (TypeError, ValueError):
        seconds = 0
    if seconds < 1:
        return "under 1s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    remainder = int(seconds % 60)
    return f"{minutes}m {remainder}s"


def validate_assessment_integrity_event(raw):
    """Validate a browser-local assessment integrity event.

    Only compact metadata is accepted. Raw frames, videos, face embeddings, or
    payload-like fields are rejected by key name before anything is persisted.
    """
    if not isinstance(raw, dict):
        raise ValueError("Assessment integrity event must be an object")
    lower_keys = {str(k).strip().lower() for k in raw.keys()}
    if lower_keys & _FORBIDDEN_CAMERA_PAYLOAD_KEYS:
        raise ValueError("Assessment integrity events must not include raw image, video or embedding data")

    event_type = str(raw.get("event_type") or raw.get("code") or "").strip()
    if event_type not in ASSESSMENT_EVENT_TYPES:
        raise ValueError("Unsupported assessment integrity event type")

    try:
        duration_ms = int(raw.get("duration_ms") or 0)
    except (TypeError, ValueError):
        raise ValueError("Assessment integrity event duration must be a number")
    if duration_ms < 0 or duration_ms > MAX_CAMERA_EVENT_DURATION_MS:
        raise ValueError("Assessment integrity event duration is out of range")

    severity = str(raw.get("severity") or ASSESSMENT_EVENT_TYPES[event_type]["severity"]).strip().lower()
    if severity not in CAMERA_SEVERITIES:
        raise ValueError("Unsupported assessment integrity severity")
    if event_type in HARD_TERMINATION_EVENT_CODES:
        severity = "high"

    occurred_at = str(raw.get("occurred_at") or "").strip()
    if len(occurred_at) > 80:
        raise ValueError("Assessment integrity event timestamp is too long")

    event = {
        "event_type": event_type,
        "duration_ms": duration_ms,
        "occurred_at": occurred_at,
        "severity": severity,
    }
    incident_id = str(raw.get("incident_id") or "").strip()
    if incident_id:
        if len(incident_id) > 96:
            raise ValueError("Assessment integrity incident id is too long")
        event["incident_id"] = incident_id
    if "confidence" in raw and raw.get("confidence") is not None:
        try:
            confidence = float(raw.get("confidence"))
        except (TypeError, ValueError):
            raise ValueError("Assessment integrity event confidence must be a number")
        if confidence < 0 or confidence > 1:
            raise ValueError("Assessment integrity event confidence is out of range")
        event["confidence"] = round(confidence, 3)
    return event


def validate_camera_integrity_event(raw):
    event = validate_assessment_integrity_event(raw)
    if event["event_type"] not in CAMERA_EVENT_TYPES:
        raise ValueError("Unsupported camera integrity event type")
    return event


def assessment_event_to_flag(event):
    event = validate_assessment_integrity_event(event)
    meta = ASSESSMENT_EVENT_TYPES[event["event_type"]]
    detail = f"{meta['detail']} Duration: {_duration_label(event.get('duration_ms'))}."
    if event.get("confidence") is not None:
        detail += f" Confidence: {event['confidence']:.2f}."
    return {
        "code": event["event_type"],
        "label": meta["label"],
        "severity": event.get("severity") or meta["severity"],
        "detail": detail,
        "source": meta.get("source") or "assessment",
        "duration_ms": event.get("duration_ms", 0),
        "occurred_at": event.get("occurred_at") or "",
        "incident_id": event.get("incident_id") or "",
    }


def camera_event_to_flag(event):
    event = validate_camera_integrity_event(event)
    return assessment_event_to_flag(event)


def assessment_events_to_flags(events):
    flags = []
    seen = set()
    validated = [validate_assessment_integrity_event(raw) for raw in list(events or [])]
    ordered = (
        [e for e in validated if is_hard_termination_event(e)]
        + [e for e in validated if not is_hard_termination_event(e)]
    )
    for event in ordered:
        key = (event["event_type"], event.get("incident_id") or event.get("occurred_at") or event.get("duration_ms"))
        if key in seen:
            continue
        seen.add(key)
        flags.append(assessment_event_to_flag(event))
        if len(flags) >= MAX_CAMERA_EVENTS_PER_SUBMISSION:
            break
    return flags


def camera_events_to_flags(events):
    for raw in events or []:
        validate_camera_integrity_event(raw)
    return assessment_events_to_flags(events)


def is_hard_termination_event(event_or_code):
    code = event_or_code.get("event_type") if isinstance(event_or_code, dict) else event_or_code
    return str(code or "") in HARD_TERMINATION_EVENT_CODES


def event_reason(event_or_code):
    code = event_or_code.get("event_type") if isinstance(event_or_code, dict) else event_or_code
    meta = ASSESSMENT_EVENT_TYPES.get(str(code or ""))
    return (meta or {}).get("reason") or "An assessment integrity rule was violated."


def is_score_blocking_flag(flag):
    return flag.get("severity") == "high" and flag.get("code") in SCORE_BLOCKING_FLAG_CODES


def result_integrity_status(flags):
    coded = [f for f in flags or [] if f.get("code")]
    if any(f.get("code") in HARD_TERMINATION_EVENT_CODES for f in coded):
        return "review_required"
    return "review_recommended" if coded else "clear"


# ---------------------------------------------------------------- AI-text detection

# Phrases and stylistic patterns more typical of polished generative text than
# of a student's own rushed free-text answer.
_AI_MARKERS = [
    re.compile(r"\b(in conclusion|furthermore|moreover|overall)\b", re.I),
    re.compile(r"\b(leverag|utiliz|harness|streamline|robust)\w*", re.I),
    re.compile(r"\b(it is (important|essential|crucial) to)\b", re.I),
    re.compile(r"\b(comprehensive|seamless|cutting-edge|state-of-the-art)\b", re.I),
    re.compile(r"\bbelow is a|here is a (detailed|summary|breakdown)\b", re.I),
    re.compile(r"\b\d+(st|nd|rd|th)\b.*\b(step|firstly|secondly)\b", re.I),
    re.compile(r"\bit('| i)?s worth noting\b", re.I),
]

# Em-dash and parenthetical density can indicate polished generated prose.
_AI_PATTERNS = [
    (lambda t: len(t.split()) >= 60, "Long, unbroken prose answer"),
    (lambda t: t.count("—") >= 3 or t.count("–") >= 3, "Heavy em/en-dash usage"),
    (lambda t: len(re.findall(r"\([^)]*\)", t)) >= 4, "Dense parentheticals"),
]


def detect_ai_text(text):
    """Return (is_flagged: bool, flags: list[dict]). Returns empty flags if clean."""
    if not text or not text.strip():
        return False, []
    flags = []
    marker_hits = []
    for pat in _AI_MARKERS:
        m = pat.search(text)
        if m:
            marker_hits.append(m.group(0))
    if len(marker_hits) >= 2:
        flags.append({
            "code": "ai_text",
            "label": "Possible AI-generated answer",
            "severity": "high",
            "detail": f"Free-text answer contains multiple stylistic markers common in generated prose ({', '.join(sorted(set(marker_hits)))}).",
        })
    for fn, label in _AI_PATTERNS:
        if fn(text):
            flags.append({
                "code": "ai_text_pattern",
                "label": "Possible AI-generated answer",
                "severity": "high",
                "detail": label,
            })
            break
    return bool(flags), flags


def evaluate_attempt(question_count, total_seconds, free_text_answers, local_tab_switches, ai_flags=None):
    """Combine locally-detected and server-side detected signals into the full
    flag list for a result screen. AI flags may be supplied by the client's own
    checks; we re-run the server-side heuristic here for authority."""
    flags = []

    if local_tab_switches:
        for _ in range(local_tab_switches):
            flags.append(flag_tab_switch())

    if ai_flags:
        flags.extend(ai_flags)

    for text in (free_text_answers or []):
        flagged, fl = detect_ai_text(text)
        if flagged:
            for f in fl:
                if f not in flags:
                    flags.append(f)

    if total_seconds is not None and question_count:
        if total_seconds / question_count < UNUSUAL_TOTAL_SECS_PER_Q:
            flags.append(flag_timing_anomaly(total_seconds, question_count))

    # de-duplicate tab switch if count == 0 handled; ensure list always JSON-safe
    return flags
