# Checkpoint: docs-agent — 2026-09-28

## What was done
- Second independent audit of tech_docs v1.1 (8 fresh agents, one per EN+VI pair), code unchanged since baselines (LAAM 355cbd6; DAAB go 88c132d · python 92f4666 · next 109e22e).
- ~50 fact fixes. Notable: LAAM cost fallback (unknown/local models → Sonnet placeholder), token-audit scope, PKCE Google/Zalo, org-wide session records, DeepSeek thinking rule, Cerebras strict opt-in, licence appendix (pdfjs-dist unused, fiber/drei landing-only). DAAB: GraphRAG seeds = vector, audit_trail = node creation only, implicit-relation review API-only, kg-migrate scope, 248+3 routes, commit stats 1,255, CI main/develop only, AWS SG outbound HTTPS, webhook secret plaintext (hardening item 1), item 9 & 15 updated (03 §8 == 04 §5.3).
- New facts recorded in tooling/FIX-BRIEF.md "Second-pass additions".

- Diagram audit (4 agents, 52 figures EN+VI): ~30 figures fixed vs code — DAAB ER cardinalities/types vs live schema, gate order (Gate1→whitelist→Gate2), playbook draft→stale/any→draft, NL query hits source DBs, read-only only on PostgreSQL, 30s/10k all dialects; LAAM chat-turn sequence (final completion in route), write-confirm (token opened in code, nonce vs audit log), run cancel states, workflow ledger = connector writes, ER nullable FKs; layout: subgraph-title crossings fixed (short titles + caption qualifier).

## Current state
- All builds ok; briefs 2 pages; pages DAAB 2/30/18/14, LAAM 2/29-31/18/16-17. Not committed.

## Next steps
- User review + commit. Product issues to raise: LAAM Sync button + Search sessions; DAAB Overview links /decisions,/agents; DAAB bridge tool descriptions say "up to 50" vs server 100/unlimited; LAAM local-model cost placeholder; unused deps pdfjs-dist, @react-three/fiber, drei.

## Blockers / Risks
- Unverifiable from code: eval scores, demo DB counts, image sizes, whether AWS/CI pipelines ran.
