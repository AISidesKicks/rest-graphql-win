"""The agent runner.

Two modes, one task, one catalog:

- **native**: the MCP tool schemas are bridged into OpenAI tool definitions,
  the model calls them one by one and every intermediate payload enters the
  context
- **code mode**: the model gets a single ``exec`` tool and writes Python that
  runs in the sandbox

The runner speaks the OpenAI chat completions API, so any compatible endpoint
works: Ollama, OpenRouter, OpenAI, vLLM. The offline harness replays the same
task with a rule based planner, so the lab never needs a key.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from agent.tasks import (
    CODE_MODE_SYSTEM_PROMPT,
    NATIVE_SYSTEM_PROMPT,
    OFFLINE_CODE_ANSWER,
    OFFLINE_CODE_PROGRAM,
    OFFLINE_NATIVE_ANSWER,
    OFFLINE_NATIVE_PLAN,
    REFERENCE_TASK,
)
from mcplab.catalog import ToolCatalog, count_tokens
from mcplab.codemode import CODE_MODE_INSTRUCTIONS, CodeModeRunner
from mcplab.server import build_tool_callable
from observability.tracing import span


@dataclass
class AgentResult:
    """What one run of one mode cost."""

    mode: str
    task: str
    tool_calls: int = 0
    round_trips: int = 0
    schema_tokens: int = 0
    payload_tokens: int = 0
    output_tokens: int = 0
    bytes_moved: int = 0
    wall_time_ms: float = 0.0
    final_answer: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.schema_tokens + self.payload_tokens + self.output_tokens

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "task": self.task,
            "tool_calls": self.tool_calls,
            "round_trips": self.round_trips,
            "schema_tokens": self.schema_tokens,
            "payload_tokens": self.payload_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "bytes_moved": self.bytes_moved,
            "wall_time_ms": round(self.wall_time_ms, 2),
            "final_answer": self.final_answer,
            "steps": self.steps,
        }


class ChatClient:
    """A very small OpenAI chat completions client."""

    def __init__(self, base_url: str, api_key: str | None, model: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


class AgentRunner:
    """Runs the reference task in native mode or in code mode."""

    def __init__(
        self,
        catalog: ToolCatalog,
        code_mode: CodeModeRunner,
        services: Any,
        runner: Any,
        client: ChatClient | None = None,
    ) -> None:
        self.catalog = catalog
        self.code_mode = code_mode
        self.services = services
        self.runner = runner
        self.client = client
        self._functions: dict[str, Callable[..., Any]] | None = None

    def functions(self) -> dict[str, Callable[..., Any]]:
        if self._functions is None:
            self._functions = {
                spec.name: build_tool_callable(spec, self.runner, self.services)
                for spec in self.catalog.tools
            }
        return self._functions

    def resolve(self, name: str) -> str:
        """Map a friendly name to the tool name of the catalog."""
        for tool_name, code_name in self.catalog.code_mode_names().items():
            if code_name == name:
                return tool_name
        return name

    def openai_tool_definitions(self) -> list[dict[str, Any]]:
        """The MCP schemas, in the shape the OpenAI tool API expects."""
        definitions = []
        for tool in self.catalog.tools:
            schema = dict(tool.input_schema)
            schema.pop("title", None)
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": schema,
                    },
                }
            )
        return definitions

    def exec_tool_definition(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "exec",
                    "description": CODE_MODE_INSTRUCTIONS,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "the Python program to run"}
                        },
                        "required": ["code"],
                    },
                },
            }
        ]

    # Live runs

    def run_native_live(self, task: str = REFERENCE_TASK, max_steps: int = 8) -> AgentResult:
        result = AgentResult(mode="native", task=task)
        definitions = self.openai_tool_definitions()
        result.schema_tokens = count_tokens(definitions)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": NATIVE_SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]
        started = time.perf_counter()
        for _ in range(max_steps):
            result.round_trips += 1
            response = self.client.complete(messages, definitions)
            message = response["choices"][0]["message"]
            content = message.get("content") or ""
            result.output_tokens += count_tokens(content)
            tool_calls = message.get("tool_calls") or []
            messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                }
            )
            if not tool_calls:
                result.final_answer = content
                break
            for call in tool_calls:
                function = call["function"]
                name = function["name"]
                arguments = json.loads(function.get("arguments") or "{}")
                payload = self.functions()[name](**arguments)
                text = json.dumps(payload, default=str)
                result.payload_tokens += count_tokens(text)
                result.bytes_moved += len(text)
                result.tool_calls += 1
                result.steps.append({"tool": name, "arguments": arguments, "bytes": len(text)})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "name": name,
                        "content": text,
                    }
                )
        result.wall_time_ms = (time.perf_counter() - started) * 1000
        return result

    def run_code_mode_live(self, task: str = REFERENCE_TASK, max_steps: int = 4) -> AgentResult:
        result = AgentResult(mode="code_mode", task=task)
        definitions = self.exec_tool_definition()
        result.schema_tokens = count_tokens(definitions)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": CODE_MODE_SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]
        started = time.perf_counter()
        for _ in range(max_steps):
            result.round_trips += 1
            response = self.client.complete(messages, definitions)
            message = response["choices"][0]["message"]
            content = message.get("content") or ""
            result.output_tokens += count_tokens(content)
            tool_calls = message.get("tool_calls") or []
            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
            if not tool_calls:
                result.final_answer = content
                break
            for call in tool_calls:
                arguments = json.loads(call["function"].get("arguments") or "{}")
                code = arguments.get("code", "")
                result.output_tokens += count_tokens(code)
                outcome = self.code_mode.run(code)
                text = outcome.render()
                result.payload_tokens += count_tokens(text)
                result.bytes_moved += len(text)
                result.tool_calls += 1
                result.steps.append(
                    {
                        "tool": "exec",
                        "code_bytes": len(code),
                        "host_calls": outcome.host_calls,
                        "bytes": len(text),
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "name": "exec",
                        "content": text,
                    }
                )
        result.wall_time_ms = (time.perf_counter() - started) * 1000
        return result

    # Offline runs, the reproducible part of the lab

    def run_native_offline(self, task: str = REFERENCE_TASK) -> AgentResult:
        """Replay the native plan with a rule based planner."""
        result = AgentResult(mode="native", task=task)
        definitions = self.openai_tool_definitions()
        result.schema_tokens = count_tokens(definitions)
        functions = self.functions()
        started = time.perf_counter()
        with span("agent.native_offline", steps=len(OFFLINE_NATIVE_PLAN)):
            for planned in OFFLINE_NATIVE_PLAN:
                result.round_trips += 1
                result.tool_calls += 1
                name = self.resolve(planned.name)
                payload = functions[name](**planned.arguments)
                text = json.dumps(payload, default=str)
                result.payload_tokens += count_tokens(text)
                result.bytes_moved += len(text)
                result.steps.append(
                    {
                        "tool": name,
                        "arguments": planned.arguments,
                        "bytes": len(text),
                    }
                )
            result.output_tokens = count_tokens(OFFLINE_NATIVE_ANSWER)
            result.final_answer = OFFLINE_NATIVE_ANSWER
        result.wall_time_ms = (time.perf_counter() - started) * 1000
        return result

    def run_code_mode_offline(self, task: str = REFERENCE_TASK) -> AgentResult:
        """Replay the code mode plan, one program inside the sandbox."""
        result = AgentResult(mode="code_mode", task=task)
        definitions = self.exec_tool_definition()
        result.schema_tokens = count_tokens(definitions)
        started = time.perf_counter()
        with span("agent.code_mode_offline"):
            result.round_trips += 1
            result.tool_calls += 1
            outcome = self.code_mode.run(OFFLINE_CODE_PROGRAM)
            text = outcome.render()
            result.payload_tokens = count_tokens(text)
            result.bytes_moved += len(text)
            result.output_tokens = count_tokens(OFFLINE_CODE_PROGRAM)
            result.steps.append(
                {
                    "tool": "exec",
                    "code_bytes": len(OFFLINE_CODE_PROGRAM),
                    "host_calls": outcome.host_calls,
                    "bytes": len(text),
                }
            )
            result.final_answer = outcome.stdout.strip() or OFFLINE_CODE_ANSWER
        result.wall_time_ms = (time.perf_counter() - started) * 1000
        return result


def build_client(settings: Any) -> ChatClient | None:
    """Build the chat client from the environment, or None when there is no key."""
    if not settings.llm_base_url or not settings.llm_model:
        return None
    return ChatClient(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
