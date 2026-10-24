"""Run configuration for the Striket orchestrator.

Every tunable (adapter, model, effort, scan mode, budget, focus, permission
mode, disallowed tools) has a default that lives *here* as a module constant — never
hardcoded at a call site. Values are resolved in this precedence order:

    built-in DEFAULT_* constants  <  config file  <  environment  <  CLI flags

No secret (LLM key, telemetry token) is ever stored in this config or placed in
a prompt; those live only in the environment the sandboxed agent inherits.
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

# --- Defaults (single source of truth; nothing hardcoded at call sites) -----

DEFAULT_ADAPTER = "claude"
DEFAULT_MODEL: str | None = "opus"
DEFAULT_EFFORT: str | None = "xhigh"
DEFAULT_SCAN_MODE = "quick"
DEFAULT_MAX_BUDGET = 10.0

# Wall-clock cap (seconds) for the agent run. ``None`` defers to the scan
# mode's own ``timeout_s`` (which itself defaults to ``0`` = no limit, so a run
# is unbounded by default). Set a positive value here, via ``STRIKET_TIMEOUT``,
# or with ``--timeout`` to impose one; ``0`` explicitly means no limit.
DEFAULT_TIMEOUT: int | None = None

# Optional operator guidance on what the scan should prioritise (e.g. "auth and
# session handling"). It narrows attention *within* the validated scope and
# never widens it; ``None`` means no extra guidance in the prompt.
DEFAULT_FOCUS: str | None = None

# Agent works autonomously *inside* the sandbox. Runs are headless (no TTY, no
# answerer), so any mode that can raise an unanswerable permission prompt —
# ``acceptEdits`` auto-approves edits but still prompts for Bash and other
# tools — deadlocks routine read-only recon (``command -v``, tool version
# checks, listing the venv). Scope is *not* enforced by this string: it is
# enforced by the orchestrator before launch and by the doctrine in the prompt,
# so the agent is safely handed ``bypassPermissions`` to run unattended.
# Configurable; never hardcoded at a call site.
DEFAULT_PERMISSION_MODE = "bypassPermissions"

# Interactive prompting has no answerer in headless runs. ``agentiscode``
# already disallows ``AskUserQuestion``; we name it explicitly so the intent
# survives if that default ever changes.
DEFAULT_DISALLOWED_TOOLS: tuple[str, ...] = ("AskUserQuestion",)

# Environment variable names (values only — never secrets).
_ENV_PREFIX = "STRIKET_"
_CONFIG_PATH_ENV = "STRIKET_CONFIG"

# Default config file names looked up in the current working directory.
_CONFIG_FILENAMES = ("striket.toml", ".striket.toml")


@dataclass(frozen=True)
class Config:
    """Immutable resolved run configuration.

    ``adapter`` and ``model`` are ordinary parameters with defaults, so the
    orchestrator stays agnostic about which harness/model is in play.
    """

    adapter: str = DEFAULT_ADAPTER
    model: str | None = DEFAULT_MODEL
    effort: str | None = DEFAULT_EFFORT
    scan_mode: str = DEFAULT_SCAN_MODE
    max_budget: float = DEFAULT_MAX_BUDGET
    timeout: int | None = DEFAULT_TIMEOUT
    focus: str | None = DEFAULT_FOCUS
    permission_mode: str = DEFAULT_PERMISSION_MODE
    disallowed_tools: tuple[str, ...] = DEFAULT_DISALLOWED_TOOLS

    def merged(self, **overrides: Any) -> Config:
        """Return a copy with non-``None`` overrides applied."""
        clean = {key: value for key, value in overrides.items() if value is not None}
        if "disallowed_tools" in clean:
            clean["disallowed_tools"] = tuple(clean["disallowed_tools"])
        return replace(self, **clean)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "model": self.model,
            "effort": self.effort,
            "scan_mode": self.scan_mode,
            "max_budget": self.max_budget,
            "timeout": self.timeout,
            "focus": self.focus,
            "permission_mode": self.permission_mode,
            "disallowed_tools": list(self.disallowed_tools),
        }


# --- Loading ----------------------------------------------------------------


def _find_config_file(cwd: Path, explicit: str | os.PathLike[str] | None) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    env_path = os.environ.get(_CONFIG_PATH_ENV)
    if env_path:
        path = Path(env_path)
        if path.is_file():
            return path
    for name in _CONFIG_FILENAMES:
        candidate = cwd / name
        if candidate.is_file():
            return candidate
    return None


def _load_file(path: Path) -> dict[str, Any]:
    """Load a TOML (or JSON) config file. A ``[striket]`` table is honored."""
    raw = path.read_bytes()
    try:
        data: dict[str, Any] = tomllib.loads(raw.decode("utf-8"))
    except tomllib.TOMLDecodeError:
        data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        return {}
    section = data.get("striket")
    if isinstance(section, dict):
        return section
    return data


_FIELD_PARSERS: dict[str, Any] = {
    "adapter": str,
    "model": str,
    "effort": str,
    "scan_mode": str,
    "max_budget": float,
    "timeout": int,
    "focus": str,
    "permission_mode": str,
}


def _coerce(source: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, parser in _FIELD_PARSERS.items():
        if key in source and source[key] is not None:
            try:
                out[key] = parser(source[key])
            except (TypeError, ValueError):
                continue
    tools = source.get("disallowed_tools")
    if isinstance(tools, str):
        out["disallowed_tools"] = tuple(t.strip() for t in tools.split(",") if t.strip())
    elif isinstance(tools, (list, tuple)):
        out["disallowed_tools"] = tuple(str(t).strip() for t in tools if str(t).strip())
    return out


def _from_env() -> dict[str, Any]:
    env: dict[str, Any] = {}
    for key in (*_FIELD_PARSERS, "disallowed_tools"):
        value = os.environ.get(_ENV_PREFIX + key.upper())
        if value is not None:
            env[key] = value
    return _coerce(env)


def load_config(
    *,
    cwd: Path | None = None,
    config_path: str | os.PathLike[str] | None = None,
    overrides: dict[str, Any] | None = None,
) -> Config:
    """Resolve a :class:`Config` from defaults, file, environment, and overrides.

    ``overrides`` (typically parsed CLI flags) wins; ``None`` values in it are
    ignored so unspecified flags fall through to lower-precedence sources.
    """
    cwd = cwd or Path.cwd()
    config = Config()

    file_path = _find_config_file(cwd, config_path)
    if file_path is not None:
        config = config.merged(**_coerce(_load_file(file_path)))

    config = config.merged(**_from_env())

    if overrides:
        config = config.merged(**overrides)

    return config


__all__ = [
    "DEFAULT_ADAPTER",
    "DEFAULT_DISALLOWED_TOOLS",
    "DEFAULT_EFFORT",
    "DEFAULT_FOCUS",
    "DEFAULT_MAX_BUDGET",
    "DEFAULT_MODEL",
    "DEFAULT_PERMISSION_MODE",
    "DEFAULT_SCAN_MODE",
    "DEFAULT_TIMEOUT",
    "Config",
    "load_config",
]
