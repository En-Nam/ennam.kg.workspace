#!/usr/bin/env bash
# Rebuild the pharmacy_demo database from demo_mockdata/*.csv.
#   DAAB_PG_CONTAINER=<container> scripts/demo_data/load_pharmacy_demo.sh <verified pg_dump -Fc backup of pharmacy_demo>
# Env: DAAB_PG_CONTAINER (REQUIRED, no default), PHARMACY_DB (default pharmacy_demo),
#      CONFIRM_LIVE_RELOAD=yes (REQUIRED additionally when the container is daab-postgres).
# Refuses to drop anything unless: target container is running, backup exists and contains
# pharmacy_demo table data, and ALL inputs (base.sql, extension.sql, 25 CSVs) exist.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DATA="$ROOT/demo_mockdata"
SCHEMA="$ROOT/scripts/demo_data/schema"
LIVE_CONTAINER="daab-postgres"
CONTAINER="${DAAB_PG_CONTAINER:-}"
DB="${PHARMACY_DB:-pharmacy_demo}"
BACKUP="${1:-}"
LOAD_ORDER="stores vendors products employees customers transactions transaction_items payments receipts
invoices refunds refund_items voids discount_overrides cash_drawers employee_shifts inventory_movements
inventory_adjustments inventory_snapshots prescriptions insurance_claims audit_events product_costs
purchase_orders purchase_order_lines"

if [ -z "$CONTAINER" ]; then
  echo "DAAB_PG_CONTAINER is not set — refusing to guess the target container" >&2
  exit 1
fi
if ! [[ "$DB" =~ ^[a-z_][a-z0-9_]*$ ]]; then
  echo "PHARMACY_DB '$DB' is not a plain lowercase identifier — refusing" >&2
  exit 1
fi
if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)" != "true" ]; then
  echo "container '$CONTAINER' is not running — refusing" >&2
  exit 1
fi
if [ "$CONTAINER" = "$LIVE_CONTAINER" ] && [ "${CONFIRM_LIVE_RELOAD:-}" != "yes" ]; then
  echo "target is the LIVE container $LIVE_CONTAINER — set CONFIRM_LIVE_RELOAD=yes to proceed" >&2
  exit 1
fi

if [ -z "$BACKUP" ] || [ ! -s "$BACKUP" ]; then
  echo "usage: $0 <backup.dump>  (backup missing or empty — refusing to drop $DB)" >&2
  exit 1
fi
if ! docker exec -i "$CONTAINER" pg_restore --list < "$BACKUP" | grep -q "TABLE DATA public transactions"; then
  echo "backup $BACKUP has no pharmacy_demo table data — refusing to drop $DB" >&2
  exit 1
fi

missing=""
for f in "$SCHEMA/base.sql" "$SCHEMA/extension.sql"; do [ -s "$f" ] || missing="$missing $f"; done
for table in $LOAD_ORDER; do [ -s "$DATA/$table.csv" ] || missing="$missing $DATA/$table.csv"; done
if [ -n "$missing" ]; then
  echo "missing inputs — refusing to drop $DB:$missing" >&2
  exit 1
fi

PGUSER_NAME="$(docker exec "$CONTAINER" printenv POSTGRES_USER)"
run_psql() { docker exec -i "$CONTAINER" psql -U "$PGUSER_NAME" -v ON_ERROR_STOP=1 -q "$@"; }

run_psql -d postgres -c "DROP DATABASE IF EXISTS $DB WITH (FORCE)"
run_psql -d postgres -c "CREATE DATABASE $DB"
run_psql -d "$DB" < "$SCHEMA/base.sql" > /dev/null
run_psql -d "$DB" < "$SCHEMA/extension.sql"

for table in $LOAD_ORDER; do
  columns="$(head -1 "$DATA/$table.csv")"
  run_psql -d "$DB" -c "\\copy public.$table ($columns) FROM pstdin WITH (FORMAT csv, HEADER true)" < "$DATA/$table.csv"
done
run_psql -d "$DB" -c "ANALYZE"

status=0
for table in $LOAD_ORDER; do
  expected=$(( $(wc -l < "$DATA/$table.csv") - 1 ))
  actual="$(run_psql -d "$DB" -At -c "SELECT count(*) FROM public.$table")"
  if [ "$expected" != "$actual" ]; then
    echo "MISMATCH $table: csv=$expected db=$actual" >&2
    status=1
  else
    echo "ok $table $actual"
  fi
done
exit $status
