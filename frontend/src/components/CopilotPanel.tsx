import React, { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import { useApp } from '../AppContext'
import { api } from '../lib/api'
import type { LearningItem, TutorMessage, TutorMode } from '../lib/types'
import { TUTOR_PROFILES, TutorAbout } from './learning'
import type { TutorId } from '../lib/tutorProfiles'
import { effectiveLanguage, LANGUAGE_LABELS, LANGUAGE_SHORT, quickActionsFor, TUTOR_LANGUAGES, tutorUi } from '../lib/tutorI18n'
import { useBrowserSpeech } from '../hooks/useBrowserSpeech'
import { IconBack, IconBackRTL, IconChat, IconChevron, IconCollapse, IconExpand, IconLock, IconMic, IconPlus, IconSend, IconSendRTL, IconStop, IconTrash, IconTutor, IconVolume } from './Icons'

function SafeMarkdown({ children }: { children: React.ReactNode }) {
  return <Markdown>{String(children ?? '')}</Markdown>
}

const ARABIC_RE = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]/
function messageDir(text: string): 'rtl' | 'ltr' {
  const ar = (text.match(ARABIC_RE) || []).length
  const en = (text.match(/[A-Za-z]/g) || []).length
  return ar > 0 && ar >= en ? 'rtl' : 'ltr'
}

const PAGE_LABELS: Record<string, string> = {
  dashboard: 'Your dashboard',
  skills_roles: 'Skills & Roles',
  learning: 'Your learning path',
  scenarios: 'Your practice scenarios',
  jobs: 'Job matching',
  career_roadmap: 'Your career roadmap',
  assessment: 'Assessment',
}

interface InterviewItem {
  id: number
  kind: 'question' | 'answer' | 'feedback'
  text: string
  turn: number
}

type InterviewVoiceState = 'interviewer_speaking' | 'student_ready' | 'student_listening' | 'processing'

