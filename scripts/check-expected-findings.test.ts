import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { checkFindings, findingColumns, formatReport, loadExpected, parseCsv } from './check-expected-findings.ts';
import type { ActualFinding } from './check-expected-findings.ts';

const csv = readFileSync(new URL('../demo_mockdata/expected_findings.csv', import.meta.url), 'utf8');
const expected = loadExpected(csv);

const allFound: ActualFinding[] = [
  { ruleId: 'RET-REF-001', dims: { location_id: 'PH-001', employee_id: 'EMP-0006' }, severity: 'high' },
  { ruleId: 'RET-INV-010', dims: { location_id: 'PH-005' }, severity: 'high' },
  { ruleId: 'RET-REF-004', dims: { location_id: ['PH-001', 'PH-002'] }, severity: 'high' },
  { ruleId: 'RET-DISC-003', dims: { location_id: 'PH-002', approver_id: 'EMP-0023' }, severity: 'medium' },
  { ruleId: 'PH-CLAIM-001', dims: { location_id: 'PH-004' }, severity: 'high' },
  { ruleId: 'RET-CASH-001', dims: { location_id: 'PH-005', employee_id: 'EMP-0102' }, severity: 'high' },
  { ruleId: 'RET-X-REPRINT-001', dims: { location_id: 'PH-001', employee_id: 'EMP-0006' }, severity: 'high' },
  { ruleId: 'RET-SALES-001', dims: { location_id: 'PH-004' }, severity: 'medium' },
  { ruleId: 'PH-MARGIN-001', dims: { location_id: 'PH-003' }, severity: 'critical' },
];

test('expected file carries a rule family for every row, incl. the new FND-008/009', () => {
  assert.equal(expected.length, 9);
  assert.deepEqual(expected.at(-1)?.ruleIds, ['PH-MARGIN-001', 'RET-MARGIN-002', 'RET-VENDOR-001']);
});

test('parseCsv keeps quoted commas inside one field', () => {
  const rows = parseCsv('a,b\n"x, y",2\n');
  assert.deepEqual(rows, [{ a: 'x, y', b: '2' }]);
});

test('PASS n/n when every expected finding is found and the only critical one is expected', () => {
  const report = formatReport(checkFindings(expected, allFound), expected.length, allFound.length);
  assert.equal(report.ok, true);
  assert.match(report.text, /^PASS 9\/9/);
});

test('a missing plant is reported by id', () => {
  const actual = allFound.filter((a) => a.ruleId !== 'PH-CLAIM-001');
  const report = formatReport(checkFindings(expected, actual), expected.length, actual.length);
  assert.equal(report.ok, false);
  assert.match(report.text, /MISS FND-005/);
});

test('right rule at the wrong store or wrong employee does not count', () => {
  const actual = allFound.map((a) => (a.ruleId === 'RET-REF-001' ? { ...a, dims: { location_id: 'PH-001', employee_id: 'EMP-0007' } } : a));
  const result = checkFindings(expected, actual);
  assert.deepEqual(result.missing.map((e) => e.findingId), ['FND-001']);
  const moved = allFound.map((a) => (a.ruleId === 'RET-INV-010' ? { ...a, dims: { location_id: 'PH-001' } } : a));
  assert.deepEqual(checkFindings(expected, moved).missing.map((e) => e.findingId), ['FND-002']);
});

test('an unexpected critical finding fails the run (case-insensitive severity)', () => {
  const actual = [...allFound, { ruleId: 'RET-VOID-001', dims: { location_id: 'PH-003' }, severity: 'CRITICAL' }];
  const report = formatReport(checkFindings(expected, actual), expected.length, actual.length);
  assert.equal(report.ok, false);
  assert.match(report.text, /UNEXPECTED CRITICAL RET-VOID-001/);
});

test('zero finding rows is a failure, never PASS 0/0', () => {
  const report = formatReport(checkFindings(expected, []), expected.length, 0);
  assert.equal(report.ok, false);
  assert.match(report.text, /no finding rows/);
});

test('finding columns are detected in snake_case and camelCase, missing table is an error', () => {
  assert.deepEqual(findingColumns(['id', 'rule_id', 'dims', 'severity', 'project_id']), { ruleCol: 'rule_id', projCol: 'project_id' });
  assert.deepEqual(findingColumns(['id', 'ruleId', 'dims', 'severity', 'projectId']), { ruleCol: 'ruleId', projCol: 'projectId' });
  assert.throws(() => findingColumns([]), /not found/);
  assert.throws(() => findingColumns(['id', 'dims']), /lacks/);
});
