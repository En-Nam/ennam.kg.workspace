# DAAB Marketing Home Page — Design Spec

**Ennam Knowledge Graph Platform — Public Marketing Landing**
Route: **`/` (public root)** in `ennam.kg.next/src/app/(marketing)/` — Next.js 16 App Router, no auth.
Date: 2026-06-24 · Status: **Approved-for-build** synthesis of design-panel concepts A/B/C, with every panel blocker resolved and every recited number corrected against source of truth.

> Produced by a counter-arguing design panel (3 Designers → Taste-Critic + Frontend-Feasibility + QA/Accessibility per concept → synthesis → completeness critic), then a ground-truth verification pass that corrected the fabricated facts the panel was seeded with (AGENTS.md Rule 13).

---

## 0. Provenance of the facts (read this first)

Every number on this page is sourced from code/config, **not** recited from docs:
- Node/edge taxonomy: `ennam.kg.go/config/config.yaml` + DB CHECK in `db/migrations/000061_ba031_closed_vocab.up.sql`.
- MCP tools: `ennam.kg.go/internal/bridge/schema.go`.
- Dashboard pages: route folders under `ennam.kg.next/src/app/(dashboard)`.
- Layout modes & performance NFRs: `ennam.kg.requirements/.../BA-004` and `BA-001` (NFR-002/003/004).
- Code-extraction behavior: `BA-003-code-indexing.md` + `config.yaml` `architecture` node.

**A `fixtures-vs-schema` type test (see §11) makes these facts non-regressable** — fixtures cannot drift back into fabrication.

---

## 1. Positioning + Design Read

**One-line positioning (VI-first):** "Nguồn sự thật duy nhất cho kỹ thuật do AI dẫn dắt." / "The single source of truth for AI-driven engineering."

**Design Read:** A pre-login B2B dev-tool landing for AI-agent teams, engineering leads, and CTOs, in a premium-dark **"observatory / data-as-art"** language — Linear-grade restraint with exactly one cinematic moment: the product's own **live WebGL knowledge graph**. Every section below the hero is a **real product surface fed by static fixtures** (live graph, real Cytoscape mini-graph, the genuine MCP tool list, the real two-gate flow, a real recharts sparkline), so the product is **shown, never faked**. Tailwind v4 + Poppins display + JetBrains Mono for the data register.

**Base concept:** B "The Knowledge Observatory" (highest blended quality; the only concept whose accent math survived verification; cleanest layout variety). **Grafted:** C's real-product-as-imagery spine + the extraction connector-draw; A's strict motion tiering + static-poster-first LCP + one-WebGL-context rule. **Cut:** B's unbuildable continuous scroll-thread, C's fabricated accent provenance, and the recited "code node-type" palette (Rule 13 fabrication).

---

## 2. Locked Product-Owner Decisions

1. **Public marketing landing at the root `/` URL**, pre-login, with a **Login button**.
2. Clean-premium **anti-slop on a dark near-black canvas**; ONE locked accent; quiet glass, no neon spam, no AI-purple.
3. ONE bold motivated motion moment = a **REAL interactive WebGL knowledge graph** (`react-force-graph-3d` / `three` v0.184, already installed) with reduced-motion + low-power + no-WebGL fallbacks and a perf budget.
4. Deliverable = a **full working coded page**, built after this spec is approved.
5. **Bilingual, Vietnamese-FIRST + English**; lightest viable i18n (typed dictionary + cookie, no framework rebuild).
6. **`motion` (`motion/react`) approved** as the only new dependency.

### 2.1 Routing change required by decision #1
- `(marketing)/page.tsx` takes over **`/`** (public, no auth).
- The current authenticated overview `(dashboard)/page.tsx` (`/`) **relocates to `/dashboard`**.
- Login-success redirect changes from `/` → **`/dashboard`**; any internal "home" links to the dashboard root update to `/dashboard`.
- Marketing nav shows a prominent **"Đăng nhập / Login"** button → `/login`.

---

## 3. Token System (locked, concrete, contrast-verified)

> Ratios computed against `--canvas` `#0A0B0D` / `--surface` `#121417`. Pure black and pure white are both avoided.

