import importlib.util
from datetime import date
from pathlib import Path

_spec = importlib.util.spec_from_file_location("topup_demo_days", Path(__file__).with_name("topup-demo-days.py"))
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def day_xml(day: str, txn: str) -> str:
    return (f'<POSLog><Transaction><SequenceNumber>{txn}</SequenceNumber><BusinessDayDate>{day}</BusinessDayDate>'
            f'<BeginDateTime>{day}T10:00:00</BeginDateTime></Transaction></POSLog>')


def make_src(root: Path, stores=("PH-001", "PH-002")) -> Path:
    """One week of days, 2026-11-01..07, per store."""
    for s in stores:
        (root / s).mkdir(parents=True)
        for n in range(1, 8):
            d = f"2026-11-{n:02d}"
            (root / s / f"{d}.xml").write_text(day_xml(d, f"TXN-{n}00"), encoding="utf-8")
    return root


def test_fills_every_missing_day_even_beyond_one_week(tmp_path):
    # A gap longer than a week must still fill: day 15 comes from day 8, which is itself a clone.
    work = make_src(tmp_path / "w")
    added = m.extend(work, date(2026, 11, 16))
    assert added[0] == date(2026, 11, 8) and added[-1] == date(2026, 11, 16) and len(added) == 9
    for s in ("PH-001", "PH-002"):
        x = (work / s / "2026-11-15.xml").read_text()
        assert "2026-11-15" in x and "2026-11-08" not in x and "2026-11-01" not in x


def test_cloned_ids_stay_unique_across_days(tmp_path):
    # Each clone prefixes the id with its day, so the same source sale never lands twice under one id.
    work = make_src(tmp_path / "w")
    m.extend(work, date(2026, 11, 15))
    ids = {(work / "PH-001" / f"2026-11-{d:02d}.xml").read_text().split("<SequenceNumber>")[1].split("<")[0]
           for d in (1, 8, 15)}
    assert len(ids) == 3


def test_same_input_gives_same_bytes(tmp_path):
    # Re-running must upload identical files so DAAB reports already-loaded days as duplicates.
    a, b = make_src(tmp_path / "a"), make_src(tmp_path / "b")
    m.extend(a, date(2026, 11, 20))
    m.extend(b, date(2026, 11, 20))
    for f in a.glob("*/*.xml"):
        assert f.read_bytes() == (b / f.parent.name / f.name).read_bytes()


def test_existing_days_are_not_rewritten(tmp_path):
    work = make_src(tmp_path / "w")
    assert m.extend(work, date(2026, 11, 7)) == []
    assert (work / "PH-001" / "2026-11-07.xml").read_text() == day_xml("2026-11-07", "TXN-700")


def test_files_between_is_inclusive_and_covers_all_stores(tmp_path):
    work = make_src(tmp_path / "w")
    got = m.files_between(work, date(2026, 11, 3), date(2026, 11, 4))
    assert [(f.parent.name, f.stem) for f in got] == [
        ("PH-001", "2026-11-03"), ("PH-001", "2026-11-04"), ("PH-002", "2026-11-03"), ("PH-002", "2026-11-04")]
