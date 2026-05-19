# Plan: UI Design — Phase 2 Knowledge Graph AI Pipeline

**Team**: ui-designer
**Prerequisite**: All 7 BA docs (BA-007 → BA-013) approved
**Output Location**: `docs/designs/DES-007-phase2/`

---

## 1. Design Scope

| # | Screen | Source BA | Priority | Complexity |
|---|---|---|---|---|
| 1 | **Knowledge Graph Interactive View** | BA-010 | Critical | High |
| 2 | **AI Query Interface** (input + results + explanation) | BA-011 | Critical | High |
| 3 | **Data Source Management** (add/edit/test connections) | BA-007 | High | Medium |
| 4 | **Admin Sync Portal** (trigger + progress monitoring) | BA-012 | High | Medium |
| 5 | **Usage/Rate Limit Dashboard** | BA-012 | Medium | Medium |
| 6 | **Benchmark Dashboard** (run results + accuracy trends) | BA-013 | Medium | Low |

---

## 2. Design Process (per screen)

### Phase 1: Brief & Discovery
- Read relevant BA doc sections (especially §9 UI/UX References)
- Explore existing NextJS dashboard for current design system and patterns
  - Current stack: NextJS 15, shadcn/ui, Tailwind, Cytoscape.js
  - Existing pages: 14 routes under `src/app/(dashboard)/`
  - Existing cyberpunk neon seed: `seeds/ui-upgrade-cyberpunk-neon.yaml`
- Identify design constraints from BA (interaction requirements, data display needs)

### Phase 2: Research
- Find 5+ trending designs for each screen type (KG viz, AI chat, admin dashboards)
- Deep-dive on 3+ design reference sites
- Collect competitor screenshots in `docs/designs/DES-007-phase2/references/`
- Reference style: Neo4j Browser (for KG viz), ChatGPT/Claude UI (for query interface)

### Phase 3: Design
- Create .pen files using Pencil MCP tools
- Follow existing design system (shadcn/ui components, Tailwind utility classes)
- Validate with screenshots at each step
- Desktop-first (1440px), with mobile considerations (375px)

### Phase 4: Handoff
- Export screenshots (desktop + mobile per screen)
- Document **Screen → Node ID Mapping** table (critical for web-dev)
- Write design README with component breakdown

---

## 3. Screen-Specific Design Requirements

### Screen 1: Knowledge Graph Interactive View (BA-010)

**Reference**: Neo4j Browser, Obsidian graph view

**Must include**:
- Force-directed graph layout as default
- Node types: table nodes with icons, colored by schema
- Edge types: FK (solid line) vs AI-detected (dashed, with confidence opacity)
- Top bar: search input, filter dropdowns (schema, table, relation type)
- Layout mode switcher: force-directed | hierarchical | radial | schema-grouped
- Node detail panel (slide-in sidebar on click): columns, types, constraints, connected tables
- Zoom controls + minimap
- Export button (PNG/SVG)
- Empty state: "Connect a data source to generate your knowledge graph"

**Interaction states**:
- Default view (full graph)
- Filtered view (subset highlighted, rest dimmed)
- Selected node (detail panel open)
- Hover state (tooltip with table name + row count)

### Screen 2: AI Query Interface (BA-011)

**Reference**: ChatGPT/Claude conversational UI + data table display

**Must include**:
- Left panel: query history (searchable, favoritable)
- Main area: conversation-style chat with NL input
- Query input: text area with "Ask a question about your data..." placeholder
- Response display: NL summary + data table + optional chart
- Query explanation toggle: "Show how this was answered" -> KG path visualization
- Loading state: streaming response indicator
- Error state: "Could not understand your question. Try rephrasing..." with suggestions
- Empty state: suggested starter questions based on KG structure

**Interaction states**:
- Idle (with starter suggestions)
- Typing (with autocomplete from KG entities)
- Loading (streaming indicator)
- Result displayed (summary + table + explanation toggle)
- Error / Clarification needed

### Screen 3: Data Source Management (BA-007)

**Must include**:
- List view: connected data sources with status badges (connected/error/syncing)
- Add form: connection string input, SSL cert upload, name, description
- Test connection button with success/failure feedback
- Detail view: schema browser (tree: schema → tables → columns)
- Schema stats: table count, total columns, FK count, last sync time

### Screen 4: Admin Sync Portal (BA-012)

**Must include**:
- Sync trigger button (with confirmation dialog)
- Real-time progress display: step indicator (connecting → extracting schema → generating KG)
- Progress bar with percentage + current step label
- Sync history table: date, duration, status, tables synced, errors
- Error detail expandable rows

### Screen 5: Usage Dashboard (BA-012)

**Must include**:
- Query volume chart (daily/weekly/monthly)
- AI token usage chart
- Average response time chart
- Rate limit utilization gauge (current vs max)
- Top queries list
- Error rate indicator

### Screen 6: Benchmark Dashboard (BA-013)

**Must include**:
- Run benchmark button
- Accuracy score (large number display: "94.5%")
- Accuracy trend chart (over multiple runs)
- Question-by-question results table (question, expected, actual, match/mismatch)
- Regression alerts if accuracy drops > 2%

---

## 4. Output Deliverables

```
designs/DES-007-phase2/
├── README.md              # Brief, decisions, research summary, component breakdown
├── design-system.lib.pen  # Library file for other pencil design files
├── kg-visualization.pen   # Knowledge Graph interactive view
├── ai-query.pen           # AI Query interface
├── data-sources.pen       # Data source management
├── admin-sync.pen         # Admin sync portal
├── usage-dashboard.pen    # Usage/rate limit dashboard
├── benchmarks.pen         # Benchmark dashboard
├── screenshots/
│   ├── kg-viz-desktop.png
│   ├── kg-viz-mobile.png
│   ├── ai-query-desktop.png
│   ├── ai-query-mobile.png
│   ├── data-sources-desktop.png
│   ├── admin-sync-desktop.png
│   ├── usage-dashboard-desktop.png
│   └── benchmarks-desktop.png
└── references/            # Competitor/inspiration screenshots
```

### Critical Handoff Table (Screen → Node ID Mapping)

| Screen | Pencil Node ID | .pen File |
|---|---|---|
| KG Interactive View | `<id>` | `kg-visualization.pen` |
| AI Query Interface | `<id>` | `ai-query.pen` |
| Data Source Management | `<id>` | `data-sources.pen` |
| Admin Sync Portal | `<id>` | `admin-sync.pen` |
| Usage Dashboard | `<id>` | `usage-dashboard.pen` |
| Benchmark Dashboard | `<id>` | `benchmarks.pen` |

> Node IDs are filled after design creation. web-dev uses these to call `batch_get(nodeIds: ["<id>"])` for exact specs.

---

## 5. Design System Constraints

- Follow existing shadcn/ui component library
- Tailwind CSS utility classes
- Dark theme support (existing dashboard has theme toggle)
- Responsive: desktop-first, mobile-friendly
- Accessibility: WCAG 2.1 AA minimum
- Consistent with existing Cytoscape.js graph styling (or document migration rationale if changing lib)
- Reference cyberpunk neon seed if applicable: `seeds/ui-upgrade-cyberpunk-neon.yaml`
