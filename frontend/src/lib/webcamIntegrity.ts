export type CameraIntegrityEventType =
  | 'camera_disabled'
  | 'camera_subject_missing'
  | 'multiple_people'
  | 'phone_detected'
  | 'attention_away'

export type BrowserIntegrityEventType =
  | 'tab_switch'
  | 'browser_hidden'
  | 'window_blur'
  | 'fullscreen_exit'

export type AssessmentIntegrityEventType = CameraIntegrityEventType | BrowserIntegrityEventType

export interface AssessmentIntegrityEvent {
  event_type: AssessmentIntegrityEventType
  duration_ms: number
  occurred_at: string
  severity: 'info' | 'warning' | 'high'
  incident_id: string
  confidence?: number
}

export type CameraIntegrityEvent = AssessmentIntegrityEvent

export interface WebcamDetectionSample {
  personCount: number
  phonePresent: boolean
  phoneConfidence: number
  attentionAway?: boolean
  attentionConfidence?: number
  trackActive: boolean
}

export interface WebcamDetector {
  detect(video: HTMLVideoElement): Promise<WebcamDetectionSample>
  dispose?: () => void
}

export interface CameraPrecheckState {
  cameraStatus: 'working' | 'problem'
  personStatus: 'one' | 'none' | 'multiple'
  ready: boolean
  stableMs: number
  message: string
}

type IncidentState = {
  activeSince: number | null
  lastObservedAt: number | null
  emitted: boolean
  lastEmittedAt: number
  incidentId: string
}

export const CAMERA_INTEGRITY_THRESHOLDS = {
  precheckStableMs: 2000,
  inferenceCadenceMs: 500,
  warningSubjectMissingMs: 3000,
  eventSubjectMissingMs: 10000,
  warningMultiplePeopleMs: 3000,
  eventMultiplePeopleMs: 8000,
  eventPhoneDetectedMs: 5000,
  warningAttentionAwayMs: 4000,
  eventAttentionAwayMs: 14000,
  eventCooldownMs: 30000,
  detectionGraceMs: 1000,
  personConfidence: 0.5,
  phoneConfidence: 0.5,
}

export const HARD_TERMINATION_EVENT_TYPES: AssessmentIntegrityEventType[] = [
  'tab_switch',
  'browser_hidden',
  'window_blur',
  'fullscreen_exit',
  'camera_disabled',
  'camera_subject_missing',
  'multiple_people',
  'phone_detected',
]

export const SOFT_INTEGRITY_EVENT_TYPES: AssessmentIntegrityEventType[] = ['attention_away']

const EVENT_THRESHOLDS: Record<CameraIntegrityEventType, { warningMs: number; eventMs: number }> = {
  camera_disabled: { warningMs: 0, eventMs: 0 },
  camera_subject_missing: {
    warningMs: CAMERA_INTEGRITY_THRESHOLDS.warningSubjectMissingMs,
    eventMs: CAMERA_INTEGRITY_THRESHOLDS.eventSubjectMissingMs,
  },
  multiple_people: {
    warningMs: CAMERA_INTEGRITY_THRESHOLDS.warningMultiplePeopleMs,
    eventMs: CAMERA_INTEGRITY_THRESHOLDS.eventMultiplePeopleMs,
  },
  phone_detected: {
    warningMs: CAMERA_INTEGRITY_THRESHOLDS.eventPhoneDetectedMs,
    eventMs: CAMERA_INTEGRITY_THRESHOLDS.eventPhoneDetectedMs,
  },
  attention_away: {
    warningMs: CAMERA_INTEGRITY_THRESHOLDS.warningAttentionAwayMs,
    eventMs: CAMERA_INTEGRITY_THRESHOLDS.eventAttentionAwayMs,
  },
}

const WARNING_TEXT: Record<CameraIntegrityEventType, string> = {
  camera_disabled: 'Camera connection lost. Re-enable your camera to continue.',
  camera_subject_missing: 'Please remain visible during the assessment.',
  multiple_people: 'Multiple people detected. Please ensure you are the only person in view.',
  phone_detected: 'Phone detected. Please remove it from view during the assessment.',
  attention_away: 'Please keep your attention on the assessment.',
}

