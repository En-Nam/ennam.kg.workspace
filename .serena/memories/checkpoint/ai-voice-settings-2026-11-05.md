# Checkpoint: ai-voice-settings — 2026-11-05 (LAAM)

## What was done
- Per-org AI model settings (spec 2026-11-05 §10b): table `llm_task_settings_org` (migration 0048), router resolves org → platform → env per column; TaskCallCtx.orgId (falls back to meter.orgId). Owner-only page `/settings/org-ai-models`, API `GET/PUT /api/settings/llm-tasks/org`. Customer: cloud only, no "low" tool-round effort. BytePlus stays offered (spec update 09e137dc).
- Voice choice: org `ttsVoices`/`ttsDefaultVoice`, user `ttsVoice` (0048; 0049 data: existing orgs → chirp3-hd). `/settings/voice`, APIs `/api/settings/voice` (+/org owner-only, /me, /preview free 10/h). `/api/tts`(+stream) enforce effective voice; browser → 409. resolveTtsEngine removed (engine follows voice). Constellation v1/v2 use `useServerVoice`.
- Settings menu: new "AI" group; platform page renamed "Mô hình AI — mặc định nền tảng".
- Commits on task/LAAM/improve: ad4aa3b3, 8fb25968, bbba17fd, 186d4b88, 25e59070.

## Current state
- tsc clean; unit 8080 pass; integration 1360 pass. Container rebuilt (port 3900). Screenshots in session scratchpad ai-voice/.

## Next steps / risks
- Internal org has no Admin pricing → all hints "chưa có giá".
- Cache TTL for task settings is 5 s in code (spec says 60 s).
- Vieneu-only deployments now give customer orgs the browser voice.
- Real measurement (§9 "Đo thật") not done.
