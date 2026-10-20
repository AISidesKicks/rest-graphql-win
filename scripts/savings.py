"""Native MCP versus code mode, with the numbers.

Offline mode (the default) replays the reference task with a rule based
planner, so the numbers are reproducible and no API key is needed. With
``--live`` the same task goes to an OpenAI compatible endpoint.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from agent.runner import AgentRunner, build_client  # noqa: E402
from agent.tasks import REFERENCE_TASK  # noqa: E402
from app import create_app  # noqa: E402
from config import load_settings  # noqa: E402
from mcplab.catalog import schema_token_report  # noqa: E402


def print_comparison(native: dict[str, Any], code_mode: dict[str, Any]) -> None:
    header = (
        f"{'metric':<22} {'native MCP':>14} {'code mode':>14} {'change':>12}"
    )
    print(header)
    print("-" * len(header))

    def line(label: str, key: str, percent: bool = True) -> None:
        left = native.get(key, 0)
        right = code_mode.get(key, 0)
        if percent and left:
            change = f"{(right - left) / left * 100:+.1f}%"
        else:
            change = f"{right - left:+,.1f}" if isinstance(left, float) else f"{right - left:+d}"
        print(f"{label:<22} {left:>14,.1f} {right:>14,.1f} {change:>12}")

    line("tool calls", "tool_calls")
    line("round trips", "round_trips")
    line("schema tokens", "schema_tokens")
    line("payload tokens", "payload_tokens")
    line("output tokens", "output_tokens")
    line("total tokens", "total_tokens")
    line("bytes moved", "bytes_moved")
    line("wall time ms", "wall_time_ms", percent=False)


def write_report(native: dict[str, Any], code_mode: dict[str, Any], settings: Any) -> Path:
    """Keep the numbers in the scratch directory, so they can be compared later."""
    settings.bench_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    path = settings.bench_dir / f"savings-{stamp}.json"
    path.write_text(
        json.dumps({"native": native, "code_mode": code_mode}, indent=2, default=str),
        encoding="utf-8",
    )
    return path


def main() -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Native MCP versus code mode")
    parser.add_argument("--live", action="store_true", help="use an OpenAI compatible endpoint")
    parser.add_argument("--task", default=REFERENCE_TASK, help="the task to run")
    parser.add_argument("--json", action="store_true", help="print the raw numbers")
    args = parser.parse_args()

    app = create_app(settings)
    with TestClient(app):
        catalog = app.state.mcp_catalog
        report = schema_token_report(catalog)
        client = build_client(settings)
        if args.live and client is None:
            print(
                "--live needs LLM_BASE_URL and LLM_MODEL, for example\n"
                "  LLM_BASE_URL=http://127.0.0.1:11434/v1 LLM_MODEL=qwen2.5-coder pixi run savings -- --live"
            )
            return 2

        runner = AgentRunner(
            catalog=catalog,
            code_mode=app.state.code_mode,
            services=app.state.services,
            runner=app.state.mcp_runner,
            client=client,
        )

        if args.live:
            native = runner.run_native_live(args.task).as_dict()
            code_mode = runner.run_code_mode_live(args.task).as_dict()
        else:
            native = runner.run_native_offline(args.task).as_dict()
            code_mode = runner.run_code_mode_offline(args.task).as_dict()

        print(f"task: {args.task}")
        print(f"mode: {'live' if args.live else 'offline, rule based planner'}")
        print()
        print_comparison(native, code_mode)
        print()
        print(f"the full catalog is {report['tool_count']} tools, {report['total_tokens']:,} tokens of schemas")
        print("native MCP pays for all of them, code mode pays for one exec tool")
        print()
        for name, result in (("native MCP", native), ("code mode", code_mode)):
            print(f"{name} steps:")
            for step in result["steps"]:
                print(f"  {json.dumps(step, default=str)}")

        if args.json:
            print()
            print(json.dumps({"native": native, "code_mode": code_mode}, indent=2, default=str))
        report = write_report(native, code_mode, settings)
        print()
        print(f"the numbers are saved in {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
