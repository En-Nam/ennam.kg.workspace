import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "add_refund_risk_score", Path(__file__).with_name("add-refund-risk-score.py"))
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)
P = m.P


def txn(begin="2026-05-03T10:00:00", amount="50.00", receipt=True, void=False, net="50.00"):
    orig = "<OriginalTransaction><SequenceNumber>T1</SequenceNumber></OriginalTransaction>" if receipt else ""
    vf = ' VoidFlag="true"' if void else ""
    return f"""<Transaction><BeginDateTime>{begin}</BeginDateTime>
<RetailTransaction TypeCode="ReturnTransaction"><LineItem{vf}><Return>
<ExtendedAmount>{amount}</ExtendedAmount><ItemAttributes RX="false"/>{orig}</Return></LineItem>
<Total TotalType="TransactionNetAmount">{net}</Total></RetailTransaction></Transaction>"""


def doc(*txns):
    return f'<?xml version="1.0"?><POSLog xmlns="{m.NS}">{"".join(txns)}</POSLog>'


def score_of(xml):
    root = ET.fromstring(xml)
    m.add_risk_scores(root)
    return [int(e.text) for e in root.iter(P + "RiskScore")]


@pytest.mark.parametrize("receipt,hour,amount,expected", [
    (True, "10", "50", 10), (True, "10", "100", 30),
    (True, "20", "50", 30), (True, "19", "99.99", 10), (True, "20", "100", 50),
    (False, "10", "50", 50), (False, "10", "100", 70),
    (False, "20", "50", 70), (False, "20", "100", 90),
])
def test_rule_table(receipt, hour, amount, expected):
    xml = doc(txn(begin=f"2026-05-03T{hour}:00:00", amount=amount, receipt=receipt))
    assert score_of(xml) == [expected]


def test_voided_line_uses_net_total():
    xml = doc(txn(amount="500", net="40", void=True))
    assert score_of(xml) == [10]


def test_inserted_before_item_attributes():
    root = ET.fromstring(doc(txn()))
    m.add_risk_scores(root)
    ret = next(root.iter(P + "Return"))
    tags = [c.tag for c in ret]
    assert tags.index(P + "RiskScore") + 1 == tags.index(P + "ItemAttributes")


def test_idempotent():
    root = ET.fromstring(doc(txn()))
    assert m.add_risk_scores(root) == 1
    assert m.add_risk_scores(root) == 0
    assert len(list(root.iter(P + "RiskScore"))) == 1


def test_files_namespace_and_byte_identity(tmp_path):
    src, dst = tmp_path / "poslog", tmp_path / "poslog-risk"
    (src / "S1").mkdir(parents=True)
    sale = doc("<Transaction><RetailTransaction TypeCode=\"SaleTransaction\"/></Transaction>")
    (src / "S1" / "sale.xml").write_text(sale)
    (src / "S1" / "ret.xml").write_text(doc(txn(receipt=False)))
    changed = m.run(src, dst)
    assert [str(c) for c in changed] == ["S1/ret.xml"]
    assert (dst / "S1" / "sale.xml").read_bytes() == (src / "S1" / "sale.xml").read_bytes()
    out = (dst / "S1" / "ret.xml").read_text()
    assert "ns0" not in out and f'xmlns="{m.NS}"' in out and out.startswith("<?xml")
    assert (dst / "changed-files.txt").read_text() == "S1/ret.xml\n"
    assert (tmp_path / "poslog-risk-changed" / "S1" / "ret.xml").exists()
    assert not (tmp_path / "poslog-risk-changed" / "S1" / "sale.xml").exists()
    # second run over the output adds nothing
    assert m.run(dst, tmp_path / "again") == []
    assert (src / "S1" / "ret.xml").read_text() == doc(txn(receipt=False))