| Token | Value | Contrast | Use |
|---|---|---|---|
| `--canvas` | `#0A0B0D` | — | page background |
| `--surface` | `#121417` | — | cards / panels |
| `--surface-2` | `#171A1E` | — | tinted bento cells |
| `--accent` (Observatory Teal) | `#5FB8A6` (~165°, sat ~38%, <80%) | **8.34:1 / 7.81:1** — AA text, AAA, 3:1 non-text | CTA fill, focus ring, active nav, sparkline, extraction connector, live/verified graph nodes |
| `--accent-foreground` | `#0A0B0D` (near-black) | **8.34:1 on teal** | text/icon ON the teal fill. **White-on-teal = 2.02:1 is FORBIDDEN.** |
| `--text-primary` | `#ECEDEF` | **16.81:1** | body, headings |
| `--text-muted` | `#9AA0A8` | **7.47:1 / 7.0:1** | secondary text |
| `--hairline` | `rgba(236,237,239,0.08)` | decorative | non-semantic dividers |
| `--border-interactive` | `rgba(236,237,239,0.18)` | + focus ring | sole bound of an interactive region |
| `--radius` | `16px` cards / `8px` inputs+chips / full-pill buttons | — | ONE 3-tier scale; no other radii |

**Focus ring:** 2px `--accent` + 2px offset on neutral/ghost elements; on the teal-FILLED primary CTA the ring is `--text-primary #ECEDEF` (never teal-on-teal).

**Node-data colors (quarantined to the hero graph + the taxonomy strip ONLY — never UI chrome):** graded **zinc tints** (`#3A3F46` → `#C4C9D0`) with `--accent` teal marking live/verified nodes. Node/edge identity is always carried by a **mono TEXT label**; color appears only as a `≥3:1` swatch. This lives in a NEW `graphPalette.ts` — it does **NOT** import `src/lib/graph/styles.ts` (the banned full-saturation neon set).

**Fonts:** Display = **Poppins 600/700**, `tracking-[-0.02em]`. Body/UI = Poppins 400/500, `max-w-[62ch]`. Mono (numbers, latencies, counts, MCP tool names, code) = **JetBrains Mono**. Re-declared in the marketing layout with `subsets: ['latin','latin-ext','vietnamese']` so VI diacritics (ế/ộ/ữ) render. No Inter, no Satoshi, no serif default.

---

## 4. Page Structure (9 sections, bilingual copy, real facts)

> Every visual is a REAL component on static fixtures. Div fake-screenshots are banned and absent. Eyebrow budget = 3 (`ceil(9/3)`), used = 0. Layout families = 9 distinct (≥4 required); the single editorial-split repeat is non-consecutive (zigzag cap respected).

### 4.1 Hero — Live Graph Observatory
- **Job:** Prove the single-source-of-truth promise with the live 3D graph; drive the one primary action.
- **Layout family:** Asymmetric split (copy `col-span-5` left / live WebGL `col-span-7` right, bleeding off the right edge). Anti-center.
- **Visual:** LIVE `react-force-graph-3d` constellation from a static fixture shaped on the **real 20 node types + 25 edge relationships**; zinc tints + teal for live nodes; slow auto-orbit. Wrapped in `<figure>` with a text equivalent (see §9). **Node ceiling ≤ 80 in the live path**; the full set appears only in the static poster.
- **VI:** H1 "Nguồn sự thật duy nhất cho kỹ thuật do AI dẫn dắt" · Sub (18 words) "Đồ thị tri thức nối quyết định với mã nguồn trích xuất tự động, cho agent và người."
- **EN:** H1 "The single source of truth for AI-driven engineering" · Sub "A knowledge graph linking decisions to auto-extracted code, for agents and humans."
- **Actions:** Primary "Khám phá đồ thị / Explore the graph" (teal fill, near-black label, leading icon) → **smooth-scrolls to and focuses the live hero graph** (the page is the demo). Nav button "Đăng nhập / Login" (teal) → `/login`.

### 4.2 Problem — Why flat markdown loses knowledge
- **Job:** Name the enemy (knowledge loss in flat docs), pivot to typed/versioned/linked graph.
- **Layout family:** Full-width editorial manifesto over a faint code-generated SVG constellation motif (`pointer-events-none`, atmosphere only).
- **VI:** H "Markdown phẳng đánh mất tri thức. Đồ thị thì không." · Sub "Node và quan hệ có kiểu, được đánh phiên bản, liên kết và tìm kiếm trên Postgres + Apache AGE."
- **EN:** H "Flat markdown loses knowledge. A graph does not." · Sub "Typed, versioned, linked, searchable nodes and relationships on Postgres + Apache AGE."

