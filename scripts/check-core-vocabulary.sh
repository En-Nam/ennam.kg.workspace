#!/usr/bin/env bash
set -euo pipefail
WORDS='pharmacy|prescription|reimburse|claim_rejection|\bndc\b|\bpbm\b|\bpayer\b'
CANDIDATES=(ennam.kg.go/internal/intel ennam.kg.go/internal/intelstore LAAM/src/lib/intel "LAAM/src/app/(app)/home" LAAM/src/components/intel LAAM/src/app/api/intel)
PATHS=()
for p in "${CANDIDATES[@]}"; do [ -d "$p" ] && PATHS+=("$p"); done
if [ ${#PATHS[@]} -eq 0 ]; then echo "core vocabulary: SKIP (no core dirs yet)"; exit 0; fi
set +e
hits=$(grep -rniE "$WORDS" "${PATHS[@]}" --include='*.go' --include='*.ts' --include='*.tsx')
rc=$?
set -e
if [ $rc -ge 2 ]; then echo "grep failed (rc=$rc)"; exit 2; fi
hits=$(printf '%s\n' "$hits" | grep -vE '_test\.go:|\.test\.tsx?:|/testdata/|/fixtures/' || true)
if [ -n "$hits" ]; then echo "Industry vocabulary in core:"; echo "$hits"; exit 1; fi
echo "core vocabulary OK (${#PATHS[@]} dirs)"
