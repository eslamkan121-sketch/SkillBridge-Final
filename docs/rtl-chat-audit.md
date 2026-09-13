# Phase A — Arabic RTL Audit: Chatbot / Tutor Subtree (read-only)

Scope: `CopilotPanel` + chat/discuss/interview surfaces for all four personas and all modes.
No file was edited in this phase. This report is audit-only (J1).

## A1. Component inventory

| # | Component | File |
|---|-----------|------|
| C1 | CopilotPanel (chat + interview containers, composer, voice, quick actions, language selector) | `frontend/src/components/CopilotPanel.tsx` (754 lines) |
| C2 | SafeMarkdown renderer (react-markdown, NO remark plugins) | `frontend/src/components/CopilotPanel.tsx:12-14` |
| C3 | Persona selector (compact avatars; full card + Expanded identity card) | `frontend/src/components/learning.tsx:229-341` (`TutorSelector`, `TutorAbout`) |
| C4 | Icons used by the subtree | `frontend/src/components/Icons.tsx` (`IconSend:85`, `IconChevron:153`, `IconBack:291`, Mic/Volume/Stop/Plus/Trash/Lock/Chat/Tutor/Expand/Collapse) |
| C5 | UI copy (ar/en) | `frontend/src/lib/tutorI18n.ts` (`tutorUi`, `TUTOR_LANGUAGES`, `LANGUAGE_SHORT/LABELS`, `quickActionsFor`) |
| C6 | Language / mode state | `frontend/src/AppContext.tsx` (`language`, `setLanguage`, `mode`, `TUTOR_DEFAULT_MODES` in `learning.tsx:35`) |
| C7 | All chat CSS (copilot, msg, tutor-, md-body, quick-action, RTL overrides) | `frontend/src/index.css` — chat blocks: 421-457 (legacy tutor), 680-693 (`.md-body`), 1919-2130 (tutor cards/selectors/about), 3087-3652 (copilot + interview + RTL), 3630-3644 (lesson discuss) |

## A2. Per-component direction / alignment / layout audit

### C1 CopilotPanel — direction handling
- Root dir: only `.copilot-body` gets `dir={lang === 'ar' ? 'rtl' : 'ltr'}` (`CopilotPanel.tsx:445`). Everything above it (bar, avatar, expand) and below the body are NOT directional → the whole subtree flips as one unit.
- B3 (per-message direction): **absent**. Messages are `<div class="msg role">` with no `dir`; they inherit the container dir. An Arabic reply never gets per-message RTL when the thread is en, and an English reply never gets LTR when the thread is ar.
- F9 copy button: **absent** in the UI (no copy control exists; nothing to fix).
- F11 streaming: **N/A** — replies are delivered whole (single `await api.tutorSend`); the busy state is a `...` bubble inside `.msg.assistant` (`CopilotPanel.tsx:708`).
- Mode selector: **not rendered** in the current chatbot UI. `.copilot-modes`/`.copilot-mode` CSS exists (`index.css:3345-3370`) but no markup emits it; mode is implicit (per-tutor default + Mock-Interview toggle). "Mode selector in Arabic" is therefore N/A until the chips are rendered.
- Language selector: rendered (`CopilotPanel.tsx:451-465`) with `LANGUAGE_SHORT` labels (`EN`/`ع`).
- Quick actions + greeting + about/back + pinned note + confirm dialog: plain buttons in the dir container — flex auto-mirrors; strings come from `tutorUi(lang)`, but interleaved English tokens (`tutor.name`, `tutor.origin`, `topicName`, `contextTitle`) are not translated.

### C2 SafeMarkdown
- No `dir="ltr"` wrapper for `pre`/`code` → B4/E6 defect (code follows message container direction).
- No `dir="auto"` per message root → B3 defect (message text is inside `.md-body` in the container dir).
- GFM tables not enabled (`react-markdown` without `remark-gfm`) → E4 effectively moot today; summary rows currently render as plain text. If GFM is later enabled, table direction must be defined.
- `word-break: normal; overflow-wrap: anywhere` on `.md-body` (`index.css:3413`) is direction-safe.

### C3 Persona selector / identity cards
- No explicit `dir`; inherits the container dir → flex `tutor-card-grid` mirrors automatically under RTL. Avatars are `<img>`, never stretched (F6/avatars OK).
- Labels are hardcoded English: "Choose your AI Tutor", "Pick the coaching style", `Origin/Specialty/Traits/Best for/Languages` (`learning.tsx:259-338`). Full non-compact selector + TutorAbout remain English in Arabic — an i18n gap (F6/H4).

### C4 Icons (direction semantics)
- `IconSend` (`Icons.tsx:85-89`): paper-plane pointing up-right. Under RTL the send control sits on the left (flex auto-mirrors), but the glyph still points right → C6 defect (should mirror).
- `IconBack` (`Icons.tsx:291-294`): arrow pointing left. In Arabic "back to chat" should point right → C6 defect.
- `IconChevron` points down (toggle) — direction-neutral-ish; keep.
- Mic/Volume/Stop/Plus/Trash/Lock/Chat/Tutor are non-directional → must NOT mirror (correct by default).

