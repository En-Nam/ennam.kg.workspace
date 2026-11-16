# Backlog: run pack semantic tests in CI

**Owner:** DAAB + packs. **Found:** final review of the semantic layer v1, 2026-11-15.

## Gap
These three tests skip in CI today:
- `TestRealPacksSemanticsValid` (internal/intel)
- `TestSemanticsExecute` (internal/service)
- `TestSemanticsMatchMetrics` (internal/service)

The Go CI job has no `PACKS_DIR` and no landed test DB, and the packs `Publish packs` workflow runs no Go validation. A broken `semantics.yaml` therefore publishes green. It does not break anything visible: kg-server logs `pack semantics invalid`, runs without the layer, and metrics stay unaffected.

## Interim
Deploy checklist §4 has a manual pre-tag step that runs the three tests against the packs commit being published.

## Target
- In the packs publish workflow, check out ennam.kg.go at a pinned ref, start pg15/pg16 service containers, and run the three tests with `PACKS_DIR=.`.
- Or add the same job to ennam.kg.go CI, checking out the packs repo.
- Fail the publish on any failure.
