import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useApp } from '../AppContext'
import { api, getToken } from '../lib/api'
import { LoadingBlock } from '../components/ui'
import type { Analysis, AssessmentAttempt, IntegrityFlag, QuizQuestion, Skill } from '../lib/types'
import {
  CAMERA_INTEGRITY_THRESHOLDS,
  CameraIncidentTracker,
  CameraPrecheckTracker,
  cameraErrorMessage,
  createCocoSsdWebcamDetector,
  integrityReasonText,
  isHardTerminationEvent,
  isHardTerminationEventType,
  isVideoTrackActive,
  type AssessmentIntegrityEvent,
  type AssessmentIntegrityEventType,
  type CameraIntegrityEvent,
  type CameraPrecheckState,
  type WebcamDetectionSample,
  type WebcamDetector,
} from '../lib/webcamIntegrity'
import { GapPill } from '../components/widgets'
import { IconAssessment, IconAlert, IconFlag, IconCheck, IconTrophy, IconClock, IconEye, IconShield, IconUsers, IconBack, IconTarget } from '../components/Icons'
import { ToastRegion, useToast } from '../components/ui'

function shuffle<T>(arr: T[]): T[] {
  const a = [...arr]
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

function makeExternalToken(): string {
  const c = globalThis?.crypto as (Crypto & { randomUUID?: () => string }) | undefined
  if (c?.randomUUID) return c.randomUUID()
  return `a-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

// Resume hook: the camera gate is otherwise in-memory only, so a hard refresh
// during the pre-check would silently drop the user back to idle. The flag is
// set when the gate opens and cleared once it passes or is cancelled.
function gatePendingKey(skillId: number): string {
  return `sbg_gate_pending_${skillId}`
}

function withTimeout<T>(promise: Promise<T>, ms: number, message: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new DOMException(message, 'AbortError')), ms)
    promise.then(
      (v) => { window.clearTimeout(timer); resolve(v) },
      (e) => { window.clearTimeout(timer); reject(e) },
    )
  })
}

function safeParseJson(raw?: string): any[] {
  try {
    const v = JSON.parse(raw || '[]')
    return Array.isArray(v) ? v : []
  } catch {
    return []
  }
}

function categoryToneFor(category: string) {
  const c = (category || '').toLowerCase()
  if (c.includes('security') || c.includes('cyber')) return 'red'
  if (c.includes('devops') || c.includes('infrastruct') || c.includes('cloud') || c.includes('ml')) return 'sky'
  if (c.includes('soft') || c.includes('communi') || c.includes('data')) return 'blue'
  return 'slate'
}

function scoreBandColor(score: number) {
  if (score < 50) return 'var(--sb-red)'
  if (score < 70) return 'var(--sb-amber)'
  return 'var(--sb-green)'
}

function formatEventDuration(ms?: number) {
  const seconds = Math.max(0, Math.round((ms || 0) / 1000))
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

function makeIntegrityEvent(eventType: AssessmentIntegrityEventType, durationMs = 0, confidence?: number): AssessmentIntegrityEvent {
  return {
    event_type: eventType,
    duration_ms: Math.max(0, Math.round(durationMs)),
    occurred_at: new Date().toISOString(),
    severity: isHardTerminationEventType(eventType) ? 'high' : 'warning',
    incident_id: `${eventType}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    ...(confidence !== undefined ? { confidence } : {}),
  }
}

function attemptCompetencyBreakdown(rawPerQuestion?: string): { competency: string; score: number; passed: boolean }[] {
  const rows: any[] = safeParseJson(rawPerQuestion)
  const by: Record<string, { count: number; correct: number }> = {}
  for (const p of rows) {
    const comp = (p && typeof p.competency === 'string' && p.competency.trim()) || ''
    if (!comp) continue
    const b = by[comp] || (by[comp] = { count: 0, correct: 0 })
    b.count += 1
    if (p.correct) b.correct += 1
  }
  return Object.entries(by)
    .map(([competency, agg]) => {
      const score = Math.round((agg.correct / agg.count) * 1000) / 10
      return { competency, score, passed: score >= 70 }
    })
    .sort((x, y) => x.score - y.score)
}

