# Checkpoint: claude — 2026-09-18 (DAAB website content brief)

## What was done
Wrote `docs/daab-web-content-brief.md` — **revision 2**, 523 lines — the canonical
content brief for the still-empty `DAAB_introduce/`, modelled on
`docs/laam-web-content-brief.md` rev 2.

Revision 1 (same day) was built from source + commit log. Revision 2 added a
**live-database sweep**, which overturned three of rev 1's load-bearing claims.
That sweep is the durable value of this session.

## ⭐ Live DB evidence (daab-postgres, 2026-09-18) — expensive to reproduce

**In real use:**
- `knowledge_nodes` 16,509 · `knowledge_edges` 35,431 · `knowledge_node_embeddings` 12,039
- `ai_queries` 6,269 — **completed 5,439 / clarification_needed 652 / failed 178**
- `draft_nodes` 473 · `projects` 10 · `data_sources` 9
- Node types: document_chunk 4,978 · concept 4,866 · organization 1,743 ·
  document_section 1,468 · location 1,015 · person 693 · architecture 595 ·
  artifact 580 · document 299 · event 268 · derived_record 3 · project 1
- Edges: similar_to 20,173 · contains_section 6,446 · mentions 5,431 ·
  related_to 1,553 · **schema_fk 663** · part_of 567 · works_for 375 ·
  evidence 186 · causes 23 · derived_from 8 · schema_many_to_many 5 · schema_implicit 1
- Per project: Cảng Định An M&A 9,307 · Halcom PM3 4,746 · Cảng Định An v3 957 ·
  Sala Food 690 · C4K Staging 317 · Salonbookly v3 257 · Dasin 214 · Pharmacy Chain 21
- Query volume is **demo-shaped**: 6,018 in Aug 2026, 251 in Sept.

**BUILT BUT NEVER EXERCISED (must not go on a website):**
- `benchmark_runs` = **0**, `benchmark_questions` = **0** — the whole NL→SQL
  accuracy harness (`benchmark_runner.go`/`benchmark_scorer.go`: question bank,
  SHA-256 expected-result hash, 4 score levels, by-difficulty/by-query-type
  breakdown, trend) has never run. Ironic: the thing that would measure accuracy.
- **0** `function`/`class`/`module` nodes → code-repo indexing pushes nothing to
  the central graph. `kg_index_source`/`kg_index_status` are **LOCAL** bridge
  tools (confirmed `internal/bridge/local_index.go`) — satellite keeps its own
  store. CLAUDE.md's "knowledge graph for Ennam engineering projects" is
  contradicted by the data.
- `sessions` = **0** → `/agents` page renders an empty table.
- `agent_context` = **3 rows** (the July dogfood rows) → memory-of-record is
  real + gate-passed but essentially unused.

**TRAP:** `ai_queries.status='completed'` = *ran and returned rows*, NOT correct.
86.8% is **not** an accuracy number — documented wrong-answer cases
(`q4-duplicate-refunds-still-wrong`, `daab-q8-column-semantics-and-row-fabrication`)
would have logged as completed. Brief §7.2 forbids any accuracy percentage.

## User decisions incorporated (2026-09-18) — ALL FIVE LOCKED
- **Audience: the technical owner of knowledge/data** (CTO / head of ops / data
  lead). The "same buyer as LAAM" alternative was explicitly rejected.
  Consequence: the reader is assumed comfortable with graph/MCP/schema/read-only
  vocabulary — do not water it down.
- **Headline: candidate A** — `EVERYTHING YOUR / COMPANY KNOWS, / IN ONE PLACE.`
  (VI: `TẤT CẢ NHỮNG GÌ / CÔNG TY BẠN BIẾT, / Ở MỘT NƠI.`). Known weakness: many
  products could write that line, so the hero lead + the §2.3 edge census must
  carry the specificity. Candidate C (`ASK YOUR DATA. / TRACE EVERY / ANSWER.`)
  is reused as the **Ask** section headline.
