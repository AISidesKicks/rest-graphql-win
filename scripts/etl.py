"""Build the DuckDB star schema from the SQLite operational data."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import load_settings  # noqa: E402
from data.etl import run_etl  # noqa: E402


def main() -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Run the ETL")
    parser.add_argument("--oltp", type=Path, default=None, help="source SQLite file")
    parser.add_argument("--olap", type=Path, default=None, help="target DuckDB file")
    parser.add_argument("--no-export", action="store_true", help="skip the Parquet and CSV export")
    parser.add_argument("--quiet", action="store_true", help="less output")
    args = parser.parse_args()

    print("building the analytical star schema")
    run_etl(
        oltp_path=args.oltp,
        olap_path=args.olap,
        export=not args.no_export,
        quiet=args.quiet,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
