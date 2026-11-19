#!/usr/bin/env python3
"""Add a <RiskScore> to every <Return> of a demo POSLog T-log tree.

Rule (integer): 10 + 40*(no receipt) + 20*(begin hour >= 20) + 20*(refunded amount >= 100)
  - receipt  = the transaction carries LineItem/Return/OriginalTransaction
  - hour     = hour of the Transaction BeginDateTime (wall clock, no tz)
  - amount   = sum of the return lines' ExtendedAmount; when any return line is
               voided, Total[@TotalType='TransactionNetAmount'] (mirrors the
               poslog-6.0 crosswalk `refund` / `refund_voided_lines` blocks)

Files without a return are copied byte-for-byte. Source is never modified.
"""
import argparse
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "http://www.nrf-arts.org/IXRetail/namespace/"
P = "{%s}" % NS
VOID_TRUE = {"true", "TRUE", "Y", "1"}
LATE_HOUR = 20
HIGH_AMOUNT = 100.0
BASE, NO_RECEIPT, LATE, HIGH = 10, 40, 20, 20

ET.register_namespace("", NS)


def risk_score(has_receipt, hour, amount):
    return (BASE + (0 if has_receipt else NO_RECEIPT)
            + (LATE if hour >= LATE_HOUR else 0)
            + (HIGH if amount >= HIGH_AMOUNT else 0))


def _num(text):
    try:
        return float((text or "").strip())
    except ValueError:
        return 0.0


def _txn_score(txn):
    """Return (score, [Return elements]) for a Transaction, or (None, [])."""
    rt = txn.find(P + "RetailTransaction")
    if rt is None:
        return None, []
    lines = [(li, li.find(P + "Return")) for li in rt.findall(P + "LineItem")]
    lines = [(li, r) for li, r in lines if r is not None]
    if not lines:
        return None, []
    returns = [r for _, r in lines]
    has_receipt = any(r.find(P + "OriginalTransaction") is not None for r in returns)
    begin = (txn.findtext(P + "BeginDateTime") or "").strip()
    hour = int(begin[11:13]) if len(begin) >= 13 and begin[11:13].isdigit() else 0
    voided = any(li.get("VoidFlag") in VOID_TRUE for li, _ in lines)
    if voided:
        net = next((t for t in rt.findall(P + "Total")
                    if t.get("TotalType") == "TransactionNetAmount"), None)
        amount = _num(net.text) if net is not None else 0.0
    else:
        amount = sum(_num(r.findtext(P + "ExtendedAmount")) for r in returns)
    return risk_score(has_receipt, hour, amount), returns


def add_risk_scores(root):
    """Insert <RiskScore> into every Return lacking one. Returns number of Returns changed."""
    changed = 0
    for txn in root.iter(P + "Transaction"):
        score, returns = _txn_score(txn)
        if score is None:
            continue
        for ret in returns:
            if ret.find(P + "RiskScore") is not None:
                continue
            el = ET.Element(P + "RiskScore")
            el.text = str(score)
            el.tail = None
            idx = next((i for i, c in enumerate(ret) if c.tag == P + "ItemAttributes"), len(ret))
            ret.insert(idx, el)
            changed += 1
    return changed


def process_file(src, dst):
    """Write dst; return True when the file was modified (re-serialized)."""
    tree = ET.parse(src)
    if add_risk_scores(tree.getroot()) == 0:
        shutil.copyfile(src, dst)
        return False
    ET.indent(tree)
    tree.write(dst, encoding="utf-8", xml_declaration=True)
    return True


def run(src_dir, dst_dir):
    src_dir, dst_dir = Path(src_dir), Path(dst_dir)
    changed_dir = dst_dir.with_name(dst_dir.name + "-changed")
    changed = []
    for src in sorted(p for p in src_dir.rglob("*") if p.is_file()):
        rel = src.relative_to(src_dir)
        out = dst_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix.lower() == ".xml" and process_file(src, out):
            changed.append(rel)
            sub = changed_dir / rel
            sub.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(out, sub)
        elif src.suffix.lower() != ".xml":
            shutil.copyfile(src, out)
    (dst_dir / "changed-files.txt").write_text("".join(f"{r}\n" for r in changed))
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    args = ap.parse_args(argv)
    if not Path(args.src).is_dir():
        sys.exit(f"source dir not found: {args.src}")
    if Path(args.src).resolve() == Path(args.dst).resolve():
        sys.exit("--dst must differ from --src")
    changed = run(args.src, args.dst)
    print(f"changed files: {len(changed)}")


if __name__ == "__main__":
    main()
