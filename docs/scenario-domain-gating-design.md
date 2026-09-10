# Practice Scenarios — Domain-Gating Design v2

Status: **APPROVED and IMPLEMENTED. 704 backend tests pass / 2 skipped; tsc + vite build clean.**

Supersedes v1. Two sections changed on user direction: (a) the empty-profile
behavior (§3.1/§3.3/§5), and (b) the eligibility overlap is no longer a plain
boolean match (§3.1) — reuse of `recommendations.py` specificity weighting,
with the reason for *not* using a plain overlap, is now stated in the doc.

## 1. Problem, restated

`list_scenarios(student)` (backend/app/scenarios.py:705) returns **all 3 scenarios** in `SCENARIOS`
regardless of the student's profile. `_skill_overlap`/`_gap_names` (scenarios.py:683, :695) only
*re-rank* the "Recommended for You" order — they never *exclude* anything. `CATEGORIES`
(scenarios.py:31-37) is a fixed static tuple of cyber-only labels, so the category filter chips are
hardcoded cyber regardless of role. There is **zero non-cyber scenario content** anywhere (confirmed
by full-repo search). So a Dentist target role gets cyber scenarios + cyber category chips, wrongly
implied to be relevant.

This is the same class of bug the CV-extraction/matching engines already fixed: an engine built and
validated against one domain with no honest domain-agnostic path. The fix must mirror those fixes:
a **generic structural gate** that reuses existing matching, plus an **honest empty state** when the
student's domain has no content — never fabricated relevance.

## 2. Design goals

1. **Generic gate, not a dentist patch.** Scenario selection keys off the student's real target
   role + skill vocabulary using the same matching machinery `recommend()`/`role_intent` run, not a
   second hardcoded role→scenario map.
2. **Cybersecurity is data, not structure.** The generic schema stays; the fact that current
   scenarios are cyber is *content* (the data set), and the taxonomy must be **derived from the
   scenarios a student can actually play** rather than a fixed cyber tuple.
3. **Honest empty state everywhere there is no content** — for a non-cyber target role *and* for a
   student with no profile yet. A pre-profile student is *expected* to have no matches; content
   must never be presented as personalized when it isn't.
4. **No framework regression:** cyber-profile students still see all 3 scenarios; practice still
   never verifies; the 698-pass suite stays green (fixture change described in §6 — required, not a
   regression).

## 3. The fix — pieces

### 3.1 Scenario eligibility = specificity-weighted match, NOT a plain boolean

A scenario is *eligible* for a student if **any** of the following holds (OR). There is **no**
"empty profile ⇒ show the pool" branch — that behavior is deleted (§3.3).

**Path A — target-role intent (strongest signal, zero skill looseness):**
`role_intent.classify_title(student.target_role.title, scenario.role_title) != "UNRELATED"`
(EXACT / CLOSE / FAMILY). This is the *same classifier the live-jobs feed already obeys*
(jobs.py uses it to gate provider results), so behavior is consistent across surfaces: a student
whose target role is "Cybersecurity Analyst" sees all 3 scenarios; a "Dentist (General Practice)"
target classifies UNRELATED against all of them. No skill names are consulted at all on this path —
it reuses the existing curated family/token machinery instead of inventing a scenario-specific one.

**Path B — specificity-weighted skill evidence (reuses `recommendations.py`):**
Compute the exact same `df` / `specificity` indices `recommend()` builds over the local role pool
(`models.list_roles()` + `models.list_catalog_roles()`), matched via the same `_key(name)` →
`skill_registry.normalise_name` normalization — the app's single source of truth for skill identity:

```
corpus = len(local_candidates)          # local roles only (deterministic, no network)
df[code]  = # candidates containing a skill that normalizes to `code`
specificity(code) = math.log1p(corpus / (1.0 + df.get(code, 0)))
```

For each scenario `skill` matched in the student's trusted profile (self-reported + verified),
weight = `specificity(_key(skill))`. A skill **absent from the role pool is treated as a small
fixed constant** `ABSENT_SKILL_WEIGHT` — *not* as maximum specificity. A scenario is eligible on
this path iff `max(weight over matched skills) >= SPECIFICITY_FLOOR`.

