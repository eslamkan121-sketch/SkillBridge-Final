// Webcam integrity MVP frontend source-contract guard.
// The real webcam/model APIs are mocked or unavailable in most CI runs, so this
// pins the privacy, lifecycle, threshold, and assessment-flow contracts to the
// actual source files.

import { readProject } from './path-helpers.mjs'
import ts from 'typescript'

const read = readProject

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const assessments = read('frontend/src/pages/AssessmentsPage.tsx')
const webcam = read('frontend/src/lib/webcamIntegrity.ts')
const api = read('frontend/src/lib/api.ts')
const css = read('frontend/src/index.css')

async function loadWebcamIntegrityModule() {
  const compiled = ts.transpileModule(webcam, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText
  return import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
}

function activeSample(overrides = {}) {
  return {
    personCount: 1,
    phonePresent: false,
    phoneConfidence: 0,
    attentionAway: false,
    attentionConfidence: 0,
    trackActive: true,
    ...overrides,
  }
}

function eventTypes(update) {
  return update.events.map((event) => event.event_type)
}

// Consent / permission: Start Assessment opens a notice; getUserMedia lives only
// in the enable-camera path and requests video without audio.
ok(/camera_notice/.test(assessments), 'AssessmentsPage: camera notice mode exists before assessment start')
ok(/Camera integrity notice/.test(assessments), 'AssessmentsPage: explicit camera notice is rendered')
ok(/Enable Camera/.test(assessments), 'AssessmentsPage: Enable Camera action is rendered')
ok(/Cancel/.test(assessments), 'AssessmentsPage: camera notice/pre-check can be cancelled')
ok(/setMode\('camera_notice'\)/.test(assessments), 'AssessmentsPage: real Start Assessment first opens the camera notice')
ok(/onClick=\{\(\) => void startCameraPrecheck\(\)\}/.test(assessments), 'AssessmentsPage: permission request is behind Enable Camera')
ok(/navigator\.mediaDevices\.getUserMedia\(\{ video: true, audio: false \}\)/.test(assessments),
   'AssessmentsPage: getUserMedia requests camera video only, no audio')

// Pre-check: local preview, active track, exactly one person, two-second stable gate.
ok(/<video ref=\{videoRef\} className="camera-preview" muted playsInline autoPlay/.test(assessments),
   'AssessmentsPage: camera pre-check shows a local preview')
ok(/CameraPrecheckTracker/.test(assessments), 'AssessmentsPage: pre-check uses the tracker')
ok(/precheck\.ready/.test(assessments), 'AssessmentsPage: Start Assessment is gated on pre-check readiness')
ok(/disabled=\{!precheck\.ready \|\| cameraLoading \|\| !detectorReady\}/.test(assessments),
   'AssessmentsPage: Start Assessment button stays disabled until camera and detector are ready')
ok(/precheckStableMs: 2000/.test(webcam), 'webcamIntegrity: one-person pre-check requires a 2s stable window')
ok(/personStatus === 'one'/.test(webcam), 'webcamIntegrity: pre-check requires exactly one visible person')
ok(/isVideoTrackActive\(cameraStream\)/.test(assessments), 'AssessmentsPage: active camera track is required before starting')

// Browser-local detection: bundled COCO-SSD, person count and phone class only.
ok(/@tensorflow-models\/coco-ssd/.test(webcam), 'webcamIntegrity: uses local COCO-SSD object detection')
ok(/@tensorflow\/tfjs/.test(webcam), 'webcamIntegrity: uses TensorFlow.js in-browser runtime')
ok(/normalizedObjectClass\(p\.class\) === 'person'/.test(webcam), 'webcamIntegrity: detects person count locally')
ok(/isPhoneClass\(p\.class\)/.test(webcam),
   'webcamIntegrity: detects the phone class locally when reliable')
ok(/personConfidence: 0\.5/.test(webcam), 'webcamIntegrity: person detection uses the conservative physical-runtime threshold')
ok(/phoneConfidence: 0\.5/.test(webcam), 'webcamIntegrity: phone detection uses the conservative physical-runtime threshold')
ok(/@tensorflow-models\/face-landmarks-detection/.test(webcam),
   'webcamIntegrity: uses local face landmarks for soft head-direction checks')
ok(!/face-api|recognition|embedding/i.test(webcam.replace(/face_embedding/g, '')),
   'webcamIntegrity: no identity matching or embeddings are used')
ok(!/openai|anthropic|nvidia/i.test(webcam), 'webcamIntegrity: webcam frames are never sent to GenAI APIs')
ok(/video\.videoWidth <= 0 \|\| video\.videoHeight <= 0/.test(webcam),
   'webcamIntegrity: detector waits for non-zero live video dimensions')
ok(/skillbridge_camera_debug/.test(webcam) && /console\.debug/.test(webcam) && /bbox/.test(webcam),
   'webcamIntegrity: gated runtime debug logs expose class, confidence, bbox, timestamp only')

// Exam monitoring thresholds and dedupe/cooldown.
ok(/inferenceCadenceMs: 500/.test(webcam), 'webcamIntegrity: inference runs at a modest cadence')
ok(/warningSubjectMissingMs: 3000/.test(webcam), 'webcamIntegrity: brief no-person misses are ignored')
ok(/eventSubjectMissingMs: 10000/.test(webcam), 'webcamIntegrity: sustained no-person incident threshold is 10s')
ok(/warningMultiplePeopleMs: 3000/.test(webcam), 'webcamIntegrity: brief multiple-person detections are ignored')
ok(/eventMultiplePeopleMs: 8000/.test(webcam), 'webcamIntegrity: sustained multiple-person threshold is 8s')
ok(/eventPhoneDetectedMs: 5000/.test(webcam), 'webcamIntegrity: sustained phone threshold is 5s')
ok(/warningAttentionAwayMs: 4000/.test(webcam), 'webcamIntegrity: brief attention-away is ignored')
ok(/eventAttentionAwayMs: 14000/.test(webcam), 'webcamIntegrity: sustained attention-away creates a soft event')
ok(/camera_disabled: !active/.test(webcam), 'webcamIntegrity: stopped camera track creates camera_disabled')
ok(/attention_away: active && sample\.personCount === 1 && sample\.attentionAway === true/.test(webcam),
   'webcamIntegrity: attention-away is tracked only for one visible person')
ok(/state\.emitted/.test(webcam), 'webcamIntegrity: one continuous incident emits once')
ok(/eventCooldownMs: 30000/.test(webcam), 'webcamIntegrity: repeated incidents observe a cooldown')
ok(/detectionGraceMs: 1000/.test(webcam), 'webcamIntegrity: detector flicker has a small grace window')
ok(/shouldKeepIncidentWarm/.test(webcam), 'webcamIntegrity: sustained incident timers survive brief detector misses')
ok(/lastEmittedAt/.test(webcam), 'webcamIntegrity: cooldown state is tracked')
ok(/HARD_TERMINATION_EVENT_TYPES/.test(webcam) && /camera_subject_missing/.test(webcam) && /phone_detected/.test(webcam),
   'webcamIntegrity: hard termination event set is explicit')
ok(/SOFT_INTEGRITY_EVENT_TYPES/.test(webcam) && /attention_away/.test(webcam),
   'webcamIntegrity: attention-away is explicitly soft')

// Metadata-only backend integration and pagehide reliability.
ok(/assessmentIntegrityEvent/.test(api), 'api.ts: camera event endpoint is exposed')
ok(/assessments\/integrity-events/.test(api), 'api.ts: camera event endpoint path exists')
ok(/camera_events: cameraEventsRef\.current/.test(assessments), 'AssessmentsPage: submit/finalize include metadata fallback')
ok(/api\.assessmentIntegrityEvent/.test(assessments), 'AssessmentsPage: camera incidents post metadata during the exam')
ok(/external_token: token/.test(assessments), 'AssessmentsPage: event posts include the active attempt token')
ok(/sendBeacon/.test(assessments), 'AssessmentsPage: pagehide finalize still uses sendBeacon')
ok(/pagehide/.test(assessments), 'AssessmentsPage: pagehide finalization remains wired')
ok(/tabSwitches/.test(assessments), 'AssessmentsPage: existing tab-switch integrity still exists')
ok(!/CHEATING DETECTED/i.test(assessments), 'AssessmentsPage: no cheating verdict is shown from camera predictions')
ok(/terminateAssessmentForIntegrity/.test(assessments), 'AssessmentsPage: hard-stop finalization helper exists')
ok(/document\.visibilityState === 'hidden'/.test(assessments) && /browser_hidden/.test(assessments),
   'AssessmentsPage: visibility hidden hard-finalizes the assessment')
ok(/window\.addEventListener\('blur', onBlur\)/.test(assessments) && /window_blur/.test(assessments),
   'AssessmentsPage: window blur hard-finalizes the assessment')
ok(/fullscreenchange/.test(assessments) && /fullscreen_exit/.test(assessments),
   'AssessmentsPage: fullscreen exit hard-finalizes the assessment')
ok(/update\.events\.find\(isHardTerminationEvent\)/.test(assessments),
   'AssessmentsPage: hard camera incidents finalize immediately')
ok(/termination_event: terminationEvent/.test(assessments),
   'AssessmentsPage: finalize payload includes the hard termination event')

// Lifecycle cleanup.
ok(/getTracks\(\)\.forEach\(\(track\) => track\.stop\(\)\)/.test(assessments),
   'AssessmentsPage: every MediaStreamTrack is stopped')
ok(/detectorRef\.current\.dispose/.test(assessments), 'AssessmentsPage: local detector is disposed')
ok(/stopCamera\(\)/.test(assessments), 'AssessmentsPage: camera cleanup is called from assessment exits')
ok(/cancelCameraFlow/.test(assessments), 'AssessmentsPage: cancel path stops camera before returning')
ok(/document\.exitFullscreen/.test(assessments), 'AssessmentsPage: intentional cleanup exits fullscreen safely')

// Result UX: score and integrity status are separate.
ok(/Assessment<\/span>/.test(assessments), 'AssessmentsPage: result shows Assessment status')
ok(/Integrity<\/span>/.test(assessments), 'AssessmentsPage: result shows Integrity status')
ok(/Review recommended/.test(assessments), 'AssessmentsPage: camera flags surface review recommendation')
ok(/Review required/.test(assessments), 'AssessmentsPage: hard integrity events surface review required')
ok(/Assessment ended because an integrity rule was violated/.test(assessments),
   'AssessmentsPage: hard-stop result explains that an integrity rule ended the assessment')
ok(/terminationReason/.test(assessments), 'AssessmentsPage: hard-stop result shows the exact reason')
ok(/Camera metadata only/.test(assessments), 'AssessmentsPage: flag UI describes camera metadata-only evidence')
ok(/assessment-result-status/.test(css), 'index.css: separate assessment/integrity result styles exist')
ok(/integrity-ended-panel/.test(css), 'index.css: hard-stop reason panel styles exist')
ok(/camera-monitor-pill/.test(css), 'index.css: unobtrusive camera indicator styles exist')
ok(/camera-precheck-grid/.test(css), 'index.css: camera pre-check layout exists')

// Permission failure messaging.
for (const name of ['NotAllowedError', 'NotFoundError', 'NotReadableError']) {
  ok(new RegExp(name).test(webcam), `webcamIntegrity: ${name} has a clear message`)
}
ok(/Try Camera Again/.test(assessments), 'AssessmentsPage: permission failure offers Try Camera Again')

// Executable timer checks for the privacy-preserving state machines. These use
// mocked detection samples only: no webcam, images, or frame pixels.
try {
  const runtime = await loadWebcamIntegrityModule()
  const {
    CameraIncidentTracker,
    CameraPrecheckTracker,
    isHardTerminationEvent,
    isVideoTrackActive,
  } = runtime

  {
    const tracker = new CameraPrecheckTracker()
    ok(tracker.update(activeSample(), 1000).ready === false,
      'webcamIntegrity runtime: pre-check is not immediately ready')
    ok(tracker.update(activeSample(), 2999).ready === false,
      'webcamIntegrity runtime: pre-check waits for the full stable window')
    ok(tracker.update(activeSample(), 3000).ready === true,
      'webcamIntegrity runtime: pre-check passes after 2s of one visible person')
    ok(tracker.update(activeSample({ personCount: 2 }), 3500).ready === false,
      'webcamIntegrity runtime: pre-check resets when multiple people appear')
  }

  {
    const tracker = new CameraIncidentTracker()
    ok(eventTypes(tracker.update(activeSample(), 30000)).length === 0,
      'webcamIntegrity runtime: one person does not emit camera events during a normal interval')
  }

  {
    const tracker = new CameraIncidentTracker()
    ok(eventTypes(tracker.update(activeSample({ personCount: 0 }), 0)).length === 0,
      'webcamIntegrity runtime: no-person does not fire on first frame')
    ok(eventTypes(tracker.update(activeSample({ personCount: 0 }), 2500)).length === 0,
      'webcamIntegrity runtime: brief no-person under 3s does not fire')
    ok(tracker.update(activeSample({ personCount: 0 }), 3000).warning.includes('visible'),
      'webcamIntegrity runtime: no-person warning appears around 3s')
    ok(eventTypes(tracker.update(activeSample({ personCount: 0 }), 9999)).length === 0,
      'webcamIntegrity runtime: no-person does not hard-stop before 10s')
    const event = tracker.update(activeSample({ personCount: 0 }), 10000).events[0]
    ok(event?.event_type === 'camera_subject_missing' && event.duration_ms === 10000 && isHardTerminationEvent(event),
      'webcamIntegrity runtime: sustained no-person hard-stops at 10s')
    ok(eventTypes(tracker.update(activeSample({ personCount: 0 }), 10500)).length === 0,
      'webcamIntegrity runtime: one sustained no-person incident emits once')
  }

  {
    const tracker = new CameraIncidentTracker()
    tracker.update(activeSample({ personCount: 0 }), 0)
    tracker.update(activeSample({ personCount: 0 }), 2500)
    tracker.update(activeSample(), 2600)
    tracker.update(activeSample(), 3701)
    ok(eventTypes(tracker.update(activeSample({ personCount: 0 }), 12000)).length === 0,
      'webcamIntegrity runtime: no-person timer resets after the person returns')
  }

  {
    const tracker = new CameraIncidentTracker()
    ok(eventTypes(tracker.update(activeSample({ personCount: 2 }), 0)).length === 0,
      'webcamIntegrity runtime: multiple-people does not fire on first frame')
    ok(eventTypes(tracker.update(activeSample({ personCount: 2 }), 2500)).length === 0,
      'webcamIntegrity runtime: second person under 3s does not hard-stop')
    ok(tracker.update(activeSample({ personCount: 2 }), 3000).warning.includes('Multiple people'),
      'webcamIntegrity runtime: multiple-people warning appears around 3s')
    ok(eventTypes(tracker.update(activeSample({ personCount: 2 }), 7999)).length === 0,
      'webcamIntegrity runtime: multiple-people does not hard-stop before 8s')
    const event = tracker.update(activeSample({ personCount: 2 }), 8000).events[0]
    ok(event?.event_type === 'multiple_people' && event.duration_ms === 8000 && isHardTerminationEvent(event),
      'webcamIntegrity runtime: sustained multiple-people hard-stops at 8s')
    ok(eventTypes(tracker.update(activeSample({ personCount: 2 }), 8500)).length === 0,
      'webcamIntegrity runtime: one sustained multiple-people incident emits once')
  }

  {
    const tracker = new CameraIncidentTracker()
    tracker.update(activeSample({ personCount: 2 }), 0)
    tracker.update(activeSample({ personCount: 2 }), 7000)
    tracker.update(activeSample(), 7500)
    ok(eventTypes(tracker.update(activeSample({ personCount: 2 }), 7900)).length === 0,
      'webcamIntegrity runtime: one missed multiple-people frame does not hard-stop by itself')
    const event = tracker.update(activeSample({ personCount: 2 }), 8200).events[0]
    ok(event?.event_type === 'multiple_people' && event.duration_ms === 8200,
      'webcamIntegrity runtime: multiple-people timer survives a brief missed inference frame')
  }

  {
    const tracker = new CameraIncidentTracker()
    tracker.update(activeSample({ personCount: 2 }), 0)
    tracker.update(activeSample({ personCount: 2 }), 4000)
    tracker.update(activeSample(), 5000)
    tracker.update(activeSample(), 6101)
    tracker.update(activeSample({ personCount: 2 }), 10000)
    ok(eventTypes(tracker.update(activeSample({ personCount: 2 }), 17999)).length === 0,
      'webcamIntegrity runtime: multiple-people timer resets after returning to one person')
    ok(tracker.update(activeSample({ personCount: 2 }), 18000).events[0]?.event_type === 'multiple_people',
      'webcamIntegrity runtime: multiple-people timer survives inference cycles after reset')
  }

  {
    const tracker = new CameraIncidentTracker()
    tracker.update(activeSample({ phonePresent: true, phoneConfidence: 0.49 }), 0)
    ok(eventTypes(tracker.update(activeSample({ phonePresent: true, phoneConfidence: 0.49 }), 6000)).length === 0,
      'webcamIntegrity runtime: phone confidence below threshold does not accumulate')
    tracker.reset()
    ok(eventTypes(tracker.update(activeSample({ phonePresent: true, phoneConfidence: 0.8 }), 0)).length === 0,
      'webcamIntegrity runtime: one-frame phone detection does not hard-stop')
    ok(eventTypes(tracker.update(activeSample({ phonePresent: true, phoneConfidence: 0.8 }), 4999)).length === 0,
      'webcamIntegrity runtime: brief phone detection under 5s does not hard-stop')
    const event = tracker.update(activeSample({ phonePresent: true, phoneConfidence: 0.8 }), 5000).events[0]
    ok(event?.event_type === 'phone_detected' && event.duration_ms === 5000 && event.confidence === 0.8 && isHardTerminationEvent(event),
      'webcamIntegrity runtime: sustained phone detection hard-stops at 5s')
  }

  {
    const tracker = new CameraIncidentTracker()
    tracker.update(activeSample({ phonePresent: true, phoneConfidence: 0.7 }), 0)
    tracker.update(activeSample({ phonePresent: true, phoneConfidence: 0.7 }), 3500)
    ok(eventTypes(tracker.update(activeSample({ phonePresent: false, phoneConfidence: 0 }), 4000)).length === 0,
      'webcamIntegrity runtime: one missed phone frame does not hard-stop by itself')
    ok(eventTypes(tracker.update(activeSample({ phonePresent: true, phoneConfidence: 0.7 }), 4800)).length === 0,
      'webcamIntegrity runtime: phone detection continues after a brief missed frame')
    const event = tracker.update(activeSample({ phonePresent: true, phoneConfidence: 0.7 }), 5200).events[0]
    ok(event?.event_type === 'phone_detected' && event.duration_ms === 5200,
      'webcamIntegrity runtime: phone timer survives a brief missed inference frame')
  }

  {
    const tracker = new CameraIncidentTracker()
    tracker.update(activeSample({ phonePresent: true, phoneConfidence: 0.7 }), 0)
    tracker.update(activeSample({ phonePresent: false, phoneConfidence: 0 }), 2000)
    tracker.update(activeSample({ phonePresent: false, phoneConfidence: 0 }), 3101)
    tracker.update(activeSample({ phonePresent: true, phoneConfidence: 0.7 }), 6000)
    ok(eventTypes(tracker.update(activeSample({ phonePresent: true, phoneConfidence: 0.7 }), 10999)).length === 0,
      'webcamIntegrity runtime: long phone absence resets sustained timer')
    ok(tracker.update(activeSample({ phonePresent: true, phoneConfidence: 0.7 }), 11000).events[0]?.event_type === 'phone_detected',
      'webcamIntegrity runtime: phone can emit after a fresh sustained interval')
  }

  {
    const tracker = new CameraIncidentTracker()
    tracker.update(activeSample({ attentionAway: true, attentionConfidence: 0.72 }), 0)
    const event = tracker.update(activeSample({ attentionAway: true, attentionConfidence: 0.72 }), 14000).events[0]
    ok(event?.event_type === 'attention_away' && event.severity === 'warning' && !isHardTerminationEvent(event),
      'webcamIntegrity runtime: attention-away remains a soft event')
  }

  {
    const tracker = new CameraIncidentTracker()
    const event = tracker.update(activeSample({ trackActive: false }), 0).events[0]
    ok(event?.event_type === 'camera_disabled' && isHardTerminationEvent(event),
      'webcamIntegrity runtime: inactive camera track hard-stops immediately')
  }

  ok(isVideoTrackActive({ getVideoTracks: () => [{ readyState: 'live', enabled: true }] }) === true,
    'webcamIntegrity runtime: live enabled track is active')
  ok(isVideoTrackActive({ getVideoTracks: () => [{ readyState: 'ended', enabled: true }] }) === false,
    'webcamIntegrity runtime: ended track is inactive')
  ok(isVideoTrackActive({ getVideoTracks: () => [{ readyState: 'live', enabled: false }] }) === false,
    'webcamIntegrity runtime: disabled track is inactive')
} catch (err) {
  problems.push(`webcamIntegrity runtime: executable timer checks failed to run: ${err?.stack || err}`)
}

if (problems.length) {
  console.error('Webcam integrity frontend contract violations:')
  for (const p of problems) console.error(`  - ${p}`)
  process.exit(1)
}
console.log('Webcam integrity frontend contracts OK')
