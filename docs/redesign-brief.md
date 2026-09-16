# SkillBridge — UI Redesign Brief

**Status:** DRAFT FOR REVIEW. **Scope:** the redesign of all six student surfaces (Dashboard, Skills & Roles, Learning, Practice, Jobs/Career Roadmap, Copilot) as self-contained static HTML mockups that review, approve, and then implement against the token layer and shell.

**Body of work:** the brief (this doc), plus one self-contained HTML file per surface under `docs/mockups/` (§13 delivery format). The first surface is the Dashboard (`docs/mockups/dashboard.html`); nothing else starts until that is reviewed and approved.

---

## §1. Purpose and scope

- Each surface ships as **one self-contained HTML file** — inline CSS, inline SVG icons, Google Fonts links, zero JavaScript.
- Each file is a **review artifact**, not the production component. Production work happens later against `frontend/src/*`; these files are the visual + interaction contract the implementation must match.
- The single file carries an **EN ⇄ AR toggle** and a **viewport toggle** implemented purely with `:has()` radio selectors (no JS) so the reviewer sees the same HTML in both languages and at 1440 / 1024 / 390 px.
- Logical properties only. No `margin-left`, `padding-left`, `border-left`, physical `left`, or physical `right` anywhere. Layout flips by `direction`, not by per-component overrides.
- The `:has()` toggle is a **review tool**; the production app already carries real language state (`AppContext.language`) and must not gain hidden radio inputs. The mockup proves the layout contract; implementation promotes the state differently (§6).

---

## §2. Color roles

Canonical tokens are `--sb-role-*` (production). The mockups reference them through **short-form aliases** defined at the top of each mockup's `<style>` (`--surface`, `--panel`, `--accent`, `--data`, `--verified`, `--success`, `--caution`, `--missing`, `--ink`, `--muted`, `--navy`, `--on-navy`, etc.). The aliases map 1:1 to the rows below; the CSS never invents a hue and never inlines a raw hex.

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
- `--sb-role-success` and `--sb-role-verified` are **deliberately distinct roles** with the same anchor today. `success` answers "did you meet the bar?" (passed assessment, ready). `verified` answers "is this claim backed by evidence?" Keeping them separate lets a future tint differ without renaming.
- `data` is indigo `#7C5CFC` only — progress rings and match breakdown visuals. Teal must not be used as a competing chart hue.
- Retired hues: `--sb-blue*`, `--sb-gold*`, `--amber` as a status, arbitrary reds outside destructive confirmations. None of them appear in the mockups; production migration gate is `rg` on `--sb-blue|--sb-gold|--amber` and raw hex in component files.

---

## §3. Typography

### §3.1 Fonts

- **Latin / EN:** `Inter` (400 / 500 / 600 / 700), loaded from Google Fonts in each mockup; fallbacks `system-ui, -apple-system, "Segoe UI"`.
- **Arabic / AR:** `"IBM Plex Sans Arabic"` (400 / 500 / 600 / 700) — neutral, text-friendly. Loaded alongside Inter. Applied via `body:has(#lang-ar:checked) { font-family: var(--font-sans-ar); }`. Latin tokens (commands, ports, filenames) keep the Latin stack via `dir="ltr"` + `unicode-bidi: isolate`.

### §3.2 Scale

| Token | Size / line | Use |
|---|---|---|
| `--sb-type-xs` | 11px / 1.4 | eyebrows, micro labels (never Arabic uppercase/tracking) |
| `--sb-type-sm` | 12.5–13px / 1.5 | meta lines, chips, card sub |
| `--sb-type-md` | 14px / 1.55 | body default |
| `--sb-type-lg` | 16–18px / 1.5 | card titles, section headers |
| `--sb-type-xl` | 20–24px / 1.35 | topbar h2, hero role title (sm) |
| `--sb-type-hero` | 26–28px / 1.3 | dashboard hero role title |

### §3.3 Arabic typography rules (non-negotiable)

