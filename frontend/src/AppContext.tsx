import React, { createContext, useCallback, useContext, useEffect, useReducer, useState } from 'react'
import { api, getToken, setToken } from './lib/api'
import type { CopilotContext, Session, TutorLanguage, TutorMode } from './lib/types'
import { TUTOR_DEFAULT_MODES, isTutorMode } from './components/learning'
import type { TutorId } from './components/learning'
import { isTutorLanguage } from './lib/tutorI18n'
import { IDLE_INTERVIEW, interviewReducer } from './lib/interviewSession'
import type { InterviewState } from './lib/interviewSession'

interface AppContextType {
  session: Session | null
  me: Session | null
  loading: boolean
  login: (email: string, password: string) => Promise<Session>
  signup: (email: string, password: string, display_name: string, role: string, university?: string, country?: string, industry?: string, location?: string, education_level?: string) => Promise<Session>
  logout: () => Promise<void>
  refreshMe: () => Promise<void>
  refreshStudent: () => void
  authBanner: boolean
  clearAuthBanner: () => void
  copilot: CopilotContext
  applyCopilot: (patch: Partial<CopilotContext>) => void
  tutorId: TutorId
  setTutorId: (id: TutorId) => void
  mode: TutorMode
  setMode: (m: TutorMode) => void
  language: TutorLanguage
  setLanguage: (l: TutorLanguage) => void
  assessmentActive: boolean
  setAssessmentActive: (active: boolean) => void
  interview: InterviewState
  startInterview: (skillId?: number | null) => Promise<string | null>
  sendInterviewAnswer: (answer: string) => Promise<string | null>
  endInterview: () => void
  resetInterview: () => void
}

const AppContext = createContext<AppContextType>(null as any)

const DEFAULT_COPILOT: CopilotContext = {
  page: 'dashboard',
  skillId: null,
  competency: null,
  jobTitle: null,
  jobUrl: null,
}

