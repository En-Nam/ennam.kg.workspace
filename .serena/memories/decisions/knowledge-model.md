# Knowledge Model (Graph Schema)

> **Full specification**: See `ennam.kg.requirements/documents/phase1/BA-001-platform-foundation.md` §6 Data Requirements
> This file is a quick-reference summary. The BA document has complete schema tables with types, constraints, indexes, and triggers.

## Node Types — Project Knowledge (Human-driven)
| Node Type | Key Fields | Created By |
|-----------|------------|------------|
| Project | name, description, repo_url, stack, status | Admin/PO |
| Decision | title, context, rationale, alternatives[], impact, status | project-owner, BA, team-lead |
| Concept | name, definition, domain, aliases[] | BA, project-owner |
| Requirement | req_id, title, description, acceptance_criteria[], priority | BA |
| Task | task_id, title, status, assignee, blockers[], branch | team-lead, workers |
| Architecture | type (api_contract/data_model/pattern), content, version | team-lead, backend-dev |
| AgentDiscovery | description, category, severity, resolved | Any worker |
| DesignArtifact | design_id, screens[], pen_file_path, node_id_mapping | ui-designer |
| Session | agent, started_at, ended_at, summary, phase | Any agent |

## Node Types — Code Knowledge (Auto-extracted by Python)
| Node Type | Key Fields | Source |
|-----------|------------|--------|
| Module | path, language, description, loc | Auto-scan |
| Function | name, file_path, line_start, line_end, signature, description, complexity | AST + AI |
| Class | name, file_path, methods[], properties[], description | AST + AI |
| Component | name, file_path, props[], description, framework | AST + AI |
| APIEndpoint | method, path, handler_function, request_schema, response_schema | AST + routes |
| DataModel | name, fields[], relations[], source_file | Schema parser |

## Edge Types

See `BA-005-enforcement.md` §3 FR-003 for the full edge whitelist with 14 rules from config.yaml.

```
# Project Knowledge edges
Decision    --impacts-->        Function | Module | Component
Decision    --relates_to-->     Concept
Concept     --implemented_by--> Module | Class | Component
Requirement --fulfilled_by-->   Task
Task        --modifies-->       Function | Class | Module
Task        --blocked_by-->     Task

# Code Knowledge edges
Function    --calls-->          Function
Function    --belongs_to-->     Class | Module
Class       --inherits-->       Class
Component   --uses-->           Component | Function | APIEndpoint
APIEndpoint --handled_by-->     Function
Module      --imports-->        Module

# Cross-layer edges
Decision    --impacts-->        Function | Module
Requirement --fulfilled_by-->   Function | Component | APIEndpoint
DesignArtifact --maps_to-->     Component
```

## All Nodes Share
id (UUID), project_id, created_by, created_at, updated_at, version (auto-increment), metadata (JSONB), is_archived (soft delete)
