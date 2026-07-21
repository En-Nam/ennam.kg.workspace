# MR Sync — Plan 2: AAAA master-record read endpoint

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose AAAA's Master Record to DAAB over the existing `daabTokenOk`-authenticated integration surface, serving only committed sections and reporting deletions as tombstones.

**Architecture:** One new `GET /api/integrations/daab/master-records` route on the same auth surface as the shipped document endpoints. Reads `EntityProfile` + `MasterRecordSection`, filters to `COMPLETED` sections, returns per-section `contentHash` + `sourceDocIds` + `citations` so DAAB can skip unchanged records and resolve provenance edges without a second call.

**Tech Stack:** Next.js 16 App Router, Prisma v7, Vitest.

**Spec:** `docs/superpowers/specs/2026-07-20-aaaa-master-record-to-daab-design.md` (D1, D3, D6, D7, D10)

**Depends on:** Nothing in code. Can run in parallel with Plan 1. **Plan 3 depends on both.**

## Global Constraints

- Repo: `other_projects/am-ai-agents` — has its own `.git`.
- Auth: reuse `daabTokenOk` from `src/lib/integrations/daab-auth.ts` (async, DB-backed, fails closed). **Do not invent a second credential.**
- The route lives under `/api/integrations/daab/` — already covered by the public-path entry `"/api/integrations/daab/documents"`… **which does NOT match this new path.** See Task 1 Step 1: `src/proxy.ts` must be extended, or the route 401s at the proxy before its own auth runs.
- Response is a **fixed snake_case contract** consumed by DAAB's Python worker — mirror the style of `src/app/api/integrations/daab/documents/route.ts`.
- Section status enum is `SectionStatus { BUILDING, COMPLETED, FAILED, STALE }` — **there is no `READY`**. Committed means `COMPLETED`.
- Profile status enum is `MasterRecordStatus { PENDING, BUILDING, COMPLETED, FAILED }`.
- Read `node_modules/next/dist/docs/` before writing route code — this Next.js version differs from training data.

---

### Task 1: Route skeleton, auth, and proxy path

**Files:**
- Create: `src/app/api/integrations/daab/master-records/route.ts`
- Modify: `src/proxy.ts` (public API paths)
- Test: `src/app/api/integrations/daab/master-records/route.test.ts`
- Test: `src/proxy.public-paths.test.ts` (extend)

**Interfaces:**
- Produces: `GET /api/integrations/daab/master-records?projectId=<uuid>` → `200` with the contract in Task 2, `400` without `projectId`, `401` without a valid sync key.

- [ ] **Step 1: Write the failing tests**

`src/proxy.public-paths.test.ts` — add:

```ts
it("exposes the DAAB master-records sync route", () => {
  // WHY: this route is called by DAAB's worker with a Bearer sync key, never a
  // Supabase session. Without a public-path entry the proxy 401s before
  // daabTokenOk ever runs — the route's own auth would be dead code.
  expect(isPublic("/api/integrations/daab/master-records")).toBe(true);
});

it("still does NOT expose the key-management route", () => {
  expect(isPublic("/api/integrations/daab/keys")).toBe(false);
});
```

