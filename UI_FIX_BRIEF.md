# SkillBridge — Theme, UI & Font Fix Brief

## What this is
SkillBridge is a React + TypeScript + FastAPI app for students/companies/universities. The frontend is in `frontend/src/`. The single CSS file `frontend/src/index.css` (2430 lines) styles the entire app.

## What happened
A previous agent added dark-mode overrides that turned the entire app dark navy/blue. We removed the dark `:root` override block and bulk-replaced ~150 hardcoded dark colors (`#070b16`, `#0b1120`, `#111a2d`, etc.) with CSS variable references. The app now uses a **light theme** but the conversion was mechanical and may have visual inconsistencies.

## Design intent (reference the old project)
- **Background**: light gray `#F8FAFC` canvas
- **Cards/panels**: white `#FFFFFF` with subtle border `#E2E8F0`
- **Headings**: deep navy `#0D1B2A`
- **Body text**: slate `#64748B` / `#334155`
- **Primary accent**: coral/orange `#FF6B2C` (buttons, active states)
- **Secondary accent**: teal `#14B8A6`
- **Success**: green `#1E8A5A`
- **Error**: red `#D7263D`
- **Nav sidebar**: deep navy `#0D1B2A` with white text
- **Font**: Inter (Google Fonts), loaded in `index.html`

## Files to examine
1. **`frontend/src/index.css`** — THE main file. ~2430 lines. Lines 1-65 are `:root` CSS variables. Lines 66-945 are original component styles (should be correct). Lines 946+ were dark overrides that got mechanically converted — these likely have color inconsistencies.
2. **`frontend/src/index.html`** — HTML shell, font imports
3. **`frontend/src/components/`** — React components
4. **`frontend/src/pages/`** — Page components (LoginPage, DashboardPage, LearningPage, AssessmentsPage, SkillsRolesPage)
5. **Reference**: `C:\Users\khale\Downloads\SkillBridge-main\SkillBridge-main\frontend\src\index.css` (920 lines) — the original light theme before dark overrides were added. Use as ground truth.

## What needs fixing
1. **Visual audit**: Open the running app (`http://localhost:8000`) and check every page for any dark/inconsistent colors — backgrounds that should be white, text that should be dark, accent colors that don't match the palette.
2. **CSS variable consistency**: Make sure all component styles use the CSS variables defined in `:root` instead of hardcoded hex values.
3. **Font**: Ensure Inter loads correctly and is applied everywhere. Check font weights and sizes are consistent.
4. **Specific problem areas** (from our mechanical replacement):
   - Messages (`.msg.assistant`, `.msg.user`, `.msg.interviewer`, `.msg.student`, `.msg.note`)
   - Learning skill cards (`.learning-skill-card`)
   - AI tutor workbench panels
   - Resource cards
   - Dashboard stat cards
   - Badge/chip colors
5. **Buttons**: Primary buttons should be coral `#FF6B2C`, secondary buttons should be outlined slate.
6. **The login page** has a split layout: left side is navy hero panel with the SkillBridge logo + journey diagram, right side is white form card. Make sure this contrast is correct.

## Demo accounts (password: `demo1234`)
- Student: `aisha@student.edu`
- Company: `hr@northstar.com`
- University: `admin@univ.edu`

## Start command
```
cd SkillBridge-Final
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\start.ps1
```
Then open `http://localhost:8000`