1. `letter-spacing: 0` on every Arabic string — tracking breaks cursive joining.
2. Line-height ≥ 1.6 for Arabic body text.
3. `text-transform: uppercase` is Latin-only; Arabic labels stay sentence case with no transform.
4. Digits follow the message language: Western digits by default (backend convention) unless a source is Arabic-native.
5. Punctuation: message roots get `dir="auto"` for `؟`/`،` placement in mixed runs.
6. Bidi isolation: every inline code, URL, port, version token, filename gets `dir="ltr"` + `unicode-bidi: isolate`.

---

## §4. Spacing / radius / elevation / motion / focus

| Token | Value |
|---|---|
| `--sb-space-1` … `--sb-space-12` | 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 / 56 / 64 / 80 (4px base) |
| Section rhythm | 24px between cards (32px desktop, 20px mobile) |
| `--sb-radius-sm / md / lg / pill` | 8 / 12 / 16 / 999px |
| Elevation | `--sb-elev-1` (soft float, resting), `--sb-elev-2` (popover/drawer, 24px 65px navy .28), `--sb-elev-3` (Copilot overlay, 32px 80px navy .32) |
| Motion | 150 / 200 / 250ms, `cubic-bezier(.22,.8,.32,1)`; reduced-motion honored |
| Focus | `:focus-visible` 2px ring in `--sb-role-accent-primary`; inputs 2px primary border on focus |
| Radius mirroring | Radii are logical — bubble tails use logical corners under both dirs; never physical `border-bottom-left-radius` for tails |

---

## §5. Layout shell diagram

```
┌──────────────────────────────────────────────────────────────┐
│ .app-shell  (display: grid; grid-template-columns: 240px 1fr) │
│                                                              │
│  ┌─────────┬────────────────────────────────────────────────┐ │
│  │ .sidebar│ .content                                       │ │
│  │ navy    │  ┌ .topbar ─────────────────────────────────┐  │ │
│  │ 240px   │  │ [burger] eyebrow+h2   [role-chip] [🔔]    │  │ │
│  │         │  │                     [user-chip]           │  │ │
│  │ brand   │  ├───────────────────────────────────────────┤  │ │
│  │  S      │  │ [section]                                 │  │ │
│  │  word   │  │  hero · journey · gap map · jobs · …      │  │ │
│  │  mark   │  │                                           │  │ │
│  │         │  ├───────────────────────────────────────────┤  │ │
│  │ nav     │  │ .app-footer                               │  │ │
│  │ [6]     │  └───────────────────────────────────────────┘  │ │
│  │ items   │                                                │ │
│  │         │  ┌ .copilot-panel (floating, logical-end) ────┐ │ │
│  │ role    │  │ │         │     .msgs thread             │  │ │
│  │ badge   │  │ │ avatar  │     .copilot-bar (frozen)    │  │ │
│  │         │  │ │  name   │     .copilot-bar-copy        │  │ │
│  └─────────┘  └────────────────────────────────────────────┘ │ │
└──────────────────────────────────────────────────────────────┘
```

- `.sidebar`: 240px, navy gradient to `--sb-role-brand-navy-deep`. Brand block (S mark, eyebrow, wordmark), nav (6 items; active item gets an accent-primary rail on the logical inline-start + white text on `rgba(255,255,255,.08)`), role-badge ("Signed in as …").
- `.topbar`: burger (hidden ≥ container 1024), eyebrow + h2, actions on the logical end (role-chip, bell, user-chip).
- `.content`: light canvas, mounts the page section, footer.
- `.copilot-panel`: floating panel on the logical end (right in LTR, left in RTL), raised elevation, sticky on desktop, fixed overlay on narrow widths.
- Ordering is unchanged from `frontend/src/App.tsx`; only the visual layer is re-specified.

---

## §6. RTL full-shell mirror

Language promotion: language state promotes to the whole shell — the root gets `dir="rtl"`/`ltr`. Every region mirrors (sidebar, topbar, breadcrumbs, pagination, rails, chips, accordions). Manual `[dir='rtl']` exceptions register here; anything not listed here must mirror automatically via logical properties.

RTL register (per-region rules; EN = no-op, AR = applied):

