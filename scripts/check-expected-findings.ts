// Compares LAAM findings with demo_mockdata/expected_findings.csv (ground truth of the pharmacy demo).
// Usage: node scripts/check-expected-findings.ts [--project <business_project id>] [--findings-json <file>]
//        [--expected <csv>]   DB: read-only SELECT via LAAM/node_modules/pg; DATABASE_URL from env or LAAM/.env (port 5500).
// Prints "PASS n/n" (exit 0) or the misses / unexpected critical findings (exit 1). Exit 2: the selected project has no rows.
// --project defaults to bp-pharmacy-chain-demo so the synthetic project (bp-demo-synthetic) never leaks in.
// Intentional leniency (do not tighten): an expected employee only has to match when the finding carries any EMP-* dim
// (store-level rules are accepted); a critical finding is "expected" if its rule family + store match any expected row;
// findings with status dismissed/resolved still count (the checker verifies detection, not triage).
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export interface ExpectedFinding { findingId: string; storeId: string; employeeId: string; ruleIds: string[] }
export interface ActualFinding { ruleId: string; dims: Record<string, unknown>; severity: string }
export interface CheckResult {
  matched: { expected: ExpectedFinding; actual: ActualFinding }[];
  missing: ExpectedFinding[];
  unexpectedCritical: ActualFinding[];
}

const MULTIPLE = 'multiple';

export function parseCsv(text: string): Record<string, string>[] {
  const records: string[][] = [];
  let field = '';
  let row: string[] = [];
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { field += '"'; i++; } else if (ch === '"') quoted = false; else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') { row.push(field); field = ''; }
    else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++;
      row.push(field); field = '';
      if (row.some((v) => v !== '')) records.push(row);
      row = [];
    } else field += ch;
  }
  if (field !== '' || row.length) { row.push(field); records.push(row); }
  const [header, ...body] = records;
  return body.map((r) => Object.fromEntries(header.map((h, i) => [h, r[i] ?? ''])));
}

export function loadExpected(csvText: string): ExpectedFinding[] {
  return parseCsv(csvText).map((r) => {
    const ruleIds = (r.rule_ids ?? '').split('|').map((s) => s.trim()).filter(Boolean);
    if (!ruleIds.length) throw new Error(`expected finding ${r.finding_id} has no rule_ids`);
    if (r.store_id === undefined) throw new Error(`expected finding ${r.finding_id} has no store_id column`);
    return { findingId: r.finding_id, storeId: r.store_id.trim(), employeeId: (r.employee_id ?? '').trim(), ruleIds };
  });
}

function dimValues(dims: Record<string, unknown>): string[] {
  return Object.values(dims).flatMap((v) => (Array.isArray(v) ? v.map(String) : [String(v)]));
}

function locationMatches(expected: ExpectedFinding, dims: Record<string, unknown>): boolean {
  if (expected.storeId.toLowerCase() === MULTIPLE) return true;
  const loc = dims.location_id;
  return Array.isArray(loc) ? loc.map(String).includes(expected.storeId) : String(loc) === expected.storeId;
}

function employeeMatches(expected: ExpectedFinding, dims: Record<string, unknown>): boolean {
  if (!expected.employeeId) return true;
  const employees = dimValues(dims).filter((v) => /^EMP-/.test(v));
  return employees.length === 0 || employees.includes(expected.employeeId);
}

export function matches(expected: ExpectedFinding, actual: ActualFinding): boolean {
  return expected.ruleIds.includes(actual.ruleId)
    && locationMatches(expected, actual.dims)
    && employeeMatches(expected, actual.dims);
}

export function checkFindings(expected: ExpectedFinding[], actual: ActualFinding[]): CheckResult {
  const matched: CheckResult['matched'] = [];
  const missing: ExpectedFinding[] = [];
  for (const e of expected) {
    const hit = actual.find((a) => matches(e, a));
    if (hit) matched.push({ expected: e, actual: hit }); else missing.push(e);
  }
  const unexpectedCritical = actual.filter((a) => a.severity.toLowerCase() === 'critical'
    && !expected.some((e) => e.ruleIds.includes(a.ruleId) && locationMatches(e, a.dims)));
  return { matched, missing, unexpectedCritical };
}

export function formatReport(result: CheckResult, total: number, actualCount: number): { ok: boolean; text: string } {
  if (actualCount === 0) return { ok: false, text: 'FAIL: no finding rows (did the analysis run?)' };
  const lines: string[] = [];
  for (const m of result.matched) lines.push(`  ok   ${m.expected.findingId} <- ${m.actual.ruleId} ${JSON.stringify(m.actual.dims)}`);
  for (const e of result.missing) lines.push(`  MISS ${e.findingId} (rules ${e.ruleIds.join('|')}, store ${e.storeId}${e.employeeId ? `, employee ${e.employeeId}` : ''})`);
  for (const a of result.unexpectedCritical) lines.push(`  UNEXPECTED CRITICAL ${a.ruleId} ${JSON.stringify(a.dims)}`);
  const ok = result.missing.length === 0 && result.unexpectedCritical.length === 0;
  const head = ok ? `PASS ${result.matched.length}/${total}` : `FAIL ${result.matched.length}/${total}`;
  return { ok, text: [head, ...lines].join('\n') };
}

