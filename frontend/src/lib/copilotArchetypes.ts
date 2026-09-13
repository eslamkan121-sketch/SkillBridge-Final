// ------------------------------------------------------------------
// SkillBridge mentors — the SINGLE source of truth in the React SPA.
//
// The mentor system is ONE: the four real mentors (Nova / Axel / Sage / Vex)
// are both the onboarding/recommendation outcomes AND the chat avatars. The
// old three archetypes (Navigator / Strategist / Confidant) no longer exist
// here and never surface in onboarding or recommendation UI.
//
// Both the first-run onboarding flow (CopilotOnboarding.tsx) and the settings
// "Change your copilot" picker (CopilotSettingsModal.tsx) read ONE structure
// from here: the exact four mentor keys, their display metadata, the four
// questions (each with four options that VOTE for a mentor key), the pure
// tally mirror of the backend's `copilot.score_archetype`, and the
// deterministic explanation builder for the recommendation result.
//
// The backend config payload (GET/PUT /api/students/{id}/copilot) remains the
// AUTHORITY for a student's stored snapshot; this module never invents state —
// everything here is the presentation/scoring mirror the UI needs.
//
// This file must stay in sync with backend/app/copilot.py (COPILOT_KEYS,
// COPILOT_PRESETS, ONBOARDING_QUESTIONS, score_archetype) — a runtime
// source-contract checker (check-copilot-onboarding-phaseP.mjs) enforces it.
// ------------------------------------------------------------------

export const COPILOT_ARCHETYPE_KEYS = ['nova', 'axel', 'sage', 'vex'] as const
export type CopilotArchetypeKey = (typeof COPILOT_ARCHETYPE_KEYS)[number]

export const DEFAULT_COPILOT_ARCHETYPE: CopilotArchetypeKey = 'nova'

export interface CopilotArchetype {
  key: CopilotArchetypeKey
  name: string
  personality: string
  /** 2–3 traits shown in the "Choose my mentor" cards / result screen. */
  shortTraits: string[]
  /** Starting-fit bullets from the owner-approved mentor definitions. */
  bestFor: string[]
  desc: string
  voice: string
  /** Existing tutor avatar image. */
  avatar: string
}

// Display metadata — mirrors the four real mentors (backend COPILOT_PRESETS
// and frontend tutorProfiles.ts identity). Four mentors, never more.
export const COPILOT_ARCHETYPES: Record<CopilotArchetypeKey, CopilotArchetype> = {
  nova: {
    key: 'nova',
    name: 'Nova',
    personality: 'Warm • Patient • Clear',
    shortTraits: ['Warm', 'Patient', 'Clear'],
    bestFor: ['Step-by-step explanations', 'Supportive feedback', 'Slower, clear teaching'],
    desc: 'Teaches step by step with warm, patient feedback and clear explanations.',
    voice: 'Nova',
    avatar: '/assets/tutors/nova.png',
  },
  axel: {
    key: 'axel',
    name: 'Axel',
    personality: 'Energetic • Practical • Fun',
    shortTraits: ['Energetic', 'Practical', 'Fun'],
    bestFor: ['Learning by doing', 'Exercises and challenges', 'Practical examples'],
    desc: 'Gets you learning by doing — exercises, challenges, and hands-on examples.',
    voice: 'Axel',
    avatar: '/assets/tutors/axel.png',
  },
  sage: {
    key: 'sage',
    name: 'Sage',
    personality: 'Calm • Analytical • Thoughtful',
    shortTraits: ['Calm', 'Analytical', 'Thoughtful'],
    bestFor: ['Understanding why things work', 'Reasoning and discussion', 'Bigger-picture thinking'],
    desc: 'Helps you understand why things work through calm, thoughtful discussion.',
    voice: 'Sage',
    avatar: '/assets/tutors/sage.png',
  },
  vex: {
    key: 'vex',
    name: 'Vex',
    personality: 'Sharp • Precise • Professional',
    shortTraits: ['Sharp', 'Precise', 'Professional'],
    bestFor: ['Being tested', 'Direct feedback', 'Interview-style preparation'],
    desc: 'Tests you with sharp, precise feedback and interview-style preparation.',
    voice: 'Vex',
    avatar: '/assets/tutors/vex.png',
  },
}

export interface CopilotQuestionOption {
  label: string
  /** The mentor key this option votes for. */
  vote: CopilotArchetypeKey
  /** Short phrase used by the deterministic recommendation reason. */
  phrase: string
}

export interface CopilotQuestion {
  question: string
  options: CopilotQuestionOption[]
}

