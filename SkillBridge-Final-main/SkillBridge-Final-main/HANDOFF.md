# SkillBridge — Complete Learning Handoff

You are receiving the CURRENT working SkillBridge project from another developer.
This project already contains substantial completed work.

**IMPORTANT:**
- Do **NOT** rebuild the project from scratch.
- Do **NOT** reset/revert/stash/clean the repo.
- Do **NOT** delete existing modified/untracked files.
- Do **NOT** recreate completed Learning features.
- Read `AGENTS.md` first.
- Find the actual `.git` repo root before doing anything.
- Inspect `git status` and `git diff`.
- Preserve the current architecture unless a real test/runtime regression is found.

The current Learning system has already gone through multiple implementation and browser-verification phases.

---

# CURRENT PRODUCT IDEA

SkillBridge is **NOT** intended to be:
```
Generate Course → Student reads → Quiz → Done
```

The Learning experience is now:
```
Skill Gap
→ Diagnostic
→ Personalized Learning Path
→ Learn
→ Example
→ Recommended Resources
→ Practical Task
→ AI Evaluation
→ Personalized Remediation
→ Follow-up Practice
→ Mini Check
→ Topic Complete
→ Final Assessment
→ Verified Skill
```

The AI is supposed to diagnose exactly what the Student is weak at, teach that part, evaluate actual work, and react to the Student's mistakes.

---

# PHASE 1 — DIAGNOSTIC-BASED LEARNING FLOW (COMPLETE)

The old generated learning roadmap is no longer the main Student UX.
The primary Learning flow is now:
```
Skill Gap → Diagnostic → Personalized Path → Lesson
```

**Diagnostic:**
- generates approximately 5–9 competency-tagged questions
- calculates competency scores
- classifies topics:
  - **Mastered:** >= 75%
  - **Developing:** 40–74%
  - **Weak:** < 40%

The Personalized Path uses the latest Diagnostic.
Weak/developing competencies become active topics.
Weak topics are prioritized.
Mastered competencies can be skipped.

---

# PERSONALIZED PATH

The personalized path is now the primary visible Learning progress source.
Student sees topic states such as:
- Not started
- In progress
- Completed
- Mastered / skipped

Manual Student checkbox completion was removed.
The Student cannot simply tick a topic as completed.
Topic completion occurs through the Mini Check.
Internal backend compatibility APIs may still exist; do not delete them unnecessarily.

---

# IMPORTANT VERIFIED-SKILL RULE

Learning completion is **NOT** Verified Skill.
Practice is **NOT** Verified Skill.
Mini Check is **NOT** Verified Skill.

Only the real Final Assessment can create/update a Verified Skill.
Preserve this distinction.

---

# FINAL ASSESSMENT RULE

Final Assessment is independent from Learning progress.
The Student does **NOT** need to finish the whole Learning Path before starting the Assessment.
The Learning Path now presents this honestly as:
```
Final Assessment — AVAILABLE ANYTIME — Independent from learning progress.
```
Do **NOT** add a Learning completion gate.

---

# PHASE 2 — REAL EVALUATED PRACTICE (COMPLETE)

Practice used to be frontend-only.
It now has a real backend evaluator.

**Flow:**
```
Practical Task → Student submits answer → Practice evaluation
→ score → status → strengths → missing points → feedback → next action
```

Practice attempts persist.
Refresh does not lose the latest result.
Retry creates another attempt instead of overwriting history.

**Statuses:**
- score >= 70 → `ready`
- score < 70 → `needs_review`

This threshold belongs to Practice readiness only.
It is **NOT** verification.

---

# PRACTICE AI + FALLBACK

The Practice evaluator supports:
1. Live GenAI semantic evaluation
2. Deterministic fallback when AI fails/unavailable

Fallback is honestly labelled: `source: "fallback"`
The UI must never pretend fallback evaluation is live AI.
Automated tests should not unnecessarily call paid AI APIs.

---

# PRACTICE SECURITY

Backend resolves trusted context.
Frontend must not be able to spoof:
- student
- skill
- target role
- lesson topic
- follow-up task
- remediation ownership

Practice submission must **NOT**:
- complete the topic
- update Verified Skill
- change Final Assessment state

---

# PHASE 3 — ADAPTIVE REMEDIATION (COMPLETE)

