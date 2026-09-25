# Checkpoint: claude — 2026-09-18 (LAAM_introduce nav/footer port)

## What was done
User asked to update LAAM_introduce's header (Nav) and footer to match AAAA_introduce's
style (screenshots given: bordered-square icon+two-line wordmark nav; wordmark+tagline+
right-aligned org-link footer).

- `Nav.tsx`: added a bordered-square "L" icon mark (signal color) beside a two-line
  block — "LAAM" (unchanged, still carries `data-navmark`) + new "by Ennam" subtitle
  line. Deliberately did NOT move `data-navmark` onto the new icon: BootSequence's own
  FLIP-on-exit animation measures `[data-navmark]` and flies its own text-shaped mark
  onto it — moving the target to a differently-shaped icon box would make a rectangle
  of text land on a square and look like a bad crop. Verified boot FLIP still lands
  cleanly post-change (scale 0.5184, settles, unmounts cleanly, VI+EN both fine).
- `Footer.tsx`: restructured from a single flex row (wordmark left / "org · Ennam" link
  right) into AAAA's grid layout — wordmark + new tagline paragraph on the left,
  "Ennam" alone (no "org ·" prefix) as the right-aligned link.
- Added `footer.tagline` to both `en.ts` (canonical here, unlike AAAA where vi.ts is
  canonical) and `vi.ts` — condensed one-liners derived from each locale's own
  `meta.description` first sentence.

## Key judgment call
LAAM's `COPY.footer.org` ("Enterprise AI Agent"/"AI Agent doanh nghiệp") is a PRODUCT
DESCRIPTOR, not an org name — unlike AAAA's `footer.org` which literally IS "EnNam SJC".
Blindly copying AAAA's "by {footer.org}" pattern would have rendered "by Enterprise AI
Agent" (nonsense). Used the literal string "Ennam" instead (matching the footer's own
pre-existing hardcoded, non-localized "Ennam" link text) since that's the actual maker
name — the correct semantic parallel to AAAA's "by EnNam SJC". `footer.org` is now only
referenced in a code comment (not deleted — a bigger content decision than was asked).

## Current state
- Build/typecheck/lint clean (LAAM's own preexisting lint warnings in AuroraField.tsx/
  DistanceTrack.tsx/useMediaQuery.ts/ChatPanel.tsx unchanged — none new).
- Verified at 1280px (VI+EN) and 375px: no overflow, nav fits (364px used of 375px).
- Not committed (repo rule: only commit when asked). `git diff --stat`: 4 files,
  Footer.tsx, Nav.tsx, en.ts, vi.ts.

## Follow-up round — user: hide mobile CTA, centre footer, "Ennam" -> "Ennam SJC"
- Nav CTA ("Book a demo") now `hidden ... sm:block`, matching AAAA's exact pattern —
  the icon+2-line mark made the row tighter, and mobile still reaches the same
  destination via hero/closing CTAs.
- Footer: `text-center sm:text-left` on the container; tagline `<p>` (the only
  multi-line, `max-w-[56ch]` block) needed `mx-auto sm:mx-0` in ADDITION —
  `text-center` alone centres text inside a still-flush-left box, doesn't move the
  box itself. Verified reverts cleanly to left-aligned at `sm:`+.
- Footer link "Ennam" -> "Ennam SJC" (full maker name, matching AAAA's "EnNam SJC").
  Given I'd earlier justified the nav's "by Ennam" as "matching the footer's own
  literal text", I ALSO updated the nav subtitle to "by Ennam SJC" to keep that
  stated rationale true — not separately requested, but the direct consequence of
  my own prior design note; flagged to user rather than silently changing scope.
- Note: LAAM's copy still calls it "Ennam" (capital E only, not AAAA's "EnNam") —
  kept that existing casing, just appended " SJC", per the user's literal ask.

## Follow-up round 3 — user: add "A product of Ennam SJC" to LAAM's Contact CTA
Matched AAAA's Contact.tsx exactly: added `contact.note` to en.ts (canonical)/vi.ts
("A product of Ennam SJC" / "Một sản phẩm của Ennam SJC"), rendered as a link to
https://ennam.vn/ below the two CTA buttons in `Contact.tsx`, same classes AAAA
uses verbatim. Verified at 375px: renders, centred, no overflow, matches reference
screenshot.

## Follow-up round 4 — user: replace boot screen's "LAAM" text mark with the icon
Two coordinated file changes, because they're one FLIP animation:
- `BootSequence.tsx`: `[data-boot="mark"]` swapped from plain text "LAAM" to the
  same bordered-square icon AAAA's boot uses (`size-12 sm:size-14`, "L" glyph).
- `Nav.tsx`: `data-navmark` MOVED from the wordmark text span to the icon span
  (the square, not "LAAM"). This reverses my earlier explicit design decision —
  I'd deliberately kept it on the text specifically BECAUSE the boot mark was
  text-shaped; now that the boot mark is ALSO an icon, icon-to-icon is the
  correct FLIP target (was the whole point of the original comment's reasoning).
  Updated both files' comments to match — the old comment explaining why NOT to
  move it would have been actively misleading left in place.
Verified via the same instrumented-`setInterval`-in-`initScript` technique used
earlier on AAAA (screenshots can't catch a 2.5s animation across MCP round-trips):
scale settles at 0.5714 (=32/56, same ratio as before — unaffected by the shape
change, since flyMarkToNav measures bounding-box width regardless of content),
clean unmount, no errors. Confirmed at 375px: no overflow, `data-navmark` sits on
the "L" `<span>`, not text.
Build/typecheck/lint clean.

## Follow-up round 5 — user: boot logo "nhấp nháy" (flickers), not smooth like AAAA
Real bug from round 4's icon swap, not a false alarm. LAAM's intro timeline still
had `.from("[data-boot='mark']", { opacity: 0, duration: 0.4 })` — the ORIGINAL
tween written for the plain-text wordmark. AAAA's equivalent is
`{ opacity: 0, scale: 0.9, duration: 0.4 }`. A pure opacity fade on a
HARD-BORDERED SQUARE (vs. antialiased letterforms) under `expo.out` easing (which
front-loads nearly all the opacity change into the first ~150ms) reads as a
pop/flicker, not an arrival — the border edges have nothing continuous for the eye
to track. Added `scale: 0.9` to match AAAA exactly.
`origin-top-left` was already present on the mark from round 4's port (needed for
flyMarkToNav's exit FLIP), so no change needed there.
Verified with a NEW instrumented technique (20ms-interval opacity+transform
sampler via `initScript`, distinct from the mark-existence poller used for the
exit FLIP): opacity and scale now ramp in lockstep from 0/0.9 to 1/1 smoothly
over ~350ms (25 samples, monotonic, no jump) — confirms the fix, not just that it
compiles.
Build/typecheck/lint clean (same 5 pre-existing warnings, none new).

## Next steps / blockers
None. Task complete as scoped (header + footer only — did not touch BootSequence.tsx
or other LAAM sections, per the user's explicit scope).
