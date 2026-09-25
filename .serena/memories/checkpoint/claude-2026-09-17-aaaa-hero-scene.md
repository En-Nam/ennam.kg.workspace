# Checkpoint: claude (AAAA_introduce hero deal-scene) — 2026-09-17

## What was done (chronological, latest first)

### Pass 3: standalone composition was too small on mobile/tablet portrait
Root cause found in `layout()` (`src/lib/deal-scene.ts`): `compositionScale` was
computed unconditionally by the DOCKED width formula
(`0.62 + 0.38*clamp((width-1100)/460,0,1)`), which only ever evaluates to its
floor (0.62) for any width standalone renders at (<1120, and the formula's own
range starts at 1100) — never actually tuned for standalone, just an accident
of reusing the docked formula. Key insight: `compositionScale` sizes the
composition against a WORLD-SPACE frustum fixed by camera FOV/z, NOT by the
container's pixel size — so bumping the standalone box's CSS height alone
would sharpen resolution but not change the core's proportion of the box; only
`compositionScale` changes that proportion. Fix: added `STANDALONE_SCALE = 0.92`
(a fixed constant, chosen against the box's own CSS mask fade zone so the doc
orbit's outer edge stays inside where the mask starts fading), and override
`compositionScale = STANDALONE_SCALE` inside the `else if (standalone)` branch
of `layout()`. Verified visually via screenshot at 375×812 and 810×1080 — core
now reads as a proportionate ~40%+ of the box height at both, since the scale
is now width/height-independent by design.

### Pass 2 (previous session, see `checkpoint/claude-2026-09-17-aaaa-hero-scene`
earlier entry if not yet overwritten): full-circle document spawn (was biased
to the left hemisphere) + standalone mode so the scene no longer disappears
below the 1120px hero breakpoint (docked full-bleed overlay ≥1120px; framed
in-flow block <1120px with beams hidden, `<DealStage>` moved into the hero's
grid between lead/actions and console; had to remove a stray `relative` from
the content wrapper div to keep the docked overlay full-bleed against the
section rather than shrinking to the content column).

## Files changed (this pass)
- `src/lib/deal-scene.ts` — added `STANDALONE_SCALE` constant + override in
  `layout()`'s standalone branch. No other files touched this pass.

## Verification
`tsc -b`, `oxlint`, `npm run build` all clean. Visually confirmed via
screenshot (fresh tab — close+reopen was needed to get real rendering; a
long-lived dev tab in this session intermittently reports `document.hidden` /
stale HMR state that blocks `ResizeObserver`/rAF and yields black screenshots)
at 375×812 (phone) and 810×1080 (tablet portrait): core + document orbit now
fill a proportionate share of the standalone box at both sizes, no longer
looking small/adrift.

## Next steps / Risks
- `STANDALONE_SCALE = 0.92` was chosen by calculation + one visual check, not
  iteratively tuned against multiple screenshots — if the user wants it bigger
  or smaller still, adjust this one constant (no other coupled values to
  rebalance, since it no longer depends on the docked width formula at all).
