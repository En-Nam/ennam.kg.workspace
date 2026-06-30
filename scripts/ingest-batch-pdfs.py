#!/usr/bin/env python3
"""Batch ingest remaining PDFs into Ennam KG project.

Uploads each PDF via multipart form to /api/v1/projects/{id}/ingest/upload,
then polls until draft status=processed, then approves (if needed).

Usage:
  cd ennam.kg.workspace
  uv run --project ennam.kg.python python scripts/ingest-batch-pdfs.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "http://127.0.0.1:8082"
API_KEY = "ennam_kg_dev_000000000000000000000000"
PROJECT_ID = "a0000000-0000-0000-0000-000000000001"
PDF_DIR = Path(__file__).parent.parent / "doc_pdf_test"

ALREADY_INGESTED = {
    "1779678111509-fe0fe235-589f-4aff-9ef8-d2222d1288a0.pdf",
    "1779678112121-f98a8648-b078-4f36-9b25-b0894d3bff75.pdf",
    "1779678112635-fde8746b-e491-4876-a2f4-77a9d119a4b1.pdf",
    "1779678112841-ae595470-cbd8-4b53-ae6b-9576b6223ce9.pdf",
    "1779678113021-a39e528d-68de-4eec-94dd-bdf1f846b890.pdf",
    "1779678413762-6f18bc89-6b3b-49c9-8bf0-59126dd69cc3.pdf",
    "1779678415596-0563cba2-2dd9-400b-8a4e-ee1721e88b23.pdf",
    "1779678417866-347e74be-57a7-45ee-a7b1-b2eafb69e131.pdf",
    "1779678417997-936bc2f3-65f6-46e2-8c8a-a7fd49dfcbb6.pdf",
    "1779678419670-59a92990-e80a-442e-ab17-799dfd990045.pdf",
}

HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def _json_req(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {**HEADERS, "Content-Type": "application/json"}
    req = urllib.request.Request(
        f"{API_URL}{path}", data=data, headers=hdrs, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} → HTTP {e.code}: {e.read().decode()}")


def upload_pdf(pdf_path: Path) -> str:
    """Upload a PDF via multipart form; return draft_id."""
    boundary = "----KGBoundary7a3f"
    body_parts: list[bytes] = []

    # file field
    body_parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{pdf_path.name}\"\r\nContent-Type: application/pdf\r\n\r\n".encode()
    )
    body_parts.append(pdf_path.read_bytes())
    body_parts.append(b"\r\n")

    # title field
    title = pdf_path.stem
    body_parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\n{title}\r\n".encode()
    )

    # auto_approve field
    body_parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"auto_approve\"\r\n\r\ntrue\r\n".encode()
    )

    body_parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(body_parts)

    req = urllib.request.Request(
        f"{API_URL}/api/v1/projects/{PROJECT_ID}/ingest/upload",
        data=body,
        headers={
            **HEADERS,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"upload → HTTP {e.code}: {e.read().decode()}")

    # Response may have draft_id or draft_ids
    draft_id = resp.get("draft_id") or (
        resp.get("draft_ids") or [None]
    )[0]
    if not draft_id:
        raise RuntimeError(f"no draft_id in response: {resp}")
    return draft_id


def wait_for_processed(draft_id: str, timeout: int = 120) -> str:
    """Poll draft node until status=processed; return final status."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = _json_req("GET", f"/api/v1/projects/{PROJECT_ID}/draft-nodes/{draft_id}")
        status = resp.get("status", "")
        if status in ("processed", "approved", "failed"):
            return status
        time.sleep(3)
    return "timeout"


def main() -> None:
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    to_ingest = [p for p in pdfs if p.name not in ALREADY_INGESTED]

    print(f"Found {len(pdfs)} PDFs in {PDF_DIR}")
    print(f"Already ingested: {len(ALREADY_INGESTED)}")
    print(f"To ingest: {len(to_ingest)}")
    print()

    ok = 0
    for i, pdf in enumerate(to_ingest, 1):
        print(f"[{i}/{len(to_ingest)}] {pdf.name}")
        try:
            draft_id = upload_pdf(pdf)
            print(f"  uploaded → draft_id={draft_id}")
            status = wait_for_processed(draft_id)
            print(f"  status={status}")
            if status in ("processed", "approved"):
                ok += 1
            else:
                print(f"  ⚠ unexpected status={status}", file=sys.stderr)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)

    print(f"\nDone: {ok}/{len(to_ingest)} ingested successfully.")


if __name__ == "__main__":
    main()
