#!/usr/bin/env python3
"""Ingest Cảng Định An deal report into Ennam KG (nodes + edges).

Usage:
  python3 scripts/ingest-cang-dinh-an.py
  python3 scripts/ingest-cang-dinh-an.py --report /path/to/report.md

Requires: Go API at http://127.0.0.1:8080 (docker compose up).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8080")
API_KEY = os.environ.get(
    "API_KEY", "ennam_kg_dev_000000000000000000000000"
)
REPORT_DEFAULT = Path.home() / "Downloads" / "2026-05-28-cang-dinh-an-deal-report.md"
ADMIN_USER_ID = "c0000000-0000-0000-0000-000000000001"
CREATED_BY = "ingest-cang-dinh-an"
PROJECT_ID = "b0000000-0000-0000-0000-000000000010"

PROJECT_NAME = "cang-dinh-an"
PROJECT_DESC = (
    "Deal Cảng Định An — báo cáo AM AI Agent (Master Record + matching 50 NĐT)"
)
PROJECT_REPO = "am-ai-agent://projects/3a305f98-a720-4e99-9521-5b40f9213880"


class KGClient:
    def __init__(self, base: str, key: str) -> None:
        self.base = base.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            headers=self.headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode()
            raise RuntimeError(f"{method} {path} → {e.code}: {err_body}") from e

    def ready(self) -> bool:
        try:
            urllib.request.urlopen(f"{self.base}/readyz", timeout=5)
            return True
        except Exception:
            return False

    def create_project(self, name: str, description: str, repo_url: str) -> dict:
        return self._request(
            "POST",
            "/api/v1/projects",
            {"name": name, "description": description, "repo_url": repo_url},
        )

    def list_projects(self) -> list[dict]:
        data = self._request("GET", "/api/v1/projects")
        return data.get("projects", data if isinstance(data, list) else [])

    def create_node(self, payload: dict) -> dict:
        out = self._request("POST", "/api/v1/nodes", payload)
        return out.get("node", out)

    def create_edge(self, payload: dict) -> dict:
        return self._request("POST", "/api/v1/edges", payload)

    def create_data_source(self, payload: dict) -> dict:
        return self._request("POST", "/api/v1/data-sources", payload)

    def search(self, project_id: str, query: str, limit: int = 5) -> dict:
        return self._request(
            "POST",
            "/api/v1/search",
            {"project_id": project_id, "query": query, "limit": limit},
        )


def load_report_excerpt(path: Path, max_chars: int = 48000) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 80] + "\n\n[... báo cáo bị cắt do giới hạn 50k ký tự KG ...]"


def build_nodes(project_id: str, report_path: Path) -> list[dict]:
    report_body = load_report_excerpt(report_path)

    nodes: list[dict] = []

    def n(node_type: str, title: str, properties: dict, scope: str = "") -> dict:
        payload: dict = {
            "project_id": project_id,
            "node_type": node_type,
            "title": title,
            "properties": properties,
            "created_by": CREATED_BY,
        }
        if scope:
            payload["scope"] = scope
        return payload

    nodes.append(
        n(
            "concept",
            "Cảng Định An — dự án hạ tầng cảng biển Trà Vinh",
            {
                "name": "Cảng Định An",
                "definition": (
                    "Dự án Khu bến tổng hợp Định An thuộc Cảng biển Trà Vinh (Nhóm 6 ĐBSCL). "
                    "Quy mô ~128,61 ha, 03 cầu cảng 30–50k DWT, kho xăng dầu 90.000 m³. "
                    "Project ID AM: 3a305f98-a720-4e99-9521-5b40f9213880. Stage: Prospecting. "
                    "Asking price: 280M USD."
                ),
                "domain": "deal-mna",
                "aliases": [
                    "Định An General Port",
                    "Khu bến tổng hợp Định An",
                    "Dinh An port",
                ],
            },
        )
    )

    nodes.append(
        n(
            "concept",
            "Công ty TNHH Xây dựng Hàm Giang — chủ đầu tư",
            {
                "name": "Công ty TNHH Xây dựng Hàm Giang",
                "definition": (
                    "Pháp nhân chủ đầu tư Cảng Định An. ERC 2100281083, IRC 3235131673. "
                    "Chủ sở hữu 100% Nguyễn Tấn Sự (Chủ tịch HĐQT kiêm GĐ). "
                    "Trụ sở: xã Dân Thành, thị xã Duyên Hải, Trà Vinh."
                ),
                "domain": "legal-entity",
                "aliases": ["Hàm Giang", "Ham Giang Construction"],
            },
        )
    )

    nodes.append(
        n(
            "concept",
            "Hạ tầng cảng biển (seaport-infrastructure)",
            {
                "name": "seaport-infrastructure",
                "definition": (
                    "Ngành chính của dự án: cảng biển tổng hợp, logistics ĐBSCL, "
                    "kho xăng dầu nhập khẩu. Phù hợp strategic port operator hoặc NĐT dầu khí/PE hạ tầng."
                ),
                "domain": "industry",
                "aliases": ["cảng biển", "port infrastructure", "petroleum-storage"],
            },
        )
    )

    nodes.append(
        n(
            "decision",
            "AI Investment Thesis — Cảng Định An (2026-05-28)",
            {
                "context": (
                    "Tổng hợp từ 20 PDF nguồn (hợp đồng, BCTC, giấy phép, QH). "
                    "Dự án ~9 năm thi công, chưa doanh thu thương mại đáng kể, "
                    "thua lỗ 2021–2024, XDCB dở dang ~84% tài sản."
                ),
                "rationale": (
                    "Điểm mạnh: vị trí cửa ngõ ĐBSCL, đất sạch GCNQSDĐ, miễn thuê đến 2066, "
                    "quy hoạch kho dự trữ xăng dầu quốc gia. Rủi ro: pháp lý (QHCT 2020 hết hạn, "
                    "GPXD có thể hết), tài chính chưa kiểm toán, thế chấp Sacombank ~599 tỷ cho "
                    "Khai Thông Trà Vinh, key person Nguyễn Tấn Sự."
                ),
                "alternatives": [
                    "Không đầu tư — chờ làm rõ pháp lý",
                    "Mua có điều kiện (conditional SPA)",
                    "Chỉ mua phần kho xăng dầu",
                ],
                "impact": (
                    "Phù hợp nhà vận hành cảng chiến lược, tập đoàn dầu khí, hoặc PE distressed. "
                    "Không phù hợp NĐT tài chính thuần túy / ngắn hạn."
                ),
                "status": "accepted",
            },
            scope="deal-analysis",
        )
    )

    nodes.append(
        n(
            "decision",
            "Khuyến nghị Due Diligence ưu tiên — Cảng Định An",
            {
                "context": "Bước tiếp theo sau báo cáo Master Record AM AI Agent.",
                "rationale": (
                    "1) Legal DD: hiệu lực GPXD 52/GPXD, đăng ký bảo đảm, chuỗi QH hậu 2020. "
                    "2) Tài chính: kiểm toán BCTC 2022–2024, nguồn vốn 625 tỷ 2022. "
                    "3) Kỹ thuật: khảo sát % hoàn thành thực địa. "
                    "4) Thương lượng: conditional SPA gắn xử lý thế chấp Sacombank."
                ),
                "alternatives": ["Đàm phán giá ngay không DD"],
                "impact": "Giảm rủi ro trước khi chuyển nhượng sạch",
                "status": "proposed",
            },
        )
    )

    nodes.append(
        n(
            "architecture",
            "Tóm tắt tài chính Cảng Định An (BCTC 2021–2024)",
            {
                "arch_type": "data_model",
                "content": (
                    "## Tài chính (chưa kiểm toán, ~23.400 VND/USD)\n"
                    "| Năm | Doanh thu USD | Lợi nhuận ròng USD |\n"
                    "| 2021 | 107k | (75k) |\n"
                    "| 2022 | 36k | (22k) |\n"
                    "| 2023 | 29k | (29k) |\n"
                    "| 2024 | 16k | (34k) |\n"
                    "Doanh thu giảm ~85% trong 3 năm. Nợ ~2.500 tỷ (2023), D/E=2,14x. "
                    "XDCB dở dang ~3.021 tỷ (2024), ~84% tổng tài sản. Asking: 280M USD."
                ),
                "content_format": "markdown",
            },
        )
    )

    nodes.append(
        n(
            "architecture",
            "Matching nhà đầu tư — tổng quan (50 NĐT)",
            {
                "arch_type": "data_model",
                "content": (
                    "## Ranking\n"
                    "- 50 nhà đầu tư match; 17 được AI re-rank.\n"
                    "- Strong: 0 (do 12 red flag critical).\n"
                    "- Weak: 5 (AI score 22–38): Saigon Petroleum & Port Holdings, "
                    "Mekong Maritime Infrastructure Fund, Pacific Shipping, "
                    "Southern Vietnam Energy Fund, ASEAN Infrastructure Partners.\n"
                    "- Top algorithm 100/100 nhưng AI tối đa 38/100.\n"
                    "Insight: synergy chiến lược có nhưng rủi ro pháp lý/tài chính chưa giải quyết."
                ),
                "content_format": "markdown",
            },
        )
    )

    if report_body:
        nodes.append(
            n(
                "architecture",
                "Báo cáo đầy đủ — Cảng Định An (markdown nguồn)",
                {
                    "arch_type": "integration",
                    "content": report_body,
                    "content_format": "markdown",
                },
            )
        )

    critical = [
        (
            "RF-01",
            "Tài chính không kiểm toán & thua lỗ liên tục",
            "BCTC 2022–2024 chưa kiểm toán. Doanh thu 2,5 tỷ→382 triệu VND. Lỗ ròng 2021–2024.",
        ),
        (
            "RF-02",
            "Nợ vay tăng vọt & rủi ro thanh khoản",
            "Nợ ~1.046→2.500 tỷ, D/E=2,14x. Tiền mặt biến động bất thường.",
        ),
        (
            "RF-03",
            "Thế chấp tài sản cho bên thứ ba (Sacombank)",
            "Bến số 1 + 2 GCNQSDĐ thế chấp bảo đảm Công ty CP Khai Thông Trà Vinh ~598,9 tỷ.",
        ),
        (
            "RF-04",
            "Tài sản dở dang ~84% tổng tài sản",
            "XDCB dở dang ~3.021 tỷ (2024), rủi ro không hoàn thành/ghi giảm.",
        ),
        (
            "RF-05",
            "Giấy phép xây dựng 52/GPXD có thể hết hạn",
            "Cấp 28/10/2019 — nhiều khả năng hết hiệu lực khi thi công tiếp.",
        ),
        (
            "RF-06",
            "Thiếu minh bạch UBO",
            "Nhiều tài liệu ghi cổ đông <UNKNOWN>; chỉ một số xác nhận Nguyễn Tấn Sự 100%.",
        ),
        (
            "RF-07",
            "Tiến độ chậm >4–5 năm so với cam kết 2020",
            "Chủ trương 2016 yêu cầu hoàn thành 2020; đến 2024 vẫn dở dang.",
        ),
        (
            "RF-08",
            "Quy hoạch chi tiết đến 2020 đã hết hạn",
            "QHCT giai đoạn 2020 hết; chưa có thay thế rõ ràng phù hợp QĐ 1579/2021.",
        ),
        (
            "RF-09",
            "Bổ sung bến chuyên dùng chưa được Bộ GTVT phê duyệt",
            "CV 420/UBND-CNXD 2023 chỉ là đề nghị, chưa phê duyệt.",
        ),
        (
            "RF-10",
            "Hợp đồng thế chấp thiếu ngày ký và số HĐ",
            "Rủi ro vô hiệu theo Luật Công chứng 2014.",
        ),
        (
            "RF-11",
            "ĐTM thay đổi 3 lần trong 5 năm",
            "ĐTM 2018 → 2022 → 2023 — phạm vi dự án không ổn định.",
        ),
        (
            "RF-12",
            "Thiếu KH tràn dầu & GP hoạt động cảng/xăng dầu",
            "PCCC nghiệm thu, GP kinh doanh cảng, xăng dầu chưa chứng minh.",
        ),
    ]

    for rid, title, desc in critical:
        nodes.append(
            n(
                "discovery",
                f"{rid} CRITICAL: {title}",
                {
                    "description": f"{desc} (Nguồn: báo cáo Master Record Cảng Định An 2026-05-28.)",
                    "category": "security",
                    "severity": "critical",
                    "resolved": False,
                },
            )
        )

    warnings = [
        ("RF-14", "VAT đầu vào bất thường so với doanh thu", "insight"),
        ("RF-15", "Tăng vốn đột biến ~625 tỷ năm 2022", "insight"),
        ("RF-16", "Chi phí QLDN tăng 9 lần năm 2023", "insight"),
        ("RF-17", "PCCC thẩm duyệt lỗi thời (894/TD-PCCC-P6)", "security"),
        ("RF-18", "20.119 m² trong hành lang đê biển", "edge_case"),
        ("RF-19", "62,84 ha mặt biển trong hồ sơ thế chấp", "legal"),
    ]
    for rid, title, _ in warnings:
        cat = "insight" if rid != "RF-17" else "security"
        if rid == "RF-18":
            cat = "edge_case"
        nodes.append(
            n(
                "discovery",
                f"{rid} WARNING: {title}",
                {
                    "description": (
                        f"Cảnh báo mức WARNING trong báo cáo rủi ro Cảng Định An: {title}."
                    ),
                    "category": cat if cat in {
                        "bug", "edge_case", "performance", "security",
                        "insight", "pattern", "debt", "improvement",
                    } else "insight",
                    "severity": "high",
                    "resolved": False,
                },
            )
        )

    nodes.append(
        n(
            "discovery",
            "RF-20 INFO: Tài liệu Nộp NSNN không liên quan dự án",
            {
                "description": (
                    "Tài liệu 17 mô tả công ty khác (Kỳ Duyên Hạo) — có thể nộp nhầm."
                ),
                "category": "insight",
                "severity": "info",
                "resolved": False,
            },
        )
    )

    open_questions = [
        "UBO và cơ cấu sở hữu thực hưởng Hàm Giang?",
        "Nguồn gốc bổ sung vốn ~624,9 tỷ năm 2022?",
        "GPXD 52/GPXD đã gia hạn chưa?",
        "Hợp đồng thế chấp Sacombank đã đăng ký bảo đảm đầy đủ?",
        "Tiến độ xây dựng thực tế % và berth nào hoàn thành?",
        "QHCT nhóm 6 sau 2020 có cập nhật Bến Định An?",
        "Đề nghị 420/UBND-CNXD đã được Bộ GTVT phê duyệt?",
        "Quan hệ Khai Thông Trà Vinh với Hàm Giang / Nguyễn Tấn Sự?",
        "KH ứng phó tràn dầu đã phê duyệt?",
        "CC PCCC sau nghiệm thu đã có?",
        "Tài liệu Nộp NSNN liên quan pháp nhân nào?",
        "ERC 3235131673 hay 2100281083 là mã chính?",
        "Tổng vốn đầu tư 4.494 tỷ hay 7.000 tỷ?",
        "Giải phóng mặt bằng 128,61 ha đã xong?",
        "BCTC 2022–2024 khi nào được kiểm toán?",
    ]

    for i, q in enumerate(open_questions, start=1):
        nodes.append(
            n(
                "requirement",
                f"OQ-{i:02d}: {q[:80]}",
                {
                    "req_id": f"REQ-{i:03d}",
                    "title": f"Câu hỏi mở DD #{i}: {q[:120]}",
                    "description": (
                        f"Câu hỏi cần làm rõ trong Due Diligence Cảng Định An: {q}"
                    ),
                    "acceptance_criteria": [
                        "Có tài liệu hoặc xác nhận pháp lý từ chủ đầu tư",
                        "Được ghi nhận trong báo cáo DD cập nhật",
                    ],
                    "priority": "high" if i <= 5 else "medium",
                    "status": "draft",
                },
            )
        )

    return nodes


def _psql(sql: str) -> None:
    import subprocess

    root = Path(__file__).resolve().parents[1]
    cmd = [
        "docker",
        "compose",
        "-f",
        str(root / "docker-compose.yml"),
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "ennam_kg",
        "-d",
        "ennam_kg",
        "-q",
        "-c",
        sql,
    ]
    subprocess.run(cmd, check=False, cwd=root)


def bootstrap_project(project_id: str) -> None:
    """Create project + dashboard access + API key scope (dev key is agent-scoped)."""
    key_hash = "f92031bd49add3f8de84da25767e77ff292b7c3e5ef7732534cde47f7c6bddc0"
    sql = f"""
