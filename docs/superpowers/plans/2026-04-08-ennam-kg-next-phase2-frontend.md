# ennam.kg.next Phase 2 — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build all Phase 2 NextJS dashboard pages (data sources, KG viz, AI query, admin sync, usage dashboard, benchmarks) consuming Go API endpoints via the existing BFF proxy.

**Architecture:** NextJS 16 App Router with TanStack Query 5 for data fetching. All API calls go through the existing BFF proxy (`/api/kg/...` catch-all route → Go API `:8080`). New pages follow the established pattern: types → hooks → pages → components. Design specs read from Pencil MCP `.pen` files.

**Tech Stack:** Next.js 16, React 19, TypeScript (strict), TanStack Query 5, shadcn/ui (base-nova), Tailwind CSS 4, Cytoscape.js, iron-session, Lucide icons

---

## Important Notes for Agents

### Pencil MCP Design Reference Protocol

Each task references specific `.pen` files and node IDs. Before implementing UI, agents MUST:

```
# 1. Read screen design
batch_get(filePath: "ennam.kg.requirements/designs/DES-007-phase2/<file>.pen", nodeIds: ["<screenId>"], readDepth: 5)

# 2. Read specific section for detail
batch_get(filePath: "...", nodeIds: ["<sectionId>"], readDepth: 3)
```

**Verified Screen Node IDs** (from Pencil MCP reads — README has one error):

| Screen | .pen File | Actual Node ID | README ID | Prefix |
|--------|-----------|---------------|-----------|--------|
| KG Interactive View | `kg-visualization.pen` | `B30vH` | `B30vH` | `P:` |
| AI Query Interface | `ai-query.pen` | `IBtey` | `lnpPf` (WRONG) | `3:` |
| Data Source Management | `data-sources.pen` | `dsdeD` | `dsdeD` | `k:` |
| Admin Sync Portal | `admin-sync.pen` | `zwNir` | `zwNir` | `1:` |
| Usage Dashboard | `usage-dashboard.pen` | `hdcYF` | `hdcYF` | `A:` |
| Benchmark Dashboard | `benchmarks.pen` | `qHzRv` | `qHzRv` | `G:` |

### Existing Patterns to Follow

- **Hook pattern**: See `src/hooks/use-nodes.ts` — `useQuery` with `['resource', projectId, filters]` keys
- **Type pattern**: See `src/types/node.ts` — literal union types, optional `?:` props
- **Page pattern**: See `src/app/(dashboard)/page.tsx` — `'use client'`, `useProject()`, stat cards grid
- **Tree pattern**: See `src/components/nodes/CodeTree.tsx` — expandable tree with toggle state
- **API pattern**: Client hooks call `/api/kg/...` BFF proxy (NOT direct Go API)
- **Sidebar pattern**: See `src/components/layout/Sidebar.tsx` — flat `navItems` array with icons

### Sidebar Navigation Structure (from .pen designs)

All 6 screens show a consistent sidebar with 3 sections:

```
MAIN:     Dashboard, Graph, Schema Graph, Decisions
DATA:     Data Sources*, AI Query*
ADMIN:    Sync Portal*, Usage*, Benchmarks*
```

Items marked `*` are new Phase 2 additions.

---

## File Structure

### New Files to Create

```
src/types/
├── datasource.ts          # DataSource, SourceSchema, SourceTable, SourceColumn, SourceFK
├── schema-graph.ts        # SchemaTable, SchemaRelationship, SchemaGraphData
├── ai-query.ts            # AIQuery, QueryResult, QueryExplanation, QueryFavorite
├── sync.ts                # SyncJob, QueueStatus, RateLimitState
├── usage.ts               # UsageMetrics, UsageSummary, BudgetStatus
└── benchmark.ts           # BenchmarkRun, BenchmarkQuestion, BenchmarkResult

src/hooks/
├── use-data-sources.ts    # useDataSources, useDataSource, useConnectionTest, useSchemaExtraction
├── use-schema-graph.ts    # useSchemaGraph
├── use-ai-query.ts        # useAIQuery, useQueryHistory, useQueryFavorites
├── use-sync.ts            # useSyncJobs, useSyncProgress, useQueueStatus
├── use-usage.ts           # useUsageMetrics, useUsageBudget
└── use-benchmarks.ts      # useBenchmarks, useBenchmarkRun

src/app/(dashboard)/
├── data-sources/
│   ├── page.tsx           # Data source list with table
│   └── [id]/
│       └── page.tsx       # Data source detail + schema browser
├── knowledge-graph/
│   └── page.tsx           # (EDIT existing graph page for schema KG)
├── query/
│   └── page.tsx           # AI NL query chat interface
├── admin/
│   ├── sync/
│   │   └── page.tsx       # Admin sync portal
│   └── usage/
│       └── page.tsx       # Usage & rate limit dashboard
└── benchmarks/
    └── page.tsx           # Benchmark dashboard

src/components/
├── data-sources/
│   ├── DataSourceTable.tsx     # Table with status badges, actions
│   ├── DataSourceForm.tsx      # Add/Edit dialog form
│   ├── ConnectionTest.tsx      # Test button with status feedback
│   └── SchemaBrowser.tsx       # Expandable tree: schema → tables → columns
├── schema-graph/
│   └── SchemaGraphControls.tsx # Control bar: layout, filter, confidence slider
├── query/
│   ├── QueryInput.tsx          # Chat-style input bar with send button
│   ├── QueryHistory.tsx        # Left panel: history items with favorites
│   ├── ResultsTable.tsx        # Sortable results table with pagination
│   ├── QueryExplanation.tsx    # Expandable explanation panel
│   └── SuggestionChips.tsx     # Query suggestion pills
├── admin/
│   ├── SyncProgress.tsx        # Multi-step progress with ProgressBar
│   ├── SyncHistory.tsx         # Job history table
│   ├── QueueStatus.tsx         # Queue stat cards row
│   ├── TokenUsageChart.tsx     # Bar chart for token usage
│   ├── RateLimitGauge.tsx      # Donut gauge for rate limits
│   └── BudgetProgress.tsx      # Budget progress bar with markers
└── benchmarks/
    ├── AccuracyCard.tsx        # Large accuracy % display
    ├── DifficultyBars.tsx      # Horizontal bars by difficulty
    ├── AccuracyTrend.tsx       # Line chart with threshold
    └── ResultsTable.tsx        # Question results with score/delta
```

