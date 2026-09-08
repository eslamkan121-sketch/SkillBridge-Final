# Phase 5.5 Step 4 — Tutor/Copilot Language Support (auto, en, ar)

## Status: IMPLEMENTED — go for demo build

- Full backend suite (incl. new 32-test language suite): **256 passed, 2 skipped**
- Frontend: `tsc --noEmit` **clean**, `vite build` **clean**
- Manual browser walkthrough still required (see below)

---

## 1. Language Preference Architecture

- Single source of truth: `tutor_preferences.language` — `'auto' | 'en' | 'ar'`, default `'auto'` (`backend/app/copilot.py`, `database.py`, `models.py`).
- Preference is profile-level: it lives next to `tutor_id` and `mode`, so changing tutors/modes never touches it, and changing it never resets tutor/mode.
- The preference sets the **default** language; the per-message backend resolution decides the actual conversation language.
- Frontend mirrors it via `AppContext.language` (loaded from GET on login, persisted on change via PUT). `interview.language` is pinned once at interview start so a running interview never flips mid-way.

## 2. Persistence & API

- **GET** `/api/students/{sid}/tutor/preference` → `{tutor_id, mode, language}` (language defaults to `auto`).
- **PUT** same route accepts independent `tutor_id` / `mode` / `language` fields; only the provided fields update.
- Invalid language payloads → **400** `"Unknown tutor language (allowed: auto, en, ar)"`; empty PUT → 400. Never silently ignored (injection-safety).
- All tests use the in-memory seeded DB — the language survives refresh/persist across tutor and mode switches.

## 3. Auto Detection

- On **POST /tutor** and **POST /interview**: prefs and request take precedence, but when the effective preference is `auto`, the backend detects from the message text: `_ARABIC_RATIO = 0.25` (share of Arabic-script letters vs combined Arabic+Latin letters, per message).
- Spec example verified by test: `"اشرحلي Docker networking"` → **ar** (more Latin letters, but Arabic-script letter ratio above threshold).
- Backend is authoritative: the frontend may display the stored preference, but the conversation language is whatever the backend resolved and returned.

## 4. English / Arabic / Mixed (deterministic)

- `auto` follows the message language. `en` stays English regardless of content; `ar` stays Arabic.
- Responses guardrail via `LANG_INSTRUCTIONS` in `genai.py` — Arabic Arabic-language instructs the model to keep the delivery natural while technical terms (Docker, networking, etc.) stay in English, and to match light Egyptian Arabic when the student's register is informal.
- Repeated single-line verification: Arabic `auto` replies stay Arabic; English `auto` replies stay English; each message re-detects (`auto` does not lock).

## 5. Persona & Mode Preservation

- Tutor-switching and mode-switching (chat/practice/discuss/interview) are fully orthogonal to language — all four personas (`nova/axel/sage/vex`) verified to reply in Arabic with persona-appropriate style (e.g. `بعنوان [بصوت {name}]`-style tags in Arabic fallback).
- Practice/discuss/interview modes lean on the mode's existing structure with Arabic delivery.

## 6. Copilot Context

- The threaded context line now includes `Language: English|Arabic`, verified present in captured user context for **dashboard, learning, jobs, roadmap, and interview** pages.
- The context still carries the student profile, current gap, and target career — the language line is additive; no personalization/context regression.

## 7. Mock Interview — Arabic

- Arabic mock interview: Vex asks natural Arabic questions about the chosen skill, and the interview keeps the pinned language (frontend `interview.language`) stable across turns.
- Deterministic Arabic fallback exists for interviewer Q/A when no live GenAI is configured.
- English mock interview remains unchanged.

## 8. Browser Speech Changes

- `speak()` picks an Arabic-capable speechSynthesis voice when the text contains Arabic script (`ar-EG` preferred, graceful fallback to the existing English voice settings if none installed); `utterance.lang` set accordingly.
- `startListening(..., 'ar')` uses `ar-EG`, `en-US` otherwise (graceful degradation when unsupported).
- `previewVoice(text?)` now speaks the localized tutor preview (`previewFor(tutor, lang)`), e.g. `مرحباً، أنا نوفا. جاهز نبدأ؟`.