export const INTEGRITY_REASON_TEXT: Record<AssessmentIntegrityEventType, string> = {
  tab_switch: 'The assessment window lost focus.',
  browser_hidden: 'The assessment browser tab was hidden.',
  window_blur: 'The assessment window lost focus.',
  fullscreen_exit: 'Fullscreen assessment mode was exited.',
  camera_disabled: 'Camera connection was lost during the assessment.',
  camera_subject_missing: 'No person was visible for more than 10 seconds.',
  multiple_people: 'Multiple people were visible for more than 8 seconds.',
  phone_detected: 'Phone detected during assessment.',
  attention_away: 'Attention appeared away from the assessment for a sustained period.',
}

function makeIncidentId(type: CameraIntegrityEventType, nowMs: number) {
  return `${type}-${Math.floor(nowMs)}-${Math.random().toString(36).slice(2, 8)}`
}

function emptyState(): IncidentState {
  return { activeSince: null, lastObservedAt: null, emitted: false, lastEmittedAt: -Infinity, incidentId: '' }
}

function resetIncidentState(state: IncidentState) {
  state.activeSince = null
  state.lastObservedAt = null
  state.emitted = false
  state.incidentId = ''
}

function shouldKeepIncidentWarm(type: CameraIntegrityEventType, state: IncidentState, nowMs: number) {
  if (type === 'camera_disabled') return false
  if (state.activeSince === null || state.lastObservedAt === null) return false
  return nowMs - state.lastObservedAt <= CAMERA_INTEGRITY_THRESHOLDS.detectionGraceMs
}

export class CameraPrecheckTracker {
  private stableSince: number | null = null

  reset() {
    this.stableSince = null
  }

  update(sample: WebcamDetectionSample, nowMs = Date.now()): CameraPrecheckState {
    const working = sample.trackActive
    const personStatus: CameraPrecheckState['personStatus'] =
      !working || sample.personCount === 0 ? 'none' : sample.personCount > 1 ? 'multiple' : 'one'

    if (working && personStatus === 'one') {
      if (this.stableSince === null) this.stableSince = nowMs
    } else {
      this.stableSince = null
    }

    const stableMs = this.stableSince === null ? 0 : nowMs - this.stableSince
    const ready = working && personStatus === 'one' && stableMs >= CAMERA_INTEGRITY_THRESHOLDS.precheckStableMs
    const message = !working
      ? 'Camera problem detected.'
      : personStatus === 'one'
        ? ready ? 'One person visible.' : 'Hold still for a moment.'
        : personStatus === 'multiple'
          ? 'Multiple people visible.'
          : 'No person detected.'

    return {
      cameraStatus: working ? 'working' : 'problem',
      personStatus,
      ready,
      stableMs,
      message,
    }
  }
}

export class CameraIncidentTracker {
  private states: Record<CameraIntegrityEventType, IncidentState> = {
    camera_disabled: emptyState(),
    camera_subject_missing: emptyState(),
    multiple_people: emptyState(),
    phone_detected: emptyState(),
    attention_away: emptyState(),
  }

  reset() {
    this.states = {
      camera_disabled: emptyState(),
      camera_subject_missing: emptyState(),
      multiple_people: emptyState(),
      phone_detected: emptyState(),
      attention_away: emptyState(),
    }
  }