If the Student gets a weak Practice score:
```
Practice → score < 70 → Practice Review → Personalized Review
```

Personalized Review includes:
- Focus Points
- targeted explanation
- targeted example
- new follow-up Practice task

The Student then answers the follow-up task.
The **SAME** Phase 2 Practice evaluator grades it.
There is no second grading system.

---

# EXAMPLE ADAPTIVE LOOP

**Attempt 1:**
Missing: persistence, bind mounts, syntax

↓ Personalized Review

Student retries.

**Attempt 2:**
Student fixed persistence and bind mounts but still misses syntax.

The next remediation should focus mainly on syntax.
Do **NOT** repeatedly reteach already-fixed concepts unnecessarily.
Do **NOT** invent mastery.

---

# TRUSTED FOLLOW-UP PRACTICE

Very important architecture rule:

The frontend may reference the prior remediation attempt.
But the backend loads the saved follow-up Practice task from persisted data.
The frontend must **NOT** be able to submit an arbitrary replacement task and ask the backend to grade against it.
This was regression-tested.

---

# REMEDIATION PERSISTENCE

Remediation is tied to the Practice attempt.
The persisted data includes the actual Practice task answered and the Personalized Review/remediation.
Old and new attempts remain available.
Refresh preserves results.

---

# TOKENIZER FIX

A deterministic fallback bug was fixed.

Previously:
```
mount
```
and:
```
mount.
```
could be treated as different tokens.

Token normalization now strips surrounding punctuation while preserving meaningful technical syntax where possible.
Examples that remain meaningful: `docker-compose`, `read-only`, `--mount`

Regression tests exist.
Do **NOT** undo this normalization.

---

# PRACTICE UX REDESIGN (COMPLETE)

Old Practice looked like:
```
Task 1 MCQ + Task 2 MCQ + Task 3 MCQ + one textarea
```

This was removed because it duplicated Mini Check and confused Students.
Practice is now **ONE real open-ended task**.

**Product distinction:**
- **Learn** = understand
- **Example** = see
- **Practice** = do
- **Mini Check** = check understanding

---

# PRACTICE TYPES

Technical skills should prefer tasks such as:
- code
- commands
- troubleshooting
- configuration
- analysis
- implementation
- realistic technical scenario

Example Docker Practice:
Student must give concrete Docker commands/configuration, explain them, say how they know it worked, and explain how they would debug failure.

Non-coding skills use realistic scenario responses.

---

# MINI CHECK

Mini Check remains different from Practice.
Mini Check may use: MCQ, short-answer, small knowledge questions.

**Pass threshold:** >= 70%

Mini Check pass marks the current Learning topic completed.
Mini Check does **NOT** create Verified Skill.
Practice score must **NEVER** be reused as Mini Check score.

---

# PHASE 3 UI

**Weak Practice:**
```
Practice Review → Needs Review
→ strengths → missing points → feedback → next action
→ Personalized Review
→ targeted example
→ Try This Next
→ follow-up Practice
```

**Strong Practice:**
```
Ready for Mini Check
```
The primary next action becomes: Continue to Mini Check.
Practice remains guidance and must not hard-lock Mini Check.

---

# PRACTICE LOADING UX

Real AI Practice evaluation may take roughly 10–30 seconds.
While the REAL request runs:
- show `Evaluating your practice...`
- keep the Student's answer visible
- disable duplicate Submit
- do **NOT** show fake progress percentages

On failure:
- restore controls
- show inline error
- keep the lesson open

---

# NORMAL LESSON CONTENT

**Lesson structure:** Learn → Example → Practice → Mini Check

Learn contains explanations/key ideas.
Example demonstrates the concept.
Code examples are display-only.
No code execution sandbox was added.

---

# CODE FORMATTING

Normal lesson code examples were fixed so multiline code preserves line breaks.
Adaptive Remediation `targeted_example` code formatting was also fixed.

Python examples must preserve:
- import lines
- class indentation
- method indentation
- separate statements
- proper code-block rendering

Persisted remediation is formatted at the response boundary without destructive DB rewriting.

---

# HUMAN-READABLE TOPIC LABELS

Internal topic IDs remain unchanged.
Example internal IDs: `statistics_fundamentals`, `deep_learning_fundamentals`, `pandas_fundamentals`