function AttemptEvidence({ attempt }: { attempt: AssessmentAttempt }) {
  const flags: IntegrityFlag[] = safeParseJson(attempt.flags)
  const comps = attemptCompetencyBreakdown(attempt.per_question)
  return (
    <div className="attempt-evidence" style={{ marginTop: 12 }}>
      <h5 className="small" style={{ textTransform: 'uppercase', letterSpacing: 0.06, marginBottom: 6 }}>
        Competency evidence
      </h5>
      {comps.length > 0 ? (
        <div className="fa-competencies">
          {comps.map((c) => (
            <div className={`fa-comp ${c.passed ? 'pass' : 'fail'}`} key={c.competency}>
              <span className={`fa-comp-check`}>{c.passed ? <IconCheck size={13} /> : <span className="fa-dot" />}</span>
              <span className="fa-comp-name">{c.competency.replace(/_/g, ' ')}</span>
              <span className="fa-comp-score">{c.score}%</span>
              <span className={`pill ${c.passed ? 'strong' : 'missing'}`} style={{ flexShrink: 0 }}>{c.passed ? 'Passed' : 'Fail'}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted small">No competency-tagged breakdown stored for this attempt (legacy attempt).</p>
      )}
      {flags.length > 0 ? (
        <div style={{ marginTop: 12 }}>
          <h5 className="small" style={{ textTransform: 'uppercase', letterSpacing: 0.06, color: 'var(--amber)', marginBottom: 6 }}>
            Integrity flags raised
          </h5>
          {flags.map((f, i) => (
            <div className="flag-item" key={i}>
              <IconAlert size={16} />
              <div className="flag-body">
                <div className="fl-label">{f.label}</div>
                <div className="fl-detail">{f.detail}</div>
                {f.source === 'camera' && f.duration_ms !== undefined && (
                  <div className="fl-meta">Camera metadata only · duration {formatEventDuration(f.duration_ms)}</div>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted small" style={{ marginTop: 8 }}>No integrity concerns on this attempt.</p>
      )}
    </div>
  )
}

export default function AssessmentsPage({ initialSkillId, onFocusConsumed, backTo, onNavigate }: {
  initialSkillId?: number
  onFocusConsumed?: () => void
  backTo?: { key: string; label: string } | null
  onNavigate?: (section: string, focus?: { skillId: number; roleTitle: string }) => void
}) {
  const { me, refreshStudent, applyCopilot } = useApp()
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [attempts, setAttempts] = useState<AssessmentAttempt[]>([])
  const [keepIds, setKeepIds] = useState<Set<number>>(new Set())
  const [allSkills, setAllSkills] = useState<Skill[]>([])
  const [loadError, setLoadError] = useState('')
  const [evidenceId, setEvidenceId] = useState<number | null>(null)
  const [focusSkillName, setFocusSkillName] = useState('')
  const toast = useToast()

  useEffect(() => {
    applyCopilot({ page: 'assessment', skillId: null, competency: null, jobTitle: null, jobUrl: null })
  }, [])

  // Phase 5: a role detail can deep-link here ("Verify a Skill"). Consume the
  // focus immediately (no loops), reveal the skill even when it is already
  // strong, and bring it into view once the gap list has loaded. The skill id
  // is kept in a ref so focus consumption never races the async skills fetch.
  const focusSkillIdRef = useRef<number | null>(initialSkillId != null ? initialSkillId : null)
  useEffect(() => {
    if (focusSkillIdRef.current != null) onFocusConsumed?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => {
    const id = focusSkillIdRef.current
    if (id == null) return
    const name = allSkills.find((s) => s.id === id)?.name || ''
    if (!name) return
    setFocusSkillName(name)
    setKeepIds((prev) => { const n = new Set(prev); n.add(id); return n })
    requestAnimationFrame(() => {
      const el = document.querySelector(`[data-skill-id="${id}"]`)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
        el.classList.add('asm-focus-flash')
        setTimeout(() => el.classList.remove('asm-focus-flash'), 2600)
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allSkills])

  useEffect(() => {
    if (me?.student?.id) {
      api.analysis(me.student.id)
        .then(setAnalysis)
        .catch((e) => { console.error('[assessments] analysis failed:', e); setLoadError((p) => p || ('Failed to load gap analysis: ' + (e.message || e))) })
      api.studentAssessments(me.student.id)
        .then(setAttempts)
        .catch((e) => { console.error('[assessments] history failed:', e); setLoadError((p) => p || ('Failed to load history: ' + (e.message || e))) })
      api.skills()
        .then(setAllSkills)
        .catch((e) => { console.error('[assessments] skills failed:', e); setLoadError((p) => p || ('Failed to load skills: ' + (e.message || e))) })
    }
  }, [me])

  if (!me?.student) return <div className="empty">Log in as a student to take assessments.</div>
  const viableSkills = (analysis?.skill_gaps || []).filter((g) => g.status !== 'strong')
  const allGaps = analysis?.skill_gaps || []
  const renderedGaps = allGaps.filter((g) => g.status !== 'strong' || keepIds.has(g.skill_id))
  const keep = (id: number) => setKeepIds((prev) => { const n = new Set(prev); n.add(id); return n })
  const release = (id: number) => setKeepIds((prev) => { const n = new Set(prev); n.delete(id); return n })

  // When there is no target role / no gaps, offer every known skill so a student
  // can still verify something (this is the "assessment shows no skills" fix).
  const gapSkillIds = new Set(allGaps.map((g) => g.skill_id))
  const browseSkills = allSkills.filter((s) => !gapSkillIds.has(s.id) || !renderedGaps.find((g) => g.skill_id === s.id))
  const showBrowse = viableSkills.length === 0 && allSkills.length > 0

  const renderGap = (g: any) => {
    const last = attempts.filter((a) => a.skill_id === g.skill_id).sort((a, b) => b.id - a.id)[0]
    return (
      <AssessmentStarter
        key={g.skill_id}
        gap={g}
        lastAttempt={last}
        onActivate={() => keep(g.skill_id)}
        onDeactivate={() => release(g.skill_id)}
        onDone={() => { refreshStudent(); api.analysis(me.student!.id).then(setAnalysis); api.studentAssessments(me.student!.id).then(setAttempts) }}
        onError={(m) => toast.push(m, 'error')}
        onSuccess={(m) => toast.push(m)}
      />
    )
  }

  const passedAttempts = attempts.filter((attempt) => attempt.passed).length
  const verifiedSkillIds = new Set(me.student.verified_skills.map((v) => v.skill_id))

  return (
    <div className="assessment-page">
      <nav className="crumbs" aria-label="Breadcrumbs">
        {backTo && (
          <button type="button" className="crumb-back" onClick={() => onNavigate?.(backTo.key)}>
            <IconBack size={14} /> Back to {backTo.label}
          </button>
        )}
        {focusSkillName && <span className="crumb-context">Verifying <b>{focusSkillName}</b></span>}
      </nav>
      {focusSkillName && (
        <div className="asm-focus-strip" role="status">
          <IconTarget size={15} />
          <span>Opened from your career journey — <b>{focusSkillName}</b> is highlighted below. Assessment results only ever change verification through a passed attempt.</span>
        </div>
      )}
      <section className="assessment-hero">
        <div>
          <p className="eyebrow">Assessments</p>
          <h1>Turn claimed skills into verified evidence.</h1>
          <p>Generated questions, integrity checks, and pass results continue to use the existing assessment pipeline.</p>
        </div>
        <div className="hero-metrics">
          <div className="hero-metric gaps">
            <p className="hero-metric-value">{viableSkills.length}</p>
            <p className="hero-metric-label">open skill gaps</p>
          </div>
          <div className="hero-metric passed">
            <p className="hero-metric-value">{passedAttempts}</p>
            <p className="hero-metric-label">passed assessments</p>
          </div>
          <div className="hero-metric verified">
            <p className="hero-metric-value">{me.student.verified_skills.length}</p>
            <p className="hero-metric-label">skills verified</p>
          </div>
        </div>
      </section>

      <div className="assessment-layout">
        <section className="panel assessment-panel">
          <div className="panel-head">
            <div>
              <div className="panel-title-row">
                <span className="panel-title-icon"><IconAssessment size={15} /></span>
                <h3 className="panel-title">Verify a skill</h3>
              </div>
              <p className="panel-subtitle">Take a proctored 10-question assessment to move a skill from self-reported to Verified.</p>
            </div>
          </div>
          {loadError && <div className="error" style={{ marginBottom: 12 }}><IconAlert size={15} /> {loadError}</div>}
          {renderedGaps.length === 0 && !showBrowse && (
            <div className="empty" style={{ margin: '12px 0' }}>No skill gaps to assess. Select a target role first to see tailored gaps.</div>
          )}
          <div className="verify-list">
            {renderedGaps.map(renderGap)}
            {showBrowse && (
              <>
                <div className="info" style={{ whiteSpace: 'normal' }}>
                  <IconAssessment size={15} />
                  {analysis
                    ? 'You have no open skill gaps right now. You can still verify any skill below to strengthen your profile.'
                    : 'Set a target role to get tailored gap suggestions — or verify a skill directly below.'}
                </div>
                {browseSkills.map((s) => {
                  const last = attempts.filter((a) => a.skill_id === s.id).sort((a, b) => b.id - a.id)[0]
                  return (
                    <AssessmentStarter
                      key={s.id}
                      gap={{ skill_id: s.id, skill_name: s.name, category: s.category, required_level: 'Intermediate', student_level: null, status: 'missing', verified: false }}
                      lastAttempt={last}
                      onActivate={() => {}}
                      onDeactivate={() => {}}
                      onDone={() => { refreshStudent(); api.studentAssessments(me.student!.id).then(setAttempts); api.analysis(me.student!.id).then(setAnalysis) }}
                      onError={(m) => toast.push(m, 'error')}
                      onSuccess={(m) => toast.push(m)}
                    />
                  )
                })}
              </>
            )}
          </div>
          <ToastRegion toasts={toast.toasts} dismiss={toast.dismiss} />
        </section>

        <section className="panel assessment-panel">
          <div className="panel-head">
            <div>
              <div className="panel-title-row">
                <span className="panel-title-icon"><IconTrophy size={15} /></span>
                <h3 className="panel-title">Assessment history</h3>
              </div>
              <p className="panel-subtitle">Every attempt, its score, and any integrity flags that were raised.</p>
            </div>
          </div>
          {attempts.length === 0 ? (
            <div className="empty" style={{ margin: '12px 0' }}>No attempts recorded yet.</div>
          ) : (
            <ul className="history-list">
              {attempts.map((a) => {
                const flags: IntegrityFlag[] = safeParseJson(a.flags)
                const verified = a.passed && verifiedSkillIds.has(a.skill_id)
                return (
                  <li className="history-item" key={a.id}>
                    <div className="history-top">
                      <h4>{a.skill_name}</h4>
                      <span className={`status-pill ${verified ? 'verified' : a.passed ? 'passed' : 'failed'}`}>
                        {verified ? 'Verified' : a.passed ? 'Passed' : 'Failed'}
                      </span>
                    </div>
                    {flags.length > 0 && (
                      <div className="integrity-alert">
                        <IconFlag size={14} /> {flags.length} integrity flag{flags.length === 1 ? '' : 's'} raised on this attempt.
                      </div>
                    )}
                    <p className="history-meta">
                      Score <strong className="history-score">{a.score}%</strong> · {a.level_before} → {a.level_after}
                    </p>
                    <button
                      className="link-btn"
                      onClick={() => setEvidenceId(evidenceId === a.id ? null : a.id)}
                    >
                      {evidenceId === a.id ? 'Hide evidence' : 'Evidence & competency breakdown'}
                    </button>
                    {evidenceId === a.id && <AttemptEvidence attempt={a} />}
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}

type Mode = 'idle' | 'camera_notice' | 'camera_precheck' | 'quiz' | 'practice' | 'result'

const EMPTY_PRECHECK: CameraPrecheckState = {
  cameraStatus: 'problem',
  personStatus: 'none',
  ready: false,
  stableMs: 0,
  message: 'Camera not started.',
}

function AssessmentStarter({ gap, lastAttempt, onDone, onActivate, onDeactivate, onError, onSuccess }: { gap: any; lastAttempt?: AssessmentAttempt; onDone: () => void; onActivate: () => void; onDeactivate: () => void; onError?: (m: string) => void; onSuccess?: (m: string) => void }) {
  const { me, setAssessmentActive } = useApp()
  const [mode, setMode] = useState<Mode>('idle')
  const [questions, setQuestions] = useState<QuizQuestion[]>([])
  const [answers, setAnswers] = useState<string[]>([])
  const [tabSwitches, setTabSwitches] = useState(0)
  const [result, setResult] = useState<any>(null)
  const [practiceData, setPracticeData] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [current, setCurrent] = useState(0)
  const [confirmEnd, setConfirmEnd] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [cameraStream, setCameraStream] = useState<MediaStream | null>(null)
  const [cameraLoading, setCameraLoading] = useState(false)
  const [detectorReady, setDetectorReady] = useState(false)
  const [cameraError, setCameraError] = useState('')
  const [cameraWarning, setCameraWarning] = useState('')
  const [precheck, setPrecheck] = useState<CameraPrecheckState>(EMPTY_PRECHECK)
  const [cameraEvents, setCameraEvents] = useState<CameraIntegrityEvent[]>([])
  // Multiple cameras: enumerate so a busy/absent default does not dead-end the
  // gate and the student can pick an explicit device.
  const [cameraDevices, setCameraDevices] = useState<MediaDeviceInfo[]>([])
  const [selectedCameraId, setSelectedCameraId] = useState<string>('')
  // Consecutive start failures are capped so the gate does not spin forever.
  const [gateRetries, setGateRetries] = useState(0)
  // Per-attempt shuffled option order: computed ONCE when a quiz starts, so the
  // timer-driven re-renders never reshuffle options mid-question.
  const [optOrder, setOptOrder] = useState<string[][] | null>(null)
  const startRef = useRef<number>(0)
  const modeRef = useRef<Mode>('idle')
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const cameraStreamRef = useRef<MediaStream | null>(null)
  const detectorRef = useRef<WebcamDetector | null>(null)
  const precheckTrackerRef = useRef(new CameraPrecheckTracker())
  const incidentTrackerRef = useRef(new CameraIncidentTracker())
  const cameraEventsRef = useRef<CameraIntegrityEvent[]>([])
  const fullscreenEngagedRef = useRef(false)
  // Per-attempt idempotency token, sent to the finalize endpoint so duplicate
  // exit events (route-leave + pagehide + unmount) never double-submit.
  const runTokenRef = useRef<string | null>(null)
  const finalizingRef = useRef(false)
  const sidRef = useRef<number>(me?.student?.id ?? 0)
  sidRef.current = me?.student?.id ?? 0

  // Latest attempt snapshot for the beacon path (no stale-closure surprises).
  const liveRef = useRef({ questions: questions as QuizQuestion[], answers: answers as string[], tabSwitches: 0 })
  liveRef.current = { questions, answers, tabSwitches }

  const stopCamera = useCallback(() => {
    const stream = cameraStreamRef.current
    if (stream) stream.getTracks().forEach((track) => track.stop())
    cameraStreamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    if (detectorRef.current?.dispose) detectorRef.current.dispose()
    detectorRef.current = null
    fullscreenEngagedRef.current = false
    if (document.fullscreenElement && document.exitFullscreen) {
      void document.exitFullscreen().catch(() => {})
    }
    precheckTrackerRef.current.reset()
    incidentTrackerRef.current.reset()
    setCameraStream(null)
    setDetectorReady(false)
    setCameraLoading(false)
    setCameraWarning('')
    setPrecheck(EMPTY_PRECHECK)
  }, [])

  const resetCameraEvents = useCallback(() => {
    cameraEventsRef.current = []
    setCameraEvents([])
  }, [])

  const recordCameraEvents = useCallback((events: CameraIntegrityEvent[]) => {
    if (!events.length) return
    const sid = sidRef.current
    const token = runTokenRef.current || ''
    const merged = [...cameraEventsRef.current]
    for (const event of events) {
      if (!merged.some((e) => e.event_type === event.event_type && e.incident_id === event.incident_id)) {
        merged.push(event)
      }
    }
    cameraEventsRef.current = merged
    setCameraEvents(merged)
    if (!sid || !token) return
    for (const event of events) {
      void api.assessmentIntegrityEvent(sid, {
        ...event,
        skill_id: gap.skill_id,
        external_token: token,
      }).catch(() => {
        // The final submit/finalize body also carries the metadata list, so a
        // transient POST failure does not lose the local integrity evidence.
      })
    }
  }, [gap.skill_id])

  const buildFinalizeBody = useCallback((terminationEvent?: AssessmentIntegrityEvent | null) => {
    const ext = runTokenRef.current
    if (!sidRef.current || !ext) return null
    const live = liveRef.current
    return {
      skill_id: gap.skill_id,
      questions: live.questions,
      answers: live.answers,
      total_seconds: Math.round((Date.now() - startRef.current) / 1000),
      tab_switches: live.tabSwitches,
      free_text_answers: live.questions.map((q, i) => (q.type === 'free_text' ? live.answers[i] || '' : '')).filter((x) => x),
      camera_events: cameraEventsRef.current,
      external_token: ext,
      auth_token: getToken() ?? undefined,
      ...(terminationEvent ? { termination_event: terminationEvent } : {}),
    }
  }, [gap.skill_id])

  const releaseLock = useCallback(() => {
    finalizingRef.current = true
    setAssessmentActive(false)
    if (sidRef.current) void api.endAssessmentSession(sidRef.current).catch(() => {})
  }, [setAssessmentActive])

  const sendFinalizeBeacon = useCallback((terminationEvent?: AssessmentIntegrityEvent | null) => {
    const sid = sidRef.current
    const body = buildFinalizeBody(terminationEvent)
    if (!sid || !body) return false
    try {
      navigator.sendBeacon(
        `/api/students/${sid}/assessments/finalize`,
        new Blob([JSON.stringify(body)], { type: 'application/json' }),
      )
    } catch { /* best-effort — the stale-lock TTL on the server still protects us */ }
    const stream = cameraStreamRef.current
    if (stream) stream.getTracks().forEach((track) => track.stop())
    return true
  }, [buildFinalizeBody])

  const beaconFinalize = useCallback((terminationEvent?: AssessmentIntegrityEvent | null) => {
    if (finalizingRef.current) return
    finalizingRef.current = true
    sendFinalizeBeacon(terminationEvent)
  }, [sendFinalizeBeacon])

  const terminateAssessmentForIntegrity = useCallback(async (
    event: AssessmentIntegrityEvent,
    opts: { beaconFirst?: boolean } = {},
  ) => {
    if (finalizingRef.current) return
    finalizingRef.current = true
    setBusy(true)
    setConfirmEnd(false)
    setCameraWarning('Assessment ended because an integrity rule was violated.')
    if (opts.beaconFirst) sendFinalizeBeacon(event)
    stopCamera()
    try {
      const body = buildFinalizeBody(event)
      if (!sidRef.current || !body) throw new Error('No active assessment to finalize.')
      const res = await api.finalizeAssessment(sidRef.current, body)
      runTokenRef.current = null
      releaseLock()
      setResult(res)
      setQuestions([])
      setCurrent(0)
      setMode('result')
      onDone()
    } catch (e: any) {
      if (!opts.beaconFirst) sendFinalizeBeacon(event)
      releaseLock()
      onError?.('Assessment ended because an integrity rule was violated. ' + (e?.message || ''))
      setMode('idle')
      onDeactivate()
    } finally {
      setBusy(false)
    }
  }, [buildFinalizeBody, onDeactivate, onDone, onError, releaseLock, sendFinalizeBeacon, stopCamera])

  // Track the live mode for the unmount handler.
  useEffect(() => {
    modeRef.current = mode
  }, [mode])

  // Resume a camera gate interrupted by a hard refresh: the gate state itself is
  // in-memory only, but the pending flag survives reload and lands us back on the
  // camera notice so the flow continues where the user left off.
  useEffect(() => {
    if (mode === 'idle' && sessionStorage.getItem(gatePendingKey(gap.skill_id)) === '1') {
      resetRun()
      setGateRetries(0)
      setMode('camera_notice')
      onActivate()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gap.skill_id])

  // Leaving the page while a quiz is open finalizes immediately (unanswered
  // count as zero) so an attempt is never silently thrown away.
  useEffect(() => {
    if (mode !== 'quiz') return
    const onHide = () => beaconFinalize(makeIntegrityEvent('browser_hidden'))
    window.addEventListener('pagehide', onHide)
    return () => window.removeEventListener('pagehide', onHide)
  }, [mode, beaconFinalize])

  useEffect(() => () => {
    if (modeRef.current === 'quiz') {
      beaconFinalize()
      setAssessmentActive(false)
    }
    stopCamera()
    // Leaving the gate (including SPA navigation away) clears its resume flag.
    sessionStorage.removeItem(gatePendingKey(gap.skill_id))
  }, [beaconFinalize, setAssessmentActive, gap.skill_id, stopCamera])

  useEffect(() => {
    const video = videoRef.current
    if (!video || !cameraStream) return
    video.srcObject = cameraStream
    void video.play().catch(() => {})
  }, [cameraStream, mode])

  useEffect(() => {
    if ((mode !== 'camera_precheck' && mode !== 'quiz') || !cameraStream || !detectorReady) return
    let cancelled = false
    let timer: number | null = null
    const blankSample = (): WebcamDetectionSample => ({
      personCount: 0,
      phonePresent: false,
      phoneConfidence: 0,
      trackActive: isVideoTrackActive(cameraStream),
    })
    const tick = async () => {
      let sample = blankSample()
      if (sample.trackActive && detectorRef.current && videoRef.current) {
        try {
          sample = { ...(await detectorRef.current.detect(videoRef.current)), trackActive: isVideoTrackActive(cameraStream) }
        } catch {
          sample = blankSample()
        }
      }
      if (cancelled) return
      if (mode === 'camera_precheck') {
        setPrecheck(precheckTrackerRef.current.update(sample))
      } else if (mode === 'quiz') {
        const update = incidentTrackerRef.current.update(sample)
        setCameraWarning(update.warning || 'Camera monitoring active')
        recordCameraEvents(update.events)
        const hardEvent = update.events.find(isHardTerminationEvent)
        if (hardEvent) {
          void terminateAssessmentForIntegrity(hardEvent)
          return
        }
      }
      timer = window.setTimeout(tick, CAMERA_INTEGRITY_THRESHOLDS.inferenceCadenceMs)
    }
    void tick()
    return () => {
      cancelled = true
      if (timer !== null) window.clearTimeout(timer)
    }
  }, [cameraStream, detectorReady, mode, recordCameraEvents, terminateAssessmentForIntegrity])

  const requestAssessmentFullscreen = useCallback(() => {
    if (!document.fullscreenEnabled || document.fullscreenElement || !document.documentElement.requestFullscreen) return
    void document.documentElement.requestFullscreen()
      .then(() => { fullscreenEngagedRef.current = true })
      .catch(() => { fullscreenEngagedRef.current = false })
  }, [])

  const resetRun = useCallback(() => {
    setResult(null)
    setPracticeData(null)
    setTabSwitches(0)
    setAnswers([])
    setCurrent(0)
    setConfirmEnd(false)
    setElapsed(0)
    setOptOrder(null)
    setCameraError('')
    setCameraWarning('')
    resetCameraEvents()
  }, [resetCameraEvents])

  const cancelCameraFlow = useCallback(() => {
    stopCamera()
    resetRun()
    sessionStorage.removeItem(gatePendingKey(gap.skill_id))
    runTokenRef.current = null
    finalizingRef.current = true
    setMode('idle')
    onDeactivate()
  }, [gap.skill_id, onDeactivate, resetRun, stopCamera])

  const startCameraPrecheck = async () => {
    setMode('camera_precheck')
    setCameraError('')
    setCameraWarning('')
    setPrecheck(EMPTY_PRECHECK)
    precheckTrackerRef.current.reset()
    stopCamera()
    setCameraLoading(true)
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError(cameraErrorMessage(null))
      setCameraLoading(false)
      return
    }
    // Enumerate cameras first: lets the user pick between devices and lets the
    // gate automatically fall back to another camera when the default is busy.
    let deviceIds: string[] = []
    try {
      const cameras = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput')
      setCameraDevices(cameras)
      deviceIds = cameras.map((d) => d.deviceId).filter(Boolean)
    } catch {
      setCameraDevices([])
    }
    const candidates = deviceIds.length ? (selectedCameraId ? [selectedCameraId] : deviceIds) : ['']
    let stream: MediaStream | null = null
    let usedDevice = ''
    let lastError: string | null = null
    for (const deviceId of candidates) {
      try {
        const video = deviceId ? { deviceId: { exact: deviceId } } : true
        stream = await withTimeout(
          navigator.mediaDevices.getUserMedia({ video, audio: false }),
          12000,
          'Starting the camera took too long. Check the device and try again.',
        )
        usedDevice = deviceId
        break
      } catch (e: any) {
        const name = (e as DOMException | undefined)?.name || ''
        if ((name === 'NotReadableError' || name === 'TrackStartError') && deviceId && candidates.length > 1) {
          // Another app holds this camera — move on to the next one.
          lastError = cameraErrorMessage(e)
          continue
        }
        if (name === 'AbortError') {
          setCameraError('Starting the camera took too long. Check the device and try again.')
          setGateRetries((r) => r + 1)
          setCameraLoading(false)
          return
        }
        setCameraError(cameraErrorMessage(e))
        setGateRetries((r) => r + 1)
        setCameraLoading(false)
        return
      }
    }
    if (!stream) {
      setCameraError(lastError ?? 'The camera could not be started. Check the device and try again.')
      setGateRetries((r) => r + 1)
      setCameraLoading(false)
      return
    }
    cameraStreamRef.current = stream
    setCameraStream(stream)
    setSelectedCameraId(usedDevice)
    setCameraLoading(false)
    setCameraWarning('Loading local camera checks.')
    try {
      const detector = await createCocoSsdWebcamDetector()
      detectorRef.current = detector
      setDetectorReady(true)
      setCameraWarning('Camera monitoring active')
    } catch {
      stopCamera()
      setCameraError('The local camera analysis engine could not be loaded. Try again.')
      setGateRetries((r) => r + 1)
    } finally {
      setCameraLoading(false)
    }
  }

  const beginVerifiedAssessment = async () => {
    if (!precheck.ready || !cameraStream || !isVideoTrackActive(cameraStream)) {
      setCameraError('Camera pre-check must pass before the Final Assessment can start.')
      return
    }
    requestAssessmentFullscreen()
    setGenerating(true)
    resetRun()
    incidentTrackerRef.current.reset()
    try {
      // Lock chat/interview/TTS immediately when the actual assessment begins.
      finalizingRef.current = false
      runTokenRef.current = makeExternalToken()
      setAssessmentActive(true)
      if (me?.student?.id) {
        // Server-side gate: the session is only created when the local pre-check
        // passed. Only metadata is sent — never any frame or recording.
        await api.startAssessmentSession(me.student.id, gap.skill_id, runTokenRef.current, {
          passed: true,
          checked_at: new Date().toISOString(),
          meta: {
            person_status: precheck.personStatus,
            camera_status: precheck.cameraStatus,
            stable_ms: precheck.stableMs,
            camera_count: cameraDevices.length,
          },
        })
        sessionStorage.removeItem(gatePendingKey(gap.skill_id))
      }
      const res = await api.generateAssessment(me!.student!.id, gap.skill_id, { practice: false })
      const idx = res.questions.map((_, i) => i)
      for (let i = idx.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1))
        ;[idx[i], idx[j]] = [idx[j], idx[i]]
      }
      const orderedQuestions = idx.map((i) => res.questions[i])
      const orderedOpt = orderedQuestions.map((q) => (q.type === 'multiple_choice' ? shuffle(q.options) : []))
      setQuestions(orderedQuestions)
      setOptOrder(orderedOpt)
      setAnswers(new Array(orderedQuestions.length).fill(''))
      startRef.current = Date.now()
      setCameraWarning('Camera monitoring active')
      setMode('quiz')
    } catch (e: any) {
      releaseLock()
      stopCamera()
      onError?.('Failed to generate quiz: ' + e.message)
      setMode('idle')
      onDeactivate()
    } finally {
      setGenerating(false)
    }
  }

  const start = async (practice: boolean) => {
    resetRun()
    onActivate()
    if (!practice) {
      runTokenRef.current = null
      finalizingRef.current = true
      setGateRetries(0)
      sessionStorage.setItem(gatePendingKey(gap.skill_id), '1')
      setMode('camera_notice')
      return
    }
    stopCamera()
    setGenerating(true)
    try {
      runTokenRef.current = null
      const res = await api.generateAssessment(me!.student!.id, gap.skill_id, { practice })
      if (res.previous_score !== null) {
        setPracticeData(res)
        setMode('practice')
      } else {
        setMode('idle')
      }
    } catch (e: any) {
      releaseLock()
      onError?.('Failed to generate quiz: ' + e.message)
      setMode('idle')
      onDeactivate()
    } finally {
      setGenerating(false)
    }
  }

  useEffect(() => {
    if (mode !== 'quiz') return
    const onVis = () => {
      if (document.visibilityState === 'hidden') {
        void terminateAssessmentForIntegrity(makeIntegrityEvent('browser_hidden'), { beaconFirst: true })
      }
    }
    const onBlur = () => {
      void terminateAssessmentForIntegrity(makeIntegrityEvent('window_blur'), { beaconFirst: document.hidden })
    }
    const onFullscreen = () => {
      if (fullscreenEngagedRef.current && !document.fullscreenElement) {
        void terminateAssessmentForIntegrity(makeIntegrityEvent('fullscreen_exit'), { beaconFirst: document.hidden })
      }
    }
    document.addEventListener('visibilitychange', onVis)
    window.addEventListener('blur', onBlur)
    document.addEventListener('fullscreenchange', onFullscreen)
    return () => {
      document.removeEventListener('visibilitychange', onVis)
      window.removeEventListener('blur', onBlur)
      document.removeEventListener('fullscreenchange', onFullscreen)
    }
  }, [mode, terminateAssessmentForIntegrity])

  useEffect(() => {
    if (mode !== 'quiz') return
    const t = window.setInterval(() => setElapsed((e) => e + 1), 1000)
    return () => window.clearInterval(t)
  }, [mode, current])

  const setAnswer = (i: number, v: string) => setAnswers((prev) => prev.map((x, idx) => (idx === i ? v : x)))

  const selectOption = (opt: string) => {
    setAnswer(current, opt)
  }
  const next = () => {
    if (current + 1 < questions.length) setCurrent((c) => c + 1)
    else submit()
  }

  const submit = async () => {
    setBusy(true)
    try {
      const res = await api.submitAssessment(me!.student!.id, {
        skill_id: gap.skill_id,
        questions,
        answers,
        total_seconds: Math.round((Date.now() - startRef.current) / 1000),
        tab_switches: tabSwitches,
        free_text_answers: questions.map((q, i) => (q.type === 'free_text' ? answers[i] || '' : '')).filter((x) => x),
        camera_events: cameraEventsRef.current,
        external_token: runTokenRef.current ?? undefined,
      })
      runTokenRef.current = null
      releaseLock()
      stopCamera()
      setResult(res)
      setQuestions([])
      setCurrent(0)
      setConfirmEnd(false)
      setMode('result')
      onDone()
      onSuccess?.(res.passed
        ? ((res.flags || []).length ? `${gap.skill_name} passed. Integrity review recommended.` : `${gap.skill_name} verified — you passed!`)
        : `Assessment complete for ${gap.skill_name}.`)
    } catch (e: any) {
      onError?.('Submit failed: ' + e.message)
    } finally {
      setBusy(false)
    }
  }

  // Leaving mid-quiz finalizes immediately with unanswered = 0.
  const finalizeNow = async () => {
    if (finalizingRef.current) return
    setBusy(true)
    try {
      const res = await api.finalizeAssessment(me!.student!.id, {
        skill_id: gap.skill_id,
        questions,
        answers,
        total_seconds: Math.round((Date.now() - startRef.current) / 1000),
        tab_switches: tabSwitches,
        free_text_answers: questions.map((q, i) => (q.type === 'free_text' ? answers[i] || '' : '')).filter((x) => x),
        camera_events: cameraEventsRef.current,
        external_token: runTokenRef.current ?? undefined,
      })
      runTokenRef.current = null
      releaseLock()
      stopCamera()
      setResult(res)
      setQuestions([])
      setCurrent(0)
      setConfirmEnd(false)
      setMode('result')
      onDone()
    } catch (e: any) {
      releaseLock()
      stopCamera()
      onError?.('Could not end the assessment: ' + e.message)
      setMode('idle')
      onDeactivate()
    } finally {
      setBusy(false)
    }
  }

  if (generating) {
    return (
      <div className="assessment-generating">
        <LoadingBlock label="Generating assessment questions with AI…" />
      </div>
    )
  }

  if (mode === 'camera_notice') {
    return (
      <div className="learning-item open camera-consent-card">
        <div className="li-body" style={{ display: 'block', padding: 18 }}>
          <div className="camera-panel-head">
            <span className="camera-panel-icon"><IconShield size={18} /></span>
            <div>
              <h4>Camera integrity notice</h4>
              <p className="small muted">
                This assessment uses your camera to support assessment integrity.
              </p>
            </div>
          </div>
          <p className="camera-copy">
            During the assessment SkillBridge checks whether the camera remains active and may flag events such as no person being visible, multiple people appearing, or a phone being detected.
          </p>
          <p className="camera-copy">
            Video is not recorded or stored. Camera analysis is used only during the assessment.
          </p>
          <div className="camera-actions">
            <button className="btn" onClick={cancelCameraFlow}>Cancel</button>
            <button className="btn btn-primary" onClick={() => void startCameraPrecheck()}>
              <IconEye size={14} /> Enable Camera
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (mode === 'camera_precheck') {
    const cameraLabel = precheck.cameraStatus === 'working' ? 'Working' : 'Problem'
    const personLabel = precheck.personStatus === 'one'
      ? 'One person visible'
      : precheck.personStatus === 'multiple' ? 'Multiple people' : 'Not detected'
    const stablePct = Math.min(100, Math.round((precheck.stableMs / CAMERA_INTEGRITY_THRESHOLDS.precheckStableMs) * 100))
    const gateBlocked = gateRetries >= 4
    return (
      <div className="learning-item open camera-precheck-card">
        <div className="li-body" style={{ display: 'block', padding: 18 }}>
          <div className="camera-panel-head">
            <span className="camera-panel-icon"><IconEye size={18} /></span>
            <div>
              <h4>Camera pre-check: {gap.skill_name}</h4>
              <p className="small muted">Camera monitoring is required for the Final Assessment.</p>
            </div>
          </div>
          <div className="camera-precheck-grid">
            <div className="camera-preview-wrap">
              <video ref={videoRef} className="camera-preview" muted playsInline autoPlay />
              {(cameraLoading || (!detectorReady && cameraStream)) && (
                <div className="camera-preview-state">
                  {cameraLoading ? 'Starting camera...' : 'Loading local checks...'}
                </div>
              )}
            </div>
            <div className="camera-check-list">
              <div className={`camera-check ${precheck.cameraStatus === 'working' ? 'ok' : 'warn'}`}>
                <span><IconEye size={15} /> Camera</span>
                <strong>{cameraLabel}</strong>
              </div>
              <div className={`camera-check ${precheck.personStatus === 'one' ? 'ok' : 'warn'}`}>
                <span><IconUsers size={15} /> Person</span>
                <strong>{personLabel}</strong>
              </div>
              <div className="camera-stability">
                <span>{precheck.message}</span>
                <div className="camera-stability-track">
                  <div className="camera-stability-fill" style={{ width: `${stablePct}%` }} />
                </div>
              </div>
              {cameraDevices.length > 1 && (
                <label className="camera-check camera-device-row">
                  <span><IconEye size={15} /> Camera device</span>
                  <select
                    aria-label="Choose camera"
                    value={cameraDevices.some((d) => d.deviceId === selectedCameraId) ? selectedCameraId : ''}
                    onChange={(e) => { setSelectedCameraId(e.target.value); void startCameraPrecheck() }}
                  >
                    <option value="">Default camera</option>
                    {cameraDevices.map((d, i) => (
                      <option key={d.deviceId || `cam-${i}`} value={d.deviceId}>{d.label || `Camera ${i + 1}`}</option>
                    ))}
                  </select>
                </label>
              )}
              {gateBlocked ? (
                <div className="error" style={{ whiteSpace: 'normal' }}>
                  <IconAlert size={15} /> The camera gate could not be completed after several attempts. The Final Assessment requires a working camera. Close any other app using it, check browser permissions, restart your browser, then start again.
                </div>
              ) : cameraError ? (
                <div className="error" style={{ whiteSpace: 'normal' }}>
                  <IconAlert size={15} /> {cameraError}
                </div>
              ) : null}
              <p className="small muted" style={{ marginTop: 8 }}>
                Video is analysed locally on your device only — it is never recorded, stored or uploaded.
              </p>
            </div>
          </div>
          <div className="camera-actions">
            <button className="btn" onClick={cancelCameraFlow}>Cancel</button>
            {cameraError && !gateBlocked && <button className="btn" onClick={() => void startCameraPrecheck()}>Try Camera Again</button>}
            <button
              className="btn btn-primary"
              disabled={!precheck.ready || cameraLoading || !detectorReady}
              onClick={() => void beginVerifiedAssessment()}
            >
              <IconAssessment size={14} /> Start Assessment
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (mode === 'practice' && practiceData) {
    return (
      <div className="learning-item open" style={{ border: '1.5px solid var(--sb-indigo)' }}>
        <div className="li-body" style={{ display: 'block', padding: 16 }}>
          <h4 style={{ marginBottom: 6 }}>Practice review: {gap.skill_name}</h4>
          <p className="small muted mb">
            These are the questions from your last attempt — score {practiceData.previous_score}%,{' '}
            {practiceData.previous_passed ? 'passed' : 'not passed'}. This mode doesn't affect your Verified profile.
          </p>
          {practiceData.previous_results.map((r: any) => {
            const q = practiceData.questions[r.index]
            return (
              <div className="question-block" key={r.index}>
                <div className="flex between">
                  <div className="q-text">{r.index + 1}. {q.question}</div>
                  <span className={`pill ${r.correct ? 'strong' : 'missing'}`} style={{ flexShrink: 0 }}>{r.correct ? 'Correct' : 'Incorrect'}</span>
                </div>
                {q.type === 'multiple_choice'
                  ? q.options.map((opt: string) => (
                      <div key={opt} className={`mc-option read-only ${opt === q.answer ? 'is-answer' : ''} ${opt === r.answer ? 'is-taken' : ''}`}>
                        <span className="radio" /> {opt}{opt === q.answer ? ' ✓' : ''}
                      </div>
                    ))
                  : <div className="free-text read-only">Your answer: {r.answer || '(empty)'}</div>}
                <div className="q-expl"><IconTrophy size={14} /> {q.explanation}</div>
              </div>
            )
          })}
          <div className="flex" style={{ justifyContent: 'flex-end' }}>
            <button className="btn" onClick={() => { setMode('idle'); onDeactivate() }}>Back</button>
            <button className="btn btn-primary" onClick={() => start(false)}><IconAssessment size={14} /> Redo for real</button>
          </div>
        </div>
      </div>
    )
  }

  if (mode === 'quiz' && questions.length) {
    const q = questions[current]
    const isLast = current === questions.length - 1
    const chosen = answers[current] || ''
    const order = optOrder && optOrder[current]?.length ? optOrder[current] : (q?.options || [])
    const progressPct = ((current + 1) / questions.length) * 100
    const mm = String(Math.floor(elapsed / 60)).padStart(2, '0')
    const ss = String(elapsed % 60).padStart(2, '0')
    const answered = chosen.trim().length > 0
    return (
      <div className="assessment-run-fullscreen">
        <div className="assessment-run-head">
          <div>
            <p className="eyebrow">Verified Final Assessment</p>
            <h1>{gap.skill_name}</h1>
          </div>
          <button className="btn btn-ghost" disabled={busy} onClick={() => setConfirmEnd(true)} aria-label="End assessment">
            End assessment
          </button>
        </div>
        <div className="assessment-run-card">
          <div className="quiz-top">
            <div className="quiz-progress-wrap">
              <div className="quiz-head">
                <span className="quiz-count">Question {current + 1} of {questions.length}</span>
                <span className="quiz-timer"><IconClock size={14} /> {mm}:{ss}</span>
              </div>
              <div className="quiz-progress"><div className="quiz-progress-fill" style={{ width: `${progressPct}%` }} /></div>
            </div>
            {tabSwitches > 0 && (
              <div className="integrity-pill">
                <IconAlert size={14} />
                <span>{tabSwitches} tab-switch{tabSwitches === 1 ? '' : 'es'} detected — this is logged as an integrity flag.</span>
              </div>
            )}
            <div className={`camera-monitor-pill ${cameraWarning && cameraWarning !== 'Camera monitoring active' ? 'warn' : 'ok'}`}>
              <video ref={videoRef} className="camera-mini-preview" muted playsInline autoPlay />
              <div>
                <span><IconEye size={14} /> {cameraWarning || 'Camera monitoring active'}</span>
                <small>{cameraEvents.length ? `${cameraEvents.length} review signal${cameraEvents.length === 1 ? '' : 's'} logged` : 'Local analysis, no recording'}</small>
              </div>
            </div>
          </div>
          <div className="question-block" key={current}>
            <p className="run-question">{q.question}</p>
            {q.type === 'multiple_choice' ? (
              order.map((opt) => (
                <button key={opt} className={`run-option ${chosen === opt ? 'selected' : ''}`} onClick={() => selectOption(opt)}>
                  <span className="run-radio">{chosen === opt && <span className="run-radio-dot" />}</span>
                  {opt}
                </button>
              ))
            ) : (
              <textarea className="free-text" value={answers[current]}
                onChange={(e) => setAnswer(current, e.target.value)}
                placeholder="Type your answer… (pasted polished/AI-style text may be flagged)" />
            )}
          </div>
          {q.type === 'multiple_choice' ? (
            chosen ? (
              <div className="flex run-cta">
                <button className="btn btn-primary" onClick={next} disabled={busy}>
                  {isLast ? (busy ? 'Submitting…' : 'Submit assessment') : `Next question ›`}
                </button>
              </div>
            ) : (
              <div className="flex run-cta">
                <button className="btn btn-primary" disabled>Select an answer</button>
              </div>
            )
          ) : answered ? (
            <div className="flex run-cta">
              <button className="btn btn-primary" onClick={next} disabled={busy}>
                {isLast ? (busy ? 'Submitting…' : 'Submit assessment') : `Next question ›`}
              </button>
            </div>
          ) : (
            <div className="flex run-cta">
              <button className="btn btn-primary" disabled>Type an answer to continue</button>
            </div>
          )}
        </div>
        {confirmEnd && (
          <div className="confirm-overlay" role="dialog" aria-modal="true" aria-labelledby="confirm-end-title">
            <div className="confirm-dialog">
              <h2 id="confirm-end-title">End this assessment early?</h2>
              <p>Your attempt will be finalized with unanswered questions scored as zero. This cannot be undone.</p>
              <div className="confirm-actions">
                <button className="btn btn-ghost" onClick={() => setConfirmEnd(false)} aria-label="Cancel ending assessment">Cancel</button>
                <button className="btn btn-danger" disabled={busy} onClick={() => { setConfirmEnd(false); void finalizeNow() }}>
                  End assessment
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    )
  }

  if (mode === 'result' && result) {
    const correctN = (result.per_question || []).filter((p: any) => p.correct).length
    const flags = (result.flags || []) as IntegrityFlag[]
    const endedByIntegrity = result.ended === 'integrity_violation'
    const reviewRequired = result.integrity_status === 'review_required' || endedByIntegrity
    const reviewRecommended = reviewRequired || result.integrity_status === 'review_recommended' || flags.length > 0
    const terminationReason = result.termination_reason || (
      result.termination_event?.event_type ? integrityReasonText(result.termination_event.event_type) : ''
    )
    const resultTitle = endedByIntegrity
      ? 'Assessment Ended'
      : result.passed ? `Assessment passed: ${gap.skill_name}` : `Not passed — keep learning ${gap.skill_name}`
    return (
      <div className="learning-item open" style={{ border: `1.5px solid ${result.passed ? 'var(--green)' : 'var(--red)'}` }}>
        <div className="li-body" style={{ display: 'block', padding: 18 }}>
          {result.passed && (
            <div className="particle-burst" aria-hidden="true">
              {Array.from({ length: 14 }).map((_, i) => (
                <span key={i} className="particle" style={{ ['--angle' as any]: `${i * 25.7}deg`, animationDelay: `${i * 0.02}s` }} />
              ))}
            </div>
          )}
          <div className="result-summary">
            <div className={`result-score ${result.passed ? 'pass' : 'fail'}`}>{Math.round(result.score)}%</div>
            <h4>{resultTitle}</h4>
            <p className="muted small mb">
              {correctN} of {result.questions.length} correct · Proficiency {result.level_before} → {result.level_after}
            </p>
            <div className="assessment-result-status">
              <div>
                <span>Assessment</span>
                <strong className={result.passed && !endedByIntegrity ? 'pass' : 'fail'}>{endedByIntegrity ? 'Ended' : result.passed ? 'Passed' : 'Not passed'}</strong>
              </div>
              <div>
                <span>Integrity</span>
                <strong className={reviewRecommended ? 'review' : 'clear'}>{reviewRequired ? 'Review required' : reviewRecommended ? 'Review recommended' : 'Clear'}</strong>
              </div>
            </div>
            {endedByIntegrity && (
              <div className="integrity-ended-panel">
                <IconAlert size={15} /> Assessment ended because an integrity rule was violated.
                {terminationReason && <span><strong>Reason:</strong> {terminationReason}</span>}
              </div>
            )}
            {result.ended === 'exit' && (
              <div className="info" style={{ whiteSpace: 'normal', marginBottom: 10 }}>
                <IconAlert size={15} /> This attempt ended early — unanswered questions were scored as zero.
              </div>
            )}
            <div className="flex" style={{ gap: 8 }}>
              <button className="btn" onClick={() => { setMode('idle'); onDeactivate() }}>Back to skill list</button>
              {lastAttempt && <button className="btn" onClick={() => start(true)}><IconTrophy size={14} /> Practice review</button>}
            </div>
          </div>
          {Array.isArray(result.competencies) && result.competencies.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <h5 className="small" style={{ textTransform: 'uppercase', letterSpacing: 0.06, marginBottom: 6 }}>
                Competency breakdown{result.full_coverage ? ' · full coverage' : ' · partial coverage'}
              </h5>
              <div className="fa-competencies">
                {result.competencies.map((c: any) => (
                  <div className={`fa-comp ${c.passed ? 'pass' : 'fail'}`} key={c.competency}>
                    <span className={`fa-comp-check`}>{c.passed ? <IconCheck size={13} /> : <span className="fa-dot" />}</span>
                    <span className="fa-comp-name">{c.competency.replace(/_/g, ' ')}</span>
                    <span className="fa-comp-score">{c.score}%</span>
                    <span className={`pill ${c.passed ? 'strong' : 'missing'}`} style={{ flexShrink: 0 }}>{c.passed ? 'Passed' : 'Fail'}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {flags.length > 0 && (
            <div>
              <h5 className="small" style={{ textTransform: 'uppercase', letterSpacing: 0.06, color: 'var(--amber)', marginBottom: 6 }}>
                Integrity flags raised
              </h5>
              {flags.map((f: IntegrityFlag, i: number) => (
                <div className="flag-item" key={i}>
                  <IconAlert size={16} />
                  <div className="flag-body">
                    <div className="fl-label">{f.label}</div>
                    <div className="fl-detail">{f.detail}</div>
                    {f.source === 'camera' && f.duration_ms !== undefined && (
                      <div className="fl-meta">Camera metadata only · duration {formatEventDuration(f.duration_ms)}</div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          {flags.length === 0 && (
            <p className="muted small" style={{ marginTop: 8 }}>No integrity concerns on this attempt.</p>
          )}
          <div style={{ marginTop: 14 }}>
            <h5 className="small" style={{ textTransform: 'uppercase', letterSpacing: 0.06, marginBottom: 6 }}>Question review</h5>
            {result.questions.map((q: QuizQuestion, i: number) => {
              const r = result.per_question[i]
              return (
                <div className="question-block" key={i}>
                  <div className="flex between">
                    <div className="q-text">{i + 1}. {q.question}</div>
                    <span className={`pill ${r.correct ? 'strong' : 'missing'}`} style={{ flexShrink: 0 }}>{r.correct ? 'Correct' : 'Incorrect'}</span>
                  </div>
                  {q.type === 'multiple_choice'
                    ? q.options.map((opt: string) => (
                        <div key={opt} className={`mc-option read-only ${opt === q.answer ? 'is-answer' : ''} ${opt === r.answer ? 'is-taken' : ''}`}>
                          <span className="radio" /> {opt}{opt === q.answer ? ' ✓ correct' : ''}
                        </div>
                      ))
                    : <div className="free-text read-only">Your answer: {(r.answer as string) || '(empty)'}</div>}
                  <div className="q-expl"><IconTrophy size={14} /> {q.explanation}</div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="verify-item" data-skill-id={gap.skill_id}>
      <span className={`verify-icon ${categoryToneFor(gap.category)}`}>
        <IconAssessment size={17} />
      </span>
      <div className="verify-text">
        <h4>{gap.skill_name}</h4>
        <div className="verify-meta">
          <span>Required <strong>{gap.required_level}</strong></span>
          {lastAttempt && (
            <>
              <span aria-hidden="true">·</span>
              <span>Last score <strong>{lastAttempt.score}%</strong></span>
            </>
          )}
        </div>
      </div>
      {lastAttempt && (
        <div className="verify-lastscore">
          <div className="progress-track on-light">
            <div className="progress-fill" style={{ width: `${lastAttempt.score}%`, background: scoreBandColor(lastAttempt.score) }} />
          </div>
          <div className="verify-lastscore-pct" style={{ color: scoreBandColor(lastAttempt.score) }}>{lastAttempt.score}%</div>
        </div>
      )}
      <div className="verify-actions">
        {lastAttempt && (
          <button className="btn btn-sm" onClick={() => start(true)}><IconTrophy size={14} /> Practice</button>
        )}
        <button className="btn btn-primary btn-sm" onClick={() => start(false)}><IconAssessment size={14} /> Start assessment</button>
      </div>
    </div>
  )
}
