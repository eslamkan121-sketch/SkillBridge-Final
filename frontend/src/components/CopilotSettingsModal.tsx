import React from 'react'
import { api } from '../lib/api'
import { useApp } from '../AppContext'
import {
  COPILOT_ARCHETYPES,
  COPILOT_ARCHETYPE_KEYS,
  DEFAULT_COPILOT_ARCHETYPE,
  isArchetypeKey,
  type CopilotArchetypeKey,
} from '../lib/copilotArchetypes'

export interface CopilotSettingsModalProps {
  studentId: number
  open: boolean
  onClose: () => void
  /** Fired after a successful change so the dashboard can refresh. */
  onChanged?: () => void
  /** Fired from "Retake the quiz" — the parent opens CopilotOnboarding forceOpen. */
  onRetakeQuiz?: () => void
}

/**
 * Settings picker: "Change your copilot". Shows the four mentors from
 * lib/copilotArchetypes.ts (avatar, name, traits, description), pre-selecting
 * the currently stored snapshot (GET copilotConfig); confirming issues the PUT
 * (backend persists it as the active voice agent and re-marks the onboarding
 * row as manual). The "Retake the quiz" action is delegated to the parent via
 * onRetakeQuiz — this modal never runs the quiz itself.
 */
export default function CopilotSettingsModal({
  studentId,
  open,
  onClose,
  onChanged,
  onRetakeQuiz,
}: CopilotSettingsModalProps) {
  const [current, setCurrent] = React.useState<CopilotArchetypeKey | null>(null)
  const [pick, setPick] = React.useState<CopilotArchetypeKey | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [saving, setSaving] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const { setTutorId } = useApp()

  React.useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .copilotConfig(studentId)
      .then((cfg) => {
        if (cancelled) return
        const currentKey = isArchetypeKey(cfg.copilot?.choice) ? cfg.copilot.choice : DEFAULT_COPILOT_ARCHETYPE
        setCurrent(currentKey)
        setPick(currentKey)
      })
      .catch((e) => {
        if (cancelled) return
        setError(e instanceof Error ? e.message : 'Could not load your copilot preferences.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, studentId])

  if (!open) return null

  const save = async () => {
    if (saving || !pick) return
    setSaving(true)
    setError(null)
    try {
      await api.setCopilot(studentId, pick)
      setCurrent(pick)
      // The newly selected mentor becomes the ACTIVE tutor immediately, so the
      // chat header (which shows only the current mentor) reflects the change
      // without a reload. setTutorId also persists a chat-capable mode, so a
      // Vex selection never auto-enters Interview mode.
      setTutorId(pick)
      if (onChanged) onChanged()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change your copilot right now.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="csm-backdrop" role="dialog" aria-modal="true" aria-label="Change your copilot">
      <div className="csm-shell">
        <div className="csm-head">
          <div>
            <h2 className="csm-h">Change your copilot</h2>
            <p className="csm-sub">Pick any mentor — Nova, Axel, Sage, or Vex. Switch anytime.</p>
          </div>
          <button type="button" className="cob-close csm-close" aria-label="Close settings" onClick={onClose} disabled={saving}>✕</button>
        </div>

        {error && <p className="cob-banner" role="alert">{error}</p>}

        {loading ? (
          <p className="csm-loading" role="status">Loading your copilot…</p>
        ) : (
          <>
            <div className="csm-options" role="group" aria-label="Choose your copilot">
              {COPILOT_ARCHETYPE_KEYS.map((key) => {
                const info = COPILOT_ARCHETYPES[key]
                const picked = pick === key
                const isCurrent = current === key
                return (
                  <button
                    key={key}
                    type="button"
                    className={`csm-card ${picked ? 'csm-picked' : ''}`}
                    aria-pressed={picked}
                    onClick={() => setPick(key)}
                  >
                    <img className="csm-avatar" src={info.avatar} alt="" />
                    <span className="csm-card-body">
                      <span className="csm-card-title">
                        <span className="csm-name">{info.name}</span>
                        {isCurrent && picked && <span className="csm-badge">Current</span>}
                      </span>
                      <span className="csm-personality">{info.shortTraits.join(' • ')}</span>
                      <span className="csm-desc">{info.desc}</span>
                    </span>
                  </button>
                )
              })}
            </div>

            <div className="csm-actions">
              <button type="button" className="btn btn-primary cob-primary" onClick={save} disabled={saving || !pick}>
                {saving ? 'Saving…' : 'Save my copilot'}
              </button>
              {onRetakeQuiz && (
                <button type="button" className="cob-text-btn" onClick={onRetakeQuiz} disabled={saving}>
                  Retake the quiz
                </button>
              )}
            </div>
            <p className="cob-helper">You can change this anytime. Currently seated as: {current ?? '…'}</p>
          </>
        )}
      </div>
    </div>
  )
}