### 4.3 Extraction — Code knowledge, automatically (standout)
- **Job:** Prove auto-extraction truthfully: tree-sitter AST → Claude Haiku 4.5 one-line summary, SHA-256 cached, stored as a searchable node.
- **Layout family:** Editorial split — real mono code snippet (existing `rehype-highlight`) left / real re-skinned `NodeCard` (fixture-fed) right.
- **Truthful model:** the extracted node is an **`architecture` node** with `properties.kind = "function"` and the Haiku summary — NOT a fictional "function" node type. The card shows: `architecture · kind: function`, the symbol name, the one-line AI summary.
- **Standout motion:** a single teal connector draws from the highlighted function in the snippet to the node card — the page's one causal beat ("your code becomes searchable knowledge").
- **VI:** H "Mã nguồn tự kể câu chuyện của nó" · Sub "Tree-sitter phân tích AST cho TypeScript và Python. Claude Haiku 4.5 tóm tắt một dòng, cache theo SHA-256."
- **EN:** H "Your code explains itself, automatically" · Sub "Tree-sitter parses TypeScript and Python ASTs. Claude Haiku 4.5 writes one-line summaries, cached by SHA-256." (Dart is on the roadmap — not claimed as live.)

### 4.4 Dual access — Agents and humans
- **Job:** One graph, two front doors: MCP tools for agents, a dashboard for humans.
- **Layout family:** 2-cell asymmetric bento (60/40) — exactly 2 cells for 2 audiences.
- **Visual:** Cell A — real fixture-fed MCP tool list in mono (real names: `kg_store_decision`, `kg_search`, `kg_traverse`, `kg_get_context`, `kg_get_impact_analysis`, …) with count badge **`35`** (verify registered count at build — see §11). Cell B — real **2D Cytoscape** mini-graph thumbnail (declared decorative; NO second WebGL context).
- **VI:** H "Một đồ thị, hai cách dùng" · Sub "35 công cụ MCP cho agent. Dashboard Next.js 31 trang cho con người. Cùng một đồ thị."
- **EN:** H "One graph, two ways in" · Sub "35 MCP tools for agents. A 31-page Next.js dashboard for humans. The same graph."
- **Action:** text link "Đăng nhập để khám phá / Sign in to explore" → `/login` (distinct intent from the hero's on-page scroll).

### 4.5 Enforcement — Knowledge is required, not suggested
- **Job:** Differentiate on enforcement: Gate 1 schema + Gate 2 completeness + per-session provenance + cross-project edges.
- **Layout family:** Full-width horizontal process-flow band.
- **Visual:** STATIC valid-vs-rejected payload diagram (malformed payload struck at Gate 1; valid one accepted with a teal tick), a small real cross-project edge SVG, and a mono session-provenance row (git `.kg_session`). No scripted bounce.
- **VI:** H "Tri thức là bắt buộc, không phải gợi ý" · Sub "Cổng 1 kiểm tra schema. Cổng 2 kiểm tra tính đầy đủ. Mỗi node ghi nhận phiên agent đã tạo ra nó."
- **EN:** H "Knowledge is enforced, not suggested" · Sub "Gate 1 checks schema. Gate 2 checks completeness. Every node records the agent session that created it."

### 4.6 Performance — Fast at real graph scale
- **Job:** Back claims with the real, defensible NFRs.
- **Layout family:** Metric band of breathing mono numerals (no card boxes, no filled progress tracks) + a real recharts sparkline (declared decorative).
- **Visual + figures (all real NFRs from BA-001):** `<500ms` graph traversal (depth 3, 10k nodes), `<200ms` search (10k nodes), `<10ms` Gate-1 node validation. Sparkline = single teal stroke, no background track, the time axis labeled illustrative.
- **VI:** H "Nhanh ở quy mô đồ thị thật" · Sub "Duyệt đồ thị dưới 500ms ở độ sâu 3 trên 10k node. Tìm kiếm dưới 200ms. Kiểm tra node dưới 10ms."
- **EN:** H "Fast at real graph scale" · Sub "Graph traversal under 500ms at depth 3 on 10k nodes. Search under 200ms. Node validation under 10ms."

### 4.7 Type system — A typed vocabulary for everything you know
- **Job:** Make the schema tangible — and serve as the **keyboardable text equivalent** of the hero graph.
- **Layout family:** Content-exact 3-cell bento.
- **Truthful content:** **20 typed node types** (decision, concept, requirement, task, initiative, document, dataset, architecture, discovery, person, organization, event, project, … and more), connected by **25 relationship types**, governed by **49 whitelist rules**. Representative chips (≈8–10) + a quiet "…và nhiều hơn / …and more". Each chip = a zinc swatch + a mono text label; edge types shown as a typed mono list with relationship arrows. No live WebGL.
- **VI:** H "Một từ vựng có kiểu cho mọi tri thức" · Sub "20 loại node, 25 loại quan hệ, 49 quy tắc hợp lệ. Có phiên bản và liên kết chéo dự án."
- **EN:** H "A typed vocabulary for everything you know" · Sub "20 node types, 25 relationship types, 49 whitelist rules. Versioned and cross-project."

### 4.8 Cost-aware backbone — An AI backbone that watches the bill
- **Job:** Address the CTO budget objection: Haiku 4.5 default, multi-provider circuit breaker, budget tracking.
- **Layout family:** Vertical-stack centered statement band + a compact static provider/breaker SVG diagram (illustrative values labeled).
- **VI:** H "Backbone AI có ý thức về chi phí" · Sub "Mặc định Haiku 4.5 chi phí thấp, circuit breaker đa nhà cung cấp, theo dõi ngân sách."
- **EN:** H "An AI backbone that watches the bill" · Sub "Low-cost Haiku 4.5 by default, a multi-provider circuit breaker, and budget tracking."

### 4.9 Closing CTA + Footer
- **Job:** Single conversion repeating the hero intent; quiet footer.
- **Layout family:** Centered closing band over a faint static graph motif + multi-column hairline footer.
- **Visual:** Low-opacity static constellation behind the CTA; footer = plain hairline columns. NO version stamps, NO locale/time strip, NO decorative dots.
- **VI:** H "Ngừng đánh mất tri thức của đội ngũ" · Sub "Đưa quyết định và mã nguồn vào một đồ thị duy nhất."
- **EN:** H "Stop losing what your team knows" · Sub "Put decisions and code into one graph."
- **Action:** Primary "Khám phá đồ thị / Explore the graph" (scrolls to hero) + "Đăng nhập / Login" → `/login`. Footer links only — no third CTA intent.

---

## 5. 3D WebGL Hero — Technical Spec

- **Library:** `react-force-graph-3d` (already installed) wrapping `3d-force-graph` + `three` v0.184. No `@react-three/fiber` (the library owns three directly).
- **SSR-safe mount (proven pattern):** a `'use client'` `HeroGraph` leaf that **statically** imports `ForceGraph3D`, wrapped by `next/dynamic(() => import('./HeroGraph'), { ssr:false, loading: <StaticConstellation/> })` — copying the repo's existing `KnowledgeGraphWrapper.tsx` (`next/dynamic` + `React.memo`). **NOT** a `useEffect` dynamic import.
- **Data:** static bundled `graph.fixture.ts` shaped on the **real 20 node types + 25 edge relationships**. **No API/BFF call** — the BFF returns 401 without a session and the page is public. Fixture nodes carry **pre-baked x/y/z** so the live graph never runs a cold layout. Live node ceiling **≤ 80**; full set only in the poster.
- **Config:** `nodeColor` = zinc tints, teal for live/verified; `backgroundColor` transparent over `#0A0B0D`; **bloom OFF**; `linkDirectionalParticles 0`; link opacity ~0.18; `warmupTicks` set for an instant-settled first paint, then `cooldownTicks ~120` → **freeze** the sim; `renderer().setPixelRatio(Math.min(devicePixelRatio, 2))` after mount; IntersectionObserver pauses/tears down the renderer on scroll-out.
- **Perf budget:** the **static poster is the unconditional first paint and the LCP element** (LCP = headline text + poster, target **<2.5s**). Defer ALL three.js JS **post-LCP** (`requestIdleCallback` + capability gate) — NOT "in view" (the hero is above the fold). Reserve the canvas aspect-ratio box (**CLS <0.1**). Freeze after cooldown (idle CPU ~0, **INP <200ms**). The `(marketing)` layout imports only `LocaleProvider`, never `QueryProvider`/`ProjectProvider`. **Exactly ONE WebGL context page-wide.**
- **Delivery / fallbacks:** static-poster-first for ALL clients. Upgrade to live WebGL only when the gate passes: `matchMedia('(min-width:1024px) and (pointer:fine)')` AND not `prefers-reduced-motion` AND not `navigator.connection?.saveData` AND WebGL2 present AND `requestIdleCallback` fired. On mobile / coarse-pointer / save-data / reduced-motion / no-WebGL → never load the 3D chunk; render the static constellation. Catch `webglcontextlost` → swap to the poster.
- **Interaction:** drag-orbit + hover-label are decorative niceties (canvas `aria-hidden`). A visible, keyboard-reachable **Pause/Play** toggle controls the auto-orbit (WCAG 2.2.2). The graph's information is reachable non-visually via the figure `aria-label` + the Type-system section.

---

## 6. Motion Plan (dial 5; tiered; "motion claimed = motion shown")

**Library:** `motion` (`motion/react`) — approved — for spring scroll-reveals, count-ups, and its `useReducedMotion` hook. NO GSAP (no pinned/scrub section is justified). three.js stays isolated in the hero leaf. Build ONE shared `useReducedMotion` + `saveData` hook; everything above intensity 3 routes through it and renders final state synchronously when reduced. No window scroll listeners — `whileInView` / IntersectionObserver only.

**Tier-1 (MUST ship AND degrade to static):**
1. Hero auto-orbit + force-settle — *this knowledge is alive and interconnected, not flat files.* (reduced → frozen poster)
2. Performance numbers count-up once on view — *emphasis on real measured values* (final value in DOM, animation layer `aria-hidden`; not framed as a live read). (reduced → instant final)
3. Extraction connector draw (function → node card) — *code becomes searchable knowledge* (the standout). (reduced → pre-drawn)
4. Sparkline draws once left-to-right — *latency stays flat as the graph grows.* (reduced → completed line)

**Tier-2 (ship OR static fallback, never stubbed):**
5. MCP tool row highlights the matching edge on `:hover` AND `:focus` — *agents and humans read the same graph.* (fallback → static)
6. Taxonomy chip highlights matching nodes on `:hover` AND `:focus` — *these types are what you saw orbiting above.* (fallback → static emphasis)

**Cut:** the continuous cross-page scroll-thread + traveling node-pulse (B), the "Gate-1 blocks the thread" bounce (B), the self-typing MCP filter (C). Optional decorative per-section left-gutter draw lives behind `@supports(animation-timeline)` → static line on Safari/iOS. Footer drift: at most one low-amplitude ambient loop, frozen under reduced-motion. **Zero marquees.**

---

## 7. i18n Approach (lightest viable, VI-first)

A single typed dictionary `(marketing)/lib/dict.ts` exporting `vi` and `en`. **Parity is compile-time enforced:** `const en = { … } satisfies typeof vi` (a missing/renamed EN key fails `tsc`). A tiny `'use client'` `LocaleProvider` holds `'vi' | 'en'`, defaults to **vi**, persisted to cookie **`daab_lang`** (namespaced away from LAAM's `laam_lang`). The marketing layout reads the cookie server-side (`next/headers` `cookies()`) for vi-first first paint and sets `<html lang>`. `useT()` returns `t('hero.headline')`. The VI|EN toggle (nav + footer) flips context + cookie + `document.documentElement.lang`. No `next-intl`, no `[locale]` route segments. Number/mono strings (35, <500ms) are locale-invariant. **All** non-copy strings (graph `aria-label`/`alt`, Pause label, tooltips, icon names, recharts axis/tick labels, loading/empty/error copy) live in the dictionary, vi+en.

---

## 8. Icon + Font Final Decisions (Rule 11)

- **Icons: KEEP lucide-react** (standardized across 31 dashboard pages). Taste skills prefer Phosphor, but AGENTS.md Rule 11 = conform, and a second icon family for one route violates "one family per project." **Mitigation:** global `strokeWidth={1.5}` (lucide defaults to the banned thick 2), `size 16–18`, sparse usage (nav, CTA arrow, dual-access split). Tradeoff surfaced, not silently forked.
- **Fonts: KEEP Poppins + JetBrains Mono.** Poppins is not banned and is already bundled; a third display family is unjustified weight against LCP and risks incomplete VI diacritics. The single required change: re-declare both with the `vietnamese` subset.

---

## 9. Accessibility Checklist (WCAG AA)

- **Canvas text alternative (1.1.1):** hero canvas is decorative — `<figure>` wrapper, canvas `aria-hidden` + non-focusable; figure has a localized `aria-label` (vi: "Đồ thị tri thức trực tiếp nối các node quyết định, mã nguồn và yêu cầu"; en: "Live knowledge graph linking decision, code and requirement nodes") + a visually-hidden text equivalent naming the **20 node types and 25 relationship types**. The static fallback `<img>` carries the SAME non-empty localized alt. Page is fully comprehensible with the graph removed.
- **Decorative live components:** the **Cytoscape mini-graph (§4.4) and the recharts sparkline (§4.6) are also declared decorative** (`aria-hidden`, non-interactive); their information is carried by adjacent real text. They are NOT keyboard traps.
- **Reduced motion + pause (2.2.2, 2.3.3):** `prefers-reduced-motion` is the authoritative gate (CSS `@media` + JS `matchMedia`), halting ALL animation and rendering final state synchronously. A visible keyboard-reachable Pause/Play stops the auto-orbit independent of the OS flag. `saveData`/`(update:slow)` are best-effort perf add-ons only.
- **Keyboard (2.1.1, 1.4.13):** all interactive elements are real focusable button/link controls; every `:hover` highlight also fires on `:focus`; no info conveyed by hover alone.
- **Contrast (1.4.3, 1.4.11):** text 16.81:1; muted 7.47:1; accent 8.34:1; CTA near-black-on-teal 8.34:1 (white-on-teal forbidden); focus ring 8.34:1 on canvas, `#ECEDEF` ring on the teal CTA.
- **Color not sole carrier (1.4.1):** node/edge types always carry a mono text label; color is only a `≥3:1` swatch.
- **Tap targets (2.5.8):** min 44×44px on every interactive element (VI|EN toggle, MCP rows, type chips, footer links, Pause/Play).
- **Language switch (3.1.1, 3.1.2):** `<html lang>` from `daab_lang` server-side (default vi); toggle is a real keyboard control (radiogroup/`aria-pressed`) with a bilingual accessible name; dual-locale labels render only the active locale OR wrap the other-language span with its own `lang`.
- **Live-component states:** dimension-reserved skeleton (CLS), static fallback on parse-fail (never blank), quiet textual error — for the hero graph and any lazy component.

---

## 10. Taste-Compliance Checklist (mechanical)

- EM-DASH: zero in all vi+en strings (hyphens/periods/commas only).
- ONE accent <80% sat: Observatory Teal `#5FB8A6` only; node colors are zinc, quarantined to 2 surfaces.
- NO AI-purple/neon: scoped tokens, `background-image:none`, zero `.glass/.glow/.text-glow/.neon-*`, bloom OFF; `styles.ts` never imported.
- Pure black avoided (`#0A0B0D`); pure white avoided (`#ECEDEF`).
- No three equal cards; no div fake-screenshots (every visual is a real component on fixtures).
- Hero fits viewport: H1 ≤2 lines, VI sub 18 words (<20), actions above fold, `pt-24` max, `min-h-[100dvh]`, no eyebrow/trust-strip.
- Eyebrows: 0 (budget 3). Layout families: 9 distinct (≥4). Zigzag cap respected.
- No duplicate CTA intent (one "Explore the graph"; "Login" and "Sign in to explore" are distinct).
- **No fake-precise numbers — all sourced** (20/25/49, 35 MCP, 31 pages, 4 layouts, <500ms/<200ms/<10ms); hero fixture node count + cost-meter values labeled illustrative. No fabricated accent provenance. No fabricated logo wall.
- Icons: single lucide family, strokeWidth 1.5, sparse. One radius scale. One theme.
- Motion motivated + shown (6 tiered, each one-sentence reason; nothing narrated-but-unbuilt). Zero marquees. No scroll cues / version stamps / locale-time strips / decorative dots / section-number eyebrows / filled progress tracks. No emojis.

---

## 11. Build Plan

**Route group:** new `ennam.kg.next/src/app/(marketing)/` — public, no auth, NOT under the dashboard providers. Relocate `(dashboard)/page.tsx` → `(dashboard)/dashboard/page.tsx` and update the login-success redirect to `/dashboard`.

**Files to create:**
- `(marketing)/layout.tsx` — RSC. Re-declares `Poppins` + `JetBrains_Mono` (`subsets:['latin','latin-ext','vietnamese']`); reads `daab_lang` via `cookies()` for vi-first paint; renders `<div data-surface="marketing">` + sets `lang`; mounts ONLY `LocaleProvider`; imports `marketing.css`; exports bilingual `generateMetadata` (title/description, `openGraph` image = committed OG render, `alternates.languages`). Does NOT import `QueryProvider`/`ProjectProvider`/`VfxProvider`.
- `(marketing)/marketing.css` — `@layer` overrides redefining `--background/--card/--primary/--accent/--accent-foreground/--border/--ring/--radius` for `[data-surface="marketing"]`; `background-image:none` to kill the inherited `.dark` grid; zero neon utilities.
- `(marketing)/page.tsx` — RSC composing the 9 sections.
- `(marketing)/lib/dict.ts` — `vi` + `en` with `en … satisfies typeof vi` parity.
- `(marketing)/lib/LocaleProvider.tsx` — `'use client'` context + `useT()`; persists `daab_lang`.
- `(marketing)/lib/fixtures/{graph,mcpTools,codeMap,gates,cost,nodeTypes}.ts` — static fixtures shaped on the real 20 node + 25 edge taxonomy; graph fixture has pre-baked coords.
- `(marketing)/lib/graphPalette.ts` — NEW teal-on-zinc map (does NOT import `styles.ts`).
- `(marketing)/lib/schema.ts` — exported `NodeType` / `EdgeType` string-literal unions derived from the real taxonomy (the contract the fixtures must satisfy).
- `(marketing)/lib/useReducedMotion.ts` — shared reduced-motion + saveData hook.
- Components: `HeroGraph.tsx` (`'use client'` leaf), `HeroGraphWrapper.tsx` (`next/dynamic ssr:false`, `loading=StaticConstellation`), `StaticConstellation.tsx`, `LanguageToggle.tsx`, `MarketingNav.tsx`, `MarketingFooter.tsx`, and section components `Hero/Problem/Extraction/DualAccess/Enforcement/Performance/TypeSystem/Cost/ClosingCta`, plus a re-skinned fixture-fed `MetricTile` + `NodeCard` (do NOT import dashboard `MetricsCards`).

**RSC vs client:** layout/page/most sections are RSC. Client leaves only where needed — `HeroGraphWrapper`, `LocaleProvider`/`LanguageToggle`, motion `whileInView` wrappers, the lazy Cytoscape mini-graph, the recharts sparkline (all `next/dynamic ssr:false` + IntersectionObserver lazy-mount). ONE WebGL context page-wide (hero only); all other graph echoes are 2D Cytoscape or static SVG/CSS.

**Deps to add:** `motion` (`motion/react`) — the only new package. Already installed: react-force-graph-3d, three, recharts, rehype-highlight, lucide. Do NOT add GSAP, @react-three/fiber, Satoshi, or a second icon family.

**Assets:** ship the **CSS dot-constellation as the initial poster**; replace with a pre-rendered hero PNG + OG 1200×630 (from the same fixture) when produced. No picsum, no fabricated photos.

**Next 16 note:** read the metadata + route-group guidance in `node_modules/next/dist/docs/` before writing — this is not the Next.js in training data.

**Verification steps:**
1. `npm run lint && npm run build` (must pass; TS strict, no `any`).
2. **Fixtures-vs-schema test:** a tiny type/unit test asserts every fixture `node.type`/`edge.type` is a member of `lib/schema.ts` unions (fixtures cannot drift into fabrication).
3. **Confirm the registered MCP tool count** against `schema.go` at build; if the bridge registers a number other than 35, update the §4.4 badge + `mcpTools.ts` length + copy to match.
4. Grep the `(marketing)` tree — zero matches for `.glass`/`.glow`/`.text-glow`/`.neon-`/`styles.ts` import.
5. Manual check: no cyan/magenta/grid leaks into any marketing section; `/dashboard` relocation + login redirect verified.
6. Lighthouse on the production build: LCP <2.5s, CLS <0.1, INP <200ms.
7. Verify VI diacritics (ế/ộ/ữ) render in headlines; test `prefers-reduced-motion` ON/OFF; keyboard-tab the whole page incl. Pause/Play and VI|EN toggle.

---

## 12. Resolved (formerly open) questions

1. **CTA destination** — RESOLVED: landing at public `/`; primary "Explore the graph" scrolls to the on-page live graph (the page is the demo); a "Login" button → `/login`; the authenticated overview moves to `/dashboard`.
2. **`motion` package** — RESOLVED: approved.
3. **Hero poster** — RESOLVED: ship the CSS dot-constellation poster first; swap to a rendered PNG later.

---

## 13. Implementation deviations (2026-06-24 build — recorded post-build)

These changed during the build for correctness reasons; the design intent is unchanged.

- **Display/body font = Be Vietnam Pro, not Poppins (scoped to the marketing route).** Verified against `next/font` `font-data.json`: Poppins offers only `['devanagari','latin','latin-ext']` — **no `vietnamese` subset**, and `latin-ext` does not cover the Vietnamese tone-marked vowels (U+1EA0–1EF9). For a Vietnamese-first page that is a hard failure. Be Vietnam Pro is purpose-built for Vietnamese (`['latin','latin-ext','vietnamese']`), not on any taste ban list, and is loaded only in the `(marketing)` layout — the dashboard keeps Poppins untouched. Mono stays JetBrains Mono (it has a `vietnamese` subset).
- **Homepage owns `/`; dashboard overview relocated to `/dashboard`.** Per the PO decision ("homepage at public `/` with a Login button"). `(dashboard)/page.tsx` deleted; `(dashboard)/dashboard/page.tsx` added; `login` success redirect and the sidebar "Dashboard" link updated to `/dashboard`. Verified build route table: `/` = marketing (dynamic), `/dashboard` = overview.
- **`<html lang>`** stays `en` from the shared root layout (not edited); the marketing subtree sets `lang` on its wrapper `<div>` and `LocaleProvider` syncs `document.documentElement.lang` to the active locale on the client.
- **OG image deferred.** The page ships the CSS/SVG constellation poster as the hero LCP visual; `openGraph` carries title/description/siteName but no static image yet (follow-up: render a 1200×630 from the fixture).
- **`motion` 12.41.0** added (the only new dependency), as approved.
- **QA pass applied:** removed all em-dashes from visible strings (gate labels, rejected line, page title → colons); raised dimmed `text-muted-foreground/60–70` captions to the full token (≥7.47:1); fixed the reduced-motion specificity so the extraction connector freezes under `prefers-reduced-motion`; bumped the language toggle + nav Login + footer/link tap targets toward 44px; dropped redundant `aria-pressed` on the Pause/Play toggle; refactored hooks to satisfy the React 19 `react-hooks` rules (`useSyncExternalStore` for reduced-motion, derived `showGraph`, lazy-init graph clone).
- **Pre-existing, left untouched (surgical-change rule):** the repo's existing `react-hooks/set-state-in-effect` lint errors in `lib/context/*` and the login redirect's `.message === 'NEXT_REDIRECT'` check (works on Next 16.2.1; harden to `isRedirectError` before a Next upgrade).

---

### Appendix A — Verified taxonomy (for fixtures)

**Node types (20, `config.yaml`):** decision, concept, requirement, task, initiative, document, dataset, document_section, document_chunk, external, architecture, discovery, person, organization, event, document_ref, location, artifact, master_record, project. *(DB CHECK in `000061` also allows `session` = 21 in DB.)* Code symbols are stored as **`architecture`** with `properties.kind`.

**Relationship types (25, `config.yaml` edge_whitelist):** relates_to, impacts, supersedes, fulfilled_by, implements, blocked_by, depends_on, about, schema_fk, schema_implicit, schema_many_to_many, upload_batch, references_table, references_component, references_document, data_maps_to_table, cross_source_reference, contains_section, mentions, works_for, part_of, causes, derived_from, evidence, related_to. **49 whitelist rules.**

**MCP tools (35 per `schema.go:190`, Claude adapter — verify registered count at build):** kg_store_decision, kg_store_concept, kg_store_requirement, kg_store_task, kg_store_architecture, kg_store_discovery, kg_store_session, kg_end_session, kg_link, kg_update, kg_update_decision, kg_update_concept, kg_update_requirement, kg_update_task, kg_update_architecture, kg_update_discovery, kg_deprecate, kg_query, kg_traverse, kg_get_context, kg_search, kg_search_chunks, kg_get_node, kg_get_neighbors, kg_get_history, kg_get_impact_analysis, kg_get_document, kg_list_drafts, kg_approve_drafts, kg_process_drafts, kg_ingest_node, kg_ingest_batch, kg_index_source, kg_index_status, kg_list_projects.
