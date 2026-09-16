# SkillBridge — Design Token & Shell Spec (EN + AR)

**Deliverable 1 of the UI redesign.** Scope: the visual language (tokens) and the application shell (layout, chrome, direction). Paired with the single-file Dashboard mockup (`docs/mockups/dashboard.html`, EN/AR toggle inside) and the Skills & Roles mockup (`docs/mockups/skills-and-roles.html`) which serve as the executable proof of this spec. **Nothing else in the redesign starts until these mockups are reviewed.**

Status: DRAFT FOR REVIEW.

---

## 1. Guiding rules (read first)

1. **Named roles only.** No component or new code may reference a raw hex value. Every color used must come from the role table (below). Grey-area cases (charts, status) must map to an existing role — never invent a hue.
2. **Full-shell RTL is first-class, not an add-on.** The app already carries app-level language state (`AppContext.language`). The spec promotes that state to the whole shell: the shell root gets `dir="rtl"`/`ltr`, and every region mirrors (sidebar, topbar, breadcrumbs, pagination, rails, chips, accordions). Anything that needs a manual `[dir='rtl']` exception must be registered in the RTL register (section 5).
3. **Class contract is frozen.** All classes asserted by `frontend/scripts/*.mjs` keep their literal names and semantic roles. The redesign restyles onto tokens; it does not rename, merge, or restructure the asserted markup (section 6).
4. **Voice overlay is skin-only.** The voice state machine and every class it depends on are frozen. We restyle existing states; we do not redesign the state machine.
5. **Honesty of provenance.** Mock data and the "verified" evidence chain must never imply a verification (or an AI source) that does not exist. Verified-green is only ever used for assessment-passed evidence; anything self-reported is labelled `Self-reported` and stays muted/caution.

---

## 2. Color roles

The anchors from the current system are kept: **navy** (brand), **coral** (primary accent), **teal** (secondary accent). **Indigo** is promoted to the formal *data / progress* role. **Verified-green** is formalized. Arbitrary red / blue / sky / gold hues are retired from new work and are being migrated out (section 2.4).

### 2.1 Named role table

| Role token | Anchor | Used for | Do NOT use for |
|---|---|---|---|
| `--sb-role-surface-canvas` | `#F8FAFC` | App background, page canvas | Accent surfaces |
| `--sb-role-surface-panel` | `#FFFFFF` | Cards, panels, popovers | Canvas |
| `--sb-role-surface-border` | `#E2E8F0` | Hairlines, card/drawer borders | Text |
| `--sb-role-surface-raised` | `#FFFFFF` | Floating shell (Copilot overlay, drawers) + elevation | — |
| `--sb-role-accent-primary` | `#FF6B2C` | Primary buttons, active nav, live/unread, user bubble | Verified claims |
| `--sb-role-accent-primary-strong` | `#E85A1F` | Hover/pressed of primary, dark accents on navy | — |
| `--sb-role-accent-primary-soft` | `#FFF0E8` | Soft selected chips, tag backgrounds | Text |
| `--sb-role-accent-primary-border` | `#FAD4C2` | Hairline of accent-soft chips | — |
| `--sb-role-accent-secondary` | `#14B8A6` | Secondary buttons, success-ish actions, teal rails | Data series |
| `--sb-role-accent-secondary-strong` | `#0F766E` | Hover of secondary, teal on navy | — |
| `--sb-role-accent-secondary-soft` | `#E6FBF8` | Soft teal chips, completed phase fills | — |
| `--sb-role-data` | `#7C5CFC` | Scores, progress rings, charts, gap maps, data series | Buttons |
| `--sb-role-data-soft` | `#F0EBFC` | Data chip fills, active trend markers | — |
| `--sb-role-success` | `#1E8A5A` | Passed assessment, "ready", positive outcome | Verified claims (see below) |
| `--sb-role-success-soft` | `#E7F7EF` | Success chip backgrounds | — |
| `--sb-role-verified` | `#1E8A5A` | The verification mark (skill tag `verified`, verified badge, share-green) | Anything not backed by assessment evidence |
| `--sb-role-verified-soft` | `#E6F6EE` | Verified chip fill | — |
| `--sb-role-caution` | `#B45309` | Pending, needs-review, "in progress", warnings | Errors, arbitrary red |
| `--sb-role-caution-soft` | `#FEF3E2` | Caution chip backgrounds | — |
| `--sb-role-danger` | `#D7263D` | Only destructive confirmations (Clear chat, delete) | Status coloring |
| `--sb-role-danger-soft` | `#FDEBEC` | Destructive button fills | — |
| `--sb-role-muted` | `#64748B` | Body secondary text, placeholders, meta lines | Borders (use surface-border) |
| `--sb-role-muted-strong` | `#334155` | Body primary text on light | — |
| `--sb-role-muted-faint` | `#94A3B8` | Tertiary labels, icon-only meta | — |
| `--sb-role-brand-navy` | `#0D1B2A` | Sidebar, brand surfaces, login hero, on-dark chrome | Body text on light |
| `--sb-role-brand-navy-deep` | `#0F1B2E` | Sidebar gradient stop, footer | — |
| `--sb-role-ink` | `#14273B` | Headings on light panels | — |
| `--sb-role-on-navy` | `#FFFFFF` | Text/icons on navy | — |
| `--sb-role-on-navy-muted` | `rgba(255,255,255,.72)` | Secondary text on navy (nav sublabels, meta) | — |

