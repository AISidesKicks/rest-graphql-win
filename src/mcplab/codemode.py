"""Code mode: the Monty sandbox.

The model sees one tool, ``exec(code)``. The code runs inside Monty, a Rust
interpreter for a Python subset. The sandbox has no filesystem, no network and
no imports, the only way out is the host functions.

Those host functions are the same catalog the native MCP tools publish, one
typed Python function per entry. So the comparison in the savings chapter is
fair: the same operations, exposed in two ways.

Limits, all enforced on the host side:

- a wall clock timeout for the program
- a maximum number of host calls
- a maximum output size
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic_monty import CollectStreams, Monty, MontyError

from config import Settings
from mcplab.catalog import ToolCatalog
from mcplab.server import ToolRunner, build_tool_callable
from observability.tracing import span


@dataclass
class CodeModeResult:
    """What one code mode run produced."""

    stdout: str = ""
    value: Any = None
    host_calls: int = 0
    duration_ms: float = 0.0
    error: str | None = None
    truncated: bool = False
    host_call_log: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stdout": self.stdout,
            "value": self.value,
            "host_calls": self.host_calls,
            "duration_ms": round(self.duration_ms, 2),
            "error": self.error,
            "truncated": self.truncated,
            "host_call_log": self.host_call_log,
        }

    def render(self) -> str:
        """The text the model sees."""
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.value is not None:
            parts.append(json.dumps(self.value, default=str))
        if self.error:
            parts.append(f"error: {self.error}")
        if self.truncated:
            parts.append("the output was truncated")
        return "\n".join(parts) if parts else "(no output)"


class CodeModeRunner:
    """Runs Python programs against the lab through the Monty sandbox."""

    def __init__(
        self,
        catalog: ToolCatalog,
        runner: ToolRunner,
        services: Any,
        settings: Settings,
    ) -> None:
        self.catalog = catalog
        self.runner = runner
        self.services = services
        self.settings = settings
        self._functions: dict[str, Callable[..., Any]] | None = None

    def host_functions(self) -> dict[str, Callable[..., Any]]:
        """The typed Python functions the sandbox can call."""
        if self._functions is None:
            names = self.catalog.code_mode_names()
            functions: dict[str, Callable[..., Any]] = {}
            for spec in self.catalog.tools:
                base = build_tool_callable(spec, self.runner, self.services)
                functions[names[spec.name]] = base
            self._functions = functions
        return self._functions

    def stubs(self) -> str:
        """The ``.pyi`` stub the sandbox uses for type hints."""
        names = self.catalog.code_mode_names()
        lines = []
        for spec in self.catalog.tools:
            stub = spec.stub()
            lines.append(stub.replace(f"def {spec.name}(", f"def {names[spec.name]}(", 1))
        return "\n".join(lines)

    def run(self, code: str) -> CodeModeResult:
        """Run one program and return what happened."""
        result = CodeModeResult()
        started = time.perf_counter()
        counter = {"calls": 0, "log": []}

        functions = {
            name: self._counting(name, function, counter, result)
            for name, function in self.host_functions().items()
        }

        with span(
            "codemode.exec",
            code_bytes=len(code),
            tools=len(functions),
        ) as current:
            try:
                with Monty(request_timeout=self.settings.code_mode_timeout_s + 5) as pool:
                    with pool.checkout(
                        limits={
                            "max_feed_duration_secs": self.settings.code_mode_timeout_s,
                            "max_suspensions": self.settings.code_mode_max_host_calls,
                        }
                    ) as session:
                        stream = CollectStreams()
                        value = session.feed_run(
                            code, external_lookup=functions, print_callback=stream
                        )
                result.value = _plain(value)
                stdout = "".join(text for _name, text in stream.output)
                limit = self.settings.code_mode_max_output_bytes
                if len(stdout) > limit:
                    result.stdout = stdout[:limit]
                    result.truncated = True
                else:
                    result.stdout = stdout
            except MontyError as exc:
                result.error = _monty_message(exc)
            except Exception as exc:
                result.error = f"{type(exc).__name__}: {exc}"
            finally:
                result.host_calls = counter["calls"]
                result.host_call_log = counter["log"]
                result.duration_ms = (time.perf_counter() - started) * 1000
            current.set_attribute("codemode.host_calls", result.host_calls)
            current.set_attribute("codemode.error", result.error)
        return result

    def _counting(
        self,
        name: str,
        function: Callable[..., Any],
        counter: dict[str, Any],
        result: CodeModeResult,
    ) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            if counter["calls"] >= self.settings.code_mode_max_host_calls:
                raise RuntimeError(
                    f"the program used more than {self.settings.code_mode_max_host_calls} host calls"
                )
            counter["calls"] += 1
            counter["log"].append(name)
            return function(*args, **kwargs)

        return call


def _plain(value: Any) -> Any:
    """Turn the value the sandbox returned into plain Python."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return str(value)


def _monty_message(exc: MontyError) -> str:
    display = getattr(exc, "display", None)
    if callable(display):
        try:
            return str(display(format="type-msg"))
        except Exception:
            pass
    return f"{type(exc).__name__}: {exc}"


CODE_MODE_INSTRUCTIONS = """You drive the lab with code, not with one tool call per row.

Write a short Python program and send it to exec(code).

Inside the program you can call the lab functions directly, for example:

    accounts = list_accounts(status="past_due", limit=50)
    invoices = list_invoices(status="overdue", limit=50)
    rows = []
    for invoice in invoices["items"]:
        rows.append({"account": invoice["account_id"], "cents": invoice["total_cents"]})
    rows.sort(key=lambda row: row["cents"], reverse=True)
    rows[:10]

The rules of the sandbox:

- no imports, no filesystem, no network
- only the lab functions are reachable
- print what you want to see, the last expression is returned as well
- keep the output small, the model pays for every byte
"""