- **Problem order: §4 unchanged** (ask → trust → every tool starts from zero).
  Promoting item 3 to first was considered and rejected — but item 3 is still the
  only uniquely-DAAB problem, so it gets the most space and hands off into the
  AAAA proof.

- **Locale: EN default, VI second** — the `LAAM_introduce` convention, the
  REVERSE of `AAAA_introduce`. Forking AAAA means flipping the default.
- **DAAB will have no chat.** Turned into positioning (§1.1): none of the 55 MCP
  tools is a chat tool — *"DAAB doesn't have a chat window. It's what your chat
  windows read from."* Dashboard `chat*` **and `favorites`** (it stores
  `ThreadFavorite` = saved chat threads) are out of scope for content.

## Brief's content decisions (flagged for sign-off, none locked)
- Pillars re-ordered **evidence-first: Ask → Ingest → Serve** (rev 1 led with
  Serve/memory because the ecosystem docs do — same staleness trap one level up).
- Memory-of-record **demoted** from headline to one sentence; the **AAAA
  master-record sync** (derived_record + provenance edges + revoke/reactivate +
  live SSE progress) carries the Serve pillar instead — a real live consumer.
- Code indexing **cut from the pitch** entirely.
- New differentiator in §2.3: **documents and DB schema in ONE graph**, proven by
  the edge-type census (`schema_fk` beside `mentions`/`contains_section`).
- Audience: technical owner of knowledge/data (CTO/data lead), alternative named.

## Features found in code worth promoting (all verified in use)
- NL→SQL is a **pipeline, not one call**: intent parse → plan harden → normalize
  → repair → SQL generate → `sql_verifier.go` (confidence level + auto-correct)
  → execute.
- **Read-only is enforced at the connection**, not by policy: `source_executor.go`
  single-use conn, session `SET TRANSACTION READ ONLY` (defence in depth),
  SELECT/WITH-only guard, timeout + row cap; writes on a physically separate
  connection gated on `AllowWrites` + table whitelist + approved playbook.
- Supabase identity is consumed (`auth_supabase.go`/`user_supabase.go`) — the
  June direction doc listed this as "chưa có".
- `/impact` blast-radius, `/schema-graph` (Cytoscape, 4 layouts, export),
  `/decisions` timeline with superseded status — all live surfaces.

## Files changed
- `docs/daab-web-content-brief.md` (rev 1 → rev 2, rewritten)
- Auto-memory corrections: `bridge-tool-count-drift` (45→**55** schemas),
  `friday-pharmacy-demo-readiness-gap` (gap 1 superseded)
- Nothing in `ennam.kg.*` or `DAAB_introduce/` touched. No commits.

## Rev 3 — register correction (user, 2026-09-18, mid-session)
User: *"đây là web marketing giới thiệu sản phẩm, nên không cần quá kĩ thuật và
khó hiểu, toàn bộ data sẽ là mock hết."* Two consequences, both now in the brief:

- **§1.2 Register.** The audience lock (technical owner) says WHO, not HOW. A
  CTO reading a product page is still reading a product page. Jargon budget ≈ 3
  words for the whole page: **MCP** (explained in one clause), **knowledge
  graph** (once), **read-only**. Banned from the page: RRF, pgvector, 384-dim,
  entity resolution, `schema_fk`, draft nodes, provenance edges, derived
  records, Bearer auth, `SET TRANSACTION READ ONLY`. §1.2 carries a
  translation table (internal → benefit). Sentence test: if it would fit in an
  API doc unedited, it is wrong for the page.
- **§1.3 All displayed data is mock — four rules.** (1) Mock what exists, never
  what doesn't — no screen for anything in §7.1 (benchmark dashboard, code map,
  agent sessions, memory timeline), since a mockup IS a claim. (2) Illustrative
  figures never read as a customer result — no "trusted by", no %, no
  testimonial, no logo wall. (3) Plausibly boring numbers, not round flattering
  ones. (4) One fictional scenario held consistently across every panel —
  recommend basing it on the synthetic `demo_mockdata/` pharmacy set.
