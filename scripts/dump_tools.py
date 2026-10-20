"""Print the MCP catalog with the token cost of every tool.

This is the baseline number of the savings story: what a model pays for the
tool schemas before it even calls a tool.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from app import create_app  # noqa: E402
from config import load_settings  # noqa: E402
from mcplab.catalog import schema_token_report  # noqa: E402


def main() -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Print the MCP tool catalog")
    parser.add_argument(
        "--exposure",
        default=None,
        help="override the MCP exposure switch, for example rest,curated",
    )
    parser.add_argument("--json", action="store_true", help="print the raw numbers")
    parser.add_argument("--schemas", action="store_true", help="print every tool schema")
    args = parser.parse_args()

    if args.exposure:
        settings.mcp_exposure = args.exposure

    app = create_app(settings)
    with TestClient(app):
        catalog = app.state.mcp_catalog
        report = schema_token_report(catalog)

        print(f"exposure: {', '.join(sorted(settings.exposure_groups))}")
        print(f"tools:    {report['tool_count']}")
        print(f"tokens:   {report['total_tokens']:,} for the schemas alone")
        print()
        header = f"{'tool':<34} {'group':<9} {'tokens':>8}  {'arguments':<44}"
        print(header)
        print("-" * len(header))
        for tool in report["tools"]:
            spec = catalog.by_name()[tool["name"]]
            arguments = ", ".join(spec.arguments)[:44]
            print(f"{tool['name']:<34} {tool['group']:<9} {tool['tokens']:>8,}  {arguments}")

        if args.schemas:
            print()
            for tool in catalog.tools:
                print()
                print(f"### {tool.name}")
                print(json.dumps(tool.as_mcp_tool(), indent=2))

        if args.json:
            print()
            print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
