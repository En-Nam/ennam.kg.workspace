# mcp-write follow-ups (phase 1+2 shipped on `task/mcp-write-datasource`, 2026-08-03)

Shipped: kg_describe_table, kg_insert_datasource_row (opt-in allow_writes + whitelist + audit), playbook engine + kg_list_playbooks/kg_execute_playbook (atomic multi-table, verified rollback), executor read-only hardening, migration 000082/000084. Seeded `create_order` for pharmacy (SQL-only).

Remaining from `docs/mcp-write-datasource-spec.md` (workspace):
1. **AI playbook proposal pass (spec §5.2)** — analysis over FK topology + naming + data patterns → draft playbooks with confidence + evidence. Likely Python-side (extraction pipeline has the LLM plumbing). Never auto-approve.
2. **Stale-marking on sync-schema (spec §5.3, MANDATORY per spec)** — post-sync validation of every playbook vs source_columns; mark stale + reason; execute already rejects stale (409 path exists, tested at engine level) but nothing SETS stale yet.
3. **Playbook CRUD/approve endpoints + dashboard UI** — currently seeding/approval is direct SQL. Needs: create draft, approve (admin), disable, view definition diff.
4. **MSSQL write support** — phase 1 rejects with clear error; needs sqlserver param syntax + tx semantics.
5. **LAAM display bug (their side):** confirm-card shows object args as "[object Object]" — values/input objects should render as JSON. Report to LAAM team.
6. Single-row insert whitelist is per-datasource config via SQL only — dashboard toggle for allow_writes + whitelist belongs with item 3.

Related: `mem:checkpoint/claude-2026-08-03`, spec §8 decisions (adopted defaults: phase split, explicit whitelist, developer role, YAML/JSON DSL, UPDATE/DELETE out of scope).
