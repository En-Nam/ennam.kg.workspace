"""CLI: uv run python -m pharmacy_demo_gen --base ../../demo_mockdata/base --out ../../demo_mockdata"""
import argparse
import sys
from pathlib import Path

from . import config as C
from .generate import generate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the 12-month pharmacy_demo CSV package.")
    parser.add_argument("--base", type=Path, required=True, help="directory with the original 21 CSVs")
    parser.add_argument("--out", type=Path, required=True, help="output directory (demo_mockdata)")
    parser.add_argument("--seed", type=int, default=C.SEED)
    args = parser.parse_args(argv)
    if args.base.resolve() == args.out.resolve():
        print("--base and --out must differ (base is the immutable input)", file=sys.stderr)
        return 2
    tables = generate(args.base, args.out, args.seed)
    for name in sorted(tables):
        print(f"{name}: {len(tables[name].rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