- **§2 and the hero lead rewritten in page voice**, each pillar now given twice
  (page voice + internal substance). §2.3 reframed: the "documents and database
  in the same picture" claim leads; the edge census is demoted to internal
  backup. §5 restructured into 5.1 *what may be depicted* / 5.2 *what may be
  claimed in words without a statistic* / 5.3 *true, measured, stays off the
  page*.
- **The verified DB numbers stay internal.** Their job changed from "figures to
  print" to "what may honestly be depicted at all" — which makes the §7.1
  built-but-unused ledger MORE load-bearing, not less.

## DAAB_introduce BUILT (same session) — commit 4fa29a2, own git repo, not pushed
User: apply the AAAA/LAAM web style, layout may be arranged differently.

- Forked `AAAA_introduce/` (system layer copied verbatim: tokens structure,
  index.css, Section, Button, Eyebrow, ScrambleText, Rail, Grain, motion.ts,
  scroll.ts, 3 hooks). **Dropped `three` + `ogl`** — no WebGL; hero and
  centrepiece are DOM/SVG. Entry chunk 133 kB gzip, CSS 7.8 kB.
- **Accent: green `#4ef08f` (~144deg).** The constraint is hue distance, not
  taste: inherited `trace` is 219deg and `ion` 255deg, and the palette's own
  rule is that two accents a few degrees apart read as one colour at 1px
  borders. 144 clears both by 75deg+, and reads green against AAAA's 171 teal
  and LAAM's 187 cyan. Ground retuned to a neutral-green ink `#06090b`.
- **Layout deliberately NOT AAAA's five uniform alternating blocks:** hero →
  three-column problem band → pillar 1 (Ask) → **full-bleed centrepiece graph**
  → pillar 2 (Ingest) → pillar 3 (Connect) → trust Q&A → CTA. The centrepiece
  sits between Ask and Ingest on purpose: before the pillars it would open the
  page on the ingest claim and invert the locked evidence-led pillar order.
- **`--text-hero` had to be re-derived, and the first attempt was wrong.**
  Tuned by eye to a headline in the hero's left column → at 1440 two of three
  EN lines silently wrapped, because `text-wrap: balance` makes an overflow
  look like a design choice. Also: measuring a rendered line that has ALREADY
  wrapped reports the widest fragment, which reads as fitting — must use a
  `white-space: nowrap` probe. Real widest = **11.44 font-sizes**
  (EN "EVERYTHING YOUR"; VI "CÔNG TY BẠN BIẾT," at 11.40 — the two locales bind
  within 0.04, which is luck, not design). Fix: headline spans the FULL
  container, `clamp(1.4rem, 0.3rem + 4.4vw, 5.25rem)`, plus `text-wrap: nowrap`
  on the h1 so a future miss is visible instead of silent.
- **Real bug found by measuring:** 14px horizontal overflow at 320px — a `1fr`
  grid track still has `min-width: auto`, so `purchase_orders` pushed the
  Converge column wider and `truncate` never engaged. Fixed with
  `minmax(0,1fr)` + `min-w-0`.
- **Verified in-browser** (iframes at real widths; the Chrome window floors at
  ~500px so resizing cannot test 320): 320/375/768/1024/1440/1920 × EN/VI — all
  headline lines single-line, zero horizontal overflow, no console errors.
  `npm run build` and `oxlint` both clean.
- **Second real bug, found only by measuring INK:** each headline line sits in an
  `overflow-hidden` mask whose height IS the line box, so ink taller than the
  box is silently clipped — Vietnamese tone marks just vanish and it reads as a
  font choice. Measure with canvas `actualBoundingBoxAscent/Descent`, NOT a
  Range (a Range reports the font's metrics and will claim English is clipping
  when it is not). At 68px `CÔNG TY BẠN BIẾT,` inks 83.9px against the 84.5px
  box that AAAA's inherited `1.24` leading gives — passing by **0.6px**, which
  is a coincidence, not a margin. Raised VI `--leading-display` to **1.32**
  (~6px slack). EN unchanged at 0.94 (59.1px ink / 64.1px box).
  ⚠️ **`AAAA_introduce` may have the same latent bug** — its VI headline is
  four lines of uppercase on the same 1.24. Not touched; worth checking.
