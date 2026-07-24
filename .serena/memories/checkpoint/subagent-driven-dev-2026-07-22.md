# Checkpoint: subagent-driven-dev — 2026-07-22 (Part H — VieNeu streaming spec + plan)

## Parts A-G: see prior content. A-E fixes committed & valid; F (piper-tts cpus:"4") reverted; G = Supertonic prototype (running on :5003, uncommitted, user auditioning).

## Part H — VieNeu voice STREAMING: brainstormed → spec → plan (NOT yet implemented)
- User noticed VieNeu has streaming. Verified: `vieneu` (v3.2.3, in the piper-tts container) exposes `infer_stream(text, voice=…)` → Generator yielding **float32 mono [-1,1] @ 48000Hz** frames. Measured: first audio **~0.17-0.23s** vs ~3.5s for whole-clip `infer()`. Long text (>256 char max_chars) streams fine (internal chunking, 24 frames, no error).
- **Brainstormed (superpowers:brainstorming) — decisions locked:**
  - Engine: **VieNeu** (user committed, over Piper/Supertonic).
  - **VieNeu for BOTH vi + en, DROP Piper** (VieNeu is bilingual; `infer_stream` takes NO lang param — language inferred from text). `lang` selects VOICE preset only.
  - Per-language voice **seam** for a future English "Emma" voice — NOT built now ("tạm thời chưa cần"); both langs use `Thục Đoan` preset today.
  - Playback: **AudioBufferSourceNode scheduling** (Approach A) — also replaces `MediaElementAudioSourceNode`, killing the Part C crash class at root.
  - Transport: **PCM Int16LE, 48kHz, mono** (fixed constant both ends).
  - **Animation stutter EXPLICITLY out of scope** (CPU contention, separate core-limit fix).
  - Scope: `/constellation` voice path only (`/chat` uses browser TTS, untouched).
- **Spec written + committed:** `docs/superpowers/specs/2026-07-22-constellation-voice-streaming-design.md` (commit 405b0ca).
- **Verified spec against real code (no errors):** `infer_stream` format ✅; `chunkForSpeech`/`speakChunks` used ONLY in ConstellationClient ✅ (safe to remove); `/api/tts` fetched ONLY in ConstellationClient ✅; `/chat` uses `useVoice` not `/api/tts` ✅; long-text streaming ✅.
- **Plan written + self-reviewed + committed:** `docs/superpowers/plans/2026-07-22-constellation-voice-streaming.md` (commit 2525847). 7 tasks + final verification, all with COMPLETE code (no placeholders):
  1. piper-tts service → VieNeu-only + `/tts/stream` StreamingResponse (drop Piper model from Dockerfile, add numpy).
  2. `src/app/api/tts/stream/route.ts` (new) — auth + pipe `${CONSTELLATION_TTS_URL}/stream` body through, 60s timeout, no unit test (plumbing).
  3. `src/lib/chat/streamingAudio.ts` (new) — `int16ToFloat32` + `drainPcmChunk` (TDD).
  4. same file — `playPcmStream(body, {context, analyser, onFirstAudio, signal})` gapless scheduling (TDD w/ mock AudioContext + fake ReadableStream + fake timers).
  5. `useAudioAnalyser.ts` — replace `attachTts(el)` with `getTtsSink(): {context, analyser}|null` (persistent AnalyserNode→destination, created once); rewrite its test.
  6. `ConstellationClient.tsx` — `speakReply` streams via `/api/tts/stream`+`playPcmStream`; remove `synthChunk`/`playUrl`/`ttsElRef`/chunk imports; `neuralSpeaking` on `onFirstAudio`; new `speakAbortRef` to cancel prior playback; PRESERVE Part D/E fallback-handoff (fellBackRef + 4s safety net + voice.speaking→clear effect).
  7. remove dead `chunkForSpeech`/`speakChunks`/`defer`/`SpeakChunksDeps` from voice.ts + their tests (keep stripForSpeech).

## Current state
- Branch `task/improve-mcp-tool-call-voice`, HEAD `2525847`. Nothing from Part H implemented yet — only spec + plan committed.
- Both TTS containers still healthy (piper-tts :5002 = VieNeu+Piper current; supertonic-tts :5003 = audition prototype). `.env` CONSTELLATION_TTS_URL still :5002 (VieNeu), unchanged.
- Awaiting user's execution-mode choice (subagent-driven vs inline) to start implementing the plan.

## Next steps
- Execute the plan (Task 1→7 + verification). RECOMMENDED: subagent-driven-development (fresh subagent per task + task review + final whole-branch review), which is the workflow already used successfully for Parts A-E this session.
- Note for execution: Task 1 rebuilds the piper-tts image (drops Piper, ~smaller). The supertonic-tts prototype (Part G) is independent — can be removed separately once engine choice final; NOT part of this plan.
- Pre-existing-WIP-in-commits still applies to piper-tts/* and docker-compose.yml (`preexisting-uncommitted-changes-before-git-add.md`); plan's Global Constraints notes it.

## Meta
Long session. This is the first piece done via the full brainstorm→spec→plan pipeline (Parts A-G were direct fixes). Animation stutter (H1 CPU contention, confirmed via docker stats both engines ~1230%) remains OPEN by user choice — separate from streaming.