Student-facing UI shows:
- Statistics Fundamentals
- Deep Learning Fundamentals
- Pandas Fundamentals

Do **NOT** replace internal competency IDs in storage/API logic.
Humanization is presentation only.

---

# PHASE 4 — RECOMMENDED LEARNING RESOURCES (COMPLETE)

Personalized lessons now contain: **Recommended Resources**

**IMPORTANT:**
Resources currently appear **INSIDE** the Learn section.
They have not disappeared.
They are intentionally shown below/supporting the Learn content rather than as a separate top-level tab.

---

# RESOURCE UX

A lesson may show approximately 2–4 useful resources.
Each resource can show:
- title
- provider/source
- type
- why it helps
- link status
- Open Resource

Resources are visually secondary to the main Learning flow.

---

# RESOURCE TYPES

Examples: Documentation, Tutorial, Article, Video, Reference

---

# RESOURCE SOURCES

URLs do **NOT** come from free-form LLM generation.
The backend uses:
- curated known resources
- trusted catalog entries
- existing resource infrastructure
- validated retrieval/checking

AI must never invent a URL and present it as real.
AI may assist with relevance/ranking/explanation, but URLs remain trusted.

---

# TOPIC-SPECIFIC RESOURCES

Browser verified examples include:

## Pandas
Official Pandas documentation/tutorial resources.
Example: 10 Minutes to Pandas

## Docker
Official Docker documentation.
Topics: containers, images, ports, Dockerfile, volumes, networking, multi-stage builds

## Deep Learning / PyTorch
Official PyTorch tutorials/documentation.

## Statistics for AI/ML roles
Resource ranking can prefer model-evaluation/statistics material useful for the Student's target role.

---

# RESOURCE RELEVANCE

Ranking can use: skill, competency/topic, required level, target role signal, official-source preference.
This is explainable recommendation logic.
Do **NOT** build complex recommendation scoring.
Do **NOT** modify job-match scoring.

---

# RESOURCE URL SAFETY

The server performs URL safety validation.
Unsafe URLs are rejected before link checking.
Protection includes rejection of:
- non-http/https
- localhost, private IPs, loopback, link-local, multicast
- reserved/unspecified IPs
- `.local`, `.internal`
- embedded URL credentials

Do **NOT** weaken these protections.

---

# RESOURCE LINK STATUS

Avoid the word "Verified" for resource links because Verified Skill already has product meaning.
Use honest states such as: Checked, Unavailable, Status unknown.
If availability cannot be determined: do not claim it was checked successfully.

---

# OFFLINE / LINK FAILURE

External link checking must **NEVER** break the lesson.
If checking fails:
- lesson still loads
- trusted curated resources may remain
- status can be unknown

Never fake live availability.

---

# LEARNING RESOURCE FALLBACK

If exact topic resources are limited:
the system can use safe skill-level resources.
Topic-specific official resources should be preferred when enough are available.

The system was tightened so Pandas/Docker fundamentals do not get unnecessarily padded with generic marketplace/video links when strong official topic links already exist.

---

# OLD/PERSISTED LESSON COMPATIBILITY

**Important:**
Old persisted lessons must continue working.
Response normalization attaches:
- practical Practice shape
- human-readable labels
- resources
- formatted examples

without destructively rewriting old stored lesson JSON.
Do not remove this compatibility layer.

---

# STALE SERVER ISSUE — IMPORTANT

We hit stale uvicorn processes more than once.

Example symptom:
```
Practice Submit → 405 Method Not Allowed
```

The source code was correct.
An old backend process on port 8000 had been started before the Practice endpoints existed.

**Fix was simply to stop the stale server and restart the CURRENT backend.**

Therefore:
Whenever a runtime behavior contradicts current tests/source:
**FIRST** confirm port 8000 is running the CURRENT checkout.
Do not immediately rewrite working code.

---

# CURRENT VERIFIED TEST BASELINE

Final Phase 4 closeout:
- **Full backend:** 445 passed / 2 skipped
- **Focused Learning/Phase 4:** 92 passed / 2 skipped
- **Frontend:** TypeScript PASS, Vite production build PASS, Browser verification PASS

---

# REAL BROWSER VERIFICATION COMPLETED

