// Explicit state machine for the Mock Interview running inside the Global
// Copilot. Interview state is never inferred from chat text — it moves
// through explicit phases: idle -> starting -> active -> completed.

export type InterviewPhase = 'idle' | 'starting' | 'active' | 'completed'

export interface InterviewState {
  phase: InterviewPhase
  /** The turn the student is currently answering (starts at 1). */
  turn: number
  /** Skill the interview is focused on, when one is in scope. */
  skillId: number | null
  /** Language pinned for the whole interview session (stable across turns). */
  language: 'en' | 'ar'
}

export const IDLE_INTERVIEW: InterviewState = { phase: 'idle', turn: 1, skillId: null, language: 'en' }

export type InterviewAction =
  | { type: 'START'; skillId: number | null; language: 'en' | 'ar' }
  | { type: 'READY'; turn: number }
  | { type: 'ANSWERED'; nextTurn: number }
  | { type: 'END' }
  | { type: 'RESET' }

export function interviewReducer(
  state: InterviewState = IDLE_INTERVIEW,
  action: InterviewAction,
): InterviewState {
  switch (action.type) {
    case 'START':
      return { phase: 'starting', turn: 1, skillId: action.skillId, language: action.language }
    case 'READY':
      // First question received; the student now answers, so the next turn is
      // the one the engine returned (engine replies with the next turn number).
      return state.phase === 'starting'
        ? { ...state, phase: 'active', turn: action.turn }
        : state
    case 'ANSWERED':
      // A student answer produced feedback + a follow-up question.
      return state.phase === 'idle' ? state : { ...state, turn: action.nextTurn }
    case 'END':
      return state.phase === 'idle' ? state : { ...state, phase: 'completed' }
    case 'RESET':
      return IDLE_INTERVIEW
    default:
      return state
  }
}