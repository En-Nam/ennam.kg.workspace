# Checkpoint: claude (AAAA_introduce Flow redesign) — 2026-09-17

## What was done
Redesigned the pipeline section of `AAAA_introduce` (between capability blocks 02
and 03, titled "Đường đi của dữ liệu"). Six passes, each driven by explicit user
feedback. Final: an orthogonal routed trace with one continuous light, two-line
labels (ordinal + name only — subtitle removed).

- Removed the old hairline rail + three.js packet (`src/lib/flow-scene.ts` deleted).
- Figure: orthogonal route changing level between stations; labels alternate
  above/below; a drop hairline ties each label to its station.
- **Latest pass**: dropped the `does` subtitle line from both the desktop routed
  view and the mobile vertical `Descent` view (user found it visually noisy).
  For upper stations (1, 3 — labels above the route) the ordinal and name are now
  rendered in `title, ordinal` order instead of `ordinal, title`, so the ordinal
  ends up nearest the route (matching stations 2/4, where it already was nearest
  since those grow downward from the route). Implemented by building `ordinal`
  and `title` as two JSX consts once per step, then choosing render order with
  `station.upper ? <>{title}{ordinal}</> : <>{ordinal}{title}</>` — not
  `flex-col-reverse` (that would also flip reading order, not just visual order).
  `LABEL_H` re-measured and shrunk 82→60 to fit the now-2-line content (41px) +
  `LABEL_PAD` (18px). Figure height dropped 236→192.
- Motion: one `stroke-dashoffset` traverse — halo + trail + packet, all on the
  same path, same duration, same easing. No timers, no rAF, no WebGL.
- Copy: `flow.steps` is `{ name, does }[]` in i18n; `does` is now unused by the
  component (kept in the data files, harmless) after this pass.

## A real bug found and fixed this pass (not cosmetic — fixes real users too)
`useMeasuredWidth`'s `ResizeObserver` alone left `width` stuck at 0 → the whole
route (svg + stations) failed to render, silently, whenever the observer's first
callback didn't fire before paint. Confirmed the mechanism: RO's initial report
rides the same rendering step as `requestAnimationFrame`, which browsers suspend
for backgrounded/hidden tabs (verified via `document.hidden` in this session's
Browser pane, which was itself hidden). **Fix**: read `getBoundingClientRect()`
synchronously in the same `useLayoutEffect`, before subscribing the observer, so
first paint never depends on RO firing. This makes the component correct for any
tab that's slow to get its first rendering tick, not just this dev environment.

## Files changed
- `src/components/sections/Flow.tsx` — rewritten (see current file, ~500 lines)
- `src/lib/flow-scene.ts` — DELETED
- `src/lib/i18n/vi.ts`, `src/lib/i18n/en.ts` — flow block reshaped (from earlier
  pass; `does` field present but no longer rendered)
- `src/index.css` — old `.flow-*` rail CSS removed
- `<workspace>/.claude/launch.json` — `aaaa-introduce` dev-server entry (port 5273)

## Verification note for next session
This session's Browser pane was hidden for the whole final pass (`document.hidden
=== true`, confirmed via `tabs_context`), which makes `computer:screenshot` return
solid black and throttles `ResizeObserver`/rAF. **Verify via DOM measurement
(`getBoundingClientRect`, `getComputedStyle`) instead of screenshots when this
happens** — it was the only way to confirm the label reorder and band-height fix
in this session. Ask the user for a real screenshot before trusting a visual
description of anything this pane can't actually show.

## Current state
`tsc -b` clean, `oxlint` clean (pre-existing `useMediaQuery` warning only),
`npm run build` green. DOM-measured: upper stations (1,3) render name-then-ordinal
with ordinal nearest the route; lower (2,4) render ordinal-then-name, also nearest
the route — symmetric now. No content overflow in the 60px label band. Mobile
`Descent` view has no subtitle and no horizontal overflow.

## Next steps / Risks
- Reduced motion still relies on the global CSS duration collapse, not a branch —
  unverified in-browser this session for the same hidden-pane reason.