Real browser checks confirmed:

## Pandas
- Recommended Resources visible
- official topic resources
- Practice reachable
- Mini Check reachable

## Docker
- official Docker resources
- resources cards render
- Practice works
- Mini Check works

## Deep Learning / PyTorch
- relevant PyTorch resources render

## Adaptive Learning
- weak Practice shows Personalized Review
- follow-up Practice works
- refresh preserves result
- strong Practice shows Ready for Mini Check

No real React runtime/page errors were found.

---

# CURRENT SERVER

At last verification the current project backend was successfully running on:
`http://localhost:8000`

Do not assume the same PID after project transfer.
Start the backend from THIS transferred project folder.

---

# CURRENT LEARNING STATUS

Consider Learning **FEATURE-COMPLETE** for the current prototype/hackathon scope.

Do **NOT** create a Phase 5 unless the user explicitly asks.
Do **NOT** add:
- path-level adaptive mutation
- new grading architecture
- code execution environment
- browser IDE
- certificates
- unnecessary AI agents

Focus next on stability, demo readiness, and presentation.

---

# IDEAL DEMO STORY

Use one Student story such as:

**Target Role:** Junior AI Engineer / Machine Learning Engineer
**Skill Gap:** Statistics / Docker / Deep Learning

Then demonstrate:
```
Skill Gap
→ Diagnostic
→ Weak competency detected
→ Personalized Path
→ Learn
→ Example
→ Recommended Resources
→ Practice practical task
→ intentionally weak answer
→ AI Evaluation
→ Personalized Review
→ follow-up task
→ improved answer
→ Ready for Mini Check
→ Mini Check pass
→ Topic Complete
→ Final Assessment
→ Verified Skill
```

---

# GOOD WEAK DOCKER PRACTICE ANSWER FOR DEMO

For a Docker Containers task, an intentionally weak answer can be:

> "I would put the app in Docker and run it. If it starts, then it works. If there is a problem, I would restart the container."

This should demonstrate the remediation system because it lacks:
- real Docker commands
- configuration
- port mapping
- persistence
- environment setup
- proper success signal
- proper debugging

---

# BEFORE MODIFYING ANYTHING

The new agent should:
1. Read `AGENTS.md`.
2. Find the real git root.
3. Run `git status`.
4. Inspect current Learning code.
5. Start the CURRENT backend.
6. Run existing tests before assuming something is broken.

**Do NOT reset existing work.**

---

# RECOMMENDED NEXT ACTION

Do **NOT** implement new Learning features.
First perform a smoke test of the transferred folder:

- login
- Learning
- Diagnostic
- Personalized Path
- Learn
- Recommended Resources
- Example
- Practice
- weak answer
- Personalized Review
- follow-up Practice
- Mini Check

Then report whether the transferred project behaves the same as the verified source machine.

**Expected automated baseline:**
- 445 passed / 2 skipped
- TypeScript PASS
- Vite build PASS

Exact test count may legitimately increase if new tests are later added.
**Zero failures** is what matters.

**Return:**
- Repo Status
- Backend Startup
- Learning Smoke Test
- Diagnostic
- Personalized Path
- Learn
- Recommended Resources
- Example
- Practice
- Adaptive Remediation
- Mini Check
- Final Assessment
- Test Results
- Frontend Build
- Remaining Issues

Do not implement new features unless a real transferred-folder regression is found.

**STOP.**

---

# PROJECT TECH STACK

| Layer | Technology |
|-------|-----------|
| Backend | Python 3 + FastAPI 0.110.0 + Uvicorn |
| Database | SQLite (stdlib sqlite3) |
| Frontend | React 18 + TypeScript 5.5 + Vite 5 |
| GenAI | Anthropic / OpenAI / NVIDIA NIM (with deterministic fallback) |
| Voice | ElevenLabs TTS |
| Auth | Email/password, 3 roles (Student, Company, University Admin) |
| Tests | pytest (backend), tsc + vite build (frontend) |

---

# KEY COMMANDS

```bash
# Start the app (single command)
./start.sh          # Linux/Mac
./start.bat          # Windows
# or: npm start

# Start with fresh DB
./start.sh --reset

# Backend tests
./scripts/test-backend.sh

# Frontend typecheck
npm run test:frontend

# Full build
npm run build

# Access the app
http://localhost:8000
```

