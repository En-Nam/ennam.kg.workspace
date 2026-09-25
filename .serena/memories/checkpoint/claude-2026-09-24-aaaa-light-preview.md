# Checkpoint: claude — 2026-09-24 (AAAA redesign → merged to main)

## What was done
- Client feedback "too tech". Explored A/B/C previews; the user picked C (Plus Jakarta Sans, pastel, brush headline, dashboard hero, after middle.finance).
- Implemented C on the main page, keeping the motion system (Lenis, GSAP intro, reveals, count-ups, FLIP board).
- Removed boot sequence, three.js, WebGL aurora, grain, rail, and decoding labels (three/ogl uninstalled).
- Product palette (AM Gradient: ink #0d253d, indigo #533afd) + Ennam icon. AM AI Agent is ENNAM's product; Alliance Mount is only a customer.
- Added: hero 3D tilt + parallax (useTilt), drifting aurora blobs on the CTA (CSS transform, paused off screen), NoteCard per capability (plain card, no shadow), board loop paused off screen (useOnScreen).
- Scroll: Lenis lerp 0.12; will-change and nav blur removed. Measured 120 fps, 0 long frames even at 6x CPU throttle, 0 raster drops. The user still reports scroll not smooth → added a TEMPORARY `?scroll=native` switch (App.tsx NATIVE_SCROLL); awaiting the user's A/B verdict.
- VI copy rewritten in LAAM_introduce's voice; EN nav/CTA/company name aligned (Ennam SJC). EN body copy NOT yet rewritten.
- COMMITTED 643ce6b (redesign) + c5fca57 (A/B/C previews kept, dev-server only) on main in AAAA_introduce; PUSHED to origin/main (d4a1d3b..c5fca57). The user deleted AAAA_introduce/.spectex/ themselves.
- Verified: clean detached-worktree build of main passes (tsc + vite + oxlint).

## Current state
- Untracked, left local on purpose: light.html, light-b.html, light-c.html, src/preview/ (stale previews, no longer in the vite input).
- AAAA_introduce/.spectex/ vanished around 17:28, same time as the workspace .spectex reindex.lock. Likely Spectex's own reindex; not caused by any rm in this session. It is a regenerable local index.

## Next steps
- Push main to origin when the user asks.
- Resolve Lenis vs native scroll, then remove the ?scroll=native switch.
- Optional: rewrite EN body copy; delete the preview files; update README (still describes the old dark design).
