"""Build and run the ``agentiscode`` command behind a unified interface.

The orchestrator stays adapter-agnostic: it asks this module for a command and
to run it, and never branches on which harness/model is in play. Adapter-
specific differences (how ``opencode`` vs ``claude``/``claude-p`` read doctrine,
skills, and agents) are isolated here.

First-phase milestones (M0-M3) are exercised only with ``--adapter claude``.
``claude-p`` and ``opencode`` are accepted as known adapters and must not be
excluded by validation; they are verified in M4.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .config import Config

AGENTISCODE_BIN = "agentiscode"

# Canonical adapters and their accepted aliases (from ``agentiscode --help``).
# Unknown adapters are a usage error (exit code 2) — see :class:`UnknownAdapterError`.
_ADAPTER_ALIASES: dict[str, str] = {
    "opencode": "opencode",
    "oc": "opencode",
    "claude": "claude",
    "claudecode": "claude",
    "cloud": "claude",
    "claude-p": "claude-p",
    "cp": "claude-p",
}

KNOWN_ADAPTERS: tuple[str, ...] = ("opencode", "claude", "claude-p")

USAGE_EXIT_CODE = 2


class UnknownAdapterError(ValueError):
    """Raised for an adapter not in the known set. Maps to exit code 2."""

    exit_code = USAGE_EXIT_CODE


def canonical_adapter(name: str) -> str:
    """Resolve an adapter name or alias to its canonical form.

    Raises :class:`UnknownAdapterError` for anything unrecognized so the CLI can
    print a clear error and exit 2.
    """
    key = (name or "").strip().lower()
    resolved = _ADAPTER_ALIASES.get(key)
    if resolved is None:
        known = ", ".join(sorted(set(_ADAPTER_ALIASES)))
        raise UnknownAdapterError(
            f"unknown adapter {name!r}; known adapters/aliases: {known}"
        )
    return resolved


@dataclass(frozen=True)
class Telemetry:
    """Optional telemetry identifiers; only present when supplied."""

    task_id: str | None = None
    project_id: str | None = None
    run_id: str | None = None


def build_command(
    config: Config,
    *,
    sandbox_workdir: Path,
    run_dir: Path,
    schema_path: Path,
    timeout_s: int,
    telemetry: Telemetry | None = None,
    add_dirs: Sequence[Path | str] = (),
    allowed_tools: Sequence[str] = (),
) -> list[str]:
    """Assemble the ``agentiscode`` argv.

    The adapter is validated here; an unknown adapter raises
    :class:`UnknownAdapterError`. ``claude-p`` and ``opencode`` pass validation
    unchanged — they are only *tested* in M4, never excluded.

    ``sandbox_workdir`` is the agent's cwd — the staged harness workspace from
    which doctrine/agents/skills/MCP are discovered. ``add_dirs`` are additional
    directories (the authorized targets) the agent may read; they are passed to
    the runtime via ``--extra-args-json`` as ``--add-dir`` so the orchestrator
    stays adapter-agnostic while the target repo is never used as cwd.
    """
    adapter = canonical_adapter(config.adapter)

    cmd: list[str] = [AGENTISCODE_BIN, "--adapter", adapter]

    if config.model:
        cmd += ["--model", config.model]
    if config.effort:
        cmd += ["--effort", config.effort]

    cmd += ["--cwd", str(sandbox_workdir)]
    cmd += ["--json"]
    cmd += ["--die-with-parent"]
    cmd += ["--timeout", str(timeout_s)]
    cmd += ["--output-schema", str(schema_path)]
    cmd += ["--final-output", str(run_dir / "final.json")]
    cmd += ["--session-output", str(run_dir / "session.id")]

    # Autonomous inside the sandbox: headless runs have no answerer, so the
    # mode must not raise permission prompts. Scope is enforced before launch
    # and by the prompt doctrine, not by this mode. See DEFAULT_PERMISSION_MODE.
    cmd += ["--permission-mode", config.permission_mode]

    # Forbid interactive questions in headless mode.
    if config.disallowed_tools:
        cmd += ["--disallowed-tools", ",".join(config.disallowed_tools)]

    if telemetry:
        if telemetry.task_id:
            cmd += ["--task-id", telemetry.task_id]
        if telemetry.project_id:
            cmd += ["--project-id", telemetry.project_id]
        if telemetry.run_id:
            cmd += ["--run-id", telemetry.run_id]

    # Expose the authorized targets to the runtime as read-accessible dirs
    # without making any of them the cwd. These pass straight through to the
    # underlying CLI; the orchestrator does not branch on the adapter here.
    extra_args: list[str] = []
    for directory in add_dirs:
        extra_args += ["--add-dir", str(directory)]
    # Pre-approve non-interactive tools (e.g. the staged evidence_store MCP) so
    # they are not blocked by an unanswerable permission prompt in headless.
    if allowed_tools:
        extra_args += ["--allowedTools", ",".join(allowed_tools)]
    if extra_args:
        cmd += ["--extra-args-json", json.dumps(extra_args)]

    return cmd


def run_agent(
    cmd: Sequence[str],
    prompt: str,
    *,
    on_line: Callable[[str], None] | None = None,
    env: dict[str, str] | None = None,
) -> int:
    """Run ``agentiscode``, feeding ``prompt`` on stdin and streaming stdout.

    Each stdout line (a JSON-Lines event) is passed to ``on_line`` as it
    arrives. Returns the process exit code. ``stderr`` is inherited so adapter
    diagnostics reach the operator. No secret is placed in ``cmd`` or
    ``prompt``; keys live in ``env`` (inherited from the caller).
    """
    process = subprocess.Popen(
        list(cmd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
        bufsize=1,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        process.stdin.write(prompt)
        process.stdin.close()
    except BrokenPipeError:
        pass

    for line in process.stdout:
        if on_line is not None:
            on_line(line.rstrip("\n"))

    return process.wait()


__all__ = [
    "AGENTISCODE_BIN",
    "KNOWN_ADAPTERS",
    "Telemetry",
    "USAGE_EXIT_CODE",
    "UnknownAdapterError",
    "build_command",
    "canonical_adapter",
    "run_agent",
]