---

# DEMO ACCOUNTS

Password for all: `demo1234`

| Role | Email |
|------|-------|
| Student | aisha@student.edu |
| Student | omar@student.edu |
| Company | hr@northstar.com |
| Company | hr@signal.com |
| University Admin | admin@univ.edu |

---

# KEY FILE LOCATIONS

```
backend/
  app/
    main.py          — FastAPI app + all routes
    database.py      — SQLite schema
    models.py        — CRUD operations
    lessons.py       — Lesson engine (Phase 4)
    practice.py      — Practice evaluator
    resources.py     — Curated learning resources
    genai.py         — GenAI integration + fallback
    path_builder.py  — Personalized path builder
    diagnostics.py   — Diagnostic engine
    copilot.py       — AI tutor
    jobs.py          — Job matching
    career_roadmap.py — Career roadmap
    tts.py           — ElevenLabs TTS
  tests/             — 38+ test files

frontend/
  src/
    pages/
      LearningPage.tsx    — Main learning UI
      AssessmentsPage.tsx — Assessment UI
      DashboardPage.tsx   — Dashboard
    components/
      learning.tsx        — Learning components
      CopilotPanel.tsx    — AI tutor panel
    lib/
      api.ts              — API functions
      types.ts            — TypeScript types
      topicLabels.ts      — Human-readable labels
    index.css             — All styles

AGENTS.md           — Full spec + delivery log (416 lines)
```

---

# GIT STATUS (at time of handoff)

**Branch:** master
**Modified files:** 33 files tracked as modified
**Untracked files:** 25+ new test files and components
**Recent commits:**
- `77858c5` fix: MockInterviewPanel TTS autoplay retry on user gesture
- `477f15c` feat: AI tutors with ElevenLabs voices + variable-step roadmap

**Do NOT commit, push, or modify git history.**
Just inspect and work on top of the current state.

---

# ADDENDUM — Learning Content Quality & Job-Readiness Refinement

This is an ADDITION to the existing handoff. It does not change architecture,
does not reopen Phase 1–4, and does not ask for new features. It only
constrains WHAT the AI generates inside `Learn`, `Example`, and
`Recommended Resources` so the content is actually correct, actually
useful, and actually makes a Student job-ready — not just "a lesson
that technically renders."

Do NOT restructure the pipeline. Do NOT add new phases. Only change the
prompts/generation logic that produce Learn/Example content and the
lesson-quality checks around them.

---

## PROBLEM TO FIX

The pipeline (Diagnostic → Path → Learn → Practice → Remediation → Mini
Check → Assessment) is architecturally complete and tested. But nothing
in the current implementation verifies that the generated `Learn` content
is:

- factually correct
- current / not outdated practice
- actually targeted at the Student's specific weak competency (not generic)
- relevant to the Student's target role
- pitched at the right depth (not a Wikipedia summary, not a grad-school
  paper)
- something a hiring manager would recognize as real preparation

Right now content generation and content correctness are being treated as
the same problem. They are not. Fix correctness and job-relevance
explicitly.

---

## 1. GROUNDING & ACCURACY RULES

Apply this the same way Resources already trusts curated URLs, not free LLM output.

- The AI must not invent APIs, commands, flags, library behavior, or
  version-specific syntax. If it is not confident, it must say so or omit
  it — never fabricate a plausible-looking wrong answer.
- Where a competency has a canonical/official source (official docs,
  language spec, framework guide), the Learn content should be generated
  WITH that source as grounding context, not from unguided generation.
  Reuse the same "trusted source" infrastructure that Phase 4 Resources
  already built — do not build a second trust system.
- Version-sensitive content (e.g. Docker Compose syntax, Pandas API,
  PyTorch API) must state or infer the version it's teaching, since wrong
  version syntax is a common failure mode for LLM-generated tutorials.
- Any code shown in Learn/Example must be runnable/valid, not just
  visually plausible. If there's no execution sandbox (there isn't, by
  design), this means static correctness review is mandatory before the
  content is trusted, not just formatting fixes.
- Add a lightweight self-check pass: after generating Learn content, the
  agent should validate its own output against the grounding source
  (or a checklist) before serving it, and log/flag content it isn't
  confident about instead of silently shipping it.