Notes:
- **success vs verified are deliberately distinct roles** even though the anchor is the same today. `success` answers "did you meet the bar?" (passed assessment, ready ≥70). `verified` answers "is this claim backed by evidence?" (assessment-record claim, verified skill card). Keeping them separate lets a future differentiation (e.g., a lighter tint for verified tags vs strong for pass) land without renaming.
- `data` is only indigo `#7C5CFC` — progress rings and the match breakdown visuals. Teal must not be used as a competing chart hue; teal stays an interaction accent.

### 2.2 Role → component map

| Component | Role usage |
|---|---|
| Primary button / user bubble | `accent-primary` fill, `accent-primary-strong` hover |
| Secondary button | white `surface-panel`, `surface-border` hairline, `muted-strong` text |
| Sidebar, login hero | `brand-navy` gradient to `brand-navy-deep`, `on-navy` text |
| Active nav item | `accent-primary` left rail (logical `inline-start`) + `on-navy` text on `rgba(255,255,255,.08)` |
| ScoreRing / progress | `data` ring on `surface-border` track |
| Gap map bars | `data` (progress), `caution` (gap), `surface-border` (missing) |
| Skill tag unverified | `muted-strong` text, `u-dot` `caution` |
| Skill tag verified | `verified` text/icon, `verified-soft` fill |
| LevelBadge Verified / Self-reported | verified role vs muted chip |
| Passed assessment chip | `success` icon/text |
| Pending assessment chip | `caution` icon/text |
| Copilot assistant bubble | `surface-panel` fill, `surface-border` hairline, tail-near `muted-strong` |
| Copilot live chip | `accent-secondary` dot + `muted-strong` text — **never a provider name** |
| Fallback / deterministic note | `caution` label — must read "fallback" honestly |

### 2.3 Missing-requirement vs gap vs strong (visual contract)

- **Strong** — verified or self-reported level meets the requirement: row pill `success-soft` / `success` text. If the level is only self-reported, pill stays `success` but LevelBadge says `Self-reported`.
- **Gap** — present but below required level: pill `caution-soft` / `caution` text.
- **Missing** — not present: pill `surface-border` fill / `muted` text. Not a danger/red — it is neutral-dd, actionable, not alarming.

### 2.4 Retired hues and the migration rule

Retired from new work: `--sb-blue`, `--sb-blue-dark`, `--sb-blue-soft`, `--sb-gold*`, `--amber` as a standalone status, and arbitrary `#D7263D`-type reds outside destructive confirmations. Migration rule: at the end of the redesign, `rg Grep` for `--sb-blue|--sb-gold|--amber` in `frontend/src/index.css` and component `style={{ color: '#...' }}` must return only the role aliases defined in the token layer. No component file may contain a raw hex.

---

## 3. Type

### 3.1 Fonts

- **Latin / EN:** `Inter` (UI) — loaded at `frontend/index.html`; fallbacks `system-ui, -apple-system, "Segoe UI"`.
- **Arabic / AR:** `"Noto Kufi Arabic"`, `"Noto Sans Arabic"`, `"Cairo"` first in the stack under `[dir='rtl']`; Latin tokens (commands, ports, filenames) keep Inter via `:lang` isolation. Rule: the stack is chosen by the shell `dir`, and code/data runs are always `dir="ltr"` wrapped (section 5).

### 3.2 Scale (type tokens)

| Token | Size / line | Use |
|---|---|---|
| `--sb-type-xs` | 11px / 1.4 | eyebrows, micro labels (never Arabic uppercase/tracking) |
| `--sb-type-sm` | 12.5–13px / 1.5 | meta lines, chips, card sub |
| `--sb-type-md` | 14px / 1.55 | body default |
| `--sb-type-lg` | 16–18px / 1.5 | card titles, section headers |
| `--sb-type-xl` | 20–24px / 1.35 | topbar h2, hero role title (sm) |
| `--sb-type-hero` | 26–28px / 1.3 | dashboard hero role title |

### 3.3 Arabic typography rules (non-negotiable)

