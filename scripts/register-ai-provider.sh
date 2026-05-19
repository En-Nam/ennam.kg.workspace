#!/bin/bash
# Register an AI provider with the Go API.
# Usage: ./scripts/register-ai-provider.sh <ANTHROPIC_API_KEY>

set -e

API_KEY="${KG_API_KEY:-ennam_kg_dev_000000000000000000000000}"
API_URL="${KG_SERVER_URL:-http://localhost:8080}"
ANTHROPIC_KEY="${1:-$ANTHROPIC_API_KEY}"

if [ -z "$ANTHROPIC_KEY" ]; then
  echo "Usage: $0 <ANTHROPIC_API_KEY>"
  echo "  or set ANTHROPIC_API_KEY env var"
  exit 1
fi

echo "Registering Anthropic Claude provider..."
curl -s -X POST "$API_URL/api/v1/ai-providers" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"claude-haiku\",
    \"provider_type\": \"anthropic_api\",
    \"base_url\": \"https://api.anthropic.com\",
    \"api_key\": \"$ANTHROPIC_KEY\",
    \"model_id\": \"claude-haiku-4-5-20251001\",
    \"rate_limit_rpm\": 60,
    \"rate_limit_tpd\": 1000000,
    \"cost_per_input_token\": 800,
    \"cost_per_output_token\": 4000,
    \"priority\": 1,
    \"is_active\": true
  }" | python3 -m json.tool

echo ""
echo "Done. Test with:"
echo "  curl -X POST $API_URL/api/v1/ai/request \\"
echo "    -H 'Authorization: Bearer $API_KEY' \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}],\"max_tokens\":50}'"
