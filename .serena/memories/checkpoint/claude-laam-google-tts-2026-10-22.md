# Checkpoint: claude (LAAM Google TTS) — 2026-10-22

## What was done
- LAAM voice (/constellation) moved from self-hosted VieNeu to Google Cloud TTS, Chirp3-HD-Charon (vi-VN / en-US / cmn-CN).
- Branch `feat/google-cloud-tts` in LAAM (NOT pushed, NOT merged): 8e2f5c4f feat + 4a592f04 fix (input cap 5000 bytes → 413, 120 req/min/user → 429, 20s timeout on /tts).
- `TTS_ENGINE=google|vieneu` (compose default google). Creds: `GOOGLE_TTS_CREDENTIALS_B64` (Docker) or ADC `GOOGLE_APPLICATION_CREDENTIALS` (host dev). `GOOGLE_TTS_VOICE` optional.
- vieneu-tts behind compose profile `vieneu` (re-enable: TTS_ENGINE=vieneu + `docker compose --profile vieneu up -d`).
- `@google-cloud/text-to-speech` added to serverExternalPackages (bundled → package missing from standalone; google-gax loads protos from disk).
- Local docker: laam-app:latest rebuilt from the branch, app recreated, vieneu container stopped; LAAM/.env got TTS_ENGINE/GOOGLE_TTS_VOICE/GOOGLE_TTS_CREDENTIALS_B64.
- Key file: ~/.secrets/laam-tts.json (chmod 600). GCP free trial $300 ends 2027-01-21 → API stops unless upgraded; then TTS 502s and page falls back to browser voice.

## Verified
- Unit: 27 TTS tests green; tsc clean; lint clean. Full unit suite: 7 failures in intel/admin (repo/options/scopes) pre-exist on main, unrelated.
- Live (host, real routes + real Google): wav 200 RIFF; stream vi/en/zh ttfb 200–290ms; barge-in abort cancels gRPC.
- In-container: package loads, streams vi/en/zh Charon with .env creds.
- NOT verified: the built route in the container end-to-end with a real session (Chrome extension not connected) — needs a manual /constellation listen.

## Next steps
- User listens in /constellation (vi + zh reply), check `docker logs laam-v2-app | grep -i tts` for `[tts] google … failed`.
- Push + PR/merge decision. Other hosts: add GOOGLE_TTS_CREDENTIALS_B64 to .env BEFORE `up -d app`, and `docker compose --profile vieneu stop vieneu-tts` (see LAAM docs/DEPLOYMENT.md §4).
