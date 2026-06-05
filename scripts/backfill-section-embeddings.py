#!/usr/bin/env python3
"""Backfill section embeddings + document_tree for an existing document hub."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

# Allow running from workspace root without install
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ennam.kg.python", "src"))

from ennam_kg.config import settings
from ennam_kg.embeddings.local_model import LocalEmbeddingModel
from ennam_kg.ingestion.pipeline.decompose import _content_hash
from ennam_kg.ingestion.pipeline.document_tree import build_document_tree_json, parse_markdown_sections
from ennam_kg_indexer.kg_client.client import KGClient


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--hub-node-id", required=True)
    parser.add_argument("--draft-id", required=True)
    args = parser.parse_args()

    base = os.environ.get("GO_API_URL", "http://127.0.0.1:8080")
    key = os.environ.get("GO_API_KEY", "ennam_kg_dev_000000000000000000000000")
    kg = KGClient(base, key)

    draft = await kg.get_draft_node(args.project_id, args.draft_id)
    content = str(draft.get("content_raw") or "")
    sections = parse_markdown_sections(content)
    tree = build_document_tree_json(sections)

    await kg.update_node(
        args.hub_node_id,
        {
            "expected_version": 1,
            "change_reason": "Backfill document_tree after decomposition",
            "changed_by": "backfill-section-embeddings",
            "properties": {
                "document_tree": tree,
                "section_count": len(sections),
            },
        },
    )
    print(f"document_tree: {len(tree)} roots, {len(sections)} sections")

    nodes = await kg.get_nodes(args.project_id, node_type="document_section")
    section_nodes = [
        n for n in nodes
        if (n.get("properties") or {}).get("document_id") == args.hub_node_id
    ]
    if not section_nodes:
        print("no document_section nodes for hub", file=sys.stderr)
        sys.exit(1)

    model = LocalEmbeddingModel(model_name=settings.embedding_model_name)
    texts: list[str] = []
    ids: list[str] = []
    for n in section_nodes:
        props = n.get("properties") or {}
        title = n.get("title", "")
        summary = str(props.get("summary") or props.get("content") or "")[:2000]
        texts.append(f"{title}\n{summary}")
        ids.append(n["id"])

    vectors = model.encode(texts)
    items = []
    for nid, text, vec in zip(ids, texts, vectors, strict=True):
        items.append(
            {
                "node_id": nid,
                "chunk_text": text[:8000],
                "content_hash": _content_hash(text),
                "embedding": vec,
            }
        )

    upserted = 0
    batch = 32
    for i in range(0, len(items), batch):
        upserted += await kg.upsert_node_embeddings(
            args.project_id, items[i : i + batch]
        )
    print(f"embeddings upserted: {upserted}")


if __name__ == "__main__":
    asyncio.run(main())
