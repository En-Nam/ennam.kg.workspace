// Renders every docs/tech_docs/{daab,laam}/{en,vi}/*.html to docs/tech_docs/pdf/.
// Usage: node build.mjs [filter]   e.g. `node build.mjs daab/en`
import { readdirSync, readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { resolve, dirname, basename } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const filter = process.argv[2] ?? '';
const failed = [];
const BRAND = { daab: '#0e4c6e', laam: '#36207c' };

for (const product of ['daab', 'laam']) {
  for (const lang of ['en', 'vi']) {
    const dir = resolve(root, product, lang);
    for (const file of readdirSync(dir).filter((f) => f.endsWith('.html')).sort()) {
      const rel = `${product}/${lang}/${file}`;
      if (!rel.includes(filter)) continue;
      const html = readFileSync(resolve(dir, file), 'utf8');
      const title = (html.match(/<title>([^<]*)<\/title>/) ?? [, product.toUpperCase()])[1];
      const out = resolve(root, 'pdf', `${product.toUpperCase()}-${basename(file, '.html')}-${lang.toUpperCase()}.pdf`);
      try {
        execFileSync('node', [resolve(here, 'render.mjs'), resolve(dir, file), out, title, BRAND[product]], { stdio: 'inherit' });
      } catch {
        failed.push(rel);
      }
    }
  }
}
if (failed.length) {
  console.error('FAILED:', failed.join(', '));
  process.exit(1);
}