// LAAM's Drizzle tables use quoted camelCase columns ("scheduledFor"); accept either naming.
export function findingColumns(cols: string[]): { ruleCol: string; projCol: string | null } {
  if (!cols.length) throw new Error('table "finding" not found in LAAM DB (Plan D migrations applied?)');
  const pick = (...names: string[]) => names.find((n) => cols.includes(n)) ?? null;
  const ruleCol = pick('rule_id', 'ruleId');
  if (!ruleCol || !cols.includes('dims') || !cols.includes('severity')) {
    throw new Error(`finding table lacks rule_id/dims/severity columns: ${cols.join(', ')}`);
  }
  return { ruleCol, projCol: pick('project_id', 'projectId') };
}

const LAAM_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'LAAM');

export const DEFAULT_PROJECT = 'bp-pharmacy-chain-demo';
const LAAM_DEV_PORT = '5500';

export function resolveProject(cliValue: string | null): string {
  return cliValue ?? DEFAULT_PROJECT;
}

class ExitError extends Error {
  exitCode: number;
  constructor(message: string, exitCode: number) { super(message); this.exitCode = exitCode; }
}

export function assertProjectHasRows(project: string, projectRows: number, totalRows: number): void {
  if (totalRows > 0 && projectRows === 0) {
    throw new ExitError(`project "${project}" has no finding rows although the table has ${totalRows} (wrong --project?)`, 2);
  }
}

// Only LAAM's dev DB (port 5500) is acceptable; an omitted port means 5432 and is refused too.
export function assertLaamDevUrl(url: string): void {
  let parsed: URL;
  try { parsed = new URL(url); } catch { throw new Error('invalid DATABASE_URL (not parseable)'); }
  for (const key of ['port', 'host', 'hostaddr']) {
    if (parsed.searchParams.has(key)) throw new Error(`refusing DATABASE_URL with a "${key}" query override; LAAM's dev DB is on ${LAAM_DEV_PORT}`);
  }
  const port = parsed.port || '5432';
  if (port !== LAAM_DEV_PORT) throw new Error(`refusing DATABASE_URL on :${port}; LAAM's dev DB is on ${LAAM_DEV_PORT}`);
}

// Credentials come from the environment or LAAM/.env; the URL is never printed.
export function resolveDatabaseUrl(env: NodeJS.ProcessEnv = process.env): string {
  let url = env.DATABASE_URL;
  if (!url) {
    const m = readFileSync(path.join(LAAM_DIR, '.env'), 'utf8').match(/^DATABASE_URL=(.+)$/m);
    url = m?.[1].trim().replace(/^["']|["']$/g, '');
  }
  if (!url) throw new Error('DATABASE_URL not set (env or LAAM/.env)');
  assertLaamDevUrl(url);
  return url;
}

export async function readFindingsFromDb(project: string): Promise<ActualFinding[]> {
  const { Client } = createRequire(path.join(LAAM_DIR, 'package.json'))('pg');
  const client = new Client({ connectionString: resolveDatabaseUrl() });
  await client.connect();
  try {
    await client.query('SET default_transaction_read_only = on');
    const colRes = await client.query("select column_name from information_schema.columns where table_schema='public' and table_name='finding'");
    const { ruleCol, projCol } = findingColumns(colRes.rows.map((r: { column_name: string }) => r.column_name));
    if (!projCol) throw new Error('finding table has no project column');
    const where = ` where "${projCol}" = $1`;
    const res = await client.query(`select "${ruleCol}" as "ruleId", "dims", "severity" from finding${where}`, [project]);
    const total = Number((await client.query('select count(*) as n from finding')).rows[0].n);
    assertProjectHasRows(project, res.rows.length, total);
    return res.rows.map((r: { ruleId: string; dims: Record<string, unknown> | null; severity: string | null }) => ({
      ruleId: r.ruleId, dims: r.dims ?? {}, severity: r.severity ?? '',
    }));
  } finally {
    await client.end();
  }
}

function arg(name: string): string | null {
  const i = process.argv.indexOf(name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : null;
}

async function main(): Promise<void> {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  const expectedPath = arg('--expected') ?? path.join(root, 'demo_mockdata', 'expected_findings.csv');
  const expected = loadExpected(readFileSync(expectedPath, 'utf8'));
  const jsonPath = arg('--findings-json');
  const actual = jsonPath ? (JSON.parse(readFileSync(jsonPath, 'utf8')) as ActualFinding[]) : await readFindingsFromDb(resolveProject(arg('--project')));
  const report = formatReport(checkFindings(expected, actual), expected.length, actual.length);
  console.log(report.text);
  process.exit(report.ok ? 0 : 1);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    await main();
  } catch (err) {
    console.error(`FAIL: ${(err as Error).message}`);
    process.exit((err as { exitCode?: number }).exitCode ?? 1);
  }
}
