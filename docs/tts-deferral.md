# TTS (ElevenLabs) — written deferral

## Reason it cannot be turned on today

The chat voice button (`POST /api/students/{id}/tutor/tts`) returns **503** with
`{"detail":"No ElevenLabs voice configured for nova"}` because **no ElevenLabs key
and no tutor voice IDs exist in the environment**.

Verified live on the restarted (canonical-target) server, PID 28376, nvidia provider:
- `GET /api/students/8/interview/voice` →
  `{"available": false, "api_key_loaded": false, "tutor_voices_loaded": {"nova": false, "axel": false, "sage": false, "vex": false}}`
- `POST /api/students/8/tutor/tts` body `{"tutor": "nova", "text": "hello"}` → **HTTP 503**,
  `{"detail":"No ElevenLabs voice configured for nova"}` (0.0s, expected; the UI
  shows the "Voice unavailable / الصوت غير متاح" toast).

The key was searched for in shell environment variables, `HKCU`/`HKLM` environment
keys, and a full-text search of the target tree — nothing exists. `backend/app/tts.py`
loads only `ELEVENLABS_API_KEY`, `ELEVENLABS_MODEL`, and the four
`ELEVENLABS_{NOVA,AXEL,SAGE,VEX}_VOICE_ID` values, none of which are present in the
target `.env` or anywhere else. The API key is material that only the user can supply;
fabricating it is impossible. The app is fully functional without it — TTS is a
self-contained additive feature.

## What I will do once you add the lines below

Restart the backend, then re-run the TTS gate: `interview/voice` must report
`available: true` and `POST .../tutor/tts` must return `200` with `audio/mpeg` bytes,
then verify the UI voice buttons play audio for all four personas.

## Exact lines to add to `.env`  (TARGET root: `SkillBridge-Complete-Upgraded-Private-Handoff\SkillBridge-Final-main\.env`)

```env
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here
ELEVENLABS_MODEL=eleven_multilingual_v2
ELEVENLABS_NOVA_VOICE_ID=Xb7hH8MSUJpSbSDYk0k2
ELEVENLABS_AXEL_VOICE_ID=TX3LPaxmHKxFdv7VOQHJ
ELEVENLABS_SAGE_VOICE_ID=XrExE9yKIg1WjnnlVkGX
ELEVENLABS_VEX_VOICE_ID=pNInz6obpgDQGcFmaJgB
```

Note: the four voice IDs above are the ElevenLabs public preview voices already
referenced as defaults in `frontend/src/lib/tutorProfiles.ts` (Nova/explain =
Rachel-style, Axel/Trainer = Antoni-style, Sage/Mentor = Elli-style, Vex/Examiner =
Joseph-style). Replace them with your own voice IDs if you prefer; the backend only
needs the IDs to be non-empty.

## Restart steps (exact)

1. Add the lines above to the target root `.env` (it is gitignored; keep it out of
   commits).
2. Adopt the canonical start (run from `backend/`, absolute app imports):
   ```powershell
   # kill any listener on 8000 first
   $pids = (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).OwningProcess
   $pids | ForEach-Object { Stop-Process -Id $_ -Force }
   Start-Process -FilePath "..\.venv\Scripts\python.exe" -ArgumentList '-m','uvicorn','app.main:app','--host','0.0.0.0','--port','8000' -WorkingDirectory "<target>\backend" -WindowStyle Hidden -RedirectStandardOutput "<log>.log" -RedirectStandardError "<log>.err"
   ```
3. Verify:
   ```powershell
   (Invoke-WebRequest -Uri 'http://localhost:8000/api/students/8/interview/voice' -UseBasicParsing).Content
   # expect: {"available": true, "api_key_loaded": true, "tutor_voices_loaded": {...all true}}
   ```

## Verified state (for the record)

- Full suite: **805 passed, 3 skipped, 0 failed**.
- Gate4 (8 items) on the restarted server: G1 hello → Vex persona greeting (0.0s),
  G2 2+2 → `2 + 2 = 4.` (0.0s), G3 identity → canonical Vex identity, G4 DNS →
  DNS-first + knowledge check, G5 Nova dinosaurs, G6 Sage inflation, G7 Nova Arabic
  pinned → clean Arabic profile answer (no leak markers, no half-translations),
  G8 TTS → 503 (this deferral). Provider: nvidia active, last_success true.