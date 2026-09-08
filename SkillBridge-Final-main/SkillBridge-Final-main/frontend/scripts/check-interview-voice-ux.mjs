// Mock Interview voice-first UX guard. This inspects the real frontend sources
// without making ElevenLabs calls, so it can run safely in the backend suite.

import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')
const read = (p) => readFileSync(resolve(root, p), 'utf8')

const problems = []
const ok = (cond, msg) => { if (!cond) problems.push(msg) }

const panel = read('frontend/src/components/CopilotPanel.tsx')
const speech = read('frontend/src/hooks/useBrowserSpeech.ts')
const api = read('frontend/src/lib/api.ts')
const i18n = read('frontend/src/lib/tutorI18n.ts')
const appContext = read('frontend/src/AppContext.tsx')
const backendMain = read('backend/app/main.py')
const css = read('frontend/src/index.css')

const normalComposerCount = (panel.match(/className="tutor-input copilot-input"/g) || []).length
ok(normalComposerCount === 1,
   'Interview: active interview must not render the normal text composer by default')
ok(/copilot-interview-primary/.test(panel) && /ui\.startAnswer/.test(panel),
   'Interview: microphone is the primary answer control')
ok(/kind: 'answer'.*text, turn/.test(panel),
   'Interview: speech transcript is written as a Student interview message')
ok(/startListening\(\(text\) => \{[\s\S]*void submitInterviewTranscript\(text\)/.test(panel),
   'Interview: final speech transcript is submitted automatically')
ok(/kind: 'feedback' as const, text: feedback/.test(panel),
   'Interview: avatar responses are written into the transcript')
ok(/autoSpeakInterview\(`i-\$\{item\.id\}`,\s*feedback\)/.test(panel) &&
   /autoSpeakInterview\(`i-\$\{item\.id\}`,\s*first\)/.test(panel),
   'Interview: avatar questions and feedback trigger automatic TTS')
ok(/api\.interviewTts\(studentId, tutorId, text\)/.test(panel),
   'Interview: selected tutorId is passed to interview TTS')
ok(/interviewThreads/.test(panel) && /Record<TutorId, InterviewItem\[\]>/.test(panel) &&
   /disabled=\{interviewLocked\}/.test(panel) && !/Use Vex|Vex \(recommended\)|\(recommended\)/.test(panel),
   'Interview: tutor switching preserves the selected avatar voice/persona and never forces Vex')
ok(/const finishInterview = \(\) => \{[\s\S]*speech\.stopListening\(\)[\s\S]*stopSpeak\(\)[\s\S]*endInterview\(\)/.test(panel),
   'Interview: End Interview stops listening and audio')
ok(/setMode\(prevModeRef\.current === 'interview' \? 'chat' : prevModeRef\.current\)/.test(panel) &&
   /const leaveInterview = \(\) => \{[\s\S]*resetInterview\(\)/.test(panel),
   'Interview: Return to Chat exits completed interview state, including Vex default mode')
ok(/speech\.error/.test(panel) && /typedFallbackOpen/.test(panel) && /ui\.typeAnswerInstead/.test(panel),
   'Interview: speech failure exposes the Type answer instead fallback')
ok(/speech\.startListening\([\s\S]*interviewLang/.test(panel) &&
   /recognition\.lang = lang === 'ar' \? 'ar-EG' : 'en-US'/.test(speech),
   'Interview: Arabic recognition uses ar-EG and English recognition uses en-US')
ok(/if \(busy \|\| assessmentActive \|\| !studentId\) return/.test(panel) &&
   /if \(!studentId \|\| assessmentActive\) return/.test(panel) &&
   /get_active_assessment\(student_id\)/.test(backendMain) &&
   /api_interview_tts/.test(backendMain),
   'Interview: assessment lock still blocks Interview/TTS')
ok(/api\.tutorTts\(studentId, tutorId, text\)/.test(panel) &&
   /api\.tutorSend/.test(panel) &&
   /onClick=\{\(\) => toggleMic\('chat'\)\}/.test(panel) &&
   normalComposerCount === 1,
   'Chat: normal Copilot text input and manual TTS behavior remain unchanged')
ok(/interviewer_speaking/.test(panel) && /student_ready/.test(panel) &&
   /student_listening/.test(panel) && /processing/.test(panel),
   'Interview: explicit voice state machine exists')
ok(/copilot-interview-turn/.test(css) && /copilot-interview-typing/.test(css),
   'Interview: voice-first controls and fallback input are styled')

for (const key of [
  'interviewerSpeaking', 'yourTurn', 'startAnswer', 'tapToAnswer', 'listening',
  'stopAnswer', 'thinking', 'processingAnswer', 'liveTranscript',
  'typeAnswerInstead', 'typedAnswerPlaceholder', 'submitTypedAnswer', 'stopAudio',
]) {
  ok(new RegExp(`\\b${key}:`).test(i18n), `tutorI18n: "${key}" string defined`)
}

ok(/const pinned: 'en' \| 'ar' = language === 'ar' \? 'ar' : language === 'en' \? 'en' : 'en'/.test(appContext),
   'Language: interview language pinning remains on the existing architecture')

if (problems.length) {
  console.error('Mock Interview voice UX contract violations:')
  for (const p of problems) console.error(`  - ${p}`)
  process.exit(1)
}

console.log('Mock Interview voice UX contracts OK')