### Files to Modify

```
src/components/layout/Sidebar.tsx  — Restructure nav: MAIN/DATA/ADMIN sections
src/lib/graph/styles.ts            — Add schema node/edge styles
src/components/graph/NodeInspector.tsx — Add table/column detail views
src/components/graph/GraphControls.tsx — Add confidence slider, edge type toggles
```

---

## Sprint 1: Data Source Management

**BAs**: BA-007 (Data Source) + BA-009 (AI Provider)
**Design**: `data-sources.pen` → Screen `dsdeD`
**Backend**: DONE on `feature/phase2-wave1`

### Task 1: Data Source TypeScript Types

**Files:**
- Create: `src/types/datasource.ts`

- [ ] **Step 1: Write the type definitions**

```typescript
// src/types/datasource.ts

export type DataSourceStatus = 'pending' | 'connected' | 'syncing' | 'synced' | 'error' | 'disconnected';
export type DatabaseType = 'postgresql';
export type SyncJobType = 'full' | 'incremental';
export type SyncJobStatus = 'queued' | 'preparing' | 'extracting_schema' | 'generating_kg' | 'completing' | 'completed' | 'failed' | 'cancelled';

export interface DataSource {
  id: string;
  project_id: string;
  name: string;
  description: string;
  db_type: DatabaseType;
  status: DataSourceStatus;
  last_error: string | null;
  last_tested_at: string | null;
  last_synced_at: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface SourceSchema {
  id: string;
  data_source_id: string;
  schema_name: string;
  extracted_at: string;
  created_at: string;
}

export interface SourceTable {
  id: string;
  source_schema_id: string;
  table_name: string;
  row_count_estimate: number | null;
  description: string | null;
  extracted_at: string;
  created_at: string;
  updated_at: string;
}

export interface SourceColumn {
  id: string;
  source_table_id: string;
  column_name: string;
  data_type: string;
  is_nullable: boolean;
  is_primary_key: boolean;
  default_value: string | null;
  ordinal_position: number;
  description: string | null;
}

export interface SourceForeignKey {
  id: string;
  source_table_id: string;
  column_name: string;
  referenced_table: string;
  referenced_column: string;
  constraint_name: string;
}

export interface ConnectionTestResult {
  step: string;
  status: 'pass' | 'fail';
  duration_ms: number;
  error?: string;
}

export interface ConnectionTestResponse {
  test_results: ConnectionTestResult[];
  status: DataSourceStatus;
}

export interface DataSourceListResponse {
  data_sources: DataSource[];
  total_count: number;
}

export interface CreateDataSourceInput {
  name: string;
  description: string;
  connection_string: string;
  ssl_cert?: string;
  db_type: DatabaseType;
  project_id: string;
}

export interface UpdateDataSourceInput {
  name?: string;
  description?: string;
  connection_string?: string;
}
```

- [ ] **Step 2: Commit**

```bash
git add src/types/datasource.ts
git commit -m "feat(types): add data source TypeScript types for BA-007"
```

---

### Task 2: Data Source TanStack Query Hooks

**Files:**
- Create: `src/hooks/use-data-sources.ts`

- [ ] **Step 1: Write the hooks**

```typescript
// src/hooks/use-data-sources.ts
'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type {
  DataSource,
  DataSourceListResponse,
  ConnectionTestResponse,
  CreateDataSourceInput,
  UpdateDataSourceInput,
  SourceSchema,
  SourceTable,
  SourceColumn,
  SourceForeignKey,
} from '@/types/datasource';

async function fetchDataSources(projectId: string): Promise<DataSourceListResponse> {
  const res = await fetch(`/api/kg/data-sources?project_id=${projectId}`);
  if (!res.ok) throw new Error(`Failed to fetch data sources: ${res.statusText}`);
  return res.json();
}

async function fetchDataSource(id: string): Promise<DataSource> {
  const res = await fetch(`/api/kg/data-sources/${id}`);
  if (!res.ok) throw new Error(`Failed to fetch data source: ${res.statusText}`);
  return res.json();
}

async function createDataSource(input: CreateDataSourceInput): Promise<DataSource> {
  const res = await fetch('/api/kg/data-sources', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(`Failed to create data source: ${res.statusText}`);
  return res.json();
}

async function updateDataSource(id: string, input: UpdateDataSourceInput): Promise<DataSource> {
  const res = await fetch(`/api/kg/data-sources/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(`Failed to update data source: ${res.statusText}`);
  return res.json();
}

async function deleteDataSource(id: string): Promise<void> {
  const res = await fetch(`/api/kg/data-sources/${id}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Failed to delete data source: ${res.statusText}`);
}

async function testConnection(id: string): Promise<ConnectionTestResponse> {
  const res = await fetch(`/api/kg/data-sources/${id}/test`, { method: 'POST' });
  if (!res.ok) throw new Error(`Connection test failed: ${res.statusText}`);
  return res.json();
}

async function fetchSchemas(dataSourceId: string): Promise<SourceSchema[]> {
  const res = await fetch(`/api/kg/data-sources/${dataSourceId}/schemas`);
  if (!res.ok) throw new Error(`Failed to fetch schemas: ${res.statusText}`);
  return res.json();
}