### C7 CSS audit (physical vs logical, per bubble/region)

Legacy tutor area (`.tutor-layout:421`, `.tutor-panel:426`, `.tutor-messages:428`):
- `.msg` (429): `border-radius: 12px` symmetric; tail corners come from role rules → see below.
- `.msg.user` (430): `align-self: flex-end` + `border-bottom-right-radius: 3px`.
- `.msg.assistant` (431): `align-self: flex-start` + `border-bottom-left-radius: 3px`.
  - Flex `end/start` auto-mirror under RTL (user bubble moves to the LEFT in RTL) — good — **but the tail radius stays physical** → C2 defect: user's tail is bottom-RIGHT while the bubble sits bottom-LEFT.
  - `.msg.interviewer/.student` (443-444) have the same physical tail pattern.
- `.tutor-input` (432-434): flex row; input flexes; symmetric padding → auto-mirrors; send+mic land on the logical start... DOM order is input, mic, submit → in RTL submit is leftmost (logical end) ✓; no physical prop defect here.
- `.tutor-skill-list .ts-item` (423): `text-align: left` physical (legacy page, outside CopilotPanel).

Copilot area:
- `.copilot-main-bar` (3128): `text-align: left` physical — bar is outside the dir container and stays LTR always (chrome; note only).
- `.copilot-current` (3187): `text-align: right` physical — works for LTR design intent; not logical.
- `.copilot-interview-primary` (3536): `text-align: left` + explicit `[dir='rtl']` override to `right` (3602) — already handled.
- Mobile ≤560px `.copilot-current` (3650): `text-align: left` physical — **breaks RTL on mobile** (persona info left-aligned).
- `.copilot-interview-tag` (3470-3472): `letter-spacing: 0.04em` + `text-transform: uppercase` → D3 defect for Arabic chips/labels (tracking + casing are Latin conventions).
- `.md-body` (680-693): `ul/ol { padding-left: 20px }` and `blockquote { border-left: 3px }` physical; existing RTL overrides fix list padding + quote side (3406-3408) ✓; `pre` (686) has no `dir=ltr` (B4); inline `code` (685) no isolation (B5).
- `.copilot-messages` (3328 / 428): `overflow-y: auto`; scrollbar side follows the container dir natively (RTL → left) — needs a screenshot to confirm no overlap with the bubble tail (I10). `unicode-bidi: isolate` (3412) is set on the messages container.
- `.copilot-panel` (3089-3090): `position: fixed; right: 22px` — app chrome; panel stays bottom-right in both languages (B2 cap). Debated: acceptable chrome or move to logical side.
- `.copilot-context` (3409-3411): forced `direction: ltr` under RTL + `unicode-bidi: plaintext` on `<strong>` — makes the chip RTL-hostile when `topicName` is Arabic (it renders as LTR line with bidi text). Should be `dir="auto"` at the element, not whole-LTR.
- Avatar placement: avatars only exist in the bar (chrome) and `TutorSelector` grid / `TutorAbout` head — all flex, auto-mirror; no left/right physical gaps (C3 ✓).

Typography:
- Font stack (76): Latin-first with Arabic fallbacks last, `"Noto Kufi Arabic","Noto Sans Arabic","Cairo"` → D1 OK-ish; note `--font` starts with Inter then OS/Web fonts, Arabic glyphs fall back only after all four Latin families miss (browser picks last installed Arabic font).
- Line height: `.msg` 1.5, `.md-body` p 1.55 → D2 borderline for Arabic (recommend 1.6+ under `[dir='rtl'] .md-body`).
- Letter-spacing: global `h1-h4 { -0.01em }` (90) and the chat tag tracking above → D3 candidates.
- Numbers: no explicit rendering control (D5); app/scaffold replies use Western digits (backend language lock allows short technical terms); must document convention, not force.
- Diacritics: no vertical clipping rules needed yet; no `line-height` underflow observed — flag for I3.
- Punctuation: no `dir="auto"` at message level → Arabic `؟`/`،` can land at the "wrong" visual end when a message is mostly English but partly Arabic (D8).

Interview surface:
- `.copilot-interview-turn`, `.copilot-interview-state` (3481-3519): flex, auto-mirror ✓; the big primary grid (3528-3535) uses named `grid-template-areas` `"icon label" / "icon hint"` — grid columns are physical (`32px minmax`), so under RTL the icon stays on the LEFT while the direction is RTL → E/C defect (icon should be on the logical end). Verify with screenshot (H4).
- `.copilot-interview-typing` (3584-3589): grid `minmax(0,1fr) auto` — submit button column is physical `auto` second; under RTL the submit lands on the left (logical end) ✓; input inherits container dir ✓ (F4 fine, F2 via dir).

## A3. Render expectations (no screenshots yet — backend was rebuilt mid-audit; matrix is Phase I)

