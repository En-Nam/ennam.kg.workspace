#!/usr/bin/env python3
"""Ingest the 2 payment-hooks PDFs into a fresh project for BA-033 testbed.

Creates project `ba033-payment-hooks`, splits each PDF into chunks, uploads
document + document_chunk nodes, then triggers extraction (Phase A pipeline).
Two topically-related docs → a clean cross-document corpus for BA-033
(chunk-similarity links FR-001 + community detection FR-002 after resolution).

Usage:
  cd ennam.kg.workspace
  uv run --project ennam.kg.python python scripts/ingest-ba033-payment-hooks.py
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
API_URL  = "http://127.0.0.1:8082"
API_KEY  = "ennam_kg_dev_000000000000000000000000"
CHUNK_WORDS = 400
PROJECT_NAME = "ba033-payment-hooks"
CREATED_BY = "ingest-ba033"

PDFS = [
    Path(__file__).parent.parent / "Nuvei_Payment_Hooks V2.pdf",
    Path(__file__).parent.parent / "3rd party payment hooks.pdf",
]

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _req(method: str, path: str, body: dict | None = None,
         project_id: str | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    # Intentionally NOT sending X-Project-ID: that triggers the project-override
    # auth gate. Node creation carries project_id in the body (honored cross-project),
    # and the extract endpoint derives the project from the doc_id. _ = project_id

    req = urllib.request.Request(
        f"{API_URL}{path}", data=data, headers=headers, method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        raise RuntimeError(f"{method} {path} → HTTP {e.code}: {err}") from e


def get_or_create_project() -> str:
    import os
    forced = os.environ.get("KG_PROJECT_ID")
    if forced:
        print(f"[project] using KG_PROJECT_ID={forced}")
        return forced
    data = _req("GET", "/api/v1/projects")
    projects = data.get("projects") or (data if isinstance(data, list) else [])
    for p in projects:
        if p["name"] == PROJECT_NAME:
            print(f"[project] reusing existing: {p['id']}")
            return p["id"]
    proj = _req("POST", "/api/v1/projects", {
        "name": PROJECT_NAME,
        "description": "BA-033 cross-document testbed — Nuvei + 3rd-party payment hooks PDFs",
        "repo_url": "local://ba033-payment-hooks",
    })
    pid = proj.get("id") or proj.get("project_id") or proj["id"]
    print(f"[project] created: {pid}")
    return pid


def extract_text_from_pdf(pdf_path: Path) -> str:
    try:
        import pypdf
    except ImportError:
        sys.exit("pypdf not available — run: uv add pypdf")
    text_parts: list[str] = []
    with open(pdf_path, "rb") as f:
        reader = pypdf.PdfReader(f)
        for page in reader.pages:
            t = page.extract_text() or ""
            if t.strip():
                text_parts.append(t)
    return "\n\n".join(text_parts)


def split_into_chunks(text: str, words_per_chunk: int = CHUNK_WORDS) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    for i in range(0, len(words), words_per_chunk):
        chunk = " ".join(words[i : i + words_per_chunk])
        if chunk.strip():
            chunks.append(chunk)
    return chunks


def create_document_node(project_id: str, name: str, source: str) -> str:
    node = _req("POST", "/api/v1/nodes", {
        "project_id": project_id,
        "created_by": CREATED_BY,
        "node_type": "document",
        "title": name,
        "name": name,
        "description": f"Ingested PDF: {name}",
        "properties": {"source": source, "status": "ingested"},
    }, project_id=project_id)
    return (node.get("node") or node)["id"]


def create_chunk_node(project_id: str, doc_id: str, idx: int, content: str) -> str:
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    node = _req("POST", "/api/v1/nodes", {
        "project_id": project_id,
        "created_by": CREATED_BY,
        "node_type": "document_chunk",
        "title": f"chunk-{idx:04d}",
        "name": f"chunk-{idx:04d}",
        "description": content[:120].replace("\n", " "),
        "properties": {
            "document_id": doc_id,
            "chunk_index": idx,
            "content": content,
            "content_hash": content_hash,
        },
    }, project_id=project_id)
    return (node.get("node") or node)["id"]


def trigger_extract(doc_id: str, project_id: str) -> dict:
    return _req("POST", f"/api/v1/ingestion/documents/{doc_id}/extract",
                body={}, project_id=project_id)


def main() -> None:
    try:
        urllib.request.urlopen(f"{API_URL}/readyz", timeout=5)
    except Exception:
        sys.exit(f"KG server not reachable at {API_URL} — run: docker compose up -d")

    project_id = get_or_create_project()

    for pdf_path in PDFS:
        if not pdf_path.exists():
            print(f"[SKIP] not found: {pdf_path}")
            continue
        print(f"\n── {pdf_path.name} ──")
        text = extract_text_from_pdf(pdf_path)
        print(f"  total chars: {len(text):,}")
        chunks = split_into_chunks(text)
        print(f"  chunks: {len(chunks)} × ~{CHUNK_WORDS} words")
        doc_id = create_document_node(project_id, pdf_path.stem, str(pdf_path))
        print(f"  document node: {doc_id}")
        chunk_ids: list[str] = []
        for i, chunk_text in enumerate(chunks):
            chunk_ids.append(create_chunk_node(project_id, doc_id, i, chunk_text))
            if (i + 1) % 10 == 0:
                print(f"    created {i+1}/{len(chunks)} chunks...")
        print(f"  all {len(chunk_ids)} chunk nodes created")
        result = trigger_extract(doc_id, project_id)
        print(f"  extraction triggered → run_id={result.get('run_id')} "
              f"dispatched={result.get('dispatched')} skipped={result.get('skipped')}")

    print(f"\n✓ Done. project_id={project_id}")
    print(f"  Monitor: docker compose logs -f worker")


if __name__ == "__main__":
    main()