async function fetchTables(dataSourceId: string, schemaId: string): Promise<SourceTable[]> {
  const res = await fetch(`/api/kg/data-sources/${dataSourceId}/schemas/${schemaId}/tables`);
  if (!res.ok) throw new Error(`Failed to fetch tables: ${res.statusText}`);
  return res.json();
}

async function fetchTableDetail(dataSourceId: string, tableId: string): Promise<{
  table: SourceTable;
  columns: SourceColumn[];
  foreign_keys: SourceForeignKey[];
}> {
  const res = await fetch(`/api/kg/data-sources/${dataSourceId}/tables/${tableId}`);
  if (!res.ok) throw new Error(`Failed to fetch table detail: ${res.statusText}`);
  return res.json();
}

export function useDataSources(projectId: string) {
  return useQuery({
    queryKey: ['data-sources', projectId],
    queryFn: () => fetchDataSources(projectId),
    enabled: !!projectId,
  });
}

export function useDataSource(id: string) {
  return useQuery({
    queryKey: ['data-source', id],
    queryFn: () => fetchDataSource(id),
    enabled: !!id,
  });
}

export function useCreateDataSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createDataSource,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['data-sources'] });
    },
  });
}

export function useUpdateDataSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: UpdateDataSourceInput }) =>
      updateDataSource(id, input),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['data-sources'] });
      queryClient.invalidateQueries({ queryKey: ['data-source', variables.id] });
    },
  });
}

export function useDeleteDataSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteDataSource,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['data-sources'] });
    },
  });
}

export function useConnectionTest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: testConnection,
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ['data-source', id] });
      queryClient.invalidateQueries({ queryKey: ['data-sources'] });
    },
  });
}

export function useSchemas(dataSourceId: string) {
  return useQuery({
    queryKey: ['schemas', dataSourceId],
    queryFn: () => fetchSchemas(dataSourceId),
    enabled: !!dataSourceId,
  });
}

export function useTables(dataSourceId: string, schemaId: string) {
  return useQuery({
    queryKey: ['tables', dataSourceId, schemaId],
    queryFn: () => fetchTables(dataSourceId, schemaId),
    enabled: !!dataSourceId && !!schemaId,
  });
}

