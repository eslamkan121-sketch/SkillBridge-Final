import React, { useCallback, useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import { useApp } from '../AppContext'
import { api } from '../lib/api'
import type { LearningItem, TutorConversation, TutorMessage, TutorMode } from '../lib/types'
import { TUTOR_PROFILES, TutorAbout } from './learning'
import type { TutorId } from '../lib/tutorProfiles'
import { effectiveLanguage, LANGUAGE_LABELS, LANGUAGE_SHORT, quickActionsFor, TUTOR_LANGUAGES, tutorUi } from '../lib/tutorI18n'
import { useBrowserSpeech } from '../hooks/useBrowserSpeech'
import { resolveInitialLiveLang, useVoiceSession } from '../hooks/useVoiceSession'
import { VoiceMode } from './VoiceMode'
import { PersonaMenu } from './PersonaMenu'
import { MoreMenu } from './MoreMenu'
import { ChatThread } from './ChatThread'
import { SuggestionGrid } from './SuggestionGrid'
import { Composer } from './Composer'
import { IconBack, IconBackRTL, IconBook, IconChat, IconCheck, IconChevron, IconClock, IconCollapse, IconCopy, IconDots, IconExpand, IconHeadset, IconLightbulb, IconLock, IconMic, IconPlus, IconSendUp, IconShield, IconSparkles, IconStop, IconVolume, IconClipboard, IconWaveform } from './Icons'
import { type ResponseRating } from './ResponseActions'

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

function conversationStamp(value?: string | null) {
  if (!value) return ''
  const date = new Date(String(value).replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

interface InterviewItem {
  id: number
  kind: 'question' | 'answer' | 'feedback'
  text: string
  turn: number
}

type InterviewVoiceState = 'interviewer_speaking' | 'student_ready' | 'student_listening' | 'processing'

export function CopilotPanel() {
  const { session, copilot, tutorId, setTutorId, mode, setMode, language, setLanguage, assessmentActive, interview, startInterview, sendInterviewAnswer, endInterview, resetInterview } = useApp()
  const studentId = session?.student?.id ?? 0
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [conversations, setConversations] = useState<TutorConversation[]>([])
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null)
  const [chats, setChats] = useState<Record<number, TutorMessage[]>>({})
  const [interviewThreads, setInterviewThreads] = useState<Partial<Record<TutorId, InterviewItem[]>>>({})
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [items, setItems] = useState<LearningItem[]>([])
  const [interviewInput, setInterviewInput] = useState('')
  const [interviewError, setInterviewError] = useState('')
  const [aboutOpen, setAboutOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [toolsOpen, setToolsOpen] = useState(false)
  const [clearModalOpen, setClearModalOpen] = useState(false)
  const [lastReply, setLastReply] = useState<'en' | 'ar' | null>(null)
  const [speakingKey, setSpeakingKey] = useState<string | null>(null)
  const [speakBusy, setSpeakBusy] = useState(false)
  const [voiceNote, setVoiceNote] = useState('')
  const [micTarget, setMicTarget] = useState<'chat' | 'interview'>('chat')
  const [interviewVoiceState, setInterviewVoiceState] = useState<InterviewVoiceState>('student_ready')
  const [typedFallbackOpen, setTypedFallbackOpen] = useState(false)
  const [voiceOpen, setVoiceOpen] = useState(false)
  // Explicit Live speech language (EN | Arabic). Live Voice has NO Auto mode:
  // resolved to an explicit locale when Live opens (see startLiveVoice) and then
  // switched mid-session only through the in-surface EN | عربي selector.
  const [voiceLang, setVoiceLang] = useState<'en' | 'ar'>('en')
  const [copiedKey, setCopiedKey] = useState<string | null>(null)
  const [ratings, setRatings] = useState<Record<string, ResponseRating | null | undefined>>({})
  const [retryingKey, setRetryingKey] = useState<string | null>(null)
  const shareDisabled = typeof navigator === 'undefined' || !('share' in navigator)
  const scrollRef = useRef<HTMLDivElement>(null)
  const interviewScrollRef = useRef<HTMLDivElement>(null)
  const nextId = useRef(0)
  const activeConversationIdRef = useRef<number | null>(null)
  const clearCancelRef = useRef<HTMLButtonElement>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const urlRef = useRef<string | null>(null)
  const audioRequestRef = useRef(0)
  const interviewCancelledRef = useRef(false)
  // Chat dictation state: transcript is typed into the composer (never opens
  // the live VoiceMode orb — that is the separate Live/waveform button).
  const dictatingRef = useRef(false)
  const dictBaseRef = useRef('')
  // The tutor's working mode before an interview, restored by "Return to Chat".
  const prevModeRef = useRef<TutorMode>('chat')
  const speech = useBrowserSpeech()

  const tutor = TUTOR_PROFILES.find((t) => t.id === tutorId) || TUTOR_PROFILES[0]
  const lang = effectiveLanguage(language, lastReply)
  const ui = tutorUi(lang)
  const greetingText = ui.greeting.replace('{name}', tutor.name).replace('{purpose}', tutor.purpose)
  const interviewLang: 'en' | 'ar' = interview.language === 'ar' ? 'ar' : 'en'
  const selectedInterviewLang: 'en' | 'ar' = language === 'ar' ? 'ar' : 'en'

  const upsertConversation = useCallback((conversation?: TutorConversation | null) => {
    if (!conversation) return
    setConversations((prev) => {
      const next = [conversation, ...prev.filter((c) => c.id !== conversation.id)]
      return next.sort((a, b) => {
        const byTime = String(b.last_message_at || b.updated_at).localeCompare(String(a.last_message_at || a.updated_at))
        return byTime || b.id - a.id
      })
    })
  }, [])

  const refreshConversations = useCallback(async () => {
    if (!studentId) return [] as TutorConversation[]
    try {
      const res = await api.tutorConversations(studentId)
      setConversations((prev) => {
        const activeId = activeConversationIdRef.current
        const activeEmpty = activeId ? prev.find((c) => c.id === activeId && (c.message_count ?? 0) === 0) : undefined
        return activeEmpty && !res.conversations.some((c) => c.id === activeEmpty.id)
          ? [activeEmpty, ...res.conversations]
          : res.conversations
      })
      return res.conversations
    } catch (e) {
      console.error('[copilot] conversations failed:', e)
      return [] as TutorConversation[]
    }
  }, [studentId])

  const ensureChatConversation = useCallback(async () => {
    if (!studentId) throw new Error('No active student')
    if (activeConversationIdRef.current) return activeConversationIdRef.current
    const res = await api.newTutorConversation(studentId, tutorId)
    const conversation = res.conversation
    activeConversationIdRef.current = conversation.id
    setActiveConversationId(conversation.id)
    upsertConversation(conversation)
    setChats((prev) => ({ ...prev, [conversation.id]: prev[conversation.id] ?? [] }))
    return conversation.id
  }, [studentId, tutorId, upsertConversation])

  useEffect(() => {
    if (!studentId) return
    api.learning(studentId)
      .then(setItems)
      .catch((e) => { console.error('[copilot] learning items failed:', e) })
  }, [studentId])

  useEffect(() => {
    activeConversationIdRef.current = activeConversationId
  }, [activeConversationId])

  useEffect(() => {
    setConversations([])
    setChats({})
    setActiveConversationId(null)
    activeConversationIdRef.current = null
  }, [studentId])

  useEffect(() => {
    if (!studentId) return
    void refreshConversations()
  }, [studentId, refreshConversations])

  useEffect(() => {
    if (!studentId) return
    if (activeConversationId) {
      const active = conversations.find((c) => c.id === activeConversationId)
      if (!active || active.tutor_id === tutorId) return
    }
    const next = conversations.find((c) => c.tutor_id === tutorId)
    const nextId = next?.id ?? null
    activeConversationIdRef.current = nextId
    setActiveConversationId(nextId)
  }, [studentId, tutorId, conversations, activeConversationId])

  useEffect(() => {
    if (!studentId || !activeConversationId || chats[activeConversationId]) return
    const active = conversations.find((c) => c.id === activeConversationId)
    api.tutorHistory(studentId, active?.tutor_id || tutorId, activeConversationId)
      .then((rows) => setChats((c) => ({ ...c, [activeConversationId]: rows })))
      .catch((e) => { console.error('[copilot] tutor history failed:', e) })
  }, [studentId, tutorId, activeConversationId, conversations, chats])

  useEffect(() => {
    const onFocus = () => setOpen(true)
    window.addEventListener('copilot:focus', onFocus)
    return () => window.removeEventListener('copilot:focus', onFocus)
  }, [])

  useEffect(() => {
    if (expanded) {
      const region = (scrollRef.current?.querySelector('.thread, .welcome, .copilot-messages') as HTMLElement | null) ?? scrollRef.current
      region?.scrollTo({ top: region.scrollHeight })
    } else {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
    }
    interviewScrollRef.current?.scrollTo({ top: interviewScrollRef.current.scrollHeight })
  }, [chats, busy, interviewThreads, activeConversationId, expanded])

  useEffect(() => () => {
    if (audioRef.current) { audioRef.current.pause(); audioRef.current = null }
    if (urlRef.current) { URL.revokeObjectURL(urlRef.current); urlRef.current = null }
    speech.stopListening()
  }, [speech.stopListening])

  const messages = activeConversationId ? (chats[activeConversationId] ?? []) : []
  const interviewItems = interviewThreads[tutorId] ?? []
  const interviewLocked = interview.phase === 'starting' || interview.phase === 'active'

  const skillName = items.find((item) => item.skill_id === copilot.skillId)?.skill_name
  const topicName = copilot.competency || skillName || 'your current topic'

  const quickActions = quickActionsFor(lang, tutorId, mode, topicName)

  const localMessage = (role: 'user' | 'assistant', content: string, skillId: number | null, conversationId: number | null = activeConversationIdRef.current): TutorMessage =>
    ({ id: ++nextId.current, role, content, skill_id: skillId, tutor_id: tutorId, conversation_id: conversationId, created_at: '' })

  const appendChat = (conversationId: number, msg: TutorMessage) =>
    setChats((prev) => ({ ...prev, [conversationId]: [...(prev[conversationId] ?? []), msg] }))

  const appendInterview = (tid: TutorId, item: InterviewItem) =>
    setInterviewThreads((prev) => ({ ...prev, [tid]: [...(prev[tid] ?? []), item] }))

  // ChatGPT-style voice session. The engine (lib/voiceSession) drives browser
  // speech -> /tutor -> /tutor/tts with instant barge-in.
  // Every voice reply also lands in this tutor's normal chat thread.
  const voice = useVoiceSession({
    studentId,
    tutor: tutorId,
    language: voiceLang,
    recognitionSupported: speech.recognitionSupported,
    send: async (text, signal, sessionOpts) => {
      const conversationId = await ensureChatConversation()
      try {
        const res = await api.tutorSendAbortable(studentId, text, {
          skillId: copilot.skillId,
          page: copilot.page,
          competency: copilot.competency,
          jobTitle: copilot.jobTitle,
          jobUrl: copilot.jobUrl,
          tutorId,
          mode,
          // Explicit Live speech language: the engine always passes the current
          // selection (or a mid-session switch), never an Auto preference, so
          // the mentor replies (and speaks) in the user's chosen language.
          language: sessionOpts?.language ?? voiceLang,
          conversationId,
          spoken: true,
        }, signal)
        upsertConversation(res.conversation)
        return res.reply ?? res.content ?? ''
      } catch (err) {
        // Keep the engine's own error handling; surface only safe diagnostics.
        console.info('[voice-live] tutor.http_error', {
          mentor: tutorId,
          status: (err as { status?: number })?.status ?? null,
          kind: (err as { name?: string })?.name ?? 'Error',
        })
        throw err
      }
    },
    onAssistantReply: (replyText) => {
      if (!replyText) return
      const conversationId = activeConversationIdRef.current
      if (!conversationId) return
      appendChat(conversationId, { id: ++nextId.current, role: 'assistant', content: replyText, skill_id: copilot.skillId, tutor_id: tutorId, conversation_id: conversationId, created_at: '' })
    },
    onUserMessage: (text) => {
      const conversationId = activeConversationIdRef.current
      if (!conversationId) return
      appendChat(conversationId, localMessage('user', text, copilot.skillId, conversationId))
    },
  })
  const voiceRef = useRef(voice)
  voiceRef.current = voice

  // An active Verified assessment pauses the tutor — voice mode closes with it.
  useEffect(() => {
    if (assessmentActive || !studentId) {
      setVoiceOpen(false)
      voiceRef.current.close()
    }
  }, [assessmentActive, studentId])

  const stopSpeak = () => {
    audioRequestRef.current += 1
    if (audioRef.current) { audioRef.current.pause(); audioRef.current = null }
    if (urlRef.current) { URL.revokeObjectURL(urlRef.current); urlRef.current = null }
    setSpeakingKey(null)
    setSpeakBusy(false)
    setVoiceNote('')
  }

  const copyMessage = (key: string, text: string) => {
    if (!navigator.clipboard || !text) return
    void navigator.clipboard.writeText(text)
      .then(() => {
        setCopiedKey(key)
        window.setTimeout(() => setCopiedKey((k) => (k === key ? null : k)), 1600)
      })
      .catch(() => { /* clipboard unavailable — nothing to recover */ })
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
    setToolsOpen(false)
    setBusy(true)
    let conversationId: number | null = null
    try {
      conversationId = await ensureChatConversation()
      appendChat(conversationId, localMessage('user', text, copilot.skillId, conversationId))
      const res = await api.tutorSend(studentId, text, {
        skillId: copilot.skillId,
        page: copilot.page,
        competency: copilot.competency,
        jobTitle: copilot.jobTitle,
        jobUrl: copilot.jobUrl,
        tutorId,
        mode,
        language,
        conversationId,
      })
      setLastReply(res.language === 'ar' ? 'ar' : 'en')
      const replyText = res.reply ?? res.content
      const resolvedConversationId = res.conversation_id ?? conversationId
      activeConversationIdRef.current = resolvedConversationId
      setActiveConversationId(resolvedConversationId)
      upsertConversation(res.conversation)
      appendChat(resolvedConversationId, { id: res.id, role: 'assistant', content: replyText, skill_id: res.skill_id ?? copilot.skillId, tutor_id: res.tutor_id ?? tutorId, conversation_id: resolvedConversationId, created_at: res.created_at })
      void refreshConversations()
    } catch (err) {
      const detail = (err as Error)?.message?.trim()
      if (conversationId) {
        appendChat(conversationId, localMessage('assistant', detail && !detail.startsWith('Request failed') ? detail : '(Tutor unavailable - is the backend running?)', copilot.skillId, conversationId))
      } else {
        setVoiceNote(detail && !detail.startsWith('Request failed') ? detail : 'Tutor unavailable - is the backend running?')
      }
    } finally {
      setBusy(false)
    }
  }

  const rateMessage = (message: TutorMessage, rating: ResponseRating) => {
    const key = `m-${message.id}`
    setRatings((prev) => ({ ...prev, [key]: prev[key] === rating ? null : rating }))
  }

  const shareMessage = async (message: TutorMessage) => {
    if (typeof navigator === 'undefined' || !('share' in navigator) || !message.content.trim()) return
    try {
      await navigator.share({ text: message.content })
    } catch {
      // User cancelled the native share sheet (AbortError) or sharing failed —
      // nothing to recover, keep the message untouched.
    }
  }

  const regenerate = async (message: TutorMessage) => {
    if (!studentId || busy || assessmentActive || interviewLocked) return
    const conversationId = activeConversationIdRef.current
    if (!conversationId) return
    const thread = chats[conversationId] ?? []
    const index = thread.findIndex((m) => m.id === message.id)
    if (index < 1 || thread[index].role !== 'assistant' || thread[index - 1].role !== 'user') return
    const userText = thread[index - 1].content
    const retrying = `m-${message.id}`
    setRetryingKey(retrying)
    setBusy(true)
    try {
      const res = await api.tutorSend(studentId, userText, {
        skillId: copilot.skillId,
        page: copilot.page,
        competency: copilot.competency,
        jobTitle: copilot.jobTitle,
        jobUrl: copilot.jobUrl,
        tutorId,
        mode,
        language,
        conversationId,
      })
      setLastReply(res.language === 'ar' ? 'ar' : 'en')
      const replyText = res.reply ?? res.content
      const resolvedConversationId = res.conversation_id ?? conversationId
      activeConversationIdRef.current = resolvedConversationId
      setActiveConversationId(resolvedConversationId)
      upsertConversation(res.conversation)
      setChats((prev) => {
        const arr = [...(prev[resolvedConversationId] ?? [])]
        const i = arr.findIndex((m) => m.id === message.id)
        if (i >= 0) {
          arr[i] = { id: res.id, role: 'assistant', content: replyText, skill_id: res.skill_id ?? copilot.skillId, tutor_id: res.tutor_id ?? tutorId, conversation_id: resolvedConversationId, created_at: res.created_at }
        }
        return { ...prev, [resolvedConversationId]: arr }
      })
      void refreshConversations()
    } catch (err) {
      const detail = (err as Error)?.message?.trim()
      const fallback = '(Tutor unavailable - is the backend running?)'
      setChats((prev) => {
        const arr = [...(prev[conversationId] ?? [])]
        const i = arr.findIndex((m) => m.id === message.id)
        if (i >= 0) {
          arr[i] = { ...arr[i], content: detail && !detail.startsWith('Request failed') ? detail : fallback }
        }
        return { ...prev, [conversationId!]: arr }
      })
    } finally {
      setRetryingKey(null)
      setBusy(false)
    }
  }
  const contextTitle = PAGE_LABELS[copilot.page] || 'Your learning'
  const barSubtitle = assessmentActive
    ? ui.lockedTitle
    : `${ui.tutorRole[tutor.id]} · ${ui.ready}`

  const beginInterview = async () => {
    if (busy || assessmentActive || !studentId) return
    setInterviewError('')
    setClearModalOpen(false)
    setHistoryOpen(false)
    setToolsOpen(false)
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
    setClearModalOpen(false)
    resetInterview()
  }

  const startNewChat = async () => {
    if (!studentId || busy || interviewLocked) return
    setAboutOpen(false)
    setClearModalOpen(false)
    setHistoryOpen(false)
    setToolsOpen(false)
    setInput('')
    if (activeConversationId && messages.length === 0) return
    setBusy(true)
    try {
      const res = await api.newTutorConversation(studentId, tutorId)
      activeConversationIdRef.current = res.conversation.id
      setActiveConversationId(res.conversation.id)
      upsertConversation(res.conversation)
      setChats((prev) => ({ ...prev, [res.conversation.id]: [] }))
      setLastReply(null)
    } catch (e) {
      console.error('[copilot] new conversation failed:', e)
    } finally {
      setBusy(false)
    }
  }

  const clearCurrentConversation = async () => {
    if (!studentId || busy || interviewLocked) return
    const conversationId = activeConversationIdRef.current
    if (!conversationId) {
      setClearModalOpen(false)
      return
    }
    setAboutOpen(false)
    setClearModalOpen(false)
    setToolsOpen(false)
    try {
      await api.clearTutorChat(studentId, tutorId, conversationId)
    } catch (e) { console.error('[copilot] clear chat failed:', e) }
    setChats((c) => ({ ...c, [conversationId]: [] }))
    setConversations((prev) => prev.map((c) => c.id === conversationId
      ? { ...c, title: 'New conversation', message_count: 0, preview: '', last_message_at: null, updated_at: new Date().toISOString() }
      : c))
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

  const selectConversation = (conversation: TutorConversation) => {
    if (busy || interviewLocked) return
    activeConversationIdRef.current = conversation.id
    setActiveConversationId(conversation.id)
    setHistoryOpen(false)
    setToolsOpen(false)
    setAboutOpen(false)
    if (conversation.tutor_id !== tutorId) setTutorId(conversation.tutor_id as TutorId)
    if (!chats[conversation.id]) {
      api.tutorHistory(studentId, conversation.tutor_id, conversation.id)
        .then((rows) => setChats((prev) => ({ ...prev, [conversation.id]: rows })))
        .catch((e) => { console.error('[copilot] conversation restore failed:', e) })
    }
  }

  useEffect(() => {
    if (!clearModalOpen) return
    clearCancelRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setClearModalOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [clearModalOpen])

  const interviewRunning = mode === 'interview' && interview.phase !== 'idle'
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

  // One shared browser-speech hook for BOTH surfaces. Normal chat uses the mic
  // purely as speech-to-text dictation that types the transcript into the
  // composer (review, then hit Send). Live/voice chat (the wave button) opens
  // the VoiceMode orb separately. Mock Interview keeps its own automatic
  // submit-through-turn-taking flow.
  const stopChatDictation = () => {
    if (dictatingRef.current) {
      dictatingRef.current = false
      speech.stopListening()
    }
  }

  const startChatDictation = () => {
    if (assessmentActive || busy || !studentId) return
    if (dictatingRef.current || (speech.listening && micTarget === 'chat')) {
      stopChatDictation()
      return
    }
    if (!speech.recognitionSupported) { setVoiceNote(ui.voiceUnsupported); return }
    setVoiceNote('')
    dictatingRef.current = true
    dictBaseRef.current = input
    speech.startListening((text) => {
      const base = dictBaseRef.current.trim()
      const merged = `${base}${base && text ? ' ' : ''}${text}`
      dictatingRef.current = false
      setInput(merged)
    }, lang, () => {
      dictatingRef.current = false
    })
  }

  const toggleMic = (target: 'chat' | 'interview' = 'chat') => {
    if (target === 'interview') {
      toggleInterviewMic()
      return
    }
    setMicTarget('chat')
    startChatDictation()
  }

  const startLiveVoice = () => {
    if (assessmentActive || busy || !studentId) return
    if (!speech.recognitionSupported) { setVoiceNote(ui.voiceUnsupported); return }
    stopChatDictation()
    setVoiceNote('')
    // Explicit Live language: an already-explicit chat preference (English /
    // Arabic) opens Live in that language; an Auto chat preference is NEVER
    // silently treated as English — we use the last explicitly selected Live
    // language if one was saved, else a clear deterministic default (English),
    // and the visible EN | عربي control in the surface stays obvious.
    setVoiceLang(resolveInitialLiveLang(language))
    void ensureChatConversation()
      .then(() => setVoiceOpen(true))
      .catch((e) => {
        console.error('[copilot] voice conversation failed:', e)
        setVoiceNote('Voice chat could not start.')
      })
  }

  // Live-dictate the browser's interim transcript into the composer textarea
  // (pure speech-to-text; the orb is only for the separate Live button).
  useEffect(() => {
    if (!dictatingRef.current || micTarget !== 'chat') return
    const interim = speech.interimTranscript
    if (interim) {
      const base = dictBaseRef.current.trim()
      setInput(`${base}${base ? ' ' : ''}${interim}`)
    }
  }, [speech.interimTranscript, micTarget])

  const visibleConversations = conversations.filter((c) =>
    (c.message_count ?? 0) > 0 || c.id === activeConversationId)
  const toolActions = [
    {
      key: 'practice',
      label: ui.practiceAction,
      icon: <IconBook size={15} />,
      action: () => void send(undefined, `Give me a practical exercise for ${topicName}.`),
    },
    {
      key: 'quiz',
      label: ui.quizMeAction,
      icon: <IconClipboard size={15} />,
      action: () => void send(undefined, `Quiz me on ${topicName}.`),
    },
    {
      key: 'interview',
      label: ui.mockInterviewAction,
      icon: <IconHeadset size={15} />,
      action: () => void beginInterview(),
    },
    {
      key: 'explain',
      label: ui.explainTopicAction,
      icon: <IconLightbulb size={15} />,
      action: () => void send(undefined, `Explain ${topicName} simply and step by step.`),
    },
  ]

  return (
    <div className={`copilot-panel ${tutor.theme} ${open ? 'copilot-open' : 'copilot-closed'} ${expanded ? 'copilot-expanded' : ''} ${historyOpen ? 'history-open' : ''}`}>
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
        <div className="copilot-body copilot-v2" ref={scrollRef} dir={lang === 'ar' ? 'rtl' : 'ltr'}>
          <div className="copilot-top">
            <div className="copilot-header chat-header-compact">
              <div className="chat-header-main">
                <button
                  type="button"
                  className={`history-toggle ${historyOpen ? 'active' : ''}`}
                  onClick={() => { setHistoryOpen((h) => !h); setToolsOpen(false); setAboutOpen(false) }}
                  aria-label={ui.historyAria}
                  aria-expanded={historyOpen}
                  title={ui.history}
                >
                  <IconClock size={18} />
                </button>
                <div className="mentor-identity">
                  <span className="persona-avatar copilot-current-avatar"><img src={tutor.avatar} alt={tutor.name} /></span>
                  <div className="persona-info">
                    <div className="persona-title-row">
                      <h1>{tutor.name}</h1>
                      <span className="online-status"><span className="online-dot" />{ui.ready}</span>
                    </div>
                    <p>{ui.tutorRole[tutor.id]}</p>
                  </div>
                </div>
              </div>

              <div className="header-actions">
                <div className="mentor-change" tabIndex={0} aria-haspopup="menu" aria-label={ui.chooseCopilot}>
                  <button
                    type="button"
                    className="mentor-change-button"
                    disabled={assessmentActive || interviewLocked}
                    aria-label={ui.changeMentor}
                  >
                    {ui.changeMentor}
                    <IconChevron size={14} />
                  </button>
                  <PersonaMenu ui={ui} locked={assessmentActive || interviewLocked} />
                </div>
                <div className="lang" role="group" aria-label={ui.languages}>
                  {TUTOR_LANGUAGES.map((l) => (
                    <button
                      key={l}
                      type="button"
                      className={language === l ? 'active' : ''}
                      disabled={assessmentActive || interviewLocked}
                      onClick={() => setLanguage(l)}
                      aria-pressed={language === l}
                      title={LANGUAGE_LABELS[l]}
                    >
                      {LANGUAGE_SHORT[l]}
                    </button>
                  ))}
                </div>
                <div className="more-wrap" tabIndex={0}>
                  <button type="button" className="more-button" aria-label={ui.moreOptions} aria-haspopup="menu" title={ui.moreOptions}>
                    <IconDots size={18} />
                  </button>
                  <MoreMenu
                    ui={ui}
                    tutorName={tutor.name}
                    disabled={busy || interviewLocked || !studentId}
                    onNewChat={() => void startNewChat()}
                    onClearChat={() => setClearModalOpen(true)}
                    onProfile={() => { setAboutOpen((o) => !o); setHistoryOpen(false); setToolsOpen(false) }}
                  />
                </div>
              </div>
            </div>

            {historyOpen && (
              <div className="history-drawer" role="dialog" aria-label={ui.chatHistory}>
                <div className="history-head">
                  <strong>{ui.chatHistory}</strong>
                  <button type="button" onClick={() => void startNewChat()} disabled={busy || interviewLocked || !studentId} aria-label={ui.newChatChip}>
                    <IconPlus size={15} />
                  </button>
                </div>
                {visibleConversations.length === 0 ? (
                  <div className="history-empty">{ui.emptyHistory}</div>
                ) : (
                  <div className="history-list">
                    {visibleConversations.map((conversation) => {
                      const profile = TUTOR_PROFILES.find((p) => p.id === conversation.tutor_id) || TUTOR_PROFILES[0]
                      const active = conversation.id === activeConversationId
                      const stamp = conversationStamp(conversation.last_message_at || conversation.updated_at)
                      return (
                        <button
                          key={conversation.id}
                          type="button"
                          className={`history-row ${active ? 'active' : ''}`}
                          onClick={() => selectConversation(conversation)}
                          disabled={busy || interviewLocked}
                        >
                          <span className="history-avatar"><img src={profile.avatar} alt={profile.name} /></span>
                          <span className="history-copy">
                            <strong>{conversation.title || ui.currentConversation}</strong>
                            <small>{profile.name}{stamp ? ` / ${stamp}` : ''}</small>
                          </span>
                          {active && <span className="history-current">{ui.currentConversation}</span>}
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
            )}

            <div className="copilot-context">
              <span className="context-item"><IconShield size={12} /> {ui.talkingAbout} <strong>{topicName}</strong></span>
              <span className="context-divider" />
              <span className="context-item muted">{contextTitle}</span>
            </div>
          </div>

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
              {interviewRunning ? (
                <>
                  <div className="tutor-messages copilot-messages" ref={interviewScrollRef}>
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
                        {(item.kind === 'question' || item.kind === 'feedback') && (
                          <button
                            type="button"
                            className="copilot-msg-copy"
                            onClick={() => copyMessage(`i-${item.id}`, item.text)}
                            disabled={assessmentActive || !studentId}
                            aria-label={ui.copyAria}
                            title={ui.copyAria}
                          >
                            {copiedKey === `i-${item.id}` ? <IconCheck size={13} /> : <IconCopy size={13} />}
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
                            <IconSendUp size={18} />
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
                  {messages.length === 0 ? (
                    <section className="welcome">
                      <div className="welcome-symbol"><span className="symbol-core"><IconSparkles size={20} /></span></div>
                      <h2>{ui.welcomeTitle}</h2>
                      <p>{ui.welcomeBody}</p>
                      <SuggestionGrid ui={ui} onPick={(prompt) => void send(undefined, prompt)} />
                      <div className="welcome-greet">
                        <span className="wg-avatar"><img src={tutor.avatar} alt={tutor.name} /></span>
                        <span className="wg-copy">{greetingText}</span>
                      </div>
                    </section>
                  ) : (
                    <ChatThread
                      messages={messages}
                      busy={busy}
                      tutor={tutor}
                      ui={ui}
                      speakingKey={speakingKey}
                      copiedKey={copiedKey}
                      speakDisabled={assessmentActive || speakBusy || !studentId}
                      audioDisabled={assessmentActive || !studentId}
                      onSpeak={(message) => void toggleSpeak(`m-${message.id}`, message.content)}
                      onCopy={(message) => copyMessage(`m-${message.id}`, message.content)}
                      ratings={ratings}
                      retryingKey={retryingKey}
                      shareDisabled={shareDisabled}
                      onRate={rateMessage}
                      onShare={(message) => void shareMessage(message)}
                      onRetry={(message) => void regenerate(message)}
                      chips={quickActions}
                      onChip={(prompt) => void send(undefined, prompt)}
                    />
                  )}

                  {interviewError && !aboutOpen && (
                    <div className="copilot-interview-error">{interviewError}</div>
                  )}

                  {!aboutOpen && (
                    <Composer
                      footer={<>
                        <span>{ui.composerFooter1.replace('{name}', tutor.name)}</span>
                        <span className="cf-dot" aria-hidden="true" />
                        <span>{ui.composerFooter2}</span>
                      </>}
                    >
                      <div className="composer">
                        <form className="tutor-input copilot-input" onSubmit={(e) => void send(e)}>
                          <textarea
                          rows={1}
                          value={input}
                          onChange={(e) => setInput(e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send() } }}
                          placeholder={ui.askPlaceholder.replace('{name}', tutor.name)}
                          dir="auto"
                          aria-label={ui.sendAria}
                        />
                        <div className="composer-actions">
                          <div className="composer-tools-wrap">
                            <button
                              type="button"
                              className={`composer-attach ${toolsOpen ? 'active' : ''}`}
                              onClick={() => { setToolsOpen((o) => !o); setHistoryOpen(false) }}
                              aria-label={ui.toolsAria}
                              aria-expanded={toolsOpen}
                              title={ui.toolsAria}
                              disabled={assessmentActive || busy || !studentId}
                            >
                              <IconPlus size={18} />
                            </button>
                            {toolsOpen && (
                              <div className="composer-tools-menu" role="menu" aria-label={ui.toolsMenu}>
                                {toolActions.map((action) => (
                                  <button
                                    key={action.key}
                                    type="button"
                                    role="menuitem"
                                    onClick={action.action}
                                    disabled={assessmentActive || busy || !studentId}
                                  >
                                    {action.icon}
                                    <span>{action.label}</span>
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>
                          <button
                            type="button"
                            className="composer-live copilot-live"
                            onClick={startLiveVoice}
                            aria-label={ui.liveAria.replace('{name}', tutor.name)}
                            title={ui.liveAria.replace('{name}', tutor.name)}
                            disabled={assessmentActive || busy || !studentId}
                          >
                            <IconWaveform size={18} />
                          </button>
                          <button
                            type="button"
                            className="composer-mic copilot-mic"
                            onClick={() => toggleMic('chat')}
                            aria-label={speech.listening && micTarget === 'chat' ? ui.micListeningAria : ui.micAria}
                            title={speech.listening && micTarget === 'chat' ? ui.micListeningAria : ui.micAria}
                            disabled={assessmentActive || busy || !studentId}
                          >
                            {speech.listening && micTarget === 'chat' ? <IconStop size={18} /> : <IconMic size={18} />}
                          </button>
                          <button type="submit" className="composer-send" disabled={busy || !input.trim() || !studentId} aria-label={ui.sendAria} title={ui.sendAria}>
                            <IconSendUp size={18} />
                          </button>
                        </div>
                      </form>
                      </div>
                    </Composer>
                  )}

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

          {clearModalOpen && (
            <div className="chat-modal-backdrop" role="presentation" onMouseDown={() => setClearModalOpen(false)}>
              <div
                className="chat-clear-modal"
                role="alertdialog"
                aria-modal="true"
                aria-labelledby="chat-clear-title"
                aria-describedby="chat-clear-body"
                onMouseDown={(e) => e.stopPropagation()}
              >
                <h2 id="chat-clear-title">{ui.clearChatTitle}</h2>
                <p id="chat-clear-body">{ui.clearChatConfirm.replace('{name}', tutor.name)}</p>
                <div className="chat-clear-actions">
                  <button ref={clearCancelRef} type="button" className="btn" onClick={() => setClearModalOpen(false)} disabled={busy}>
                    {ui.cancel}
                  </button>
                  <button type="button" className="btn btn-primary chat-clear-danger" onClick={() => void clearCurrentConversation()} disabled={busy || !activeConversationId}>
                    {ui.clear}
                  </button>
                </div>
              </div>
            </div>
          )}

          {voiceOpen && (
            <VoiceMode voice={voice} tutor={tutor} lang={lang} ui={ui} onClose={() => setVoiceOpen(false)} />
          )}
        </div>
      )}
    </div>
  )
}