  update(sample: WebcamDetectionSample, nowMs = Date.now()): { warning: string; events: CameraIntegrityEvent[] } {
    const active = sample.trackActive
    const phonePresent = sample.phonePresent && sample.phoneConfidence >= CAMERA_INTEGRITY_THRESHOLDS.phoneConfidence
    const conditions: Record<CameraIntegrityEventType, boolean> = {
      camera_disabled: !active,
      camera_subject_missing: active && sample.personCount === 0,
      multiple_people: active && sample.personCount > 1,
      phone_detected: active && phonePresent,
      attention_away: active && sample.personCount === 1 && sample.attentionAway === true,
    }
    const warnings: string[] = []
    const events: CameraIntegrityEvent[] = []

    ;(['camera_disabled', 'camera_subject_missing', 'multiple_people', 'phone_detected', 'attention_away'] as CameraIntegrityEventType[])
      .forEach((type) => {
        const state = this.states[type]
        if (!conditions[type]) {
          if (shouldKeepIncidentWarm(type, state, nowMs)) return
          resetIncidentState(state)
          return
        }
        if (state.activeSince === null) {
          state.activeSince = nowMs
          state.incidentId = makeIncidentId(type, nowMs)
        }
        state.lastObservedAt = nowMs
        const durationMs = nowMs - state.activeSince
        const limits = EVENT_THRESHOLDS[type]
        if (durationMs >= limits.warningMs) warnings.push(WARNING_TEXT[type])
        const cooldownReady = nowMs - state.lastEmittedAt >= CAMERA_INTEGRITY_THRESHOLDS.eventCooldownMs
        if (!state.emitted && durationMs >= limits.eventMs && cooldownReady) {
          state.emitted = true
          state.lastEmittedAt = nowMs
          events.push({
            event_type: type,
            duration_ms: Math.max(0, Math.round(durationMs)),
            occurred_at: new Date(state.activeSince).toISOString(),
            severity: isHardTerminationEventType(type) ? 'high' : 'warning',
            incident_id: state.incidentId,
            ...(type === 'phone_detected' ? { confidence: Number(sample.phoneConfidence.toFixed(3)) } : {}),
            ...(type === 'attention_away' && sample.attentionConfidence !== undefined
              ? { confidence: Number(sample.attentionConfidence.toFixed(3)) }
              : {}),
          })
        }
      })

    return { warning: warnings[0] || '', events }
  }
}

export function isHardTerminationEventType(type: AssessmentIntegrityEventType): boolean {
  return HARD_TERMINATION_EVENT_TYPES.includes(type)
}

export function isHardTerminationEvent(event: AssessmentIntegrityEvent): boolean {
  return isHardTerminationEventType(event.event_type)
}

export function integrityReasonText(type: AssessmentIntegrityEventType): string {
  return INTEGRITY_REASON_TEXT[type] || 'An assessment integrity rule was violated.'
}

export function isVideoTrackActive(stream: MediaStream | null): boolean {
  const track = stream?.getVideoTracks()[0]
  return !!track && track.readyState === 'live' && track.enabled !== false
}

export function cameraErrorMessage(error: unknown): string {
  if (!navigator.mediaDevices?.getUserMedia) {
    return 'Camera access is not supported in this browser.'
  }
  const name = (error as DOMException | undefined)?.name || ''
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return 'Camera permission was denied. Camera monitoring is required for the Final Assessment.'
  }
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
    return 'No camera was found on this device.'
  }
  if (name === 'NotReadableError' || name === 'TrackStartError') {
    return 'The camera is already in use or could not be started.'
  }
  return 'The camera could not be started. Check the device and try again.'
}

function blankDetectionSample(trackActive = false): WebcamDetectionSample {
  return {
    personCount: 0,
    phonePresent: false,
    phoneConfidence: 0,
    attentionAway: false,
    attentionConfidence: 0,
    trackActive,
  }
}

function cameraDebugEnabled(): boolean {
  try {
    return window.localStorage.getItem('skillbridge_camera_debug') === '1'
  } catch {
    return false
  }
}

function debugDetections(predictions: Array<{ class: string; score: number; bbox?: number[] }>, video: HTMLVideoElement) {
  if (!cameraDebugEnabled()) return
  console.debug('[SkillBridge camera detection]', {
    timestamp: new Date().toISOString(),
    videoWidth: video.videoWidth,
    videoHeight: video.videoHeight,
    predictions: predictions.map((p) => ({
      class: p.class,
      confidence: Number(p.score.toFixed(3)),
      bbox: Array.isArray(p.bbox) ? p.bbox.map((n) => Number(n.toFixed(1))) : [],
    })),
  })
}

type LandmarkPoint = { x: number; y: number; z?: number }

function normalizedObjectClass(value: string) {
  return String(value || '').trim().toLowerCase()
}

function isPhoneClass(value: string) {
  const cls = normalizedObjectClass(value)
  return cls === 'cell phone' || cls === 'mobile phone'
}