export function useTableDetail(dataSourceId: string, tableId: string) {
  return useQuery({
    queryKey: ['table-detail', dataSourceId, tableId],
    queryFn: () => fetchTableDetail(dataSourceId, tableId),
    enabled: !!dataSourceId && !!tableId,
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add src/hooks/use-data-sources.ts
git commit -m "feat(hooks): add data source TanStack Query hooks for BA-007"
```

---

### Task 3: Update Sidebar Navigation

**Files:**
- Modify: `src/components/layout/Sidebar.tsx`

**Design ref**: All `.pen` screens show sidebar with MAIN/DATA/ADMIN sections. Read any screen's sidebar node for the nav structure.

- [ ] **Step 1: Read Pencil design for sidebar structure**

Read `data-sources.pen` node `Smk9y` to verify nav items and icons.

- [ ] **Step 2: Update navItems to sectioned structure**

Replace the flat `navItems` array with a sectioned structure:

```typescript
// In Sidebar.tsx, replace the navItems array:

import {
  LayoutDashboard,
  Scale,
  FolderTree,
  Network,
  Bot,
  Zap,
  BarChart3,
  Settings,
  ChevronsLeft,
  ChevronsRight,
  X,
  Share2,
  Database,
  Sparkles,
  RefreshCw,
  Activity,
  Target,
} from 'lucide-react';

interface NavSection {
  label: string;
  items: { href: string; label: string; icon: React.ComponentType<{ className?: string }> }[];
}

const navSections: NavSection[] = [
  {
    label: 'MAIN',
    items: [
      { href: '/', label: 'Dashboard', icon: LayoutDashboard },
      { href: '/graph', label: 'Graph', icon: Network },
      { href: '/knowledge-graph', label: 'Schema Graph', icon: Share2 },
      { href: '/decisions', label: 'Decision Log', icon: Scale },
      { href: '/code-map', label: 'Code Map', icon: FolderTree },
      { href: '/agents', label: 'Agent Activity', icon: Bot },
      { href: '/impact', label: 'Impact Analysis', icon: Zap },
      { href: '/metrics', label: 'Metrics', icon: BarChart3 },
    ],
  },
  {
    label: 'DATA',
    items: [
      { href: '/data-sources', label: 'Data Sources', icon: Database },
      { href: '/query', label: 'AI Query', icon: Sparkles },
    ],
  },
  {
    label: 'ADMIN',
    items: [
      { href: '/admin/sync', label: 'Sync Portal', icon: RefreshCw },
      { href: '/admin/usage', label: 'Usage', icon: Activity },
      { href: '/benchmarks', label: 'Benchmarks', icon: Target },
    ],
  },
];
```

- [ ] **Step 3: Update the navigation rendering to use sections**

Replace the `<nav>` section to render section labels and items:

```typescript
{/* Navigation */}
<nav className="flex-1 overflow-y-auto py-3 px-2 space-y-1">
  {navSections.map((section) => (
    <div key={section.label}>
      {!isCollapsed && (
        <div className="px-3 py-2">
          <span className="text-[11px] font-semibold tracking-wider text-muted-foreground/60">
            {section.label}
          </span>
        </div>
      )}
      {section.items.map((item) => {
        const isActive =
          item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
        return (
          <NavLink
            key={item.href}
            href={item.href}
            label={item.label}
            icon={item.icon}
            isActive={isActive}
            isCollapsed={isCollapsed}
          />
        );
      })}
    </div>
  ))}
  {/* Keep settings at bottom */}
  <NavLink
    href="/settings"
    label="Settings"
    icon={Settings}
    isActive={pathname.startsWith('/settings')}
    isCollapsed={isCollapsed}
  />
</nav>
```

- [ ] **Step 4: Verify build**

Run: `cd ennam.kg.next && npm run build`
Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add src/components/layout/Sidebar.tsx
git commit -m "feat(sidebar): restructure nav with MAIN/DATA/ADMIN sections for Phase 2"
```

---

### Task 4: Data Source List Page

**Files:**
- Create: `src/app/(dashboard)/data-sources/page.tsx`
- Create: `src/components/data-sources/DataSourceTable.tsx`

**Design ref**: `data-sources.pen` → Screen `dsdeD`, table `wem7h`, list header `NrqCO`

- [ ] **Step 1: Read Pencil design for data source table layout**

```
batch_get(filePath: "ennam.kg.requirements/designs/DES-007-phase2/data-sources.pen", nodeIds: ["0RYOe"], readDepth: 4)
```

Verify: 6 columns (NAME, TYPE, STATUS, TABLES, LAST SYNCED, ACTIONS), 3 sample rows with badges.

- [ ] **Step 2: Install shadcn table component**

Run: `cd ennam.kg.next && npx shadcn@latest add table`

- [ ] **Step 3: Create DataSourceTable component**

```typescript
// src/components/data-sources/DataSourceTable.tsx
'use client';

import { Database, RefreshCw, Pencil, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import type { DataSource, DataSourceStatus } from '@/types/datasource';

const STATUS_STYLES: Record<DataSourceStatus, { label: string; className: string }> = {
  connected: { label: 'Connected', className: 'bg-[#00FF94]/10 text-[#00FF94] border-[#00FF94]/20' },
  syncing: { label: 'Syncing', className: 'bg-[#FFD600]/10 text-[#FFD600] border-[#FFD600]/20' },
  synced: { label: 'Synced', className: 'bg-[#00FF94]/10 text-[#00FF94] border-[#00FF94]/20' },
  error: { label: 'Error', className: 'bg-[#FF4757]/10 text-[#FF4757] border-[#FF4757]/20' },
  pending: { label: 'Pending', className: 'bg-[#FFD600]/10 text-[#FFD600] border-[#FFD600]/20' },
  disconnected: { label: 'Offline', className: 'bg-[#5C6080]/10 text-[#5C6080] border-[#5C6080]/20' },
};

function StatusBadge({ status }: { status: DataSourceStatus }) {
  const style = STATUS_STYLES[status];
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${style.className}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {style.label}
    </span>
  );
}

function formatTimeAgo(dateStr: string | null): string {
  if (!dateStr) return 'Never';
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

interface DataSourceTableProps {
  dataSources: DataSource[];
  isLoading: boolean;
  selectedId: string | null;
  onSelect: (ds: DataSource) => void;
  onSync: (id: string) => void;
  onEdit: (ds: DataSource) => void;
  onDelete: (id: string) => void;
}

export default function DataSourceTable({
  dataSources,
  isLoading,
  selectedId,
  onSelect,
  onSync,
  onEdit,
  onDelete,
}: DataSourceTableProps) {
  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  }

  if (dataSources.length === 0) {
    return (
      <div className="text-center py-12">
        <Database className="mx-auto h-10 w-10 text-muted-foreground/40 mb-3" />
        <p className="text-muted-foreground">No data sources connected yet.</p>
        <p className="text-sm text-muted-foreground mt-1">Click "Add Data Source" to get started.</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border overflow-hidden glass">
      {/* Header Row */}
      <div className="flex items-center bg-[#161929] border-b border-border text-[#5C6080] text-xs font-semibold tracking-wider">
        <div className="flex-1 px-4 py-2.5">NAME</div>
        <div className="w-[100px] px-4 py-2.5">TYPE</div>
        <div className="w-[110px] px-4 py-2.5">STATUS</div>
        <div className="w-[80px] px-4 py-2.5">TABLES</div>
        <div className="w-[130px] px-4 py-2.5">LAST SYNCED</div>
        <div className="w-[100px] px-4 py-2.5">ACTIONS</div>
      </div>

      {/* Data Rows */}
      {dataSources.map((ds) => (
        <button
          key={ds.id}
          onClick={() => onSelect(ds)}
          className={`flex items-center w-full text-left border-b border-border/50 hover:bg-[#00D4FF]/5 transition-colors ${
            selectedId === ds.id ? 'bg-[#00D4FF]/10' : ''
          }`}
        >
          <div className="flex-1 px-4 py-3 flex items-center gap-2">
            <Database className="h-4 w-4 text-[#00D4FF] shrink-0" />
            <span className="text-sm font-medium text-[#F0F0F8] truncate">{ds.name}</span>
          </div>
          <div className="w-[100px] px-4 py-3">
            <Badge variant="secondary" className="text-xs">{ds.db_type}</Badge>
          </div>
          <div className="w-[110px] px-4 py-3">
            <StatusBadge status={ds.status} />
          </div>
          <div className="w-[80px] px-4 py-3 text-sm text-[#F0F0F8]">—</div>
          <div className="w-[130px] px-4 py-3 text-sm text-[#5C6080]">
            {formatTimeAgo(ds.last_synced_at)}
          </div>
          <div className="w-[100px] px-4 py-3 flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={() => onSync(ds.id)}
              className="p-1.5 rounded-md bg-[#1E2235] hover:bg-[#252940] text-[#8B8FA8] transition-colors"
              title="Sync"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
            <button
              onClick={() => onEdit(ds)}
              className="p-1.5 rounded-md bg-[#1E2235] hover:bg-[#252940] text-[#8B8FA8] transition-colors"
              title="Edit"
            >
              <Pencil className="h-4 w-4" />
            </button>
            <button
              onClick={() => onDelete(ds.id)}
              className="p-1.5 rounded-md hover:bg-[#FF4757]/10 text-[#FF4757]/60 hover:text-[#FF4757] transition-colors"
              title="Delete"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Create the data sources list page**

```typescript
// src/app/(dashboard)/data-sources/page.tsx
'use client';

import { useState } from 'react';
import { Plus } from 'lucide-react';
import { useProject } from '@/lib/context/project';
import { useDataSources } from '@/hooks/use-data-sources';
import { Input } from '@/components/ui/input';
import DataSourceTable from '@/components/data-sources/DataSourceTable';
import type { DataSource } from '@/types/datasource';

export default function DataSourcesPage() {
  const { projectId } = useProject();
  const { data, isLoading } = useDataSources(projectId);
  const [search, setSearch] = useState('');
  const [selectedDs, setSelectedDs] = useState<DataSource | null>(null);

  const dataSources = data?.data_sources ?? [];
  const filtered = search.trim()
    ? dataSources.filter((ds) => ds.name.toLowerCase().includes(search.toLowerCase()))
    : dataSources;

  return (
    <div className="flex gap-6 h-full">
      {/* List Column */}
      <div className="flex-1 flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <Input
            placeholder="Search data sources..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-[300px]"
          />
          <button className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-[#00D4FF] text-[#0D0F1A] font-semibold text-sm shadow-[0_0_16px_#00D4FF44] hover:brightness-110 transition">
            <Plus className="h-4 w-4" />
            Add Data Source
          </button>
        </div>

        <DataSourceTable
          dataSources={filtered}
          isLoading={isLoading}
          selectedId={selectedDs?.id ?? null}
          onSelect={setSelectedDs}
          onSync={(id) => { /* TODO: trigger sync */ }}
          onEdit={(ds) => { /* TODO: open edit dialog */ }}
          onDelete={(id) => { /* TODO: confirm & delete */ }}
        />
      </div>

      {/* Detail Panel - shown when a data source is selected */}
      {selectedDs && (
        <div className="w-[380px] shrink-0 bg-[#1A1D2E] rounded-xl border-l border-[#2A2E45] overflow-y-auto">
          <div className="p-5 border-b border-[#1E2235]">
            <h3 className="text-lg font-semibold text-[#F0F0F8]">{selectedDs.name}</h3>
            <p className="text-sm text-[#5C6080] mt-1">{selectedDs.description}</p>
          </div>
          <div className="p-5">
            <p className="text-xs font-semibold tracking-wider text-[#5C6080] mb-3">Schema Browser</p>
            <p className="text-sm text-muted-foreground">Select a connected data source to browse schema.</p>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Verify build**

Run: `cd ennam.kg.next && npm run build`

- [ ] **Step 6: Commit**

```bash
git add src/app/\(dashboard\)/data-sources/page.tsx src/components/data-sources/DataSourceTable.tsx
git commit -m "feat(data-sources): add list page with table and detail panel"
```

---

### Task 5: Schema Browser Component

**Files:**
- Create: `src/components/data-sources/SchemaBrowser.tsx`

**Design ref**: `data-sources.pen` → node `V1j8O` (tree: public → users, orders, products, sessions, roles)

- [ ] **Step 1: Read Pencil design for schema browser tree**

```
batch_get(filePath: "ennam.kg.requirements/designs/DES-007-phase2/data-sources.pen", nodeIds: ["V1j8O"], readDepth: 4)
```

- [ ] **Step 2: Create SchemaBrowser component**

Follow `CodeTree.tsx` pattern — expandable tree with toggle state per schema and table:

```typescript
// src/components/data-sources/SchemaBrowser.tsx
'use client';

import { useState } from 'react';
import { ChevronRight, ChevronDown, Folder, Table2, Key, Link2 } from 'lucide-react';
import { useSchemas, useTables, useTableDetail } from '@/hooks/use-data-sources';
import { Skeleton } from '@/components/ui/skeleton';
import type { SourceColumn, SourceForeignKey } from '@/types/datasource';

function ColumnRow({ column }: { column: SourceColumn }) {
  return (
    <div className="flex items-center gap-2 py-1 pl-16 text-xs">
      {column.is_primary_key && <Key className="h-3 w-3 text-[#FFD600] shrink-0" />}
      {!column.is_primary_key && <span className="w-3" />}
      <span className="text-[#F0F0F8]">{column.column_name}</span>
      <span className="text-[#5C6080]">{column.data_type}</span>
      {column.is_nullable && <span className="text-[#5C6080] text-[10px]">NULL</span>}
    </div>
  );
}

function TableNode({ dataSourceId, table }: { dataSourceId: string; table: { id: string; table_name: string } }) {
  const [expanded, setExpanded] = useState(false);
  const { data, isLoading } = useTableDetail(dataSourceId, expanded ? table.id : '');

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full py-1.5 pl-8 pr-2 rounded-md hover:bg-[#00D4FF]/10 transition-colors text-left"
      >
        {expanded ? <ChevronDown className="h-3.5 w-3.5 text-[#5C6080]" /> : <ChevronRight className="h-3.5 w-3.5 text-[#5C6080]" />}
        <Table2 className="h-3.5 w-3.5 text-[#00D4FF]" />
        <span className="text-sm text-[#F0F0F8]">{table.table_name}</span>
      </button>
      {expanded && (
        <div>
          {isLoading && <Skeleton className="h-4 w-32 ml-16 my-1" />}
          {data?.columns.map((col) => <ColumnRow key={col.id} column={col} />)}
          {data?.foreign_keys.map((fk) => (
            <div key={fk.id} className="flex items-center gap-2 py-1 pl-16 text-xs text-[#00D4FF]">
              <Link2 className="h-3 w-3" />
              <span>{fk.column_name} → {fk.referenced_table}.{fk.referenced_column}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

interface SchemaBrowserProps {
  dataSourceId: string;
}

export default function SchemaBrowser({ dataSourceId }: SchemaBrowserProps) {
  const { data: schemas, isLoading } = useSchemas(dataSourceId);
  const [expandedSchemas, setExpandedSchemas] = useState<Set<string>>(new Set());

  const toggleSchema = (id: string) => {
    setExpandedSchemas((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (isLoading) {
    return <div className="space-y-2">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-6 w-full" />)}</div>;
  }

  if (!schemas || schemas.length === 0) {
    return <p className="text-sm text-muted-foreground">No schemas extracted yet.</p>;
  }

  return (
    <div className="space-y-0.5">
      {schemas.map((schema) => (
        <SchemaNode key={schema.id} schema={schema} dataSourceId={dataSourceId} expanded={expandedSchemas.has(schema.id)} onToggle={() => toggleSchema(schema.id)} />
      ))}
    </div>
  );
}

function SchemaNode({ schema, dataSourceId, expanded, onToggle }: {
  schema: { id: string; schema_name: string };
  dataSourceId: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { data: tables, isLoading } = useTables(dataSourceId, expanded ? schema.id : '');

  return (
    <div>
      <button onClick={onToggle} className="flex items-center gap-2 w-full py-1.5 px-2 rounded-md hover:bg-[#00D4FF]/10 transition-colors text-left">
        {expanded ? <ChevronDown className="h-3.5 w-3.5 text-[#5C6080]" /> : <ChevronRight className="h-3.5 w-3.5 text-[#5C6080]" />}
        <Folder className="h-3.5 w-3.5 text-[#FFD600]" />
        <span className="text-sm text-[#F0F0F8] font-medium">{schema.schema_name}</span>
      </button>
      {expanded && (
        <div>
          {isLoading && <Skeleton className="h-4 w-32 ml-8 my-1" />}
          {tables?.map((table) => <TableNode key={table.id} dataSourceId={dataSourceId} table={table} />)}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Integrate into detail panel on data-sources page**

Update `src/app/(dashboard)/data-sources/page.tsx` to use `SchemaBrowser` in the detail panel.

- [ ] **Step 4: Commit**

```bash
git add src/components/data-sources/SchemaBrowser.tsx src/app/\(dashboard\)/data-sources/page.tsx
git commit -m "feat(data-sources): add schema browser tree component"
```

---

### Task 6: Data Source Detail Page

**Files:**
- Create: `src/app/(dashboard)/data-sources/[id]/page.tsx`

**Design ref**: `data-sources.pen` → Detail panel `BbKtt` (stats: 42 Tables, 312 Columns, 58 FKs)

- [ ] **Step 1: Create detail page with schema browser and stats**

```typescript
// src/app/(dashboard)/data-sources/[id]/page.tsx
'use client';

import { use } from 'react';
import Link from 'next/link';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import { useDataSource, useConnectionTest } from '@/hooks/use-data-sources';
import { Skeleton } from '@/components/ui/skeleton';
import SchemaBrowser from '@/components/data-sources/SchemaBrowser';

export default function DataSourceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: ds, isLoading } = useDataSource(id);
  const testConnection = useConnectionTest();

  if (isLoading) {
    return <div className="space-y-4"><Skeleton className="h-8 w-64" /><Skeleton className="h-40 w-full" /></div>;
  }

  if (!ds) {
    return <p className="text-muted-foreground">Data source not found.</p>;
  }

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <Link href="/data-sources" className="p-1.5 rounded-md hover:bg-[#1E2235] transition-colors">
          <ArrowLeft className="h-5 w-5 text-[#8B8FA8]" />
        </Link>
        <h2 className="text-xl font-heading font-semibold">{ds.name}</h2>
        <button
          onClick={() => testConnection.mutate(ds.id)}
          disabled={testConnection.isPending}
          className="ml-auto inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-[#1E2235] hover:bg-[#252940] text-sm font-medium transition-colors"
        >
          <RefreshCw className={`h-4 w-4 ${testConnection.isPending ? 'animate-spin' : ''}`} />
          Test Connection
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_380px] gap-6">
        <div>
          <h3 className="text-sm font-semibold tracking-wider text-[#5C6080] mb-3">SCHEMA BROWSER</h3>
          <SchemaBrowser dataSourceId={id} />
        </div>
        <div className="bg-[#1A1D2E] rounded-xl border border-[#2A2E45] p-5">
          <p className="text-sm text-[#5C6080]">{ds.description}</p>
          <div className="mt-4 text-sm text-[#8B8FA8]">
            <p>Status: <span className="text-[#F0F0F8]">{ds.status}</span></p>
            <p>Type: <span className="text-[#F0F0F8]">{ds.db_type}</span></p>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add src/app/\(dashboard\)/data-sources/\[id\]/page.tsx
git commit -m "feat(data-sources): add detail page with schema browser and connection test"
```

---

## Sprint 2: KG Generation Progress (4 tasks)

**BA**: BA-008 | **Design**: `kg-visualization.pen` → `B30vH`

### Task 7: KG Generation Types + Hook
- Create `src/types/kg-generation.ts` with `KGGenerationJob`, `GenerationStatus`
- Create `src/hooks/use-kg-generation.ts` with `useKGGeneration` (trigger mutation + poll status query)
- API: `POST /api/kg/data-sources/{id}/generate-kg`, `GET /api/kg/generation-jobs/{id}`

### Task 8: Generation Progress Component
- Create `src/components/kg-generation/GenerationProgress.tsx`
- Multi-step tracker: Extracting Schema → Detecting Relationships → Generating KG → Complete
- Uses ProgressBar design pattern from `SNXVe` component
- Badges: Warning for in-progress, Success for complete

### Task 9: Integrate into Data Source Detail Page
- Edit `src/app/(dashboard)/data-sources/[id]/page.tsx`
- Add "Generate KG" button in detail panel when status is `connected` or `synced`
- Show GenerationProgress when a job is running

### Task 10: Commit Sprint 2
```bash
git commit -m "feat(kg-generation): add generation trigger and progress tracker"
```

---

## Sprint 3: Interactive KG Visualization + Admin Sync (11 tasks)

**BAs**: BA-010 + BA-012 | **Designs**: `kg-visualization.pen` → `B30vH`, `admin-sync.pen` → `zwNir`

**Parallel tracks**: KG viz and Admin sync are independent — can run 2 agents.

### Track A: KG Visualization (Tasks 11-15)

#### Task 11: Schema Graph Types + Hook
- Create `src/types/schema-graph.ts` with `SchemaTable`, `SchemaRelationship`, `SchemaGraphData`
- Create `src/hooks/use-schema-graph.ts` with `useSchemaGraph(projectId)`
- API: `GET /api/kg/schema-graph?project_id={id}`
- Response shape matches BA-010 §8: `{ tables[], relationships[], metadata }`

#### Task 12: Schema Graph Page
- Create `src/app/(dashboard)/knowledge-graph/page.tsx`
- **Design ref**: Screen `B30vH`, canvas `umTLZ`, control bar `iDvTC`
- Layout: Sidebar + Header + Control Bar + Graph Canvas + Detail Panel (380px)
- Reuse existing `KnowledgeGraph` component pattern with Cytoscape.js
- Dynamically import Cytoscape to avoid SSR crashes (same as existing graph page)

#### Task 13: Schema Node/Edge Styles
- Edit `src/lib/graph/styles.ts`
- Add table node styles: rounded rectangle, with column count badge
- Edge styles: solid cyan for FK (confidence=1.0), dashed colored for AI-detected
- 3 depth layers: Foreground (sharp), Mid-ground (0.8 opacity), Background (0.4 opacity, blurred)

#### Task 14: Schema Graph Controls
- Create `src/components/schema-graph/SchemaGraphControls.tsx`
- **Design ref**: Control bar `iDvTC`
- Layout dropdown (Force-directed, Hierarchical, Radial)
- Schema filter dropdown, FK/AI/All toggle buttons
- Confidence slider (0-100%), search input, zoom controls, export button
- Node/edge count display

#### Task 15: Enhanced Node Inspector for Tables
- Edit `src/components/graph/NodeInspector.tsx`
- Add table detail view when a SchemaTable is selected
- Show: schema badge, column list (PK/UQ indicators), relationships (outgoing/incoming with confidence), AI description, row count

### Track B: Admin Sync Portal (Tasks 16-20)

#### Task 16: Sync Types + Hook
- Create `src/types/sync.ts`
- Create `src/hooks/use-sync.ts` with `useSyncJobs`, `useSyncTrigger`, `useQueueStatus`
- SSE hook for real-time progress: `useSyncProgress` using `EventSource`
- API endpoints from BA-012 §8

#### Task 17: Admin Sync Page
- Create `src/app/(dashboard)/admin/sync/page.tsx`
- **Design ref**: Screen `zwNir`
- Layout: Queue Status Row → Active Syncs Card → Trigger Card → Job History Card
- Uses Card/Glass, StatCard, ProgressBar, Gauge components

#### Task 18: Queue Status Row
- Create `src/components/admin/QueueStatus.tsx`
- **Design ref**: node `a93i8`
- 4 StatCards (Normal, High, Processing, Dead Letter) + 1 Gauge (RPM)

#### Task 19: Sync Progress Component
- Create `src/components/admin/SyncProgress.tsx`
- **Design ref**: Active syncs card `WXTi8`, rows `YT0yZ`/`z6OOp`
- Multi-step: Step N of 4, percentage, cancel button

#### Task 20: Sync Job History Table
- Create `src/components/admin/SyncHistory.tsx`
- **Design ref**: Table `TvoIB`
- 6 columns (JOB, DATA SOURCE, TYPE, STATUS, DURATION, TIME)

---

## Sprint 4: AI Natural Language Query (7 tasks)

**BA**: BA-011 | **Design**: `ai-query.pen` → Screen `IBtey`

### Task 21: AI Query Types + Hook
- Create `src/types/ai-query.ts`
- Create `src/hooks/use-ai-query.ts` with `useSubmitQuery`, `useQueryResult`, `useQueryHistory`, `useQueryFavorites`
- API: BA-011 §8 endpoints (`/api/v1/ai-query/submit`, `/{id}`, `/history`, `/favorites`)
- State machine: submitted → parsing → generating_sql → executing → formatting → completed

### Task 22: AI Query Page Layout
- Create `src/app/(dashboard)/query/page.tsx`
- **Design ref**: Screen `IBtey`, prefix `3:`
- 3-column layout: Sidebar (inherited) | History Panel (280px) `3Ra0M` | Chat Area `uUXNu`
- Chat area: data source bar → messages → input area

### Task 23: Query Input Component
- Create `src/components/query/QueryInput.tsx`
- **Design ref**: custom component `QueryInputBar` node `rYKyP`
- Chat-style input: message-square icon, placeholder, cyan send button with glow
- Submit on Enter, Shift+Enter for newline

### Task 24: Query History Panel
- Create `src/components/query/QueryHistory.tsx`
- **Design ref**: history panel `3Ra0M`, custom components `HistoryItem` `0Pmax`, `HistoryItemActive` `YKJOm`
- Search bar, list of history items (query preview + meta: time, row count)
- Active item: cyan highlight with border-focus

### Task 25: Results Table Component
- Create `src/components/query/ResultsTable.tsx`
- **Design ref**: Results area with Table/Chart/Summary tabs `W5qwP` (from README)
- Tabs using Tabs/Container component pattern
- Table tab: dynamic columns from query results, pagination
- Export CSV button, Star/favorite button

### Task 26: Suggestion Chips
- Create `src/components/query/SuggestionChips.tsx`
- **Design ref**: custom component `SuggestionChip` node `GpD2D`
- Pills with sparkle/trend/users icons + suggestion text
- Click to populate query input

### Task 27: Query Explanation Toggle
- Create `src/components/query/QueryExplanation.tsx`
- Expandable panel: tables used, relationships traversed, generated SQL (monospace), confidence
- "Show Explanation" button toggles visibility

---

## Sprint 5: Query Refinement + Usage Dashboard (9 tasks)

**BAs**: BA-011 (continued) + BA-012 §6 | **Designs**: `ai-query.pen`, `usage-dashboard.pen` → `hdcYF`

**Parallel tracks**: Query enhancements (28-30) + Usage dashboard (31-36) are independent.

### Track A: Query Enhancements (Tasks 28-30)

#### Task 28: Clarification Flow
- Create `src/components/query/QueryClarification.tsx`
- When query status is `clarification_needed`: show prompt + 2-4 option buttons
- API: `GET /api/v1/ai-query/{id}/clarification`, `POST /api/v1/ai-query/{id}/clarification`

#### Task 29: Query Favorites
- Add star/unfavorite toggle to results table
- API: `POST/DELETE /api/v1/ai-query/favorites`

#### Task 30: Enhanced Query History
- Add favorites filter tab to QueryHistory panel
- Show shared favorites from project

### Track B: Usage Dashboard (Tasks 31-36)

#### Task 31: Usage Types + Hook
- Create `src/types/usage.ts`, `src/hooks/use-usage.ts`
- API: BA-012 §8 usage endpoints (`/api/v1/admin/usage/summary`, `/metrics`, `/budget`)

#### Task 32: Usage Dashboard Page
- Create `src/app/(dashboard)/admin/usage/page.tsx`
- **Design ref**: Screen `hdcYF`
- Layout: Time Range Tabs → Stats Row → Budget Card → Charts Row

#### Task 33: Token Usage Chart
- Create `src/components/admin/TokenUsageChart.tsx`
- **Design ref**: Query Volume Card `MUCzF`
- 7-bar chart with gradient fills, today highlighted green

#### Task 34: Rate Limit Gauge
- Create `src/components/admin/RateLimitGauge.tsx`
- **Design ref**: Gauge component `GnpRN`
- Donut ring: current RPM / max RPM

#### Task 35: Budget Progress Bar
- Create `src/components/admin/BudgetProgress.tsx`
- **Design ref**: Token Budget Card `4nbG7`
- Progress bar: 2.1M/10M (21%), warning markers at 50% and 80%

#### Task 36: Top Queries Card
- **Design ref**: Top Queries Card `VPqzI`
- Ranked list: 5 queries with execution counts

---

## Sprint 6: Benchmark Dashboard + E2E Polish (8 tasks)

**BA**: BA-013 | **Design**: `benchmarks.pen` → Screen `qHzRv`

### Task 37: Benchmark Types + Hook
- Create `src/types/benchmark.ts`, `src/hooks/use-benchmarks.ts`
- Types: `BenchmarkRun`, `BenchmarkQuestion`, `BenchmarkResult`, `AccuracyScore`
- API: `GET/POST /api/v1/benchmarks/runs`, `GET /api/v1/benchmarks/runs/{id}/results`

### Task 38: Benchmark Dashboard Page
- Create `src/app/(dashboard)/benchmarks/page.tsx`
- **Design ref**: Screen `qHzRv`
- Layout: Top bar → Stats Row → Accuracy by Difficulty + Trend → Results Table

### Task 39: Accuracy Card
- Create `src/components/benchmarks/AccuracyCard.tsx`
- **Design ref**: node `hB0xL`
- Large "94.5%" in Orbitron + neon green glow + Pass badge

### Task 40: Difficulty Bars
- Create `src/components/benchmarks/DifficultyBars.tsx`
- **Design ref**: node `yo0Q4`
- 3 horizontal bars: Simple 97% green, Medium 94% cyan, Complex 89% yellow

### Task 41: Accuracy Trend Chart
- Create `src/components/benchmarks/AccuracyTrend.tsx`
- **Design ref**: node `g0LlQ`
- SVG line chart + 95% threshold dashed red line

### Task 42: Benchmark Results Table
- Create `src/components/benchmarks/ResultsTable.tsx`
- **Design ref**: Table `0hsPh`
- 5 columns (QUESTION, DIFFICULTY, SCORE, LATENCY, Δ delta arrows)

### Task 43: Run Benchmark Button + New Run Flow
- Top bar: data source dropdown + "Run Benchmark" primary button
- Trigger: `POST /api/v1/benchmarks/runs`
- Show progress while running

### Task 44: Final Build + CLAUDE.md Update
- `npm run build` — verify no errors
- `npm run lint` — verify no warnings
- Update `ennam.kg.next/CLAUDE.md` with Phase 2 routes and conventions

---

## Task Count Summary

| Sprint | Tasks | New Files | Modified Files |
|--------|-------|-----------|----------------|
| S1: Data Sources | 6 | 5 | 1 |
| S2: KG Generation | 4 | 3 | 1 |
| S3: KG Viz + Sync | 10 | 9 | 2 |
| S4: AI Query | 7 | 7 | 0 |
| S5: Refinement + Usage | 9 | 7 | 2 |
| S6: Benchmarks | 8 | 7 | 1 |
| **Total** | **44** | **38** | **7** |