| Region | LTR (reference) | AR rule applied via |
|---|---|---|
| Shell root | `dir=ltr` | `dir=rtl` on shell root; all layout logical |
| Sidebar nav active rail | left edge | `inset-inline-start` rail, accent-primary |
| Breadcrumbs / crumbs | left-to-right | logical separators flip |
| ScoreRing label stack | centered | unchanged (radial) |
| Gap map rows | icon-start | flex auto-mirror; dot on logical start |
| Match breakdown accordion | chevron-end | chevron flips; `border-inline-start` for the raised line |
| JourneySpine phase rail | left→right | flip to right→left reading order (DOM order preserved) |
| Copilot bubbles | user end / assistant start, tail bottom-near | auto via flex + logical tail radius |
| Copilot composer | pill at end | auto-mirror; send glyph flips |
| Tracked-panel / drawer | slide-in inline | `inset-inline` slide; drawer on logical end |

Directional icons mirror at the CSS level by `transform: scaleX(-1)` under AR (send, back, chevrons, pagination arrows). Non-directional icons (mic, volume, stop, copy, lock, target, bell) must **not** mirror.

Code, commands, ports, URLs, filenames: always `dir="ltr"` + `unicode-bidi: isolate`.

---

## §7. Responsive contract

The mockup uses **container queries** (`@container (max-width: …)`), scoped to `.viewport-wrapper { container-type: inline-size; }`, so the toggle changes only the wrapper width without affecting the outer page. The toolbar lives outside the wrapper.

| Wrapper width | Behavior |
|---|---|
| ≥ 1024 | Sidebar persistent, content max ~1200 centered, two-column grids |
| 900–1023 | Sidebar persistent, content single-flow, hero ring shrinks |
| 560–899 | Sidebar off-canvas (slides from logical start), backdrop overlay, burger in topbar |
| ≤ 390 | Single column; hero stack; touch targets ≥ 44px |

---

## §8. The `:has()` review toggle

One file, five hidden radio inputs, no JS:

```html
<input type="radio" name="lang" id="lang-en" checked>
<input type="radio" name="lang" id="lang-ar">
<input type="radio" name="vp"  id="vp-1440" checked>
<input type="radio" name="vp"  id="vp-1024">
<input type="radio" name="vp"  id="vp-390">
```

Language toggle:

```css
body:has(#lang-ar:checked) { direction: rtl; font-family: var(--font-sans-ar); }
body:has(#lang-ar:checked) .ltr-only { display: none; }
body:has(#lang-ar:checked) .rtl-only { display: inline; }
body:has(#lang-ar:checked) .icon-directional { transform: scaleX(-1); }
```

Viewport toggle:

```css
body:has(#vp-1024:checked) .viewport-wrapper { width: 1024px; }
body:has(#vp-390:checked)  .viewport-wrapper { width: 390px;  }
```

String-pair convention (every visible string):

```html
<span class="ltr-only">Dashboard</span>
<span class="rtl-only">لوحة التحكم</span>
```

AR typography resets:

```css
body:has(#lang-ar:checked) .eyebrow,
body:has(#lang-ar:checked) .ring-label small,
body:has(#lang-ar:checked) .insight-card .label { letter-spacing: 0; text-transform: none; }

body:has(#lang-ar:checked) .dashboard-hero-copy p,
body:has(#lang-ar:checked) .card-sub,
body:has(#lang-ar:checked) .sr-name,
body:has(#lang-ar:checked) .sr-cat,
body:has(#lang-ar:checked) .assess-row { line-height: 1.7; }
```

---

## §9. Trust-language primitives

Six states must be visible in every surface where they occur. The Dashboard shows all six (§11 data).

| State | Visual contract |
|---|---|
| `self-reported` | Muted chip label "Self-reported" / Arabic "مستوى ذاتي"; never green; stays muted/caution |
| `verified` | Green mark (`--sb-role-verified`), verified-soft fill; only ever on assessment-passed evidence |
| `gap` | Caution pill (`--sb-role-caution`), present but below required level |
| `missing` | Neutral pill (`surface-border` fill, muted text); actionable, not alarming |
| `pending` | Caution-chip in assessment strip; "pending" / "قيد الانتظار" |
| `passed` | Success chip in assessment strip; green text on success-soft |

Rule: green is **only** ever used for assessment-passed evidence. Anything self-reported stays muted/caution.

---

## §10. Frozen Copilot class surface

