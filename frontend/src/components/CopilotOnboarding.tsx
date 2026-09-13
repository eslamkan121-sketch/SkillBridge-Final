import React from 'react'
import { api } from '../lib/api'
import { useApp } from '../AppContext'
import {
  COPILOT_ARCHETYPES,
  COPILOT_ARCHETYPE_KEYS,
  COPILOT_QUESTIONS,
  buildRecommendationReason,
  isArchetypeKey,
  tallyAnswers,
  type CopilotArchetypeKey,
} from '../lib/copilotArchetypes'

type View = 'hidden' | 'loading' | 'visible'
type Phase = 'welcome' | 'question' | 'result' | 'choose'

export interface CopilotOnboardingProps {
  studentId: number
  /** Logged-out-of-session dismissal only (nothing persisted); autoshow is
   *  suppressed so the app behaves normally until the student decides. */
  forceOpen?: boolean
  /** Called when the flow finishes (matched via quiz, chosen directly, or
   *  dismissed); lets the parent clear forceOpen and refresh dependent UI. */
  onDone?: () => void
}

/**
 * First-run mentor onboarding — "Find your SkillBridge mentor".
 *
 * Exactly four questions with four mentor outcomes (Nova / Axel / Sage / Vex),
 * plus a direct "Choose my mentor" path so the quiz is never required. The
 * recommendation is only a starting suggestion — users can switch mentors
 * anytime, and "See all mentors" lets them override the match.
 *
 * Honesty contract (enforced by a runtime checker):
 *   - No browser-side persistent storage. No provider/voice calls.
 *   - Questions/options/mentors/tally come ONLY from lib/copilotArchetypes.
 *   - The stored assignment is ALWAYS the server's recompute
 *     (api.submitCopilotOnboarding) for the quiz path; a direct choice goes
 *     through api.setCopilot (backend marks it manual).
 *   - Recommending Vex never activates Interview mode — persona and mode stay
 *     independent (the backend owns default modes).
 */