function point(keypoints: LandmarkPoint[] | undefined, index: number): LandmarkPoint | null {
  const p = keypoints?.[index]
  return p && Number.isFinite(p.x) && Number.isFinite(p.y) ? p : null
}

function estimateAttentionAway(faces: Array<{ keypoints?: LandmarkPoint[] }>, personCount: number) {
  if (personCount !== 1) return { attentionAway: false, attentionConfidence: 0 }
  const keypoints = faces[0]?.keypoints
  if (!keypoints?.length) return { attentionAway: true, attentionConfidence: 0.6 }

  const nose = point(keypoints, 1)
  const chin = point(keypoints, 152)
  const leftCheek = point(keypoints, 234)
  const rightCheek = point(keypoints, 454)
  const leftEye = point(keypoints, 33)
  const rightEye = point(keypoints, 263)
  if (!nose || !chin || !leftCheek || !rightCheek || !leftEye || !rightEye) {
    return { attentionAway: true, attentionConfidence: 0.55 }
  }

  const faceWidth = Math.max(1, Math.abs(rightCheek.x - leftCheek.x))
  const faceCenterX = (leftCheek.x + rightCheek.x) / 2
  const yawFromCenter = Math.abs(nose.x - faceCenterX) / faceWidth
  const eyeY = (leftEye.y + rightEye.y) / 2
  const faceHeight = Math.max(1, Math.abs(chin.y - eyeY))
  const noseDownRatio = (nose.y - eyeY) / faceHeight
  const turnedAway = yawFromCenter > 0.18
  const lookingDown = noseDownRatio > 0.58
  const confidence = Math.min(0.95, Math.max(
    turnedAway ? yawFromCenter / 0.32 : 0,
    lookingDown ? (noseDownRatio - 0.45) / 0.25 : 0,
  ))

  return {
    attentionAway: turnedAway || lookingDown,
    attentionConfidence: Number(Math.max(0, confidence).toFixed(3)),
  }
}

export async function createCocoSsdWebcamDetector(): Promise<WebcamDetector> {
  await import('@tensorflow/tfjs')
  const cocoSsd = await import('@tensorflow-models/coco-ssd')
  const faceLandmarks = await import('@tensorflow-models/face-landmarks-detection')
  const model = await cocoSsd.load({ base: 'lite_mobilenet_v2' })
  const attentionDetector = await faceLandmarks.createDetector(
    faceLandmarks.SupportedModels.MediaPipeFaceMesh,
    { runtime: 'tfjs', refineLandmarks: false, maxFaces: 1 },
  )
  return {
    async detect(video: HTMLVideoElement): Promise<WebcamDetectionSample> {
      if (!video || video.readyState < 2 || video.videoWidth <= 0 || video.videoHeight <= 0) {
        return blankDetectionSample(false)
      }
      const predictions = await model.detect(video)
      debugDetections(predictions, video)
      const people = predictions.filter((p) => (
        normalizedObjectClass(p.class) === 'person' && p.score >= CAMERA_INTEGRITY_THRESHOLDS.personConfidence
      ))
      const phoneConfidence = predictions
        .filter((p) => (
          isPhoneClass(p.class) && p.score >= CAMERA_INTEGRITY_THRESHOLDS.phoneConfidence
        ))
        .reduce((max, p) => Math.max(max, p.score), 0)
      let attention = { attentionAway: false, attentionConfidence: 0 }
      try {
        const faces = await attentionDetector.estimateFaces(video, { flipHorizontal: false })
        attention = estimateAttentionAway(faces as Array<{ keypoints?: LandmarkPoint[] }>, people.length)
      } catch {
        attention = { attentionAway: false, attentionConfidence: 0 }
      }
      return {
        personCount: people.length,
        phonePresent: phoneConfidence >= CAMERA_INTEGRITY_THRESHOLDS.phoneConfidence,
        phoneConfidence,
        ...attention,
        trackActive: true,
      }
    },
    dispose() {
      const disposable = model as unknown as { dispose?: () => void }
      if (typeof disposable.dispose === 'function') disposable.dispose()
      const attentionDisposable = attentionDetector as unknown as { dispose?: () => void }
      if (typeof attentionDisposable.dispose === 'function') attentionDisposable.dispose()
    },
  }
}
