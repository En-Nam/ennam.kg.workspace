# MSSQL Data Source Support — Implementation Plan

**Date**: 2026-04-22
**Status**: IMPLEMENTED — build clean, ready for testing

## Strategy: SchemaQuerier Interface (Strategy Pattern)
Extract 13 query methods from `schema_extractor.go` into `SchemaQuerier` interface. PostgreSQL + MSSQL each get own implementation. Orchestration unchanged.

## Key Differences PG vs MSSQL
- Driver: `postgres` (lib/pq) vs `sqlserver` (go-mssqldb)
- Conn string: `postgres://` vs `sqlserver://user:pass@host:1433?database=db&encrypt=false`
- Default port: 5432 vs 1433
- SSL: sslmode=disable/require vs encrypt=true/false/strict
- Params: $1,$2 vs @p1,@p2
- FKs: information_schema.constraint_column_usage (PG only) → sys.foreign_keys (MSSQL)
- Indexes: pg_index + LATERAL unnest → sys.indexes + sys.index_columns (group in Go)
- Sizes: pg_total_relation_size() → sys.dm_db_partition_stats
- Comments: obj_description() → sys.extended_properties (MS_Description)
- System schemas: pg_catalog/pg_toast → sys/guest/db_*

## Files (10 changes)
- **Create**: migration 043, schema_querier.go (interface), schema_querier_postgres.go, schema_querier_mssql.go, driver_mssql.go
- **Modify**: schema_extractor.go (use interface), datasource.go (validation + test), source_executor.go (driver), go.mod

## Effort: ~8-12 hours
