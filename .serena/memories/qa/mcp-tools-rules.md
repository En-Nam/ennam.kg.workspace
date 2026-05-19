# MCP Tools Rules for QA Agents

**CRITICAL**: Read `ennam.kg.requirements/QA/strategy/mcp-tools-reference.md` for full API reference.

## Rule 1: No CSS Selectors
Both Playwright MCP and Chrome DevTools MCP use element references from snapshots.
- Playwright: `ref` from `browser_snapshot()`
- Chrome DevTools: `uid` from `take_snapshot()`

## Rule 2: Always Snapshot Before Interaction
```
browser_snapshot()  // → returns refs like "s1e3", "s1e5"
browser_click({ ref: "s1e3" })  // ✅ use ref
```

## Rule 3: browser_evaluate Requires Function Declaration
```
// ✅ CORRECT
browser_evaluate({ function: "async () => { return await fetch('/api').then(r=>r.json()); }" })

// ❌ WRONG
browser_evaluate("fetch('/api').then(r=>r.json())")
```

## Rule 4: browser_wait_for Takes Text, Not Selectors
```
// ✅ CORRECT
browser_wait_for({ text: "Dashboard" })
browser_wait_for({ time: 5 })

// ❌ WRONG
browser_wait_for("canvas", {timeout: 5000})
```

## Rule 5: Don't Mix MCP Tools
Use one MCP consistently per test flow. Don't mix Playwright and Chrome DevTools in same flow.

## Rule 6: When to Use Which MCP
- **Playwright MCP**: Navigation, form filling, clicking, assertions, screenshots
- **Chrome DevTools MCP**: Performance traces, Lighthouse audits, network inspection, device emulation

## Physical Docs Location
All QA docs at: `ennam.kg.requirements/QA/`
- Strategy: `QA/strategy/mcp-tools-reference.md` ← SOURCE OF TRUTH
- Agent Guide: `QA/QA-AGENT-GUIDE.md`
