"""Locate bundled data and the run output directory in every install mode.

The orchestrator ships three data trees that live at the repo root during
development — ``schemas/`` (the final-output JSON schema), ``harness/`` (the
staged ``CLAUDE.md``/agents/skills doctrine) and ``mcp/`` (the evidence_store
MCP server) — but that are *not* Python packages. A plain ``pip``/``pipx``
install only copies the ``orchestrator`` package, so walking ``__file__``'s
parents to find them works from a source checkout yet breaks once installed.

To work in both cases these trees are also force-included into the wheel under
``orchestrator/_bundle/`` (see ``pyproject.toml``). :func:`data_root` prefers the
repo-root copy (editable installs and source checkouts) and falls back to the
bundled copy, so callers get real on-disk paths either way.

Run artifacts are *written*, so they must never land next to the installed code
(site-packages is often read-only). :func:`runs_dir` resolves a writable
location: ``$STRIKET_RUNS_DIR`` if set, otherwise ``./striket_runs`` under the
current working directory (the Strix-compatible default).
"""

from __future__ import annotations

import os
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_DIR.parent
_BUNDLE = _PKG_DIR / "_bundle"

_RUNS_DIR_ENV = "STRIKET_RUNS_DIR"


def data_root() -> Path:
    """Return the directory that contains ``schemas/``, ``harness/`` and ``mcp/``.

    Prefers the repo-root layout (editable installs / source checkouts); falls
    back to the ``orchestrator/_bundle`` copy shipped inside an installed wheel.
    """
    if (_REPO_ROOT / "schemas").is_dir():
        return _REPO_ROOT
    return _BUNDLE


def schema_path() -> Path:
    """Absolute path to the final-output JSON schema."""
    return data_root() / "schemas" / "final_output.schema.json"


def harness_dir() -> Path:
    """Absolute path to the ``harness/`` doctrine tree staged into workspaces."""
    return data_root() / "harness"


def evidence_store_dir() -> Path:
    """Absolute path to the evidence_store MCP server directory."""
    return data_root() / "mcp" / "evidence_store"


def runs_dir() -> Path:
    """Writable base directory for ``striket_runs/<run-name>/`` output."""
    override = os.environ.get(_RUNS_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return Path.cwd() / "striket_runs"


__all__ = [
    "data_root",
    "schema_path",
    "harness_dir",
    "evidence_store_dir",
    "runs_dir",
]