1. `letter-spacing: 0` on every Arabic string — tracking breaks cursive joining. Global `-0.01em` on `h1–h4` is reset under `[dir='rtl']`.
2. Line-height ≥ 1.6 for Arabic body (diacritics/comprehension).
3. `text-transform: uppercase` is Latin-only; Arabic labels stay sentence case, no transform.
4. Digits follow the message language: Arabic prose uses Western digits by default (backend convention) unless the source is Arabic-native; this is a pinned convention, verified in screenshots, not forced by CSS.
5. Punctuation: message roots get `dir="auto"` so `؟`/`،` land on the correct visual end in mixed runs.
6. Bidi isolation: every inline code, URL, port, version token, filename gets `dir="ltr"` + `unicode-bidi: isolate`.

---

## 4. Spacing / radius / elevation / motion / focus

| Token | Value |
|---|---|
| `--sb-space-1` … `--sb-space-12` | 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 / 56 / 64 / 80 (4px base) |
| Section rhythm | 24px between cards (32px desktop, 20px mobile) |
| `--sb-radius-sm / md / lg / pill` | 8 / 12 / 16 / 999px |
| Elevation | `--sb-elev-1` (soft float, resting), `--sb-elev-2` (popover/drawer, 24px 65px navy .28), `--sb-elev-3` (Copilot overlay, 32px 80px navy .32) |
| Motion | 150 / 200 / 250ms, `cubic-bezier(.22,.8,.32,1)`; reduced-motion honored |
| Focus | `:focus-visible` 2px ring in `accent-primary`; inputs 2px `accent-primary` border on focus |
| Radius mirroring | radii are logical — bubble tails use the logical corner (end-bottom under both dirs); never physical `border-bottom-left-radius` for tails |

---

## 5. Shell spec & the full-shell RTL register

### 5.1 Shell anatomy

```
├─ .sidebar                     (navy; brand-block, main-nav, role-badge)
│   ├─ .brand-block             (S mark · eyebrow · wordmark)
│   ├─ nav .nav-item            (Dashboard / Skills & Roles / Learning / Practice / Assessments / University)
│   └─ .role-badge              (Signed in as …)
├─ .content                     (light canvas)
│   ├─ .topbar                  (nav-toggle · eyebrow + h2 · actions: role-chip, bell, user-chip)
│   ├─ .demo-banner             (provenance banner — honest demo note)
│   ├─ [section]                (Dashboard content; other pages mount here)
│   ├─ .app-footer
└─ .copilot-panel  (overlay, floating, logical-end; Dashboard visible behind)
```

Ordering is unchanged from `frontend/src/App.tsx`; only the visual layer is respecified here.

### 5.2 Language state → direction (first-class requirement)

- `AppContext.language` is the **only** source of truth. It is promoted from the Copilot subtree to the shell root: the shell root element receives `dir={language === 'ar' ? 'rtl' : 'ltr'}`.
- Side effects of the promotion (this is the fix scope for "full shell mirror"):
  1. `.sidebar` flex position flips natively (picture-in-picture of the RTL audit: physical `left/right` in `.nav-open`/`.nav-backdrop` become `inset-inline`).
  2. `.topbar` chrome (bell, user-chip, role-chip) reorders on the logical end; `text-align` on `.topbar h2` and `.copilot-*` chrome becomes logical.
  3. `.nav-backdrop`, skip-link, footer, drawers: all flip.
  4. Every directional glyph mirrors at the **CSS level**, not by swapping assets: `IconSend`, `IconBack`, chevrons (`.user-chev`, quick-access `chev`), pagination arrows, `crumbs` separators → `transform: scaleX(-1)` under `[dir='rtl']` (non-directional icons — mic, volume, stop, copy, lock, target, bell — must **not** mirror).
  5. Content grids that use `grid-template-areas` with physical column order (= copilot interview grid) are converted to logical ordering so the icon lands on the logical start.
- This is documented in `docs/rtl-chat-audit.md`; this spec absorbs its defect register (B1–B5, C1–C6, D1–D8, F1–F4) as the acceptance bar for the mirror.

### 5.3 The RTL register (per-region rules; EN = no-op, AR = applied)

| Region | LTR (reference) | ARRTL rule applied via |
|---|---|---|
| Shell root | `dir=ltr` | `dir=rtl` at `.app-shell`; all layout logical |
| Sidebar nav active rail | left edge | `inset-inline-start` rail, `accent-primary` |
| Breadcrumbs / crumbs | left-to-right | logical `::before` separators flip |
| ScoreRing label stack | centered | unchanged (radial) |
| Gap map rows | icon-start | flex auto-mirror; dot on logical start |
| Match breakdown accordion | chevron-end | chevron flips; `border-inline-start` for the raised "why" line |
| Job rows + filters | selects row | flex auto-mirror; select caret position physical in browser — keep default, verify |
| JourneySpine phase rail | left→right | flip to right→left reading order (DOM order preserved, `flex-direction` via dir) |
| Copilot bubbles | user right / assistant left, tail bottom-near | auto via flex + **logical tail radius** (`border-end-start-radius` on user; assistant mirrors) |
| Copilot composer | pill at bottom, send on logical end | auto-mirror; send glyph flips |
| Tracker drawer / accordions | slide-in inline | `inset-inline` slide; drawer on logical end |
| Voice overlay | (see 5.6) | chrome mirrors; mic stays unmirrored |