(Implementation note: to avoid re-implementing the df/specificity loop, expose a tiny read-only
helper in `recommendations.py` — e.g. `role_pool_specificity()` returning a `code -> weight`
callable — and have the scenario gate consume it. `recommend()` itself is unchanged.)

**Why reuse specificity weighting instead of a plain `_key` overlap (the user-flagged issue):**
a pure set-overlap lets a *generic, cross-domain* skill qualify a scenario on its own. The scenario
catalog deliberately lists process words — "Investigation", "Decision Making" — that legitimately
appear on a lawyer's, analyst's, or even a dentist's soft-skills section. `recommend.py`'s whole
design point is that such a skill must NOT be able to fake a domain match alone: rare, role-defining
skills (SIEM, Threat Detection) outweigh ubiquitous transferables (Communication, Excel) by
construction, with no hard-coded blacklist. Reusing that weighting is the only honest option.

**Crucial correctness caveat (why v1's design failed, and why the weighting must be read
carefully):** the scenario vocabulary is *entirely absent* from the local role pool —
"Investigation", "Decision Making", "Email Security", "Log Analysis", "Event Correlation" all have
`df = 0`. Under a naive `specificity()` read, `df=0 → log1p(corpus)` is the *maximum* weight, which
would give "Investigation" a *stronger* gate signal than "SIEM" — the exact inversion of the desired
behavior. Hence:

- the gate **never** derives domain evidence from a skill that cannot be grounded in the role pool:
  absent skills contribute only `ABSENT_SKILL_WEIGHT`, far below the floor, so a lawyer whose *only*
  overlap is "Investigation" + "Decision Making" is excluded (both absent → tiny weight);
- the floor is only cleared by a matched skill that is **genuinely rare in the pool** — i.e. a
  student who actually lists a recognizable security-domain skill ("SIEM", "Threat Detection",
  "Network Security", …) rather than a transferable.

