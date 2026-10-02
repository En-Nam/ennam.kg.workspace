"""Same seed => byte-identical package; generated IDs never collide with the original package."""
import hashlib

from conftest import BASE_DIR
from helpers import PRIMARY_KEYS, is_generated


def _digest(path):
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(path.glob("*.csv"))}


def test_two_runs_with_same_seed_are_byte_identical(out, tmp_path):
    from pharmacy_demo_gen.generate import generate

    generate(BASE_DIR, tmp_path)
    assert _digest(tmp_path) == _digest(out.path)
    assert (tmp_path / "DATA_SUMMARY.txt").read_bytes() == (out.path / "DATA_SUMMARY.txt").read_bytes()


def test_generated_ids_do_not_collide_with_original_ids(out, base):
    for table, pk in PRIMARY_KEYS.items():
        if table in ("vendors", "product_costs", "purchase_orders", "purchase_order_lines"):
            continue
        original = {r[pk] for r in base.rows(table)}
        new = [r[pk] for r in out.rows(table) if r[pk] not in original]
        assert len(new) == len(set(new)), table
        assert not [i for i in original if is_generated(i)], f"{table}: original id looks generated"