## 9. RTL / UI

- Compact segmented language control **Auto / EN / ع** in the Copilot toolbar (`tutorI18n.ts` `LANGUAGE_SHORT`/`LANGUAGE_LABELS`), disabled during active assessment.
- The Copilot body flips `dir="rtl"` when the conversation is Arabic (messages, quick actions, input); the app shell/sidebar stays LTR.
- Mock interview bubbles flip RTL too; `index.css` adds Arabic-capable font fallbacks (Noto Kufi Arabic/Cairo), mirrored lists/blockquotes, and `unicode-bidi: isolate`/`overflow-wrap: anywhere` so mixed English-technical terms in Arabic text don't clip or ligature-break.
- Tutor-surface strings (greeting, placeholders, quick-action labels, copy, locked banner) localized via `tutorUi(lang)` / `quickActionsFor(lang, tutorId, mode, topicName)` — globally localized only the tutor surface, per scope.

## 10. Assessment Integrity

- Verified Final Assessment lock (423) is unchanged and tested for all three language modes + `/interview` + `/interview/tts`: no language path can bypass it.
- Tutor surface swaps to the localized locked banner during an active assessment; nothing else in the app changes.

## 11. Deterministic Fallback

- `_tutor_fallback_ar` / `_interview_fallback_ar` in `genai.py` produce natural, persona-appropriate Arabic for every tutor and mode without any GenAI call — the demo works offline and Arabic grading/tests are fully deterministic.

## 12. Files Modified

Backend
- `backend/app/copilot.py` — language constants, `validate_language`, `detect_language`, `resolve_language`, `language_label`
- `backend/app/database.py` — `language TEXT` column + migration
- `backend/app/models.py` — `set_tutor_preference` (3-field upsert), `get_tutor_language`
- `backend/app/genai.py` — `LANG_INSTRUCTIONS`, `_normalized_lang`, Arabic fallbacks, `language` params
- `backend/app/main.py` — preference GET/PUT language; `/tutor` + `/interview` language validation/resolution; 423 lock intact
- `backend/tests/test_tutor_language.py` (**new**, 32 tests)
- `backend/tests/test_tutor_modes.py` — 2 assertions now expect `"language": "auto"`

Frontend
- `frontend/src/lib/types.ts` — `TutorLanguage`, `InterviewReply.language?`
- `frontend/src/lib/tutorI18n.ts` (**new**) — labels, quick actions, speech mapping, previews, effective-language
- `frontend/src/AppContext.tsx` — `language`/`setLanguage`, pinned interview language
- `frontend/src/lib/interviewSession.ts` — `START` carries pinned language
- `frontend/src/lib/api.ts` — preference/interview/send language params
- `frontend/src/hooks/useBrowserSpeech.ts` — Arabic voice/recognition/preview
- `frontend/src/components/CopilotPanel.tsx` — selector, i18n, RTL
- `frontend/src/components/interview/MockInterviewPanel.tsx` — language-aware speech/preview/send, light RTL
- `frontend/src/index.css` — RTL mirroring, Arabic font fallbacks, selector styles

## 13. Test Counts

- Added: **32** (`test_tutor_language.py`)
- Full backend: **256 passed, 2 skipped** (0 failed)
- Frontend: **tsc clean**, **vite build clean**

## 14. Manual Verification Still Needed (browser)

1. Login as `aisha@student.edu` / `demo1234`.
2. Copilot → set **Sage + Discuss + Arabic** → ask anything → Arabic reply; refresh → Arabic persists.
3. Dashboard/learning/jobs/roadmap: ask Arabic questions → Arabic replies.
4. Switch tutors: all four give Arabic replies with different personas.
5. Mock interview with Vex in Arabic — 2 turns, Arabic throughout.
6. English regression: set English → replies in English.
7. Auto: Arabic question → Arabic, English question → English.
8. Switch to `auto` → start an interview → language must not change mid-interview.
9. Start a Verified Final Assessment → tutor reads "tutor paused" until submit; start an interview → HTTP 423.