function isTutorId(value: string): value is TutorId {
  return value === 'nova' || value === 'axel' || value === 'sage' || value === 'vex'
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const [authBanner, setAuthBanner] = useState(false)
  const [copilot, setCopilot] = useState<CopilotContext>(DEFAULT_COPILOT)
  const [tutorId, setTutorIdState] = useState<TutorId>('nova')
  const [mode, setModeState] = useState<TutorMode>('chat')
  const [language, setLanguageState] = useState<TutorLanguage>('auto')
  const [assessmentActive, setAssessmentActiveState] = useState(false)
  const [interview, dispatchInterview] = useReducer(interviewReducer, IDLE_INTERVIEW)

  const isStudent = session?.entity_type === 'student' && !!session?.student?.id

  useEffect(() => {
    if (!isStudent) {
      setTutorIdState('nova')
      setModeState('chat')
      setLanguageState('auto')
      setAssessmentActiveState(false)
      dispatchInterview({ type: 'RESET' })
      return
    }
    api.tutorPreference(session!.student!.id)
      .then((r) => {
        const resolvedTutor = r.tutor_id && isTutorId(r.tutor_id) ? r.tutor_id : 'nova'
        setTutorIdState(resolvedTutor)
        setModeState(r.mode && isTutorMode(r.mode) ? r.mode : TUTOR_DEFAULT_MODES[resolvedTutor])
        setLanguageState(r.language && isTutorLanguage(r.language) ? r.language : 'auto')
      })
      .catch((e) => { console.error('[copilot] tutor preference load failed:', e) })
  }, [isStudent, session?.student?.id])

  const clearAuthBanner = useCallback(() => setAuthBanner(false), [])

  const refreshMe = useCallback(async () => {
    if (getToken()) {
      const data = await api.me()
      setSession((prev) => ({ ...(prev || {}), ...data }))
    }
  }, [])

  useEffect(() => {
    if (getToken()) {
      api.me()
        .then((data) => setSession((prev) => ({ ...(prev || {}), ...data })))
        .catch((e) => { console.error('[app] session fetch failed:', e); setToken(null) })
        .finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
  }, [])

  const login = async (email: string, password: string) => {
    const s = await api.login(email, password)
    setSession(s)
    setAuthBanner(true)
    return s
  }

  const signup = async (email: string, password: string, display_name: string, role: string, university?: string, country?: string, industry?: string, location?: string, education_level?: string) => {
    const s = await api.signup(email, password, display_name, role, university, country, industry, location, education_level)
    const me = await api.me()
    setSession({ ...s, ...me })
    setAuthBanner(true)
    return { ...s, ...me }
  }

  const logout = async () => {
    try { await api.logout() } catch { /* best effort */ }
    setToken(null)
    setSession(null)
  }

  const refreshStudent = useCallback(() => { refreshMe() }, [refreshMe])

  const applyCopilot = useCallback((patch: Partial<CopilotContext>) => {
    setCopilot((prev) => ({ ...prev, ...patch }))
  }, [])

  const setTutorId = useCallback((id: TutorId) => {
    setTutorIdState(id)
    const natural = TUTOR_DEFAULT_MODES[id]
    setModeState(natural)
    // A tutor change ends any ended/parked interview session: interview state
    // must never follow the student into another tutor's conversation. (While
    // an interview is active/starting the Copilot pins the interviewer tutor,
    // so this only ever fires after the interview has ended.)
    dispatchInterview({ type: 'RESET' })
    if (!isStudent) return
    const sid = session?.student?.id
    if (sid) {
      // 'interview' is a live session mode, never a standing preference: a
      // tutor-select must not persist it (that used to turn every fresh Vex
      // chat into an interview). Persist the persona with a chat-capable mode.
      api.setTutorPreference(sid, { tutor_id: id, mode: natural === 'interview' ? 'chat' : natural })
        .catch((e) => { console.error('[copilot] tutor preference save failed:', e) })
    }
  }, [isStudent, session?.student?.id])

  const setMode = useCallback((m: TutorMode) => {
    setModeState(m)
    if (!isStudent) return
    // 'interview' is a live session mode (the Mock Interview runs on the
    // dedicated /interview session), never a standing preference: persisting it
    // would make every later chat an interview after a refresh. The stored
    // preference keeps the student's regular working mode instead.
    const sid = session?.student?.id
    if (sid && m !== 'interview') {
      api.setTutorPreference(sid, { mode: m })
        .catch((e) => { console.error('[copilot] tutor mode save failed:', e) })
    }
  }, [isStudent, session?.student?.id])

  const setLanguage = useCallback((l: TutorLanguage) => {
    setLanguageState(l)
    if (!isStudent) return
    const sid = session?.student?.id
    if (sid) {
      api.setTutorPreference(sid, { language: l })
        .catch((e) => { console.error('[copilot] tutor language save failed:', e) })
    }
  }, [isStudent, session?.student?.id])

  const startInterview = useCallback(async (skillId: number | null = null) => {
    if (!isStudent || assessmentActive) return null
    const sid = session!.student!.id
    // Resolve the interview language ONCE at start so it stays stable for the
    // whole session (Arabic stays Arabic even if a later answer is English).
    const pinned: 'en' | 'ar' = language === 'ar' ? 'ar' : language === 'en' ? 'en' : 'en'
    dispatchInterview({ type: 'START', skillId, language: pinned })
    try {
      const res = await api.interviewSend(sid, '', 1, skillId || null, tutorId, pinned)
      dispatchInterview({ type: 'READY', turn: res.turn || 2 })
      return res.reply || ''
    } catch (e) {
      dispatchInterview({ type: 'RESET' })
      throw e
    }
  }, [isStudent, assessmentActive, session?.student?.id, tutorId, language])

  const sendInterviewAnswer = useCallback(async (answer: string) => {
    const sid = session?.student?.id
    if (!sid || !isStudent || interview.phase !== 'active') return null
    try {
      const res = await api.interviewSend(sid, answer, interview.turn, interview.skillId, tutorId, interview.language)
      dispatchInterview({ type: 'ANSWERED', nextTurn: res.turn || interview.turn + 1 })
      return res.reply || ''
    } catch (e) {
      throw e
    }
  }, [isStudent, session?.student?.id, interview.phase, interview.turn, interview.skillId, interview.language, tutorId])

  const endInterview = useCallback(() => {
    dispatchInterview({ type: 'END' })
  }, [])

  const resetInterview = useCallback(() => {
    dispatchInterview({ type: 'RESET' })
  }, [])

  const setAssessmentActive = useCallback((active: boolean) => {
    setAssessmentActiveState(active)
  }, [])

  return (
    <AppContext.Provider value={{ session, me: session, loading, login, signup, logout, refreshMe, refreshStudent, authBanner, clearAuthBanner, copilot, applyCopilot, tutorId, setTutorId, mode, setMode, language, setLanguage, assessmentActive, setAssessmentActive, interview, startInterview, sendInterviewAnswer, endInterview, resetInterview }}>
      {children}
    </AppContext.Provider>
  )
}

export const useApp = () => useContext(AppContext)