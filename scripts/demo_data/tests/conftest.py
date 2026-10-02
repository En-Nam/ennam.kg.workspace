import csv
import sys
from functools import lru_cache
from pathlib import Path

import pytest

DEMO_DATA_DIR = Path(__file__).resolve().parents[1]
WORKSPACE = Path(__file__).resolve().parents[3]
BASE_DIR = WORKSPACE / "demo_mockdata" / "base"
sys.path.insert(0, str(DEMO_DATA_DIR))


class Out:
    """Read-only view over one generated output directory."""

    def __init__(self, path: Path):
        self.path = path

    @lru_cache(maxsize=None)
    def rows(self, table: str) -> list[dict[str, str]]:
        with (self.path / f"{table}.csv").open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    @lru_cache(maxsize=None)
    def columns(self, table: str) -> list[str]:
        with (self.path / f"{table}.csv").open(newline="", encoding="utf-8") as fh:
            return next(csv.reader(fh))


@pytest.fixture(scope="session")
def out(tmp_path_factory) -> Out:
    from pharmacy_demo_gen.generate import generate

    target = tmp_path_factory.mktemp("generated")
    generate(BASE_DIR, target)
    return Out(target)


@pytest.fixture(scope="session")
def base() -> Out:
    return Out(BASE_DIR)
