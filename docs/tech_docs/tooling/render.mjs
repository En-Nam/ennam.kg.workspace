// Usage: node render.mjs <input.html> <output.pdf> "<footer title>"
import puppeteer from 'puppeteer-core';
import { resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { unlinkSync } from 'node:fs';

const MIN_LABEL_PT = 6.5;
const [, , input, output, footerTitle = '', brand = '#0e4c6e'] = process.argv;

const browser = await puppeteer.launch({
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: true,
});
const page = await browser.newPage();
await page.setViewport({ width: 673, height: 1100 }); // A4 content width at 96 dpi
await page.emulateMediaType('print');
page.on('console', (m) => { if (m.type() === 'error') console.error('[page]', m.text()); });
await page.goto('file://' + resolve(input), { waitUntil: 'networkidle0' });
// Diagrams are rendered by the document itself (tooling/mermaid-init.js); wait for it.
await page.waitForFunction('window.__diagramsDone === true', { timeout: 120000 });
const failures = await page.evaluate(() => window.__diagramErrors);
const small = (await page.evaluate(() => window.__diagramScales ?? [])).filter((d) => d.pt < MIN_LABEL_PT);
if (small.length) console.warn(`  small diagram text (<${MIN_LABEL_PT}pt): ` + small.map((d) => `${d.pt}pt "${d.cap}"`).join(' | '));
if (failures.length) { console.error('Mermaid failures:\n' + failures.join('\n')); }
const footerTemplate = `<div style="font-size:9px;width:100%;padding:0 16mm;color:#6b7686;display:flex;justify-content:space-between;align-items:center;font-family:'Be Vietnam Pro',Helvetica"><span><span style="display:inline-block;width:14px;height:3px;background:${brand};vertical-align:middle;margin-right:6px"></span>${footerTitle}</span><span style="color:${brand};font-weight:bold"><span class="pageNumber"></span><span style="color:#9aa3af;font-weight:normal"> / <span class="totalPages"></span></span></span></div>`;
const base = { printBackground: true, preferCSSPageSize: true };
const hasCover = await page.evaluate(() => !!document.querySelector('section.cover'));
if (hasCover) {
  // The full-bleed cover is printed without a footer; numbering starts after it.
  const coverPdf = output.replace(/\.pdf$/, '.cover.tmp.pdf');
  const bodyPdf = output.replace(/\.pdf$/, '.body.tmp.pdf');
  await page.pdf({ ...base, path: coverPdf, pageRanges: '1' });
  await page.evaluate(() => document.querySelector('section.cover').remove());
  await page.pdf({ ...base, path: bodyPdf, displayHeaderFooter: true, headerTemplate: '<span></span>', footerTemplate });
  execFileSync('pdfunite', [coverPdf, bodyPdf, output]);
  unlinkSync(coverPdf); unlinkSync(bodyPdf);
} else {
  await page.pdf({ ...base, path: output, displayHeaderFooter: true, headerTemplate: '<span></span>', footerTemplate });
}
await browser.close();
console.log('wrote', output, failures.length ? `(${failures.length} diagram errors)` : '(all diagrams ok)');
process.exit(failures.length ? 1 : 0);