- Hero document titles moved into i18n (prose, they translate); the table names
  beside them stay hardcoded (identifiers — translating `purchase_orders` would
  show something that does not exist).
- Scenario: **Harborline Distribution** (supplier contracts + an ERP database).
  Chosen over the pharmacy set because pharmacy POS is a database only, and the
  centrepiece has to draw documents AND tables in one picture.

## REV 4 — repositioning + prose rewrite (user feedback, same session)
User: *"giọng văn không mượt đọc như AI viết, không có tính marketing chuyên
nghiệp, đọc khó hiểu, nhất là tiếng Việt, cần thể hiện được DAAB như một second
brain dành cho AI Agent vậy."*

**The thesis was there in the user's FIRST message** ("second brain trong
ecosystem") and rev 1–3 drifted off it while reasoning about who buys DAAB.
Lesson: when the user opens by naming what the product IS, that is the
positioning — build the audience analysis on top of it, not instead of it.

- **New thesis: a second brain for every AI agent.** Headline A′:
  `BỘ NÃO THỨ HAI / CHO MỌI AI AGENT / TRONG CÔNG TY.` /
  `A SECOND BRAIN / FOR EVERY AI AGENT / IN YOUR COMPANY.`
  Names the user (agents), the role, the scope — none of which a generic
  storage product could also claim. It also resolves the "no human talks to
  DAAB" awkwardness instead of hedging around it.
- **Pillar order flipped again: Connect → Ingest → Ask**, centrepiece after
  Ingest. Rev 2 led with Ask because it has the most usage; that optimised the
  wrong thing — the first screen should say what the product IS, and the AAAA
  integration (strongest fact on the page) now sits in block one.
- **The framing does NOT reinstate memory-of-record.** Being the shared brain is
  the product's PURPOSE; `kg_remember`/`kg_recall` is a FEATURE with 3 rows.
  §7.1's ban on depicting a memory timeline still stands. Watch for this — the
  new thesis makes it tempting.
- **Vietnamese is now written FIRST, English matched to it.** Writing EN→VI
  produced real defects, not just tone: `"một góc lộn xộn nhất"` (a Vietnamese
  superlative takes no indefinite article), `"Những câu bạn định hỏi sau cùng,
  chúng tôi trả lời trước"` (double inversion), four `của bạn` in one lead, and
  em-dash chains where Vietnamese wants a full stop. Rules now live in `vi.ts`'s
  doc comment + brief §1.2b. VN sentence test: *would one founder say this out
  loud to another founder?*
- **`AI Agent` stays English in both locales** — what the VN tech audience says,
  and it is load-bearing in the headline.
- **`--text-hero` re-measured** (its comment demands it on a headline change):
  binding line is now **EN `FOR EVERY AI AGENT` at 12.60** font-sizes, up from
  11.44 — and **English binds, not Vietnamese**, reversing the usual assumption.
  Clamp retuned to `clamp(1.3rem, 0.28rem + 4.3vw, 5.25rem)`, re-verified at
  320/375/768/1024/1440/1920 × EN/VI.
- Commits: `4fa29a2` (site) → `b7bc616` (leading fix) → `9a0d014` (rev 4).
  Brief is at **revision 4**, 732 lines.

## REV 5 — register matched to LAAM_introduce (same session)
User: *"các phần nội dung phía dưới nhiều chỗ giọng văn vẫn khô khan, khó hiểu,
và chưa chuyên nghiệp. Tham khảo trang LAAM introduce đi."*