---

## 2. JOB-READINESS DEFINITION

Make this explicit — right now nothing defines it.

A topic's Learn content is "job ready" only if it teaches the Student
what they'd actually be expected to do/know in a junior role for their
target role signal — not textbook theory in isolation.

Concretely, each Learn section should connect the concept to:
- why this shows up in real work for the target role (one or two
  sentences, not a marketing paragraph)
- what a working engineer/analyst actually does with this concept
  day-to-day
- a common mistake or misconception beginners have (this is what
  interviewers/senior engineers actually probe for)

This is NOT asking for more content volume. It's asking for the existing
content to be anchored to the target role signal that Diagnostic and
Resource ranking already use — reuse that signal, don't invent a new one.

---

## 3. PERSONALIZATION DEPTH

Weak vs developing must actually look different.

Right now "Weak" and "Developing" topics likely get the same Learn
content shape. They shouldn't:

- **Weak competency** → start from fundamentals, more scaffolding, more
  worked examples, explicitly address the likely misconception.
- **Developing competency** → skip re-explaining basics, focus on the
  specific gap, move faster to Practice.

The Diagnostic already classifies this — Learn generation should
actually branch on it, not just gate topic visibility.

---

## 4. LESSON CONTENT STRUCTURE

Concrete shape to enforce. For each topic's Learn section, require this
shape (adjust wording, not structure):

1. **What & why** — the concept, and why it matters for the target role
2. **Core mechanics** — the actual how (commands/code/steps), grounded,
   version-aware
3. **Common mistake** — the beginner trap, stated explicitly
4. **Worked example** — tied 1:1 to the Practice task type coming next,
   not a disconnected toy example
5. **Recommended Resources** — unchanged, stays inside Learn as already
   verified

The Example section should not introduce a new scenario disconnected
from Learn — it should be the same scenario applied, so Practice doesn't
feel like a third unrelated task.

---

## 5. INTUITIVE EXPERIENCE REQUIREMENTS

This is UX, not content, but it's part of the same "makes it feel real"
problem:

- The Student should always be able to answer "why am I doing this
  step right now" — surface the current topic's weak/developing reason
  briefly (e.g. "Diagnostic showed this as Weak") so the Personalized
  Path doesn't feel arbitrary.
- Progress language should stay consistent across Learn → Practice →
  Mini Check → Assessment (reuse existing terms, don't introduce new
  status words).
- Keep Recommended Resources visually secondary as already decided —
  don't let content-quality fixes turn this into a wall of links.
- Loading/evaluating states (already speced for Practice) should apply
  the same honest, non-fake pattern to any new content-generation wait
  time this introduces.

---

## 6. SELF-EVALUATION CHECKLIST

Ask the agent to run this before calling Learn content "done" for a topic.

For each generated Learn section, the agent should be able to answer yes to:

- [ ] Is every technical claim grounded in a trusted/official source or
      flagged as unverified?
- [ ] Is the syntax/version correct and current?
- [ ] Does it explicitly connect to the target role?
- [ ] Does it match the Weak/Developing depth branching?
- [ ] Does the worked example feed directly into the Practice task?
- [ ] Would a hiring manager recognize this as real preparation, not
      generic filler?

If any answer is "no," that's the thing to fix — not a rewrite of the
pipeline.

---

## NON-GOALS

Keep scope tight, matching existing project discipline.

Do NOT:
- Add a new content-generation phase or pipeline stage
- Add execution/sandboxing to verify code correctness at runtime
- Rebuild Resource infrastructure — reuse it for Learn grounding
- Change Diagnostic thresholds or scoring
- Touch Verified Skill / Final Assessment logic
- Add new AI agents/services — extend the existing Learn generation call

---

## WHAT TO REPORT BACK

For 2–3 topics across different skills (pick ones already browser-verified
in the original handoff, e.g. Pandas, Docker), report:

### Before/After Comparison
- What the Learn content said before this brief
- What changed after applying grounding + job-readiness + depth branching

### Grounding Check
- Which claims are now source-grounded vs still generated freely

### Self-Evaluation Results
- Checklist results (section 6) for each sample topic

### Remaining Gaps
- Any competency where a trusted grounding source doesn't exist yet