`src/app/api/integrations/daab/master-records/route.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { NextRequest } from "next/server";

const verifyKey = vi.hoisted(() => vi.fn());
vi.mock("@/services/daab-key.service", () => ({ verifyKey }));

const findFirst = vi.hoisted(() => vi.fn());
const findMany = vi.hoisted(() => vi.fn());
vi.mock("@/lib/db", () => ({
  db: { entityProfile: { findFirst }, masterRecordSection: { findMany } },
}));

import { GET } from "./route";

const get = (url: string, token?: string) =>
  GET(new NextRequest(url, { headers: token ? { authorization: token } : {} }));

beforeEach(() => {
  vi.clearAllMocks();
  verifyKey.mockImplementation(async (t: string) => t === "s3cr3t");
});

describe("GET /api/integrations/daab/master-records", () => {
  it("401 without an Authorization header", async () => {
    const res = await get("http://x/api/integrations/daab/master-records?projectId=p1");
    expect(res.status).toBe(401);
    expect(findFirst).not.toHaveBeenCalled();
  });

  it("401 when no active key matches (fail closed)", async () => {
    verifyKey.mockResolvedValue(false);
    const res = await get("http://x/api/integrations/daab/master-records?projectId=p1", "Bearer s3cr3t");
    expect(res.status).toBe(401);
    expect(findFirst).not.toHaveBeenCalled();
  });

  it("400 when projectId is missing", async () => {
    const res = await get("http://x/api/integrations/daab/master-records", "Bearer s3cr3t");
    expect(res.status).toBe(400);
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `npm test -- src/app/api/integrations/daab/master-records src/proxy.public-paths.test.ts`
Expected: FAIL — route module missing; proxy assertion false.

- [ ] **Step 3: Add the proxy path**

In `src/proxy.ts`, add alongside the documents entry:

```ts
  // DAAB↔AAAA master-record sync: called by the DAAB worker with a Bearer sync
  // key, never a Supabase session. Listed explicitly (not a broad
  // "/api/integrations/daab" prefix) so /keys stays behind the session guard.
  "/api/integrations/daab/master-records",
```

- [ ] **Step 4: Create the route with auth + validation only**

```ts
import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { daabTokenOk } from "@/lib/integrations/daab-auth";

/**
 * Master Record feed for DAAB's sync worker. Serves only COMPLETED sections so a
 * half-built record is never ingested, and reports per-section contentHash so the
 * worker can skip unchanged records entirely (spec D6).
 *
 * Response fields are a fixed snake_case contract consumed by DAAB — do not rename
 * without a coordinated change on the DAAB side.
 */
export async function GET(req: NextRequest) {
  if (!(await daabTokenOk(req.headers.get("authorization")))) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const projectId = req.nextUrl.searchParams.get("projectId");
  if (!projectId) {
    return NextResponse.json({ error: "projectId required" }, { status: 400 });
  }

  return NextResponse.json({ master_record: null, tombstone: false });
}
```

- [ ] **Step 5: Run to verify they pass**

Run: `npm test -- src/app/api/integrations/daab/master-records src/proxy.public-paths.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/app/api/integrations/daab/master-records src/proxy.ts src/proxy.public-paths.test.ts
git commit -m "feat(daab): master-record read endpoint skeleton with sync-key auth"
```

---

### Task 2: Serve committed sections with change-detection and provenance data

**Files:**
- Modify: `src/app/api/integrations/daab/master-records/route.ts`
- Test: `src/app/api/integrations/daab/master-records/route.test.ts` (extend)

**Interfaces:**
- Produces the response contract:

```jsonc
{
  "master_record": {
    "record_ref": "project:<projectId>",       // spec D3 — stable across profile rebuild
    "project_id": "<aaaa project uuid>",
    "title": "Master Record — <project name>",
    "profile_status": "COMPLETED",
    "generated_at": "2026-07-20T09:00:00.000Z",
    "summary": "<cross-section abstract, <=8000 chars>",
    "content": "<full rendered record>",
    "sections_present": ["identity", "financial"],
    "sections_stale":   ["risk"],               // known but not COMPLETED (spec D10)
    "content_hash": "<sha256 of the COMPLETED section hashes, ordered>",
    "source_doc_ids": ["<uuid>", "..."],        // union across COMPLETED sections
    "citations": [ { "section_key": "financial", "document_id": "<uuid>" } ]
  },
  "tombstone": false
}
```

- [ ] **Step 1: Write the failing tests**

```ts
const section = (over: Partial<Record<string, unknown>> = {}) => ({
  sectionKey: "financial",
  status: "COMPLETED",
  data: { text: "Revenue 123" },
  sourceDocIds: ["doc-1"],
  citations: [{ document_id: "doc-1" }],
  contentHash: "h1",
  updatedAt: new Date("2026-07-20T09:00:00Z"),
  ...over,
});