Based on the DOM/CSS above (no live Arabic screenshot taken this phase — this is the code-based audit; Phase I will produce the 60-combination matrix screenshots):
- Short Arabic-only message: renders RTL text in a `.msg.assistant` bubble (flex-start → right side) — expected OK, tail radius wrong side.
- Mixed "اشرحلي Docker volume": text is RTL with Latin run "Docker" — bidi keeps the token order, but bubble dir = container (correct when ar); punctuation may land at wrong end if message mis-detected.
- Code block: stays inside the RTL container → code lines get RTL base direction → backticks/lists/indent visually wrong (expected defect, B4).
- Bullet list: `.md-body ul` RTL override exists; bullets right ✓ (unless nested in a code block or inside a forced-LTR region).
- Numbered list: same as bullets; numbering order under `[dir=rtl] ol { padding-right }` renders 1,2,3 right-to-left top-down ✓ expected; needs screenshot.
- Table: not rendered by react-markdown (no GFM) — plain text today (E4 N/A until plugin).
- Error/fallback (Arabic): `(Tutor unavailable — is the backend running?)` and `voiceUnavailable` are partially localized; direction follows container; expected OK.
- Composer placeholder Arabic: input in dir container → placeholder RTL, cursor starts right ✓ (F1); check `ui.askPlaceholder`.
- Language selector Arabic: chips `ع` / `EN` inside `.copilot-lang` (flex, auto-mirror) ✓.
- Persona selector Arabic: compact avatars only; full card labels English (i18n gap noted).

## A4. Defect register (every item found — nothing fixed yet)

Dir plumbing:
1. [B3/F3] Per-message `dir="auto"` absent — whole thread flips with the container only; existing messages reflow when the language toggles mid-thread instead of keeping their own direction.
2. [B4/E6] `pre`/`code` not locked LTR inside RTL.
3. [B5] Inline code / URLs / version tokens not isolated at token level (`<code>`, `a`, numbers).
4. [E7] Links inherit message dir (fine) but no href protection needed beyond bidi isolation of the token.

Layout mirroring (physical → logical):
5. [C2] Bubble tail radii are physical: `.msg.user` bottom-right, `.msg.assistant` bottom-left (and `.msg.student/.interviewer`) → wrong corner under RTL.
6. [C1] `.copilot-current { text-align: right }` (3187) and `{ text-align: left }` on mobile (3650) — not logical; mobile RTL breaks.
7. [C1] `.copilot-bar-main { text-align: left }` (3128) — chrome, never mirrors (note).
8. [C7-interview] `.copilot-interview-primary` grid icon placed via physical `grid-template-areas`/`grid-template-columns: 32px minmax(...)` → icon stays left under RTL.
9. [C4] `.copilot-context` forced `direction: ltr` (3409) — re-focus as `dir="auto"` on the element.
10. [C4] Scrollbar side needs visual confirmation (native behavior should be correct; I10).

Icon mirroring:
11. [C6] `IconSend` glyph should mirror under RTL (send points right today while control sits left).
12. [C6] `IconBack` glyph should mirror under RTL (points left today; Arabic back = right). Mic/volume/stop/copy/etc. must stay unmirrored (currently correct).

Typography:
13. [D3] `letter-spacing` on Arabic: `.copilot-interview-tag` 0.04em + global `h1-h4 -0.01em` — tracking breaks cursive shaping and is a Latin convention; scope reset for Arabic.
14. [D2] Arabic line-height slightly tight (1.5/1.55) — bump under RTL.
15. [D1] Arabic font falls back late in the stack (after all Latin families); acceptable but note.
16. [D5] Digits/punctuation convention not pinned down (no technical disruption; document + verify).
17. [D8] Message-level `dir=auto` missing ⇒ Arabic punctuation in mixed messages can sit at the wrong end.

Markdown/ranges:
18. [E2] Numbered lists rely on padding sides that are physical at line 683/407 — existing override covers ul+ol; verify nested indent (indent uses physical `padding-left` of `ol` children under RTL).
19. [E9] Emoji anchoring — no explicit handling; verify within RTL runs (mostly browser-native).

Composer/interactive:
20. [F2] Cursor/typing direction inherited from container (correct when ar); missing when a user types Arabic while thread is en (ties to #1).
21. [F9] No copy button exists (N/A, documented).
22. [H4] Persona names remain transliterated English (`tutor.name`) across ar UI; decide convention ("Nova" stays — matches backend) and pin it.
23. [F6/H] `TutorAbout` and full `TutorSelector` labels are unlocalized (English) in Arabic mode.

System/fallback:
24. [G] Item: `(Tutor unavailable — ...)` error string is partially localized (backend English detail appended). Direction is fine once #1 lands.

Streaming:
25. [F11] Not applicable (no streaming); busy `...` bubble direction-neutral.

Priority ordering per the task: B (1-4) → C (5-10) → E (4,18,19) → F (20-23) → D (13-17) → G (24) → H → I.