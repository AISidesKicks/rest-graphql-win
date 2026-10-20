"""Generate the demo dataset: CSV files plus the SQLite operational database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import SEED_PRESETS, load_settings  # noqa: E402
from data.seed import seed_all  # noqa: E402


def main() -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Seed the lab dataset")
    parser.add_argument(
        "--scale",
        choices=sorted(SEED_PRESETS),
        default=settings.scale,
        help="dataset preset, small is the default",
    )
    parser.add_argument("--seed", type=int, default=settings.seed, help="random seed")
    parser.add_argument("--db", type=Path, default=None, help="target SQLite file")
    parser.add_argument("--csv-dir", type=Path, default=None, help="target CSV directory")
    parser.add_argument("--quiet", action="store_true", help="less output")
    args = parser.parse_args()

    print(f"seeding the {args.scale} preset with seed {args.seed}")
    counts = seed_all(
        scale=args.scale,
        seed=args.seed,
        db_path=args.db,
        csv_dir=args.csv_dir,
        quiet=args.quiet,
    )
    total = sum(value for key, value in counts.items() if not key.startswith("_"))
    print(f"done, {total:,} rows in total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