it("returns only COMPLETED sections and lists the rest as stale", async () => {
  // WHY (spec D6/D10): a section mid-rebuild must never be served as fact, but the
  // consumer must still be told it exists — silence would let LAAM answer
  // "no risks identified" for a company whose risk section was merely still building.
  findFirst.mockResolvedValue({ id: "e1", projectId: "p1", status: "COMPLETED", updatedAt: new Date() });
  findMany.mockResolvedValue([
    section(),
    section({ sectionKey: "risk", status: "BUILDING", contentHash: "h2" }),
  ]);
  const res = await get("http://x/api/integrations/daab/master-records?projectId=p1", "Bearer s3cr3t");
  const json = await res.json();
  expect(json.master_record.sections_present).toEqual(["financial"]);
  expect(json.master_record.sections_stale).toEqual(["risk"]);
  expect(JSON.stringify(json)).not.toContain("Revenue 123 risk");
});

it("uses a project-scoped record_ref, not the profile id", async () => {
  // WHY (spec D3/F3): EntityProfile.id changes when a profile is rebuilt while the
  // company does not — keying on it would create a second node and orphan the first.
  findFirst.mockResolvedValue({ id: "profile-CHANGED", projectId: "p1", status: "COMPLETED", updatedAt: new Date() });
  findMany.mockResolvedValue([section()]);
  const res = await get("http://x/api/integrations/daab/master-records?projectId=p1", "Bearer s3cr3t");
  const json = await res.json();
  expect(json.master_record.record_ref).toBe("project:p1");
  expect(json.master_record.record_ref).not.toContain("profile-CHANGED");
});

it("content_hash changes when a COMPLETED section changes", async () => {
  findFirst.mockResolvedValue({ id: "e1", projectId: "p1", status: "COMPLETED", updatedAt: new Date() });
  findMany.mockResolvedValue([section({ contentHash: "h1" })]);
  const a = await (await get("http://x/api/integrations/daab/master-records?projectId=p1", "Bearer s3cr3t")).json();
  findMany.mockResolvedValue([section({ contentHash: "h2" })]);
  const b = await (await get("http://x/api/integrations/daab/master-records?projectId=p1", "Bearer s3cr3t")).json();
  expect(a.master_record.content_hash).not.toBe(b.master_record.content_hash);
});

it("content_hash is stable across section ordering", async () => {
  // Prisma ordering must not change the hash, or every fetch looks like a change
  // and the D6 skip-unchanged optimisation silently stops working.
  findFirst.mockResolvedValue({ id: "e1", projectId: "p1", status: "COMPLETED", updatedAt: new Date() });
  findMany.mockResolvedValue([section({ sectionKey: "a", contentHash: "x" }), section({ sectionKey: "b", contentHash: "y" })]);
  const a = await (await get("http://x/api/integrations/daab/master-records?projectId=p1", "Bearer s3cr3t")).json();
  findMany.mockResolvedValue([section({ sectionKey: "b", contentHash: "y" }), section({ sectionKey: "a", contentHash: "x" })]);
  const b = await (await get("http://x/api/integrations/daab/master-records?projectId=p1", "Bearer s3cr3t")).json();
  expect(a.master_record.content_hash).toBe(b.master_record.content_hash);
});