Every entry above get a screenshot in the acceptance pass.

### 5.4 Responsive contract (applies in both dirs)

| Width | Behavior |
|---|---|
| ≥ 1024 | Sidebar persistent (264px), content max ~1200px centered, grid-2 two columns |
| 900–1023 | Sidebar persistent, content single-flow, hero ring shrinks |
| < 900 | Sidebar off-canvas (`nav-open` slides from **logical** start), `.nav-backdrop` overlay, burger always in topbar |
| ≤ 390 | Single column; topbar h2 trims; hero stack; rings inline-start; touch targets ≥ 44px |

### 5.5 Class-contract preservation (frozen, asserted)

`frontend/scripts/*.mjs` scripts assert these literal class strings and/or CSS presence. The redesign must keep them verbatim in the same markup roles. (Full register in earlier analysis; summary:)

```
crumbs  mxb  srb-cat-version  tutor-input copilot-input  btn
rd-pager  rd-tabs  scn-decision-icon  scn-fam  camera-preview
job-save-btn  btn btn-primary
CSS-asserted: .job-row-actions .tracked-panel .tracked-item
              .tracked-badge .tracked-form .tracked-history
```

Semantic caveats: `btn` + `btn-primary` co-occur on primary buttons; `tutor-input copilot-input` is the single Copilot composer (keep the `tutor-input copilot-input` form element — do not swap to a div or rename); `mxb` must stay a native `<details>`; `crumbs` appears on more than one page; any additional class found later in a `.mjs` assertion is equally part of the contract. **Restyling is additive: derive new token classes, keep the strings.**

### 5.6 Voice overlay — skin-only contract

- The voice state machine (`VOICE_TOTAL_STATES`, transitions, timeouts, icons) is **frozen**. No state added, removed, or renamed.
- Every state class referenced by the overlay keeps its name and meaning.
- This spec only reskins: colors → role tokens, radii, spacing, RTL registration of the chrome.
- Mic icon and animation assets: never mirrored; stays physically neutral.

### 5.7 Provider / provenance UI rules (applies to the whole shell, EN + AR)

1. **No provider names in user-facing UI** — live chips, persona blocks, credits. The "NVIDIA NIM" chip is a defect; the live chip shows a role-colored dot (`accent-secondary`) + "Live".
2. Fallback/deterministic output is labelled honestly with the literal `fallback` source — never present as live AI.
3. Demo banner keeps the honest phrasing from `App.tsx` (no GenAI key, no email, etc.).
4. Persona avatars come from `frontend/public/assets/tutors/{nova,axel,sage,vex}.png` — local, no CDN, no expiry. `dist` copies are build artifacts.

### 5.8 Trust-language states (must be visible in the mockups; drawn from live + mixed demo data)

`self-reported skill · verified skill · gap · missing requirement · pending assessment · passed assessment` — the Dashboard mockup shows all six, with `verified` claims only on assessment-passed evidence.

---

## 6. EN + AR copy rules

- Topbar eyebrow stays an app-level string, localized: EN "Verified skill loop" → AR "حلقة التحقق من المهارات".
- Placeholders are defects to kill: "Your dashboard", "your current topic" in the Copilot context row, "Self-reported" badges rendered in English inside Arabic, "Warm • Patient • Clear" trait rows — all localized in the AR mockup.
- Persona names ("Nova", "Axel", "Sage", "Vex") stay as-is in both languages (backend identity) — pinned convention.
- Technical tokens (Docker, Python, port numbers, file names) stay Latin inside `dir="ltr"` spans.

---

## 7. Acceptance gates (for these two deliverables)

1. `npx tsc --noEmit` clean and `npm run build` clean on the frontend tree when the token layer lands.
2. All 24 hand checks in the RTL register pass in a headless render at 1440 / 1024 / 390, EN + AR (screenshots attached).
3. No raw hex outside `:root` token definitions (`rg` gate).
4. Class contract: all `frontend/scripts/*.mjs` checks still pass (contract strings unchanged).
5. Six trust-language states visible and correctly sourced in the Dashboard mockup.
6. No provider-name, no fake-"live", no English-in-Arabic defects reproduce in the mockups.
7. Human review of `docs/mockups/dashboard-en.html` + `dashboard-ar.html` before any further surface is designed.