export function CopilotPanel() {
  const { session, copilot, tutorId, mode, setMode, language, setLanguage, assessmentActive, interview, startInterview, sendInterviewAnswer, endInterview, resetInterview } = useApp()
  const studentId = session?.student?.id ?? 0
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)
  // One conversation per tutor: switching tutor swaps the whole thread, and a
  // New Chat clears only the current tutor's thread.
  const [chats, setChats] = useState<Partial<Record<TutorId, TutorMessage[]>>>({})
  const [interviewThreads, setInterviewThreads] = useState<Partial<Record<TutorId, InterviewItem[]>>>({})
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [items, setItems] = useState<LearningItem[]>([])
  const [interviewInput, setInterviewInput] = useState('')
  const [interviewError, setInterviewError] = useState('')
  const [aboutOpen, setAboutOpen] = useState(false)
  const [confirmAction, setConfirmAction] = useState<null | 'newchat' | 'clear'>(null)
  const [lastReply, setLastReply] = useState<'en' | 'ar' | null>(null)
  const [speakingKey, setSpeakingKey] = useState<string | null>(null)
  const [speakBusy, setSpeakBusy] = useState(false)
  const [voiceNote, setVoiceNote] = useState('')
  const [micTarget, setMicTarget] = useState<'chat' | 'interview'>('chat')
  const [interviewVoiceState, setInterviewVoiceState] = useState<InterviewVoiceState>('student_ready')
  const [typedFallbackOpen, setTypedFallbackOpen] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const nextId = useRef(0)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const urlRef = useRef<string | null>(null)
  const audioRequestRef = useRef(0)
  const interviewCancelledRef = useRef(false)
  // The tutor's working mode before an interview, restored by "Return to Chat".
  const prevModeRef = useRef<TutorMode>('chat')
  const speech = useBrowserSpeech()

  const tutor = TUTOR_PROFILES.find((t) => t.id === tutorId) || TUTOR_PROFILES[0]
  const lang = effectiveLanguage(language, lastReply)
  const ui = tutorUi(lang)
  const greetingText = ui.greeting.replace('{name}', tutor.name).replace('{purpose}', tutor.purpose)
  const interviewLang: 'en' | 'ar' = interview.language === 'ar' ? 'ar' : 'en'
  const selectedInterviewLang: 'en' | 'ar' = language === 'ar' ? 'ar' : 'en'

  useEffect(() => {
    if (!studentId) return
    api.learning(studentId)
      .then(setItems)
      .catch((e) => { console.error('[copilot] learning items failed:', e) })
  }, [studentId])

  // Load the selected tutor's own conversation (cached per tutor for instant
  // switch-back; the backend stays the source of truth).
  useEffect(() => {
    if (!studentId) return
    if (chats[tutorId]) return
    api.tutorHistory(studentId, tutorId)
      .then((rows) => setChats((c) => ({ ...c, [tutorId]: rows })))
      .catch((e) => { console.error('[copilot] tutor history failed:', e) })
  }, [studentId, tutorId, chats])

  useEffect(() => {
    const onFocus = () => setOpen(true)
    window.addEventListener('copilot:focus', onFocus)
    return () => window.removeEventListener('copilot:focus', onFocus)
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [chats, busy, interviewThreads, tutorId])

  useEffect(() => () => {
    if (audioRef.current) { audioRef.current.pause(); audioRef.current = null }
    if (urlRef.current) { URL.revokeObjectURL(urlRef.current); urlRef.current = null }
    speech.stopListening()
  }, [speech.stopListening])

  const messages = chats[tutorId] ?? []
  const interviewItems = interviewThreads[tutorId] ?? []
  const interviewLocked = interview.phase === 'starting' || interview.phase === 'active'

  const skillName = items.find((item) => item.skill_id === copilot.skillId)?.skill_name
  const topicName = copilot.competency || skillName || 'your current topic'

  const quickActions = quickActionsFor(lang, tutorId, mode, topicName)

  const localMessage = (role: 'user' | 'assistant', content: string, skillId: number | null): TutorMessage =>
    ({ id: ++nextId.current, role, content, skill_id: skillId, tutor_id: tutorId, created_at: '' })

  const appendChat = (tid: TutorId, msg: TutorMessage) =>
    setChats((prev) => ({ ...prev, [tid]: [...(prev[tid] ?? []), msg] }))

  const appendInterview = (tid: TutorId, item: InterviewItem) =>
    setInterviewThreads((prev) => ({ ...prev, [tid]: [...(prev[tid] ?? []), item] }))

  const stopSpeak = () => {
    audioRequestRef.current += 1
    if (audioRef.current) { audioRef.current.pause(); audioRef.current = null }
    if (urlRef.current) { URL.revokeObjectURL(urlRef.current); urlRef.current = null }
    setSpeakingKey(null)
    setSpeakBusy(false)
    setVoiceNote('')
  }

  const toggleSpeak = async (key: string, text: string, surface: 'chat' | 'interview' = 'chat') => {
    if (!studentId || assessmentActive) return
    if (speakingKey === key) {
      stopSpeak()
      if (surface === 'interview') setInterviewVoiceState('student_ready')
      return
    }
    stopSpeak()
    const requestId = audioRequestRef.current + 1
    audioRequestRef.current = requestId
    setSpeakBusy(true)
    if (surface === 'interview') {
      speech.stopListening()
      setMicTarget('interview')
      setInterviewVoiceState('interviewer_speaking')
    }
    try {
      const blob = surface === 'interview'
        ? await api.interviewTts(studentId, tutorId, text)
        : await api.tutorTts(studentId, tutorId, text)
      if (audioRequestRef.current !== requestId) return
      if (surface === 'interview' && interviewCancelledRef.current) {
        setSpeakBusy(false)
        setInterviewVoiceState('student_ready')
        return
      }
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.muted = false
      audioRef.current = audio
      urlRef.current = url
      const finish = () => {
        if (audioRequestRef.current !== requestId) return
        if (audioRef.current === audio) audioRef.current = null
        if (urlRef.current === url) urlRef.current = null
        URL.revokeObjectURL(url)
        setSpeakingKey((k) => (k === key ? null : k))
        setSpeakBusy(false)
        if (surface === 'interview') setInterviewVoiceState('student_ready')
      }
      audio.onended = finish
      audio.onerror = finish
      await audio.play()
      if (audioRequestRef.current !== requestId) return
      setSpeakingKey(key)
    } catch {
      if (audioRequestRef.current !== requestId) return
      // Avatar TTS failed (quota/API key/voice id/timeout) — keep the reply
      // text fully usable and tell the student the voice is unavailable. Never
      // fall back to a generic browser voice for a tutor avatar.
      if (urlRef.current) { URL.revokeObjectURL(urlRef.current); urlRef.current = null }
      audioRef.current = null
      setSpeakingKey(null)
      setSpeakBusy(false)
      if (surface === 'interview') setInterviewVoiceState('student_ready')
      setVoiceNote(ui.voiceUnavailable)
    }
  }

  const autoSpeakInterview = (key: string, text: string) => {
    void toggleSpeak(key, text, 'interview')
  }

  const send = async (e?: React.FormEvent, preset?: string) => {
    e?.preventDefault()
    const text = (preset ?? input).trim()
    if (!text || busy || assessmentActive || !studentId) return
    setInput('')
    appendChat(tutorId, localMessage('user', text, copilot.skillId))
    setBusy(true)
    try {
      const res = await api.tutorSend(studentId, text, {
        skillId: copilot.skillId,
        page: copilot.page,
        competency: copilot.competency,
        jobTitle: copilot.jobTitle,
        jobUrl: copilot.jobUrl,
        tutorId,
        mode,
        language,
      })
      setLastReply(res.language === 'ar' ? 'ar' : 'en')
      const replyText = res.reply ?? res.content
      appendChat(tutorId, { id: res.id, role: 'assistant', content: replyText, skill_id: res.skill_id ?? copilot.skillId, tutor_id: tutorId, created_at: res.created_at })
    } catch (err) {
      const detail = (err as Error)?.message?.trim()
      appendChat(tutorId, localMessage('assistant', detail && !detail.startsWith('Request failed') ? detail : '(Tutor unavailable — is the backend running?)', copilot.skillId))
    } finally {
      setBusy(false)
    }
  }

  const contextTitle = PAGE_LABELS[copilot.page] || 'Your learning'
  const barSubtitle = assessmentActive
    ? ui.lockedTitle
    : `${tutor.origin} · ${tutor.specialty}`

  const beginInterview = async () => {
    if (busy || assessmentActive || !studentId) return
    setInterviewError('')
    setConfirmAction(null)
    setAboutOpen(false)
    setInterviewInput('')
    setTypedFallbackOpen(false)
    setVoiceNote('')
    setMicTarget('interview')
    setInterviewVoiceState('processing')
    interviewCancelledRef.current = false
    speech.stopListening()
    stopSpeak()
    prevModeRef.current = mode
    if (mode !== 'interview') setMode('interview')
    setInterviewThreads((t) => ({ ...t, [tutorId]: [] }))
    setExpanded(true)
    setBusy(true)
    try {
      const first = await startInterview(copilot.skillId)
      setLastReply(selectedInterviewLang)
      if (first) {
        const item = { id: ++nextId.current, kind: 'question' as const, text: first, turn: 1 }
        appendInterview(tutorId, item)
        autoSpeakInterview(`i-${item.id}`, first)
      } else {
        setInterviewVoiceState('student_ready')
      }
    } catch (err) {
      const detail = (err as Error)?.message?.trim()
      setInterviewError(`Could not start the interview. ${detail && !detail.startsWith('Request failed') ? detail : 'Is the backend running?'}`)
      setExpanded(false)
      setInterviewVoiceState('student_ready')
      resetInterview()
    } finally {
      setBusy(false)
    }
  }

  const submitInterviewTranscript = async (answerText: string) => {
    const text = answerText.trim()
    if (!text || busy || assessmentActive || interview.phase !== 'active') return
    const turn = interview.turn
    setInterviewInput('')
    setTypedFallbackOpen(false)
    setInterviewVoiceState('processing')
    speech.stopListening()
    appendInterview(tutorId, { id: ++nextId.current, kind: 'answer', text, turn })
    setBusy(true)
    try {
      const feedback = await sendInterviewAnswer(text)
      if (feedback && !interviewCancelledRef.current) {
        const item = { id: ++nextId.current, kind: 'feedback' as const, text: feedback, turn }
        appendInterview(tutorId, item)
        autoSpeakInterview(`i-${item.id}`, feedback)
      } else if (!interviewCancelledRef.current) {
        setInterviewVoiceState('student_ready')
      }
    } catch (err) {
      const detail = (err as Error)?.message?.trim()
      if (!interviewCancelledRef.current) {
        appendInterview(tutorId, { id: ++nextId.current, kind: 'feedback', text: detail && !detail.startsWith('Request failed') ? `(reply failed: ${detail})` : '(reply failed — is the backend running?)', turn })
        setInterviewVoiceState('student_ready')
      }
    } finally {
      setBusy(false)
    }
  }

  const submitInterviewAnswer = async () => {
    await submitInterviewTranscript(interviewInput)
  }

  const finishInterview = () => {
    interviewCancelledRef.current = true
    speech.stopListening()
    stopSpeak()
    setInterviewVoiceState('student_ready')
    setTypedFallbackOpen(false)
    if (interview.phase === 'active' || interview.phase === 'starting') endInterview()
    // Restore the tutor's working mode exactly like Return to Chat, so a
    // message sent after ending the interview stays a normal chat and can
    // never ride a leftover 'interview' mode into the /tutor payload.
    setMode(prevModeRef.current === 'interview' ? 'chat' : prevModeRef.current)
  }

  const leaveInterview = () => {
    interviewCancelledRef.current = true
    speech.stopListening()
    stopSpeak()
    setInterviewVoiceState('student_ready')
    setTypedFallbackOpen(false)
    // Restore the tutor's previous working mode and collapse the expanded overlay.
    setMode(prevModeRef.current === 'interview' ? 'chat' : prevModeRef.current)
    setExpanded(false)
    setAboutOpen(false)
    setConfirmAction(null)
    resetInterview()
  }

  const clearCurrentConversation = async () => {
    if (!studentId || busy || interviewLocked) return
    setAboutOpen(false)
    setConfirmAction(null)
    try {
      await api.clearTutorChat(studentId, tutorId)
    } catch (e) { console.error('[copilot] clear chat failed:', e) }
    setChats((c) => ({ ...c, [tutorId]: [] }))
    setInterviewThreads((t) => ({ ...t, [tutorId]: [] }))
    setInput('')
    setInterviewInput('')
    setTypedFallbackOpen(false)
    setInterviewVoiceState('student_ready')
    speech.stopListening()
    stopSpeak()
    setLastReply(null)
    resetInterview()
  }

  const cancelConfirm = () => setConfirmAction(null)

  const interviewRunning = mode === 'interview' && interview.phase !== 'idle'
  // Every avatar offers a Mock Interview as its primary action when idle.
  const interviewCtaVisible = interview.phase === 'idle'
  const activeInterviewListening = speech.listening && micTarget === 'interview'
  const interviewTextFallbackAvailable = !speech.recognitionSupported || (micTarget === 'interview' && !!speech.error) || typedFallbackOpen
  const interviewPrimaryDisabled = assessmentActive || busy || !studentId || interview.phase !== 'active' ||
    interviewVoiceState === 'interviewer_speaking' ||
    (!speech.recognitionSupported && !activeInterviewListening)
  const interviewStatusTitle =
    interviewVoiceState === 'interviewer_speaking'
      ? ui.interviewerSpeaking.replace('{name}', tutor.name)
      : interviewVoiceState === 'student_listening'
        ? ui.listening
        : interviewVoiceState === 'processing'
          ? ui.thinking
          : ui.yourTurn
  const interviewStatusBody =
    interviewVoiceState === 'interviewer_speaking'
      ? ui.interviewerSpeakingBody
      : interviewVoiceState === 'student_listening'
        ? (speech.interimTranscript || ui.liveTranscript)
        : interviewVoiceState === 'processing'
          ? ui.processingAnswer.replace('{name}', tutor.name)
          : ui.studentReadyBody

  useEffect(() => {
    if (micTarget === 'interview' && speech.error && interview.phase === 'active') {
      setInterviewVoiceState((state) => state === 'student_listening' ? 'student_ready' : state)
    }
  }, [interview.phase, micTarget, speech.error])

  const toggleInterviewMic = () => {
    if (assessmentActive || busy || !studentId || interview.phase !== 'active') return
    setMicTarget('interview')
    if (activeInterviewListening) {
      speech.stopListening()
      setInterviewVoiceState('student_ready')
      return
    }
    if (!speech.recognitionSupported) return
    setVoiceNote('')
    setTypedFallbackOpen(false)
    setInterviewInput('')
    stopSpeak()
    setInterviewVoiceState('student_listening')
    let submitted = false
    speech.startListening((text) => {
      submitted = true
      setInterviewInput(text)
      void submitInterviewTranscript(text)
    }, interviewLang, () => {
      if (!submitted) {
        setInterviewVoiceState((state) => state === 'student_listening' ? 'student_ready' : state)
      }
    })
  }

  // One shared browser-speech hook for BOTH surfaces. Normal chat keeps its
  // review-then-Send composer; Mock Interview sends the final speech transcript
  // automatically through the turn-taking flow above.
  const toggleMic = (target: 'chat' | 'interview' = 'chat') => {
    if (target === 'interview') {
      toggleInterviewMic()
      return
    }
    setMicTarget(target)
    if (speech.listening) { speech.stopListening(); return }
    speech.startListening((text) => setInput((prev) => (prev ? `${prev} ${text}` : text)), lang)
  }

  return (
    <div className={`copilot-panel ${tutor.theme} ${open ? 'copilot-open' : 'copilot-closed'} ${expanded ? 'copilot-expanded' : ''}`}>
      <div className="copilot-bar">
        <button className="copilot-bar-main" onClick={() => setOpen(!open)} aria-expanded={open} aria-label="AI Tutor panel">
          <img className="copilot-avatar" src={tutor.avatar} alt={tutor.name} />
          <span className="copilot-bar-copy">
            <strong>{tutor.name} · {ui.copilotBar}</strong>
            <small>{barSubtitle}</small>
          </span>
          <IconChevron size={16} className={`copilot-chev ${open ? 'open' : ''}`} />
        </button>
        <button
          type="button"
          className="copilot-expand"
          onClick={() => { setExpanded((e) => !e); if (!open) setOpen(true) }}
          aria-label={expanded ? ui.collapse : ui.expand}
          title={expanded ? ui.collapse : ui.expand}
        >
          {expanded ? <IconCollapse size={16} /> : <IconExpand size={16} />}
        </button>
      </div>

      {open && (
        <div className="copilot-body" dir={lang === 'ar' ? 'rtl' : 'ltr'}>
          <div className="copilot-context">
            <IconChat size={13} /> {ui.talkingAbout} <strong>{topicName}</strong> — {contextTitle}
          </div>

          <div className="copilot-toolbar">
            <div className="copilot-lang" role="group" aria-label={ui.languages}>
              {TUTOR_LANGUAGES.map((l) => (
                <button
                  key={l}
                  type="button"
                  className={`copilot-lang-opt ${language === l ? 'selected' : ''}`}
                  disabled={assessmentActive || interviewLocked}
                  onClick={() => setLanguage(l)}
                  aria-pressed={language === l}
                  title={LANGUAGE_LABELS[l]}
                >
                  {LANGUAGE_SHORT[l]}
                </button>
              ))}
            </div>
          </div>

          {/* Normal chat shows ONLY the currently selected mentor. The other
              mentors appear only in the dedicated change-mentor UI
              (account menu → Change your copilot). */ }
          <div className="copilot-tutors">
            <div className="copilot-current-row">
              <img className="copilot-current-avatar" src={tutor.avatar} alt={tutor.name} />
              <div className="copilot-current">
                <strong>{tutor.name} · {ui.copilotBar}</strong>
                <small>{tutor.origin} · {tutor.specialty}</small>
                <small className="copilot-current-traits">{tutor.traits.slice(0, 3).join(' • ')}</small>
              </div>
            </div>
          </div>

          <div className="copilot-actions">
            <button
              type="button"
              className="copilot-about-toggle"
              onClick={() => setAboutOpen((o) => !o)}
              aria-expanded={aboutOpen}
              aria-label={ui.profileToggle(aboutOpen, tutor.name)}
            >
              <IconTutor size={13} /> {ui.profile}
            </button>
            <button
              type="button"
              className="copilot-new-chat"
              onClick={() => setConfirmAction('newchat')}
              disabled={busy || interviewLocked || !studentId}
              title={ui.newChat}
            >
              <IconPlus size={13} /> {ui.newChat}
            </button>
            <button
              type="button"
              className="copilot-clear-chat"
              onClick={() => setConfirmAction('clear')}
              disabled={busy || interviewLocked || !studentId}
              title={ui.clearChat}
            >
              <IconTrash size={13} /> {ui.clearChat}
            </button>
          </div>

          {confirmAction && (
            <div className="copilot-confirm" role="alertdialog" aria-label={ui.clearChatConfirm.replace('{name}', tutor.name)}>
              <span className="copilot-confirm-copy">
                {confirmAction === 'clear'
                  ? ui.clearChatConfirm.replace('{name}', tutor.name)
                  : ui.newChatConfirm.replace('{name}', tutor.name)}
              </span>
              <span className="copilot-confirm-actions">
                <button type="button" className="btn btn-sm" onClick={cancelConfirm} disabled={busy}>{ui.cancel}</button>
                <button type="button" className="btn btn-sm copilot-confirm-clear" onClick={() => void clearCurrentConversation()} disabled={busy}>
                  {ui.clear}
                </button>
              </span>
            </div>
          )}

          {interviewLocked && (
            <div className="copilot-pin-note" title={ui.pinnedTitle}>
              <IconLock size={13} /> {ui.interviewPinned.replace('{name}', tutor.name)}
            </div>
          )}

          {aboutOpen && (
            <div className="copilot-about-wrap">
              <div className="copilot-about-back">
                <button type="button" onClick={() => setAboutOpen(false)}>
                  {lang === 'ar' ? <IconBackRTL size={14} /> : <IconBack size={14} />} {ui.backToChat}
                </button>
              </div>
              <TutorAbout tutor={tutor} />
            </div>
          )}

          {assessmentActive ? (
            <div className="copilot-locked">
              <IconLock size={16} />
              <span>{ui.lockedBody}</span>
            </div>
          ) : (
            <>
              {interviewCtaVisible && (
                <div className="copilot-interview-hero">
                  <div className="copilot-interview-hero-copy">
                    <strong>{ui.mockInterviewTitle}</strong>
                    <span>{ui.mockInterviewDesc} {topicName} {ui.forYourRole}</span>
                  </div>
                  {interviewError && <div className="copilot-interview-error">{interviewError}</div>}
                  <div className="copilot-interview-hero-actions">
                    <button className="btn btn-primary copilot-interview-start" disabled={busy} onClick={() => void beginInterview()}>
                      <IconMic size={14} /> {ui.startMockInterview}
                    </button>
                  </div>
                </div>
              )}

              {interviewRunning ? (
                <>
                  <div className="tutor-messages copilot-messages" ref={scrollRef}>
                    {interview.phase === 'starting' && (
                      <div className="msg assistant" dir={messageDir(ui.startingInterview)}>
                        <div className="md-body"><em>{ui.startingInterview}</em></div>
                      </div>
                    )}
                    {interviewItems.map((item) => (
                      <div key={item.id} className={`msg ${item.kind === 'answer' ? 'user' : 'assistant'} copilot-interview`} dir={messageDir(item.text)}>
                        <span className={`copilot-interview-tag ${item.kind}`}>
                          {item.kind === 'question' ? ui.questionTag : item.kind === 'answer' ? ui.youTag : ui.feedbackTag}
                        </span>
                        <div className="md-body">
                          {item.kind === 'answer' ? item.text : <SafeMarkdown>{item.text}</SafeMarkdown>}
                        </div>
                        {(item.kind === 'question' || item.kind === 'feedback') && (
                          <button
                            type="button"
                            className="copilot-msg-voice"
                            onClick={() => void toggleSpeak(`i-${item.id}`, item.text, 'interview')}
                            disabled={assessmentActive || speakBusy || !studentId}
                            aria-label={ui.voiceAria}
                          >
                            {speakingKey === `i-${item.id}` ? <IconStop size={13} /> : <IconVolume size={13} />}
                          </button>
                        )}
                      </div>
                    ))}
                    {busy && <div className="msg assistant">...</div>}
                  </div>
                  {voiceNote && <div className="copilot-mic-note copilot-voice-note">{voiceNote}</div>}

                  {interview.phase === 'active' && (
                    <div className={`copilot-interview-turn ${interviewVoiceState}`} aria-live="polite">
                      <div className="copilot-interview-state">
                        <span className="copilot-interview-state-icon">
                          {interviewVoiceState === 'interviewer_speaking'
                            ? <IconVolume size={18} />
                            : interviewVoiceState === 'processing'
                              ? <IconChat size={18} />
                              : activeInterviewListening
                                ? <IconStop size={18} />
                                : <IconMic size={18} />}
                        </span>
                        <span className="copilot-interview-state-copy">
                          <strong>{interviewStatusTitle}</strong>
                          <small>{interviewStatusBody}</small>
                        </span>
                      </div>
                      <button
                        type="button"
                        className="copilot-interview-primary"
                        onClick={() => toggleMic('interview')}
                        aria-label={activeInterviewListening ? ui.stopAnswer : ui.startAnswer}
                        title={activeInterviewListening ? ui.stopAnswer : ui.startAnswer}
                        disabled={interviewPrimaryDisabled}
                      >
                        {activeInterviewListening ? <IconStop size={24} /> : <IconMic size={24} />}
                        <span>{activeInterviewListening ? ui.listening : ui.startAnswer}</span>
                        <small>{activeInterviewListening ? ui.stopAnswer : ui.tapToAnswer}</small>
                      </button>
                      {interviewVoiceState === 'interviewer_speaking' && (
                        <button
                          type="button"
                          className="copilot-interview-stop-audio"
                          onClick={() => { stopSpeak(); setInterviewVoiceState('student_ready') }}
                        >
                          <IconStop size={13} /> {ui.stopAudio}
                        </button>
                      )}
                      {(activeInterviewListening || speech.error) && micTarget === 'interview' && (
                        <div className="copilot-mic-note">
                          {activeInterviewListening ? (speech.interimTranscript || ui.listening) : speech.error}
                        </div>
                      )}
                      {interviewTextFallbackAvailable && !typedFallbackOpen && (
                        <button
                          type="button"
                          className="copilot-interview-type-fallback"
                          onClick={() => { speech.stopListening(); setTypedFallbackOpen(true); setInterviewVoiceState('student_ready') }}
                        >
                          {ui.typeAnswerInstead}
                        </button>
                      )}
                      {typedFallbackOpen && (
                        <form className="copilot-interview-typing" onSubmit={(e) => { e.preventDefault(); void submitInterviewAnswer() }}>
                          <input
                            value={interviewInput}
                            onChange={(e) => setInterviewInput(e.target.value)}
                            placeholder={ui.typedAnswerPlaceholder}
                            dir="auto"
                            aria-label={ui.submitTypedAnswer}
                          />
                          <button type="submit" className="btn btn-primary" disabled={busy || !interviewInput.trim() || !studentId} aria-label={ui.submitTypedAnswer}>
                            {lang === 'ar' ? <IconSendRTL size={15} /> : <IconSend size={15} />}
                          </button>
                        </form>
                      )}
                    </div>
                  )}

                  {(interview.phase === 'active' || interview.phase === 'starting') && (
                    <button className="copilot-interview-end" onClick={finishInterview}>
                      {ui.endInterview}
                    </button>
                  )}

                  {interview.phase === 'completed' && (
                    <div className="copilot-interview-done">
                      <strong>{ui.interviewComplete}</strong>
                      <span>{ui.interviewCompleteBody.replace('{name}', tutor.name)}</span>
                      <div className="copilot-interview-done-actions">
                        <button className="btn btn-primary" disabled={busy} onClick={() => void beginInterview()}>{ui.newInterview}</button>
                        <button className="btn" onClick={leaveInterview}>{ui.returnToChat}</button>
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <>
                  <div className="tutor-messages copilot-messages" ref={scrollRef}>
                    {messages.length === 0 && (
                      <div className="msg assistant" dir={messageDir(greetingText)}>
                        <div className="md-body">
                          {greetingText}
                        </div>
                      </div>
                    )}
                    {messages.map((message) => (
                      <div key={message.id} className={`msg ${message.role}`} dir={messageDir(message.content)}>
                        <div className="md-body">
                          {message.role === 'assistant' ? <SafeMarkdown>{message.content}</SafeMarkdown> : message.content}
                        </div>
                        {message.role === 'assistant' && (
                          <button
                            type="button"
                            className="copilot-msg-voice"
                            onClick={() => void toggleSpeak(`m-${message.id}`, message.content)}
                            disabled={assessmentActive || speakBusy || !studentId}
                            aria-label={ui.voiceAria}
                          >
                            {speakingKey === `m-${message.id}` ? <IconStop size={13} /> : <IconVolume size={13} />}
                          </button>
                        )}
                      </div>
                    ))}
                    {busy && <div className="msg assistant">...</div>}
                  </div>

                  <div className="copilot-quickactions">
                    {quickActions.map((action) => (
                      <button key={action.label} className="quick-action" disabled={busy} onClick={() => void send(undefined, action.prompt)}>
                        {action.label}
                      </button>
                    ))}
                  </div>

                  <form className="tutor-input copilot-input" onSubmit={(e) => void send(e)}>
                    <input
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      placeholder={ui.askPlaceholder.replace('{name}', tutor.name)}
                      dir="auto"
                      aria-label={ui.sendAria}
                    />
                    <button
                      type="button"
                      className="copilot-mic"
                      onClick={() => toggleMic('chat')}
                      aria-label={speech.listening && micTarget === 'chat' ? ui.micListeningAria : ui.micAria}
                      title={speech.listening && micTarget === 'chat' ? ui.micListeningAria : ui.micAria}
                      disabled={assessmentActive || busy || !studentId}
                    >
                      {speech.listening && micTarget === 'chat' ? <IconStop size={15} /> : <IconMic size={15} />}
                    </button>
                    <button type="submit" className="btn btn-primary" disabled={busy || !input.trim() || !studentId} aria-label={ui.sendAria}>
                      {lang === 'ar' ? <IconSendRTL size={15} /> : <IconSend size={15} />}
                    </button>
                  </form>
                  {(speech.listening || speech.error) && micTarget === 'chat' && (
                    <div className="copilot-mic-note">
                      {speech.listening ? (speech.interimTranscript || ui.micListeningAria) : speech.error}
                    </div>
                  )}
                  {voiceNote && <div className="copilot-mic-note copilot-voice-note">{voiceNote}</div>}
                </>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
