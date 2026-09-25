# EN → VI translation guide (tech docs pack)

The EN HTML is the source of truth. The VI file is a faithful translation: same structure,
same facts, same numbers, same diagrams, same status pills. Do not add, drop or "improve" claims.

## Output
Copy `<product>/en/NN-*.html` → `<product>/vi/NN-*.html` (same filename), set `<html lang="vi">`,
translate, then render with `node build.mjs <product>/vi/NN` from `tooling/`.

## Style
- Văn phong tài liệu kỹ thuật chuyên nghiệp, câu ngắn gọn, rõ ràng; xưng hô trung tính (không "chúng tôi/bạn" trừ khi bản EN dùng "we").
- Keep in English (as Vietnamese engineers use them): product names, technology names, protocol
  names, code identifiers, table/column names, endpoints, env vars, tool names, file paths,
  licence names, model names. Common terms may stay English where Vietnamese engineers normally
  say them: API, MCP, workflow, connector, token, prompt, embedding, pipeline, dashboard, cache,
  queue, worker, commit, test, lint, CI/CD, container, deploy, runtime, SSO, OAuth.
- Translate everything else, including table headers, captions, callouts, KPI labels, TOC, cover.
- Fixed terms: Figure → Hình · Contents → Mục lục · Appendix → Phụ lục · Version → Phiên bản ·
  Date → Ngày · Code baseline → Phiên bản mã nguồn · Technical Documentation → Tài liệu kỹ thuật ·
  System Architecture → Kiến trúc hệ thống · Infrastructure, Security & Operations → Hạ tầng, Bảo mật & Vận hành ·
  Maturity, Roadmap & IP → Mức độ hoàn thiện, Lộ trình & Sở hữu trí tuệ · Technical Brief → Tổng quan kỹ thuật ·
  pre-production → giai đoạn tiền production (chưa triển khai production) · Known limitations → Hạn chế đã biết ·
  Hardening items → Hạng mục gia cố.
- Status pills stay as-is in English (LIVE / BUILT / PLANNED / TO BE COMPLETED) — they are a
  shared vocabulary; the status-vocabulary section explains them in Vietnamese.
- Dates: keep ISO `2026-09-24`. Numbers: keep EN digit grouping as in source (1,221) to avoid
  ambiguity; percentages unchanged.
- `<title>` → Vietnamese, e.g. `LAAM — Kiến trúc hệ thống` (used as PDF footer).

## Diagrams
Translate node/edge labels and subgraph titles; keep identifiers in English. Vietnamese text is
~15–25% longer: add `<br/>` (written `&lt;br/&gt;` inside `<pre class="mermaid">` if the source
does so) to keep boxes compact. Don't change diagram structure.

## QA (mandatory)
1. Build must report `(all diagrams ok)`.
2. READ every page of the PDF: check diacritics, clipped labels, overflowing tables, orphan
   headings, awkward blank space. VI runs longer — adjust page breaks / figure height caps if needed.
3. Compare section count, figure count and table count against the EN file (a quick grep count of
   `<h2`, `<h3`, `class="figure"`, `<table`) — they must match.
4. Scrub grep as in WRITING-GUIDE.md.
