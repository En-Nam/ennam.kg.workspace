#!/usr/bin/env python3
"""Publish resolve_document messages to Redis for each document to trigger pass2."""
import json
import redis

PROJECT_ID = "a0000000-0000-0000-0000-000000000001"
QUEUE_KEY = "kg:queue:worker"

DOC_IDS = [
    "0c6758b5-135f-48d6-8cfa-548d08b03fc9",
    "7ecdda52-9513-4eca-be37-12b9d630ed8f",
    "988863b9-9f0d-4285-83c9-e26a6cbee803",
    "ee3222b0-d1c7-4705-a4e2-c10d6fc4ac6f",
    "063c4426-95bc-4931-9548-53743c142bc1",
    "51d53b6d-c154-4f49-9b61-54ebafbf73d9",
    "2d7687e5-a5f2-4440-80a9-3969b80d9564",
    "8c83f252-3db5-447f-a7b9-d2841010b151",
    "e0933edb-246a-49fd-b5e8-875102380d76",
    "42ce3568-f033-4295-a5bc-57579a2ce999",
]

r = redis.Redis(host="localhost", port=6380, decode_responses=True)

for doc_id in DOC_IDS:
    msg = {
        "type": "resolve_document",
        "project_id": PROJECT_ID,
        "doc_id": doc_id,
        "run_id": f"backfill-{doc_id[:8]}",
    }
    r.lpush(QUEUE_KEY, json.dumps(msg))
    print(f"Queued resolve_document for {doc_id[:8]}...")

print(f"Done. Queued {len(DOC_IDS)} resolve_document messages.")