it("returns master_record null when no COMPLETED section exists", async () => {
  findFirst.mockResolvedValue({ id: "e1", projectId: "p1", status: "BUILDING", updatedAt: new Date() });
  findMany.mockResolvedValue([section({ status: "BUILDING" })]);
  const res = await get("http://x/api/integrations/daab/master-records?projectId=p1", "Bearer s3cr3t");
  const json = await res.json();
  expect(json.master_record).toBeNull();
  expect(json.tombstone).toBe(false);
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `npm test -- src/app/api/integrations/daab/master-records`
Expected: FAIL — route returns the stub.

- [ ] **Step 3: Implement the body**

```ts
import { createHash } from "node:crypto";

const COMPLETED = "COMPLETED";

function stableContentHash(rows: Array<{ sectionKey: string; contentHash: string | null }>): string {
  // Sorted by sectionKey so DB ordering never changes the hash — otherwise every
  // fetch would look like a change and the skip-unchanged path (D6) would be dead.
  const material = [...rows]
    .sort((a, b) => a.sectionKey.localeCompare(b.sectionKey))
    .map((r) => `${r.sectionKey}:${r.contentHash ?? ""}`)
    .join("|");
  return createHash("sha256").update(material).digest("hex");
}
```

Then, after the `projectId` guard:

```ts
  const profile = await db.entityProfile.findFirst({
    where: { projectId, entityKind: "PROJECT" },
    select: { id: true, projectId: true, status: true, updatedAt: true, thesis: true, masterRecord: true },
  });
  if (!profile) {
    return NextResponse.json({ master_record: null, tombstone: false });
  }

  const sections = await db.masterRecordSection.findMany({
    where: { projectId },
    select: {
      sectionKey: true, status: true, data: true, sourceDocIds: true,
      citations: true, contentHash: true, updatedAt: true, builtAt: true,
    },
  });

  const done = sections.filter((s) => s.status === COMPLETED);
  const stale = sections.filter((s) => s.status !== COMPLETED).map((s) => s.sectionKey).sort();

  if (done.length === 0) {
    return NextResponse.json({ master_record: null, tombstone: false });
  }

  const sourceDocIds = [...new Set(done.flatMap((s) => s.sourceDocIds ?? []))];
  const citations = done.flatMap((s) =>
    Array.isArray(s.citations)
      ? (s.citations as Array<Record<string, unknown>>).map((c) => ({
          section_key: s.sectionKey,
          document_id: typeof c.document_id === "string" ? c.document_id : null,
        }))
      : []
  ).filter((c) => c.document_id);

  const generatedAt = done.reduce<Date | null>(
    (acc, s) => (s.builtAt && (!acc || s.builtAt > acc) ? s.builtAt : acc), null
  );

  return NextResponse.json({
    master_record: {
      record_ref: `project:${projectId}`,
      project_id: projectId,
      title: `Master Record — ${projectId}`,
      profile_status: profile.status,
      generated_at: (generatedAt ?? profile.updatedAt).toISOString(),
      summary: buildSummary(profile, done),
      content: renderContent(profile, done),
      sections_present: done.map((s) => s.sectionKey).sort(),
      sections_stale: stale,
      content_hash: stableContentHash(done),
      source_doc_ids: sourceDocIds,
      citations,
    },
    tombstone: false,
  });
```

- [ ] **Step 4: Implement `buildSummary` and `renderContent`**

Put both in `src/lib/master-record/daab-render.ts` (new) with unit tests — keep the route thin.

- `renderContent(profile, sections)` — full markdown body: `profile.thesis` first, then each COMPLETED section rendered from `data`, ordered by `sectionKey`.
- `buildSummary(profile, sections)` — cross-section abstract, **hard-capped at 8000 chars** to match the DAAB schema (Plan 1 Task 2). Truncate on a whitespace boundary and append `…`; never emit >8000 or the DAAB upsert 400s.

Test both: a >8000-char input must yield ≤8000 output, and `renderContent` must include every COMPLETED section key and no non-COMPLETED one.

- [ ] **Step 5: Run tests**

Run: `npm test -- src/app/api/integrations/daab/master-records src/lib/master-record/daab-render`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/app/api/integrations/daab/master-records src/lib/master-record/daab-render.ts src/lib/master-record/daab-render.test.ts
git commit -m "feat(daab): serve COMPLETED master-record sections with stable content hash"
```

---

### Task 3: Tombstones for deleted projects

**Files:**
- Modify: `src/app/api/integrations/daab/master-records/route.ts`
- Test: `src/app/api/integrations/daab/master-records/route.test.ts` (extend)

**Interfaces:**
- Produces: `{ "master_record": null, "tombstone": true }` when the project no longer exists.

- [ ] **Step 1: Write the failing test**

```ts
it("reports a tombstone when the project no longer exists", async () => {
  // WHY (spec D7): MasterRecordSection cascades on project delete
  // (schema.prisma:969). A pull cursor sees ABSENCE, not deletion — without an
  // explicit tombstone the derived_record survives in DAAB forever and LAAM keeps
  // answering from a company profile that no longer exists in the system of record.
  projectFindUnique.mockResolvedValue(null);   // project gone
  findFirst.mockResolvedValue(null);           // profile cascaded away
  const res = await get("http://x/api/integrations/daab/master-records?projectId=gone", "Bearer s3cr3t");
  const json = await res.json();
  expect(json.tombstone).toBe(true);
  expect(json.master_record).toBeNull();
});

it("does NOT tombstone a live project that simply has no master record yet", async () => {
  // The distinction that makes tombstones safe: "never built" must never be
  // mistaken for "deleted", or a brand-new project would revoke itself in DAAB.
  projectFindUnique.mockResolvedValue({ id: "p1" });
  findFirst.mockResolvedValue(null);
  const res = await get("http://x/api/integrations/daab/master-records?projectId=p1", "Bearer s3cr3t");
  const json = await res.json();
  expect(json.tombstone).toBe(false);
  expect(json.master_record).toBeNull();
});
```

Add `project: { findUnique: projectFindUnique }` to the `@/lib/db` mock.

- [ ] **Step 2: Run to verify it fails**

Run: `npm test -- src/app/api/integrations/daab/master-records`
Expected: FAIL — `tombstone` is always false.

- [ ] **Step 3: Implement**

Before the profile lookup:

```ts
  // Distinguish "deleted" from "never built": both yield a null profile, but only
  // the first may revoke the record in DAAB (spec D7).
  const project = await db.project.findUnique({ where: { id: projectId }, select: { id: true } });
  if (!project) {
    return NextResponse.json({ master_record: null, tombstone: true });
  }
```

- [ ] **Step 4: Run tests**

Run: `npm test -- src/app/api/integrations/daab/master-records`
Expected: PASS (all tests across Tasks 1-3).

- [ ] **Step 5: Verify build**

Run: `npm run lint && npm run build`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/app/api/integrations/daab/master-records
git commit -m "feat(daab): tombstone deleted projects so DAAB can revoke stale records"
```

---

## Self-Review

**Spec coverage:** D1 (AAAA read endpoint on the existing credential) → Task 1. D3 (`project:<id>` record_ref) → Task 2. D6 (COMPLETED-only + contentHash) → Task 2. D10 (`sections_present`/`sections_stale`) → Task 2. D7 (tombstones) → Task 3. ✓

**Corrected while writing this plan:** the spec said `status = READY`; the actual enum is `SectionStatus { BUILDING, COMPLETED, FAILED, STALE }` — no `READY` exists. The spec was fixed; this plan uses `COMPLETED`.

**Placeholder scan:** Task 2 Step 4 specifies `buildSummary`/`renderContent` by contract and test obligations rather than full bodies, because the rendering shape depends on `MasterRecordSection.data` payloads not enumerated here. Every other step carries complete code. The 8000-char cap is stated as a hard requirement because exceeding it makes the Plan 1 upsert reject the payload.

**Type consistency:** `record_ref` = `project:<projectId>` here, consumed unchanged by Plan 3 and stored as the Plan 1 idempotency key. `content_hash` (snake_case, response) ↔ `contentHash` (Prisma field). `sections_present`/`sections_stale` match the Plan 1 config field names exactly. ✓

**Not covered (by design):** the worker that calls this endpoint, edge resolution, and the reconcile sweep are Plan 3.
