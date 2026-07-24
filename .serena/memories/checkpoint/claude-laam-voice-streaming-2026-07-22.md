# Checkpoint: claude (LAAM sub-project) — 2026-07-22 (3 rounds)

**Scope:** nested `other_projects/LAAM` sub-repo, branch `task/improve-mcp-tool-call-voice`. Filed in the workspace store because this session's Serena MCP has no per-repo `activate_project`.

## Round 1 — original plan (7 tasks, subagent-driven)
Executed `docs/superpowers/plans/2026-07-22-constellation-voice-streaming.md`: VieNeu-only TTS service + `/tts/stream` PCM endpoint, `/api/tts/stream` passthrough, `streamingAudio.ts` (PCM helpers + `playPcmStream`), `getTtsSink()` replacing `attachTts`, `ConstellationClient` wiring, dead-code removal. Commits `b23aff1..1c7db1e`. Each task implemented + reviewed by fresh subagents; final whole-branch review (opus) found one gap (missing CHANGELOG entry) → fixed. Found + fixed a real TS strict-mode bug in the plan's own verbatim code.

## Round 2 — long replies silently truncated
User: "voice không đọc" on some replies. **Measured**: 3651-char reply = 149s to generate 266s audio; route killed it at exactly 60.05s (`TTS_STREAM_TIMEOUT_MS`). A **regression from round 1** — the old per-chunk path kept each request under its own 20s cap. Fix (`5204871`): `splitForSpeech` (280-char soft cap, merges stray fragments), shared `cursor` in `playPcmStream`, `speakReply` loops segments with 1-ahead prefetch, fallback re-speaks only the unspoken remainder, null sink now falls back to browser voice. Also `preparingSpeech` flag for the pre-audio animation gap (root-caused by reading `ConstellationCanvas.tsx`: `getLevel()` returned flat 0.15 in the gap; my FIRST hypothesis about `AudioWave` was wrong and I corrected it).

## Round 3 — whole-page freeze, then crackling
**Freeze**: measured `docker stats` → piper-tts hits **1374% CPU** (all 12 cores) while generating. Measured realtime factor at CPU caps: VieNeu 12 cores = 0.98x, 8 = 0.46x, 6 = 0.34x → **no cap exists that is both smooth and fast enough**; VieNeu is simply too heavy for this hardware. (Explains the earlier `94f1d62` revert of a CPU cap.) Measured Supertonic (the user's own A/B prototype, port 5003): 3.69x uncapped, **2.09x at 6 cores**, and 2.22x at speed=1.35/steps=6 → a viable engine swap. Sent the user 3 wav samples to compare voices. User then reported the freeze was gone after a page reload, so the engine swap was NOT done — **Supertonic remains the standing option if the freeze returns**.

**Crackling/stutter** (`35e11a4`): ruled out the source first — raw PCM is clean (7 clipped samples in 12.7M, no discontinuities). Root cause: `playPcmStream` scheduled each chunk on arrival, but VieNeu delivers ~0.32s of audio per ~0.40s wall early on → cursor falls behind → a gap every ~400ms. Simulated against **real captured chunk-arrival timings**: prebuffer 0s → 11 underruns/1.89s; 2s → 2; **3s → 0**. Fix: `TTS_PREBUFFER_SECONDS = 3` hold-then-release (short streams play on end), 50ms opening lead, and `AudioContext` pinned to 48kHz (hardware default 44100 resamples every small buffer individually → per-boundary artifacts). End-to-end sim with the live service: 0.14s residual underrun, all in segment 0; segments 1+ zero, lead grows to 33s. Tested delayed-prefetch alternative → clearly worse (18 underruns/3.58s), rejected. Cost: first audio ~4.3s instead of ~0.4s (unavoidable with a ~1x-realtime CPU engine).

## Method note that paid off repeatedly
Every round: measure before fixing (docker stats, chunk-cadence capture, PCM clipping analysis, timing sims on real data), and simulate candidate fixes against captured real timings rather than reasoning about them. Called `advisor()` in round 2 — it correctly caught that my evidence didn't match the user's reported symptom and that I'd mis-filed a regression as pre-existing.

## Current state
Commits `b23aff1..d18ee49`. tsc clean; 2238 pass / 4 pre-existing unrelated `search.test.ts` failures. Pre-existing WIP (`.env.example`, `docker-compose.yml`, `src/app/api/tts/route.ts`, `supertonic-tts/`, `tts-samples/`) deliberately untouched throughout.

## Next steps
- **User must verify by ear** — no audio/login in this environment. Open questions: is the crackling gone, and is ~4.3s to first audio acceptable?
- If freeze returns or 4.3s is too slow: swap to Supertonic + `cpus: 6` (measured 2.09-2.22x realtime). Needs a `/tts/stream` endpoint added to `supertonic-tts/app.py` and 44100 vs 48000 Hz handling.
- Unfixed, flagged: `VOICE_GUIDE` (`src/lib/agent/context.ts`) is ignored by the model — voice replies still contain markdown headers/bold/numbered lists, which is why they get long enough to matter.
