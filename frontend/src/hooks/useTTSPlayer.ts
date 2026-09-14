import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getToken } from '../lib/api'
import type { PlaybackHandle, VoiceTtsAdapter } from '../lib/voiceSession'

// TTS adapter + manual playback for the SkillBridge Copilot.
//
// This refactors the mechanics of the legacy inline speak/stop flow
// (fetch the speech blob from /tutor/tts -> object URL -> <audio> ->
// request-id guards) into a reusable adapter the ChatGPT-style voice session
// drives. The legacy per-message buttons in CopilotPanel intentionally keep
// their OWN inline implementation because the Step 4.5 / Interview source
// contract checkers pin literals like `api.tutorTts`, `audio.muted = false`,
// `voiceNote` and `ui.voiceUnavailable` inside that file; this module is the
// shared, first-class version used by the voice-overlay pipeline.

interface TtsResponse {
  ok: boolean
  status: number
  blob(): Promise<Blob>
  json(): Promise<unknown>
}

/** Abortable POST to the existing /tutor/tts endpoint ({tutor, text} body). */
export function fetchTutorTtsBlob(
  studentId: number,
  tutor: string,
  text: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  return fetch(`/api/students/${studentId}/tutor/tts`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ tutor, text }),
    signal,
  }).then(async (res: TtsResponse) => {
    if (!res.ok) {
      let detail = `Request failed: ${res.status}`
      try {
        const data = (await res.json()) as { detail?: string }
        if (data && data.detail) {
          detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
        }
      } catch { /* non-JSON error body */ }
      throw new Error(detail)
    }
    return res.blob()
  })
}

/** Plays a TTS blob immediately. `handle.done` resolves on natural end or error. */
export function playTtsBlob(blob: Blob): PlaybackHandle {
  const url = URL.createObjectURL(blob)
  const audio = new Audio(url)
  audio.muted = false
  let resolved = false
  let resolveDone: () => void = () => {}
  const done = new Promise<void>((resolve) => { resolveDone = resolve })
  const cleanup = () => {
    if (resolved) return
    resolved = true
    URL.revokeObjectURL(url)
  }
  const finish = () => {
    cleanup()
    resolveDone()
  }
  audio.onended = finish
  audio.onerror = finish
  void audio.play().catch(finish)
  return {
    stop() {
      try { audio.pause() } catch { /* already stopped */ }
      cleanup()
      resolveDone()
    },
    done,
  }
}

/** The VoiceSession TTS adapter (synthesize -> abortable blob fetch, play -> audio). */
export function createVoiceTtsAdapter(studentId: number, tutor: string): VoiceTtsAdapter {
  return {
    synthesize: (text, signal) => fetchTutorTtsBlob(studentId, tutor, text, signal),
    play: playTtsBlob,
  }
}

export interface TtsPlayerApi {
  /** VoiceSession-compatible adapter for the given student/tutor. */
  adapter: VoiceTtsAdapter
  /** True while a manual replay (not a session reply) is playing. */
  replaying: boolean
  /** Manually speak text. Resolves `state: 'ok' | 'voice-unavailable'`. */
  replay(text: string): Promise<'ok' | 'voice-unavailable'>
  /** Stop both session audio and any manual replay. */
  abort(): void
}

/**
 * Owns the audio lifecycle for one (student, tutor) pair. The session engine
 * consumes `adapter`; `replay` powers transcript replay-buttons without going
 * through the engine state machine.
 */
export function useTTSPlayer(studentId: number, tutor: string): TtsPlayerApi {
  const [replaying, setReplaying] = useState(false)
  const handleRef = useRef<PlaybackHandle | null>(null)
  const requestRef = useRef(0)

  const abort = useCallback(() => {
    requestRef.current += 1
    handleRef.current?.stop()
    handleRef.current = null
    setReplaying(false)
  }, [])

  useEffect(() => () => {
    requestRef.current += 1
    handleRef.current?.stop()
    handleRef.current = null
    setReplaying(false)
  }, [])

  const adapter = useMemo(() => createVoiceTtsAdapter(studentId, tutor), [studentId, tutor])

  const replay = useCallback(async (text: string): Promise<'ok' | 'voice-unavailable'> => {
    if (!studentId || !text.trim()) return 'voice-unavailable'
    const requestId = requestRef.current + 1
    requestRef.current = requestId
    abort()
    setReplaying(true)
    try {
      const blob = await fetchTutorTtsBlob(studentId, tutor, text)
      if (requestRef.current !== requestId) return 'voice-unavailable'
      const handle = playTtsBlob(blob)
      if (requestRef.current !== requestId) { handle.stop(); return 'voice-unavailable' }
      handleRef.current = handle
      handle.done.then(() => {
        if (handleRef.current === handle) handleRef.current = null
        setReplaying(false)
      })
      return 'ok'
    } catch {
      if (requestRef.current !== requestId) return 'voice-unavailable'
      setReplaying(false)
      return 'voice-unavailable'
    }
  }, [studentId, tutor, abort])

  return { adapter, replaying, replay, abort }
}
