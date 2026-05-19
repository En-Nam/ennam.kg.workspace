# ✅ FIXED: list_datasources tool uses wrong node_type

**Priority**: P2 (blocks all Deep tier flows)
**Found**: 2026-05-12, Wave 2 E2E testing session

## Bug description

The `list_datasources` agentic tool calls the KG API with `node_type: "data_source"` which returns a 400 error: `invalid node_type: data_source`.

This causes the Deep tier agent to fail after the first tool call, preventing:
- Multi-tool-call flows (UI-04)
- Accuracy test cases requiring data source discovery
- Any agent session that needs to enumerate available data sources

## Expected behavior

The tool should use the correct node type string recognized by the KG API. Check the node type registry in `ennam.kg.go/internal/validation/` or `config/config.yaml` for the correct slug.

## File to fix

`ennam.kg.python/src/ennam_kg/agentic/tools.py` — `list_datasources` tool definition or implementation

## How to verify fix

Run: `pytest tests/e2e/test_api_smoke.py::test_api_02 -v`
Expected: PASS (Deep tier SSE sequence completes with ≥2 tool calls)