export default function CopilotOnboarding({ studentId, forceOpen, onDone }: CopilotOnboardingProps) {
  const [view, setView] = React.useState<View>('hidden')
  const [phase, setPhase] = React.useState<Phase>('welcome')
  const [qIndex, setQIndex] = React.useState(0)
  const [answers, setAnswers] = React.useState<CopilotArchetypeKey[]>([])
  const [banner, setBanner] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [quizCompleted, setQuizCompleted] = React.useState(false)
  const advanceTimer = React.useRef<number | undefined>(undefined)
  const { setTutorId } = useApp()

  const winner = React.useMemo(
    () => tallyAnswers(answers),
    [answers],
  )

  const load = React.useCallback(async () => {
    setView('loading')
    try {
      const s = await api.copilotOnboardingState(studentId)
      setView(forceOpen || s.state === 'not_started' ? 'visible' : 'hidden')
    } catch (e) {
      setView('hidden')
      setBanner(e instanceof Error ? e.message : 'Could not load your mentor setup right now.')
    }
  }, [studentId, forceOpen])

  React.useEffect(() => {
    load()
  }, [load])

  // A settings "Retake the quiz" opens the flow even when already answered.
  React.useEffect(() => {
    if (forceOpen) setView('visible')
  }, [forceOpen])

  React.useEffect(() => () => { if (advanceTimer.current) window.clearTimeout(advanceTimer.current) }, [])

  const close = () => {
    if (busy) return
    setView('hidden')
    setBanner(null)
    if (onDone) onDone()
  }

  const startQuiz = () => {
    setQIndex(0)
    setAnswers([])
    setQuizCompleted(false)
    setBanner(null)
    setPhase('question')
  }

  const chooseMentorOpen = () => {
    setBanner(null)
    setPhase('choose')
  }

  const pickOption = (index: number, vote: CopilotArchetypeKey) => {
    setAnswers((prev) => {
      const next = [...prev]
      next[index] = vote
      return next
    })
    // Small pause so the selected state is visible before advancing.
    if (advanceTimer.current) window.clearTimeout(advanceTimer.current)
    advanceTimer.current = window.setTimeout(() => {
      if (index < COPILOT_QUESTIONS.length - 1) setQIndex(index + 1)
      else {
        setQuizCompleted(true)
        setPhase('result')
      }
    }, 300)
  }

  const goBack = () => {
    if (phase !== 'question' || qIndex <= 0) return
    setQIndex(qIndex - 1)
  }

  const chooseMentor = async (key: CopilotArchetypeKey) => {
    if (busy) return
    setBusy(true)
    setBanner(null)
    try {
      // A direct choice — the backend persists it and marks the onboarding row
      // manual, so the quiz is never required and never re-asked.
      await api.setCopilot(studentId, key)
      // Make the chosen mentor the ACTIVE tutor so the chat header (which
      // shows only the current mentor) updates immediately.
      setTutorId(key)
      setView('hidden')
      if (onDone) onDone()
    } catch (e) {
      setBanner(e instanceof Error ? e.message : 'Could not save your mentor right now. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  const startWith = async () => {
    if (busy || !winner) return
    setBusy(true)
    setBanner(null)
    try {
      // The submitted answer set is the source of truth for the recompute.
      const res = await api.submitCopilotOnboarding(studentId, { answers })
      // Activate the mentor the server assigned (local tally stays a faithful
      // mirror — the server recompute is the authority, so trust its result).
      setTutorId(isArchetypeKey(res.assigned) ? res.assigned : winner)
      setView('hidden')
      if (onDone) onDone()
    } catch (e) {
      setBanner(e instanceof Error ? e.message : 'Could not save your mentor right now. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  if (view === 'hidden') return null
  if (view === 'loading') {
    return (
      <div className="cob-backdrop" role="dialog" aria-modal="true" aria-label="Find your SkillBridge mentor">
        <div className="cob-shell cob-loading" role="status">Loading your mentor setup…</div>
      </div>
    )
  }

  const question = phase === 'question' ? COPILOT_QUESTIONS[qIndex] : null
  const result = phase === 'result' && winner ? COPILOT_ARCHETYPES[winner] : null
  const progress = qIndex + 1
  const reason = phase === 'result' && winner ? buildRecommendationReason(answers, winner) : ''

  return (
    <div className="cob-backdrop" role="dialog" aria-modal="true" aria-label="Find your SkillBridge mentor">
      <div className="cob-shell">
        <button type="button" className="cob-close" aria-label="Close (decide later)" onClick={close} disabled={busy}>✕</button>

        <div className={`cob-progress ${phase === 'question' ? '' : 'cob-hidden'}`} aria-hidden="true">
          {COPILOT_QUESTIONS.map((_, i) => (
            <span key={i} className={`cob-seg ${i <= qIndex ? 'cob-done' : ''}`} />
          ))}
        </div>
        <div className="cob-progress-label" role="status" aria-live="polite">
          {phase === 'question' ? `Question ${progress} of ${COPILOT_QUESTIONS.length}` : ''}
        </div>

        {banner && <p className="cob-banner" role="alert">{banner}</p>}

        {phase === 'welcome' && (
          <section className="cob-welcome">
            <h2 className="cob-h">Find your SkillBridge mentor</h2>
            <p className="cob-lead">
              Answer a few quick questions and we&rsquo;ll recommend a mentor that matches how you like to learn.
            </p>
            <p className="cob-helper">Nothing is permanent — you can switch mentors anytime.</p>
            <div className="cob-actions">
              <button type="button" className="btn btn-primary cob-primary" onClick={startQuiz}>
                Get matched
              </button>
              <button type="button" className="cob-text-btn" onClick={chooseMentorOpen} disabled={busy}>
                Choose my mentor
              </button>
            </div>
          </section>
        )}

        {phase === 'question' && question && (
          <section className="cob-question">
            <h2 className="cob-h">{question.question}</h2>
            <div className="cob-option-list" role="group" aria-label="Choose one answer">
              {question.options.map((opt) => {
                const picked = answers[qIndex] === opt.vote
                return (
                  <button
                    key={opt.label}
                    type="button"
                    className="cob-option"
                    aria-pressed={picked}
                    onClick={() => pickOption(qIndex, opt.vote)}
                  >
                    <span className="cob-ring" aria-hidden="true" />
                    <span>{opt.label}</span>
                  </button>
                )
              })}
            </div>
            <div className="cob-nav-row">
              <button type="button" className="cob-text-btn" onClick={goBack} disabled={qIndex === 0 || busy}>
                Back
              </button>
              <button type="button" className="cob-text-btn" onClick={chooseMentorOpen} disabled={busy}>
                Choose my mentor
              </button>
            </div>
          </section>
        )}

        {phase === 'result' && result && (
          <section className="cob-result">
            <p className="cob-eyebrow">Meet your recommended mentor</p>
            <div className="cob-portrait" aria-hidden="true">
              <img className="cob-avatar" src={result.avatar} alt="" />
            </div>
            <h2 className="cob-h">{result.name}</h2>
            <p className="cob-personality">{result.personality}</p>
            <p className="cob-match-line">{result.name} looks like a strong match for you.</p>
            <p className="cob-reason">{reason}</p>

            <div className="cob-result-actions">
              <button type="button" className="btn btn-primary cob-primary" onClick={startWith} disabled={busy}>
                Start with {result.name}
              </button>
              <button type="button" className="cob-text-btn" onClick={chooseMentorOpen} disabled={busy}>
                See all mentors
              </button>
            </div>
            <p className="cob-helper">You can switch mentors anytime.</p>
          </section>
        )}

        {phase === 'choose' && (
          <section className="cob-choose">
            <p className="cob-eyebrow">Choose my mentor</p>
            <h2 className="cob-h">Which mentor should you start with?</h2>
            <p className="cob-helper">This is just your starting point — you can switch mentors anytime.</p>
            <div className="cob-mentor-grid" role="group" aria-label="Choose your mentor">
              {COPILOT_ARCHETYPE_KEYS.map((key) => {
                const info = COPILOT_ARCHETYPES[key]
                return (
                  <button
                    key={key}
                    type="button"
                    className="cob-mentor-card"
                    onClick={() => chooseMentor(key)}
                    disabled={busy}
                  >
                    <img className="cob-mentor-avatar" src={info.avatar} alt="" />
                    <span className="cob-mentor-name">{info.name}</span>
                    <span className="cob-mentor-traits">{info.shortTraits.join(' • ')}</span>
                    <span className="cob-mentor-desc">{info.desc}</span>
                  </button>
                )
              })}
            </div>
            <div className="cob-nav-row">
              {quizCompleted && winner && (
                <button type="button" className="cob-text-btn" onClick={() => setPhase('result')} disabled={busy}>
                  Back to my match
                </button>
              )}
            </div>
          </section>
        )}
      </div>
    </div>
  )
}