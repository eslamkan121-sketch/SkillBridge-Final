// Canonical Tutor Identity Profiles (Phase 5.5 Step 3).
//
// This file is the ONE centralized source of tutor identity metadata for the
// frontend. Every UI surface (Copilot, Tutor Selector, Mock Interview room,
// About/Profile popover) reads from `TUTOR_PROFILES` here and from nothing
// else. The backend keeps its own *personality* system (genai.TUTOR_PERSONAS)
// which describes the same four identities by id — the two are aligned, never
// duplicated.
//
// `languages` lists the languages a tutor can coach in. English and Arabic are
// declared now because the Copilot can answer in English, Arabic, or Auto.

export type TutorId = 'nova' | 'axel' | 'sage' | 'vex'

export interface TutorProfile {
  /** Canonical id; one profile per id, ids never change. */
  id: TutorId
  name: string
  /** Display identity.
   * `origin` is character/license flavor only and must never be used to make
   * factual assumptions (job recommendations, location, assessment results
   * and learning content stay independent of it). */
  origin: string
  /** e.g. "Learn & Explain" — the tutor's working specialty. */
  specialty: string
  traits: string[]
  bestFor: string[]
  languages: string[]
  /** Legacy presentation metadata, also centralized here. */
  gender: 'Female' | 'Male'
  focus: 'Learn' | 'Practice' | 'Discuss' | 'Test'
  role: string
  personality: string
  purpose: string
  theme: 'purple' | 'cyan' | 'green' | 'orange'
  avatar: string
  voiceHint: { rate: number; pitch: number }
  voiceId: string
}

export const TUTOR_PROFILES: TutorProfile[] = [
  {
    id: 'nova',
    name: 'Nova',
    origin: 'London, United Kingdom',
    specialty: 'Learn & Explain',
    traits: ['Warm', 'Patient', 'Clear', 'Supportive'],
    bestFor: [
      'Explanations',
      'Beginner-friendly learning',
      'Simplifying difficult concepts',
      'Guided learning',
    ],
    languages: ['English', 'Arabic'],
    gender: 'Female',
    focus: 'Learn',
    role: 'Explainer Tutor',
    personality: 'Friendly, warm, calm, supportive, patient and encouraging.',
    purpose: 'Explains difficult topics simply and step by step.',
    theme: 'purple',
    avatar: '/assets/tutors/nova.png',
    voiceHint: { rate: 0.95, pitch: 1.1 },
    voiceId: 'Xb7hH8MSUJpSbSDYk0k2',
  },
  {
    id: 'axel',
    name: 'Axel',
    origin: 'California, United States',
    specialty: 'Practice & Build',
    traits: ['Energetic', 'Practical', 'Direct', 'Action-focused'],
    bestFor: [
      'Exercises',
      'Coding tasks',
      'Commands',
      'Practical challenges',
      'Mini projects',
    ],
    languages: ['English', 'Arabic'],
    gender: 'Male',
    focus: 'Practice',
    role: 'Practical Coach',
    personality: 'Energetic, confident, practical, motivating and hands-on.',
    purpose: 'Turns skills into exercises, labs, projects and real scenarios.',
    theme: 'cyan',
    avatar: '/assets/tutors/axel.png',
    voiceHint: { rate: 1.08, pitch: 0.85 },
    voiceId: 'TX3LPaxmHKxFdv7VOQHJ',
  },
  {
    id: 'sage',
    name: 'Sage',
    origin: 'Alexandria, Egypt',
    specialty: 'Discuss & Think',
    traits: ['Calm', 'Analytical', 'Thoughtful', 'Reflective'],
    bestFor: [
      'Reasoning',
      'Comparing approaches',
      'Deeper understanding',
      'Discussion',
      'Conceptual thinking',
    ],
    languages: ['English', 'Arabic'],
    gender: 'Female',
    focus: 'Discuss',
    role: 'Discussion Mentor',
    personality: 'Calm, intelligent, analytical, thoughtful, curious and patient.',
    purpose: 'Guides deeper understanding through discussion and critical thinking.',
    theme: 'green',
    avatar: '/assets/tutors/sage.png',
    voiceHint: { rate: 0.92, pitch: 1.08 },
    voiceId: 'XrExE9yKIg1WjnnlVkGX',
  },
  {
    id: 'vex',
    name: 'Vex',
    origin: 'Paris, France',
    specialty: 'Test & Interview',
    traits: ['Precise', 'Professional', 'Challenging', 'Sharp'],
    bestFor: [
      'Technical questions',
      'Testing knowledge',
      'Interview preparation',
      'Assessment-style practice',
    ],
    languages: ['English', 'Arabic'],
    gender: 'Male',
    focus: 'Test',
    role: 'Examiner',
    personality: 'Serious, precise, professional, disciplined, demanding but fair.',
    purpose: 'Supports quizzes, interview simulations and skill verification.',
    theme: 'orange',
    avatar: '/assets/tutors/vex.png',
    voiceHint: { rate: 0.9, pitch: 0.8 },
    voiceId: 'pNInz6obpgDQGcFmaJgB',
  },
]

export function tutorProfileById(id: string | null | undefined): TutorProfile | undefined {
  return TUTOR_PROFILES.find((t) => t.id === id)
}