**Rev 4 overcorrected.** Fixing translated-English syntax, I went to clipped
startup fragments ("Hỏi gì cũng phải dán tài liệu vào. Mà dán xong, hết phiên là
quên.") — which reads terse, not confident. Both failure modes are real: long
and winding, AND short and clipped.

**The reference that fixed it: `LAAM_introduce/src/lib/i18n/vi.ts`.** What it
does that this page now does too — this is the reusable part:
1. **Complete sentences with a through-line.** Brevity = cutting spare words,
   NOT dropping subject and verb.
2. **Subject is `doanh nghiệp` / `người dùng` / `đội ngũ`, never `bạn`.** On a
   B2B page the distance in address IS part of sounding professional. LAAM
   almost never says `bạn` in body copy.
3. **Every problem carries its own answer** — LAAM's `solutions` items are
   `{title, body, answeredBy}`. Biggest readability win by far: the reader meets
   a difficulty and its resolution together instead of holding three open
   questions for two screens. Now §4's structure, and a `answeredBy` field in
   both locale files + Problem.tsx.
4. **Technical vocabulary stays English** where a Vietnamese speaker says it in
   English: `database`, `agent`, `MCP`, `workflow`, `PostgreSQL`. Translating
   these makes a page HARDER to read.
5. **A closing couplet.** LAAM ends on "Doanh nghiệp không phải đổi mình cho vừa
   AI. / AI phải vừa với doanh nghiệp." DAAB now closes on its own pair.
6. VN test, updated: *would this sit in a solution brief sent to a board?* If it
   reads like a text message, rewrite.

**Layout followed the copy:** problem band + trust block got the two-column
header the centrepiece already used (the new leads needed somewhere to go, and
both titles were leaving half a band empty); problem cards stretch their bodies
with `flex-1` so the rule above each answer lands on one horizontal line across
all three columns. Also rendered `trust.lead`, which rev 4 added to i18n and
never displayed.

Brief is at **revision 5** (§1.2a records the LAAM register rules).
Commit `1e2a965`. Re-verified 320→1920 × EN/VI, all clean.

## HERO: three.js brain + two-column layout (same session)
User asked for a three.js brain in the hero, pointing at
`threejs-dala-replica.vercel.app`, then cloned the repo to
`other_projects/threejs-dala`.

**Reading their SOURCE, not their output, is what fixed it.** The gap was never
the model — it was four choices where I had picked the opposite every time:
1. **The hover effect is SCALE + SPIN, not displacement.** Instances grow up to
   8x and rotate about their own origin near the pointer. Pushing particles
   away opens a hole; growing them brings the surface alive.
2. **Opaque, not additive.** Their fragment shader is `vec4(vColor, 1.0)` on
   wireframe geometry. Additive + transparency on a dense field = glowing smear
   with no edges.
3. **Per-instance base size spans 10x** (0.3–3). Most of the grain comes from
   this one number.
4. **Rotation belongs in the shader**, on the local vertex BEFORE
   `instanceMatrix`. Baked into the matrix it is frozen and cannot respond.

**`active` is a RESERVED WORD in GLSL.** Using it as a parameter name made both
shaders fail to compile; the only layer still rendering was the edges, which
looks like a deliberate wireframe effect rather than an error. Cost a round of
guessing before reading the console.

**Model:** `public/brain.glb` from that MIT repo (notice in
`public/brain.LICENSE.txt`). It does NOT state the mesh's own provenance —
replace before commercial use. Procedural silhouettes were tried first and
looked bad: a brain is too specific a shape to approximate. Points are sampled
off the SURFACE (`MeshSurfaceSampler`, area-weighted), not the 2,879 vertices,
which are too sparse and clump where the mesh is subdivided.

**LAYOUT — the lesson worth keeping.** Four arrangements failed the same way
before the cause was named: **the full-width headline was making the hole.** Its
ink reaches ~2/3 across, leaving a dead quarter under its right half, so the
picture could only be behind the words, cornered, or small. Moving the picture
could never fix a hole the headline made. Fix = the AAAA layout: headline INSIDE
a 52% left column, brain owns the rest of the hero at full height. Every
negative margin and % offset disappeared.

**`--text-hero` now has TWO ramps** — the hero has two layouts and one ramp is
wrong for one of them (a ramp tuned for the 52% column sets 24px on a 768
tablet with 56px of room). Arithmetic per breakpoint is written out in
tokens.css. Binding line is EN `FOR EVERY AI AGENT` at **12.60 font-sizes**;
English binds, not Vietnamese.

Commits `90804fd` → `06b84f5`. Entry chunk still 136 kB gzip; three.js is a
separate 184 kB chunk behind a dynamic import, never downloaded for
reduced-motion or sub-640px visitors.

## PANELS: all three now RUN their claim instead of listing it
User asked for animation on each pillar panel in turn. The same diagnosis
applied to all three, and it is the reusable part:

**A static list says a claim; it cannot show a thing happening.** Each pillar's
strongest claims are about BEHAVIOUR — "access is scoped per project", "a
scanned document is caught and read again", "extraction stops at a person",
"answers arrive with their sources" — and none of those is visible in a
finished list. So each panel now plays the thing out on a beat loop.

- **Connect** (`b254c16`): a request runs. An agent lights as source → scope
  checks → lands on an allowed row. **Every fourth pass is refused** and the
  boundary rule turns red for that beat only. Ratio chosen deliberately: deny
  every pass reads as a broken integration, deny none shows only the happy path
  (the half nobody doubts).
- **Ingest** (`aa2b9cb`): the run executes. Rows read in order; the scanned file
  takes TWO beats and turns amber (the asymmetry is the only interesting moment
  — a uniform loop would hide it); drafts arrive and STAY. Three closing beats
  of the queue just sitting there — that pause IS the "nothing enters without
  approval" claim.
- **Ask** (`2629f0d`): the question types itself in (the `.caret` class was
  already in index.css, written for this and never used); sources land ONE AT A
  TIME (three at once read as decoration, three in turn read as assembly); the
  read-only rule seals on the last beat.

**Two layout rules learned the hard way, applied to all three:**
1. **Reserve height, never grow into it.** A panel that resizes mid-loop drags
   the whole section down while someone is reading the prose beside it.
2. **Fade the CONTENT, not the container.** Fading a whole block leaves beats of
   blank panel that read as broken; keeping labels and rails visible makes the
   same space read as a form waiting to be filled.

Every panel keeps a REST beat so it has a calm state, and reduced motion gets
the finished state permanently with no cycle.

**Centrepiece graph** (`20c9bbf`, `c7ba1a2`): redrawn as spine + procedural
field (seeded, not random — an unseeded layout re-rolls per mount and no
screenshot ever matches the live page), canvas 2D, then wrapped in `PanelFrame`
because it was the only illustrative box on the page without one, which is why
it read as foreign.

## Next steps
- User picks: audience (§1), headline A/B/C, problem order.
- Then fork `AAAA_introduce/` → `DAAB_introduce/`, **flip locale default to EN**.
- Worth doing separately: put a superseded banner on
  `docs/daab-ecosystem-direction-2026-06-24.md` itself.
- Open question for the product owner, not the website: benchmarks + code
  indexing + session tracking are fully built and unused. Use or remove.

## Blockers / Risks
- §7 lists what copy must not contradict: BA-033 cross-doc retrieval gated NO-GO;
  per-user isolation not built; Phase-A GenerateKG IDOR still open; demo data
  ends 2026-08-04.
- Embed cold-start ~25s → 502 on first query after idle: NOT re-verified today.

Links: `mem:decisions/daab-rbac-isolation-keystone-gate-verdict`
`mem:checkpoint/ocr-content-loss-fix-2026-07-16` `mem:checkpoint/claude-2026-09-17`
`mem:checkpoint/claude-2026-08-04` `mem:checkpoint/claude-2026-09-07`