// The exact four quiz questions, each with one option per mentor. Select an
// option and it places that mentor's vote in the answer set. Mirror of
// copilot.ONBOARDING_QUESTIONS (owner-approved copy) — keep in sync.
export const COPILOT_QUESTIONS: CopilotQuestion[] = [
  {
    question: 'When you\u2019re learning something difficult, what helps you most?',
    options: [
      { label: 'Explain it clearly, step by step', vote: 'nova', phrase: 'clear step-by-step explanations' },
      { label: 'Let me try something practical', vote: 'axel', phrase: 'hands-on practice' },
      { label: 'Help me understand why it works', vote: 'sage', phrase: 'understanding the why' },
      { label: 'Test me and show me what I\u2019m missing', vote: 'vex', phrase: 'being tested on my gaps' },
    ],
  },
  {
    question: 'When you make a mistake, how should your mentor respond?',
    options: [
      { label: 'Patiently explain it again', vote: 'nova', phrase: 'patient feedback' },
      { label: 'Tell me directly and let me retry', vote: 'axel', phrase: 'direct feedback and a retry' },
      { label: 'Discuss my thinking with me', vote: 'sage', phrase: 'discussing my thinking' },
      { label: 'Challenge me with another question', vote: 'vex', phrase: 'being challenged to go deeper' },
    ],
  },
  {
    question: 'What kind of mentor personality keeps you engaged?',
    options: [
      { label: 'Friendly and supportive', vote: 'nova', phrase: 'a friendly, supportive style' },
      { label: 'Energetic and fun', vote: 'axel', phrase: 'an energetic, fun style' },
      { label: 'Calm and thoughtful', vote: 'sage', phrase: 'a calm, thoughtful style' },
      { label: 'Serious and challenging', vote: 'vex', phrase: 'a serious, challenging style' },
    ],
  },
  {
    question: 'What do you expect to use SkillBridge for most?',
    options: [
      { label: 'Learning new things', vote: 'nova', phrase: 'learning new things' },
      { label: 'Practicing and building', vote: 'axel', phrase: 'practicing and building' },
      { label: 'Understanding concepts and decisions', vote: 'sage', phrase: 'understanding concepts and decisions' },
      { label: 'Testing myself and preparing for interviews', vote: 'vex', phrase: 'testing myself for interviews' },
    ],
  },
]

export function isArchetypeKey(value: unknown): value is CopilotArchetypeKey {
  return typeof value === 'string' && (COPILOT_ARCHETYPE_KEYS as readonly string[]).includes(value)
}

/** Backend mirror: validate a 4-answer set of voted mentor keys. */
export function validAnswers(answers: unknown): CopilotArchetypeKey[] | null {
  if (!Array.isArray(answers) || answers.length !== COPILOT_QUESTIONS.length) return null
  const out: CopilotArchetypeKey[] = []
  for (const entry of answers) {
    if (!isArchetypeKey(entry)) return null
    out.push(entry)
  }
  return out
}

/**
 * Pure tally of a 4-answer set — the SPA's mirror of the backend's recompute,
 * used only for the instant result preview. The backend POST is ALWAYS the
 * authority for the stored assignment. Ties resolve deterministically: the
 * Question 4 answer, then the Question 1 answer, then DEFAULT_COPILOT_ARCHETYPE
 * (Nova). Degenerate input never fabricates a result.
 */
export function tallyAnswers(answers: unknown): CopilotArchetypeKey {
  const valid = validAnswers(answers)
  if (!valid) return DEFAULT_COPILOT_ARCHETYPE
  const counts: Record<CopilotArchetypeKey, number> = { nova: 0, axel: 0, sage: 0, vex: 0 }
  for (const key of valid) counts[key] += 1
  const best = Math.max(...COPILOT_ARCHETYPE_KEYS.map((k) => counts[k]))
  const winners = COPILOT_ARCHETYPE_KEYS.filter((k) => counts[k] === best)
  if (winners.length === 1) return winners[0]
  // Tie-break 1: Question 4 answer.
  if (winners.includes(valid[3])) return valid[3]
  // Tie-break 2: Question 1 answer.
  if (winners.includes(valid[0])) return valid[0]
  // Tie-break 3: deterministic default.
  return DEFAULT_COPILOT_ARCHETYPE
}

/**
 * Deterministic recommendation reason built from the selected answers — NOT an
 * LLM. For every question whose chosen option voted for the winner, its short
 * phrase is collected and joined into a "You prefer …" sentence, so the
 * explanation always reflects the student's actual selections.
 */
export function buildRecommendationReason(answers: unknown, winner?: CopilotArchetypeKey): string {
  const valid = validAnswers(answers)
  if (!valid) return 'You prefer a mentor who matches how you like to learn.'
  const target = winner ?? tallyAnswers(valid)
  const phrases: string[] = []
  COPILOT_QUESTIONS.forEach((q, i) => {
    const option = q.options.find((o) => o.vote === valid[i])
    if (option && option.vote === target) phrases.push(option.phrase)
  })
  if (phrases.length === 0) return `You prefer a mentor like ${target}.`
  const joined = phrases.length > 1
    ? `${phrases.slice(0, -1).join(', ')}, and ${phrases[phrases.length - 1]}`
    : phrases[0]
  return `You prefer ${joined}.`
}

/**
 * Answer-set substitution for encoded overrides: make the submitted answer set
 * decisively vote for the desired mentor, so the server's recompute yields
 * exactly that key. Honest by construction — the server never trusts an
 * unverified `choice` key for correctness.
 */
export function forcedAnswers(key: CopilotArchetypeKey): CopilotArchetypeKey[] {
  const safe = isArchetypeKey(key) ? key : DEFAULT_COPILOT_ARCHETYPE
  return COPILOT_QUESTIONS.map(() => safe)
}