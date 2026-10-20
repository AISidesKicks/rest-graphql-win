"""Settings for the lab, read from the environment with sane defaults.

Every path in the project hangs off the repo root so the lab can be started
from any working directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

EXPOSURE_ALL = "all"
EXPOSURE_REST = "rest"
EXPOSURE_GRAPHQL = "graphql"
EXPOSURE_CURATED = "curated"

EXPOSURE_GROUPS = (EXPOSURE_ALL, EXPOSURE_REST, EXPOSURE_GRAPHQL, EXPOSURE_CURATED)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
TLS_PORT = 8443

SEED_PRESETS = {
    "small": {
        "accounts": 500,
        "tickets": 5_000,
        "messages_per_ticket": 5,
        "invoices": 2_000,
        "days": 180,
    },
    "large": {
        "accounts": 5_000,
        "tickets": 150_000,
        "messages_per_ticket": 5,
        "invoices": 40_000,
        "days": 730,
    },
}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    """Runtime settings, built once from the environment."""

    project_root: Path = PROJECT_ROOT
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")
    scratch_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "scratch")

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    tls_port: int = TLS_PORT

    scale: str = "small"
    seed: int = 20240701

    mcp_exposure: str = EXPOSURE_ALL
    mcp_path: str = "/mcp"

    cors_origins: tuple[str, ...] = ("*",)
    dev_mode: bool = True

    otel_service_name: str = "rest-graphql-lab"
    otlp_endpoint: str | None = None
    tracing_enabled: bool = True

    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None

    code_mode_timeout_s: float = 15.0
    code_mode_max_output_bytes: int = 64_000
    code_mode_max_host_calls: int = 200

    _oltp_path: Path | None = None
    _olap_path: Path | None = None

    @property
    def oltp_path(self) -> Path:
        return self._oltp_path or self.data_dir / "oltp.sqlite"

    @oltp_path.setter
    def oltp_path(self, value: Path | str) -> None:
        self._oltp_path = Path(value)

    @property
    def olap_path(self) -> Path:
        return self._olap_path or self.data_dir / "olap.duckdb"

    @olap_path.setter
    def olap_path(self, value: Path | str) -> None:
        self._olap_path = Path(value)

    @property
    def csv_dir(self) -> Path:
        return self.data_dir / "csv"

    @property
    def traces_dir(self) -> Path:
        return self.scratch_dir / "traces"

    @property
    def bench_dir(self) -> Path:
        return self.scratch_dir / "bench"

    @property
    def exposure_groups(self) -> frozenset[str]:
        return parse_exposure(self.mcp_exposure)

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.csv_dir, self.scratch_dir, self.traces_dir, self.bench_dir):
            path.mkdir(parents=True, exist_ok=True)


def parse_exposure(raw: str) -> frozenset[str]:
    """Turn an exposure spec into the set of tool groups the MCP server publishes.

    Accepted values are ``all``, ``rest``, ``graphql``, ``curated`` and comma
    separated mixes of them. Unknown names raise, because a silent typo would
    quietly shrink the tool catalog.
    """
    tokens = [t.strip().lower() for t in raw.split(",") if t.strip()]
    if not tokens:
        return frozenset({EXPOSURE_ALL})
    groups: set[str] = set()
    for token in tokens:
        if token not in EXPOSURE_GROUPS:
            raise ValueError(
                f"unknown MCP exposure group {token!r}, pick one of {', '.join(EXPOSURE_GROUPS)}"
            )
        if token == EXPOSURE_ALL:
            groups.update({EXPOSURE_REST, EXPOSURE_GRAPHQL, EXPOSURE_CURATED})
        else:
            groups.add(token)
    return frozenset(groups)


def load_settings(**overrides) -> Settings:
    """Build settings from the environment, then apply explicit overrides."""
    settings = Settings(
        host=os.environ.get("LAB_HOST", DEFAULT_HOST),
        port=int(os.environ.get("LAB_PORT", DEFAULT_PORT)),
        scale=os.environ.get("LAB_SCALE", "small"),
        seed=int(os.environ.get("LAB_SEED", "20240701")),
        mcp_exposure=os.environ.get("MCP_EXPOSURE", EXPOSURE_ALL),
        dev_mode=_env_flag("LAB_DEV", True),
        otlp_endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
        tracing_enabled=_env_flag("LAB_TRACING", True),
        llm_base_url=os.environ.get("LLM_BASE_URL"),
        llm_api_key=os.environ.get("LLM_API_KEY"),
        llm_model=os.environ.get("LLM_MODEL"),
        code_mode_timeout_s=float(os.environ.get("CODE_MODE_TIMEOUT_S", "15")),
        code_mode_max_output_bytes=int(os.environ.get("CODE_MODE_MAX_OUTPUT_BYTES", "64000")),
        code_mode_max_host_calls=int(os.environ.get("CODE_MODE_MAX_HOST_CALLS", "200")),
    )
    for key, value in overrides.items():
        if value is not None:
            setattr(settings, key, value)
    settings.ensure_dirs()
    return settings
