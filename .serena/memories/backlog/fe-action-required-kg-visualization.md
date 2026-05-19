# FE Action Required: KG Generation + Schema Graph Integration

**Date**: 2026-04-13
**Status**: BE DEPLOYED — endpoints working, verified with real data

---

## KG Generation Flow (for FE)

### Step 1: Trigger generation
```
POST /api/v1/data-sources/{id}/generate-kg
Body: {"project_id": "uuid"}
Response 202: KGGenerationJob {id, status: "completed", nodes_created: 85, ...}
```

### Step 2: Poll status (if needed)
```
GET /api/v1/data-sources/{id}/kg-status
Response 200: KGGenerationJob (same shape)
```

### Step 3: Get visualization data
```
GET /api/v1/schema-graph?data_source_id={uuid}
Response 200: {tables: [...], relationships: [...], metadata: {...}}
```

---

## Schema Graph Response (verified from C4K Datawarehouse)

```json
{
  "tables": [
    {
      "id": "38db85ad-...",           // Cytoscape node ID
      "table_name": "gs_performance",  // Node label
      "schema_name": "public",
      "row_count_estimate": 48166968,  // For node sizing
      "column_count": 25              // For node badge
    }
  ],
  "relationships": [],                 // Empty for data warehouses (no FKs)
  "metadata": {
    "total_tables": 85,
    "total_relationships": 0,
    "total_fk_edges": 0,
    "total_ai_edges": 0,
    "generated_at": "2026-04-13T07:00:41Z",
    "data_source_id": "3f97a910-..."
  }
}
```

## KG Node Properties (verified)

Each node in kg-nodes response has `properties` JSONB:
```json
{
  "arch_type": "schema_table",
  "content": "Schema table public.gs_performance (25 columns, ~48166968 rows)",
  "node_subtype": "schema_table",
  "source_data_source_id": "3f97a910-...",
  "source_table_name": "gs_performance",
  "schema_group": "public",
  "column_count": 25,
  "row_count_estimate": 48166968,
  "ai_description": ""
}
```

## Edge Types (for styling)

| relationship_type | Meaning | Confidence | Edge Style |
|-------------------|---------|------------|------------|
| `schema_fk` | Foreign key constraint | 1.0 (always) | Solid cyan |
| `schema_implicit` | AI-detected relationship | 0.0-1.0 | Dashed, opacity=confidence |
| `schema_many_to_many` | Junction table M:N | 1.0 | Dotted yellow |

## TypeScript Types

```typescript
interface SchemaGraphResponse {
  tables: SchemaGraphTable[];
  relationships: SchemaGraphRelationship[];
  metadata: SchemaGraphMetadata;
}

interface SchemaGraphTable {
  id: string;
  table_name: string;
  schema_name: string;
  row_count_estimate: number;
  column_count: number;
  ai_description?: string;
}

interface SchemaGraphRelationship {
  id: string;
  source_table_id: string;
  target_table_id: string;
  relationship_type: 'schema_fk' | 'schema_implicit' | 'schema_many_to_many';
  label: string;
  confidence: number;
  source_column: string;
  target_column: string;
}

interface SchemaGraphMetadata {
  total_tables: number;
  total_relationships: number;
  total_fk_edges: number;
  total_ai_edges: number;
  generated_at: string;
  data_source_id: string;
}

interface KGGenerationJob {
  id: string;
  data_source_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  nodes_created: number;
  edges_explicit: number;
  edges_implicit: number;
  edges_rejected: number;
  error_message?: string;
  started_at?: string;
  completed_at?: string;
  created_at: string;
}
```

## Notes
- `kg-nodes` and `kg-edges` now return `[]` not `null` when empty
- Data warehouses typically have 0 relationships (no FK constraints)
- AI descriptions require registered AI provider via POST /ai-providers
- Generation is fast (~200ms for 85 tables without AI, longer with AI descriptions)