INSERT INTO projects (id, name, description, repo_url)
VALUES (
  '{project_id}',
  '{PROJECT_NAME}',
  '{PROJECT_DESC.replace("'", "''")}',
  '{PROJECT_REPO}'
) ON CONFLICT (name) DO UPDATE SET
  description = EXCLUDED.description,
  repo_url = EXCLUDED.repo_url;

INSERT INTO project_members (project_id, user_id, role)
VALUES ('{project_id}', '{ADMIN_USER_ID}', 'admin')
ON CONFLICT DO NOTHING;

UPDATE api_keys
SET project_ids = (
  SELECT array_agg(DISTINCT x)
  FROM unnest(project_ids || '{project_id}'::uuid) AS x
)
WHERE key_hash = '{key_hash}';
"""
    _psql(sql)


def register_kg_data_source(client: KGClient, project_id: str) -> str | None:
    """Register internal postgres so /chat has a selectable data source."""
    payload = {
        "project_id": project_id,
        "name": "KG Platform (read-only)",
        "description": (
            "PostgreSQL nội bộ — tra cứu knowledge_nodes khi cần SQL; "
            "chat chủ yếu dùng search_kg trên graph đã ingest."
        ),
        "db_type": "postgresql",
        "host": "postgres",
        "port": 5432,
        "database_name": "ennam_kg",
        "connection_string": (
            "postgresql://ennam_kg:ennam_kg_dev@postgres:5432/ennam_kg?sslmode=disable"
        ),
        "ssl_mode": "disable",
        "created_by": CREATED_BY,
    }
    try:
        ds = client.create_data_source(payload)
        ds_id = ds.get("id") or ds.get("data_source", {}).get("id")
        if ds_id:
            client._request(
                "POST", f"/api/v1/data-sources/{ds_id}/test-connection", {}
            )
        return ds_id
    except RuntimeError as e:
        print(f"  ⚠ Data source (optional): {e}", file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=REPORT_DEFAULT)
    parser.add_argument("--skip-datasource", action="store_true")
    args = parser.parse_args()

    client = KGClient(API_URL, API_KEY)

    print(f"API: {API_URL}")
    if not client.ready():
        print("Go API chưa sẵn sàng. Chạy: docker compose up -d", file=sys.stderr)
        return 1

    project_id = PROJECT_ID
    print(f"Bootstrap project «{PROJECT_NAME}» ({project_id})...")
    bootstrap_project(project_id)

    payloads = build_nodes(project_id, args.report)
    ids: dict[str, str] = {}
    created = 0
    failed = 0

    print(f"\nNạp {len(payloads)} nodes...")
    for payload in payloads:
        label = payload["title"][:70]
        try:
            node = client.create_node(payload)
            nid = node.get("id", "")
            if nid:
                ids[payload["title"]] = nid
                created += 1
                print(f"  ✓ {label}")
            else:
                failed += 1
                print(f"  ✗ {label} (no id)")
        except RuntimeError as e:
            failed += 1
            print(f"  ✗ {label}: {e}")

    def edge(src_title: str, tgt_title: str, rel: str, label: str) -> None:
        sid, tid = ids.get(src_title), ids.get(tgt_title)
        if not sid or not tid:
            print(f"  ⊘ edge skipped: {label}")
            return
        try:
            client.create_edge(
                {
                    "project_id": project_id,
                    "source_id": sid,
                    "target_id": tid,
                    "relationship": rel,
                    "created_by": CREATED_BY,
                }
            )
            print(f"  → {label}")
        except RuntimeError as e:
            print(f"  ✗ edge {label}: {e}")

    print("\nTạo edges...")
    concept_proj = "Cảng Định An — dự án hạ tầng cảng biển Trà Vinh"
    concept_hg = "Công ty TNHH Xây dựng Hàm Giang — chủ đầu tư"
    concept_ind = "Hạ tầng cảng biển (seaport-infrastructure)"
    thesis = "AI Investment Thesis — Cảng Định An (2026-05-28)"
    dd_rec = "Khuyến nghị Due Diligence ưu tiên — Cảng Định An"

    edge(thesis, concept_proj, "relates_to", "thesis → dự án")
    edge(thesis, concept_hg, "relates_to", "thesis → Hàm Giang")
    edge(thesis, concept_ind, "relates_to", "thesis → ngành")
    edge(dd_rec, thesis, "relates_to", "DD khuyến nghị → thesis")

    arch_fin = "Tóm tắt tài chính Cảng Định An (BCTC 2021–2024)"
    arch_match = "Matching nhà đầu tư — tổng quan (50 NĐT)"
    arch_full = "Báo cáo đầy đủ — Cảng Định An (markdown nguồn)"
    for t in (arch_fin, arch_match, arch_full):
        if t in ids:
            edge(t, concept_proj, "relates_to", f"{t[:40]} → dự án")

    for title in ids:
        if title.startswith("RF-"):
            edge(title, concept_proj, "about", f"{title[:50]} → dự án")
            edge(title, thesis, "about", f"{title[:50]} → thesis")

    for title in ids:
        if title.startswith("OQ-") or title.startswith("REQ-") or "OQ-" in title:
            pass
    for title in ids:
        if title.startswith("OQ-"):
            edge(title, concept_proj, "relates_to", f"{title[:40]} → dự án")

    if not args.skip_datasource:
        print("\nĐăng ký data source (cho UI chat)...")
        ds_id = register_kg_data_source(client, project_id)
        if ds_id:
            print(f"  ✓ data_source_id: {ds_id}")

    print("\nKiểm tra search...")
    try:
        hits = client.search(project_id, "thế chấp Sacombank", 5)
        total = hits.get("total_count", len(hits.get("results", [])))
        print(f"  search 'thế chấp Sacombank': {total} kết quả")
    except RuntimeError as e:
        print(f"  search failed: {e}")

    print("\n" + "=" * 60)
    print(f"Project ID:  {project_id}")
    print(f"Nodes OK:    {created}  (failed: {failed})")
    print(f"Dashboard:   http://localhost:3500")
    print("Chat:")
    print("  1. Đăng nhập admin@ennam.kg")
    print("  2. Chọn project «cang-dinh-an» trên sidebar")
    print("  3. Mở http://localhost:3500/chat/")
    print("  4. Chọn data source «KG Platform (read-only)»")
    print("  5. Hỏi: «Liệt kê red flag CRITICAL của Cảng Định An»")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