This is *not* an additional soft-skill category filter, and we deliberately avoid one: the scenario
skills are process vocabulary a security analyst genuinely uses, and even the registry's
`category_for()` cannot classify "Email Security"/"Log Analysis" today (neither is in
`CANONICAL_CATEGORIES`/`DOMAIN_TERMS`), so a category-based guard would wrongly drop the phishing
scenario. Specificity over the pool — the same signal `recommend()` already trusts for every other
surface — is category-free and consistent. **Decision recorded: reuse `recommendations.py`
specificity/weighting (the user's first-listed option); the boolean-overlap-with-domain-category
variant is *not* chosen** because (a) it would misclassify unregistered-but-genuine security skills
as generic, and (b) it duplicates the weighting logic `recommend()` already owns.

`SPECIFICITY_FLOOR` / `ABSENT_SKILL_WEIGHT` are **derived, not fitted to fixtures**
(see the computed floor math in §5b): the fixed values must satisfy *both* directions —
SOC-vocabulary profiles pass, generic/transferable-only profiles fail — and they are locked by
fixture assertions (yara, generic-only, dentist). `DOMAIN_DF_CAP` anchors the floor to the
least-common genuinely-cyber skill the live pool actually contains; every transferable in the pool
(Communication df=13 → 1.05, Python df=15 → 0.97, SQL df=11 → 1.15, Excel df=6 → 1.55,
Critical Thinking df=5 → 1.67) sits strictly below it by construction.

**The gate keys and their normalization:** scenario `skills` are normalized with the same `_key`
used everywhere else; the student's trusted profile is built the same way
(`_student_skill_profile`-style, self-reported merged with verified). No new "domain" field, no
hardcoded role→scenario table, and **no dentist reference anywhere** in code.

### 3.2 Taxonomy derived from eligible scenarios

Replace the static `CATEGORIES` / `PHASES` in the **library payload only** with a set **derived from
the scenarios actually returned**:

- `categories`: the unique `{key, label, icon}` set from eligible scenarios (keeps the existing
  shape so the frontend type doesn't change). If a profile has no eligible scenarios, `categories`
  is `[]` (frontend shows empty state, not cyber chips).
- `PHASES` remains static per-scenario (they're player-phase labels within a scenario and stay
  generic — `Detection/Investigation/Analysis/...` are universal process words, **approved as
  static** per review). Only the *library* category facet is content-derived.

### 3.3 Honest empty state (backend + frontend), incl. no-profile students

**Backend** `list_scenarios` gains a field so the frontend can distinguish "no relevant content"
from "loading/error":

```
{
  "scenarios": [...],        # only eligible ones (may be [])
  "recommended": [...],
  "categories": [...],       # derived from eligible (may be [])
  "stats": {...},
  "target_role": str | None,
  "availability": "ok" | "none",
  "availability_reason": str | None,
  "note": "..."
}
```

- `availability: "ok"` when `len(scenarios) >= 1`, else `"none"`.
- `availability_reason` is role/profile-driven, never the falsehood "no scenarios exist":

  | Profile state | `availability_reason` |
  |---|---|
  | has `target_role`, no eligible scenarios (e.g. Dentist) | "No practice scenarios are available for `{target_role}` yet — check back as more roles are added." |
  | no `target_role` / no skills (fresh student) | "Add skills to your profile (upload a CV) and choose a target role to see practice scenarios matched to you." (nudge — **approved** per review) |

**Frontend** `ScenariosPage.tsx`:
- When `library.availability === 'none'`: render an explicit empty-state panel (post-hero, before
  stats/filters) using the reason above. Show the **CV/role nudge** when there is no target role; the
  role-specific copy when there is one. **No category chips, no stats block implying completion, and
  no scenario grid.** CTA to the Learning page / profile (upload CV).
- The hero subtitle must stop hardcoding "cybersecurity"/"analyst" fallbacks (ScenariosPage.tsx:142-143);
  use `library.target_role` when present, else a neutral "for your target role" phrasing.
- Keep the existing "No scenarios in this category yet." fallback for `ok`-availability + empty
  filtered list (a real edge when all categories are filtered out).

The "Recommended for You" badge (ScenarioCardView) only ever appears on eligible scenarios — since
ineligible ones are excluded, it can never badge content that wasn't matched.

### 3.4 Type changes (minimal)

- `frontend/src/lib/types.ts`: `ScenarioLibrary` gains optional `availability?: 'ok' | 'none'` and
  `availability_reason?: string | null`. No other type churn.

### 3.5 Start endpoint is gate-aware (no end-run)

`POST /api/students/{id}/scenarios/{scenario_id}/start` returns **403** (not 200) when the scenario
is ineligible for that student **and** the student has no prior in-progress/completed attempt for
it. Existing attempts stay resumable even if the profile later changes (game states are durable);
an in-progress attempt on a now-ineligible scenario is still playable and completable. This keeps
the library and the playing surface consistent and honest.

## 4. What this deliberately does NOT do (boundary)

- **Does not author non-cyber scenario content.** That's a content backlog, explicitly out of scope
  for the gating fix. Per prior decision: filter + empty state, no fabricated/generic scenarios.
- **Does not touch the scenario engine, scoring, or practice/verify boundary.** Those are correct
  and domain-agnostic already; they stay.
- **Does not hardcode "Dentist"** anywhere. The gate is role-intent + skill-specificity based;
  Dentist users fall out as an honest empty state because no scenario's role_title classifies near a
  dental target and no believable dental skill clears the specificity floor.
- **Does not present cyber scenarios to a student with no profile.** The old "no target + no skills
  ⇒ show all 3" fallback is **removed**. Per review: showing the cyber pool pre-CV would be
  "a narrower version of the same problem" — every onboarding user would land on cyber content
  presented as relevant. A fresh student sees the honest empty state with the CV/role nudge instead.
  (The library's `showAll` does not transfer: its catalog is domain-diverse, so "everything" is a
  real mix; the scenario pool is 100% cyber, so "everything" is cyber.)

## 5. Test matrix

Backend (`test_scenarios.py` — extend, don't rewrite):

| Case | Fixture | Expected |
|---|---|---|
| Existing play-through/hint/progress/verify suite | **switch to `yara@student.edu`** (seeded SOC student: target "Cybersecurity Analyst", skills SIEM/Cybersecurity/Network Security/Linux/Threat Detection/Incident Response) | All 3 scenarios eligible via Path A (EXACT) — `availability: "ok"`, `len == 3`. Engine/score tests unchanged. |
| Catalog gate-aware | yara | `scenarios` = the expected 3-set (not a hardcoded count from a non-cyber student). |
| Path A positive | yara | `role_intent.classify_title` EXACT on each scenario title, hence all 3 shown even before skill overlap is consulted. |
| Path B positive (skills, no target help) | student with `Threat Detection` (df=2 in pool) or `SIEM` skills and an unrelated target | Eligible via specificity floor; assert gateway opens. |
| Generic transferable-only profile (LAWYER — the mismatch the 4th review point calls out) | profile whose only overlap is "Investigation" + "Decision Making" (both absent from pool) | `scenarios == []`, `availability: "none"` — a generic soft-skill overlap must NOT open a cyber scenario. |
| Non-cyber target (Dentist) | target `Dentist (General Practice)` + dental skills | `scenarios == []`, `availability: "none"`, `availability_reason` mentions the role. |
| Empty profile (no skills, no target) | fresh student | `scenarios == []`, `availability: "none"`, reason is the CV/role nudge (NOT "show all"). |
| Start-gate | yara starts eligible scenario → 200; non-cyber student tries `start` on `suspicious-login-001` → **403** | No end-run around the library gate. |
| In-progress survives profile change | yara starts, then target pivoted to Dentist + skills cleared → brand-new `start` on another scenario → **403**, but the started attempt still resumes 200 | Durability preserved; only fresh attempts are gated. |
| Existing ownership/progress/decision/hint/practice-boundary tests | unchanged scenarios, fixture swapped to yara | Still green (engine untouched). |

### 5b. Computed floor math (show-your-work requirement #1 — real values)

Computed over the **live seeded pool via `recommendations.role_pool_specificity()`**
(corpus = 26 local roles = `models.list_roles()` + `models.list_catalog_roles()`), same code a
one-off diagnostic script used — nothing was hand-fit:

| Skill | df in pool | specificity = `log1p(26/(1+df))` | Clears floor? |
|---|---|---|---|
| SIEM | 1 | 2.6391 | yes |
| Threat Detection | 2 | 2.2687 | yes (equals floor) |
| Cybersecurity · Network Security · Incident Response | 2 | 2.2687 | (not scenario skills) |
| Critical Thinking | 5 | 1.6740 | no |
| Excel | 6 | 1.5506 | no |
| SQL | 11 | 1.1527 | no |
| Communication | 13 | 1.0498 | no |
| Python | 15 | 0.9651 | no |
| **Investigation · Decision Making · Email Security · Threat Analysis · Log Analysis · Event Correlation** | **0 (absent)** | **ABSENT_SKILL_WEIGHT = 0.0** | **no** |

- Pool stats: 96 pooled skills, min weight 0.9651, max 2.6391.
- `DOMAIN_DF_CAP = 2` — anchored to Threat Detection (df=2), the **least-common genuinely-cyber
  skill present in the pool**; a skill appearing in more than ~7.7% of the pool is a transferable,
  not a role-defining signal.
- `SPECIFICITY_FLOOR = log1p(corpus / (1 + DOMAIN_DF_CAP))` = `log1p(26/3)` = **2.2687** — computed
  from the pool, so it scales as roles are added/removed (see the corpus-relative caveat on
  `role_pool_specificity()`).
- `ABSENT_SKILL_WEIGHT = 0.0` — a df=0 skill has NO pool grounding, so it contributes no domain
  evidence; this is the guard against the naive-`log1p` inversion (§3.1).
- Since every matched scenario skill is either rare-in-pool (SIEM, Threat Detection) or
  absent-from-pool (the chapter process words), the `>= floor` test on the max is decisive and the
  transferable band (df≥5) can never qualify a scenario.

**Removed from v1 (fabricated):** the "Security Operations → matches Threat Detection via
token/TF-IDF" row. `recommendations.py` does *exact* normalized-key matching, not token fuzzy
matching — the row implied machinery that doesn't exist. The real synonym story is
`_key`/`normalise_name` full-phrase equivalence (e.g. "Network Security" ↔ "networking").

Frontend: `tsc`, `vite build`, and the existing source-contract checker patterns; extend the
`check-tutor-language`-style source-contract checker to require the hero subtitle no longer hardcodes
`cybersecurity`/`analyst`.

## 6. Impact on existing tests (fixture change is **required**, not cosmetic)

Under the gate, `aisha@student.edu` (Junior AI Engineer target; Python/SQL/ML/Docker/Git skills) is
a *negative* fixture — she will see **zero** scenarios (no security role intent, no security-pool
skill). Everything in `test_scenarios.py` that logs in as aisha to start/decide/hint scenarios
**must switch to `yara@student.edu`** (the seeded SOC student — see §5). This includes
`test_catalog_lists_scenarios_with_progress`. The `student_id` used in URL paths must be yara's own
id (routes are ownership-gated). No engine/scoring changes are needed; only the fixture + the gate.

**Pre-existing-fixture note (requirement #2):** `yara@student.edu` is a *pre-existing seeded
student* — `seed.py` STUDENTS line 34, `SELF_REPORTED` line 63 (SIEM/Cybersecurity/Network
Security/Linux/Threat Detection/Incident Response), catalog target "Cybersecurity Analyst" assigned
at seed time. She was **not** authored for this fix and the scenario test file states so explicitly
in its module docstring. No gate-authored fixture is used in the configurable tests.

`698 passed` is the baseline; the change keeps `0 failed` (count rose to **704** with the new
negative-gate and show-your-work tests).

## 7. Resolved decisions vs v1

| # | Question | Resolution |
|---|---|---|
| 1 | Empty-profile fallback ("no target + no skills ⇒ show all") | **Removed.** Honest empty state with CV/role nudge. Review: `showAll` doesn't transfer to a 100%-cyber pool. |
| 2 | `PHASES` static vs derived | **Static** (approved). Only library `categories` are derived. |
| 3 | Skill normalization | `recommendations._key` → `skill_registry.normalise_name`, single source of truth (approved). |
| 4 | `availability_reason` "add more skills" nudge | **Yes** (approved); applied as the no-profile reason + a role-aware variant when a target exists. |
| 4b | Overlap gate | **New.** Reuse `recommendations.py` specificity weighting (role-pool df/`log1p`), matched skills normalized by `_key`; absent-from-pool skills carry `ABSENT_SKILL_WEIGHT` (never max); floor only cleared by a genuinely rare pooled skill. Plain boolean overlap rejected (lawyer/dentist soft-skill false positives); boolean+category variant rejected (scenario security vocabulary is unregistered — see §3.1 rationale). |
| 5 | Floor constants source | **Derived, not fitted:** `DOMAIN_DF_CAP=2` anchors to the least-common cyber skill in the pool (Threat Detection, df=2); `SPECIFICITY_FLOOR = log1p(corpus/(1+DOMAIN_DF_CAP))` recomputed from the live pool; `ABSENT_SKILL_WEIGHT = 0`. Corpus-relative drift is documented in a code comment on `role_pool_specificity()` (requirement #3) and the computed values are in §5b. |

## 8. Implementation status

Approved design fully implemented:

- `backend/app/recommendations.py` — `role_pool_specificity()` exposes the `code -> weight` IDF map
  (`recommend()` unchanged), with the corpus-relative drift note in its docstring.
- `backend/app/scenarios.py` — `scenario_eligible()` (Path A via `role_intent.classify_title`; Path B
  via `_scenario_specificity` + `_specificity_floor`), `availability_reason()`, `has_attempt()`;
  `list_scenarios` now returns only eligible scenarios, derived `categories`, and
  `availability`/`availability_reason` fields.
- `backend/app/main.py` — `start` endpoint returns 403 for a fresh attempt on an ineligible scenario.
- `frontend/src/lib/types.ts` — `ScenarioLibrary` gains `availability: 'ok'|'none'` and
  `availability_reason: string`.
- `frontend/src/pages/ScenariosPage.tsx` — honest empty-state panel with CTA; hero subtitle no
  longer hardcodes "cybersecurity"/"analyst" fallbacks (ScenariosPage.tsx:142-143).
- `backend/tests/test_scenarios.py` — expanded from 10 to 16 tests (yara swap, Path-B show-work,
  generic-`Investigation` profile, dentist negative, empty-profile nudge, 403 start-gate,
  resume-after-pivot durability).

Verify: `backend/tests` **704 passed / 2 skipped**; `tsc --noEmit` clean; `vite build` clean.