These classes are asserted by the frontend contract scripts and/or are part of the production Copilot structure. They must keep their literal names and semantic roles in every mockup and in implementation:

```
copilot-panel      (the floating Copilot panel)
copilot-bar        (the composer bar at the bottom)
copilot-avatar     (the persona avatar in the composer bar)
copilot-bar-copy   (the copy area of the composer bar)
```

Plus the wider class contract (kept verbatim, restyled additively):

```
crumbs  mxb  srb-cat-version  tutor-input copilot-input  btn
rd-pager  rd-tabs  scn-decision-icon  scn-fam  camera-preview
job-save-btn  btn btn-primary
CSS-asserted: .job-row-actions .tracked-panel .tracked-item
              .tracked-badge .tracked-form .tracked-history
```

Semantic caveats: `btn` + `btn-primary` co-occur on primary buttons; `tutor-input copilot-input` is the single Copilot composer — keep it one form element; `mxb` must stay a native `<details>`; `crumbs` appears on more than one page. Restyling is additive.

---

## §11. Demo data contract

The Dashboard mockup exercises all six trust states with a single coherent persona. Fixed values (do not swap the topic):

- **Target role:** Cybersecurity Analyst — 54% match
- **Verified:** Network Security (Intermediate — passed)
- **Self-reported:** Communication, Cybersecurity, Threat Detection, SIEM, Incident Response
- **Gap:** Vulnerability Management
- **Missing:** Active Directory, Linux, Risk Assessment, Windows Server, Critical Thinking
- **Assessments:**
  - NetSec Fundamentals — **passed**, 86, 2026-02-14
  - SIEM Analyst — Tier 1 — **pending**, 40%, due 2026-03-12
- **`.mxb-body` match breakdown** (three weighted bars): Core 80% · Tools 50% · Soft 13%

Skill gap map rows (strong / gap / missing):

| Skill | State | Level evidence | mask |
|---|---|---|---|
| Network Security | Verified | passed assessment | `verified` badge, strong pill |
| Communication | Self-reported | CV | self-reported badge, strong pill |
| Cybersecurity | Self-reported | CV | self-reported badge, strong pill |
| Threat Detection | Self-reported | CV | self-reported badge, gap pill (below required) |
| SIEM | Self-reported | CV | self-reported badge, gap pill |
| Vulnerability Management | Gap | present, below level | gap pill |
| Active Directory | Missing | absent | missing pill |
| Linux | Missing | absent | missing pill |
| Risk Assessment | Missing | absent | missing pill |

Copilot thread: real topic, real scope label (e.g. a Network Security / SIEM tutoring turn). No placeholder text anywhere.

---

## §12. Provider / provenance rules

1. **No provider names in user-facing UI** — live chips, persona blocks, credits. No "NVIDIA", no "NIM", no provider blink text.
2. Fallback/deterministic output is labelled honestly with the literal `fallback` source (`caution` label) — never presented as live AI.
3. Demo banner keeps the honest phrasing (no GenAI key, no email, no overclaim).
4. Persona avatars come from `frontend/public/assets/tutors/{nova,axel,sage,vex}.png` in production; mockups use colored initials placeholders (static files cannot resolve app assets).
5. No placeholder text — every visible string is real content or a paired EN/AR string.

---

## §13. Delivery format

- **One self-contained HTML file per surface** under `docs/mockups/<surface>.html`.
- Each file: inline CSS, inline SVG, Google Fonts links, five hidden radios (`lang-en`/`lang-ar`, `vp-1440`/`vp-1024`/`vp-390`), zero JS.
- EN default (`<html lang="en">`); AR reached via `body:has(#lang-ar:checked)`.
- String-pair convention (§8): every visible string is `<span class="ltr-only">…</span><span class="rtl-only">…</span>`.
- Logical properties only (§5, §6). Container queries for the responsive behavior (§7).
- Frozen class surface preserved (§10). Demo data per §11. Provenance per §12.
- This file format **replaces** the previous two-file (per-language) delivery. There are no more `-en.html` / `-ar.html` pairs; the toggle lives in the file.
- The surface list, in order: Dashboard → Skills & Roles → Learning → Practice → Jobs/Career Roadmap → Copilot. Dashboard is reviewed and approved before the next file starts.