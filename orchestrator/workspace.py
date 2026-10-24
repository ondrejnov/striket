"""Stage the striket harness into a per-run workspace the agent's cwd can load.

The live ``claude`` adapter discovers operational doctrine (``CLAUDE.md``),
subagents (``.claude/agents/*.md``), skills (``.claude/skills/<name>/SKILL.md``)
and project MCP servers (``.mcp.json``) from its working directory. We therefore
build a disposable workspace under the run directory, copy the harness into the
layout Claude Code expects, and point ``--cwd`` at it. The real target is exposed
read-only via ``--add-dir`` (see :mod:`harness`), so the audited repository is
never modified or polluted with harness files.

No secret is ever written here; only methodology (doctrine/skills) and the
evidence_store MCP wiring (an absolute command plus a run-scoped data dir).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .resources import evidence_store_dir, harness_dir

_HARNESS_DIR = harness_dir()
_EVIDENCE_STORE = evidence_store_dir()


def _copy_skills(src_skills: Path, dst_skills: Path) -> int:
    """Flatten ``skills/<category>/<name>/SKILL.md`` into ``<category>-<name>/``.

    Claude Code discovers each skill as a direct child directory of
    ``.claude/skills`` holding a ``SKILL.md``; the striket harness nests skills
    one level deeper by category, so we flatten while keeping names unique.
    """
    count = 0
    for skill_md in sorted(src_skills.rglob("SKILL.md")):
        rel = skill_md.parent.relative_to(src_skills)
        flat = "-".join(rel.parts)
        target_dir = dst_skills / flat
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_md, target_dir / "SKILL.md")
        count += 1
    return count


def stage_workspace(run_dir: Path) -> Path:
    """Materialize the harness into ``<run_dir>/workspace`` and return its path.

    Lays out ``CLAUDE.md``, ``.claude/agents/``, ``.claude/skills/`` and an
    ``.mcp.json`` registering the evidence_store MCP with a run-scoped data dir.
    Idempotent: a stale workspace from a resumed run is rebuilt.
    """
    workspace = run_dir / "workspace"
    if workspace.exists():
        shutil.rmtree(workspace)
    claude_dir = workspace / ".claude"
    (claude_dir / "agents").mkdir(parents=True, exist_ok=True)
    (claude_dir / "skills").mkdir(parents=True, exist_ok=True)

    claude_md = _HARNESS_DIR / "CLAUDE.md"
    if claude_md.is_file():
        shutil.copy2(claude_md, workspace / "CLAUDE.md")

    agents_src = _HARNESS_DIR / "agents"
    if agents_src.is_dir():
        for agent_md in sorted(agents_src.glob("*.md")):
            shutil.copy2(agent_md, claude_dir / "agents" / agent_md.name)

    skills_src = _HARNESS_DIR / "skills"
    if skills_src.is_dir():
        _copy_skills(skills_src, claude_dir / "skills")

    _write_mcp_config(workspace, run_dir)
    return workspace


def _write_mcp_config(workspace: Path, run_dir: Path) -> None:
    """Register the evidence_store MCP server, scoped to this run's data dir."""
    if not _EVIDENCE_STORE.exists():
        return
    # The server takes the run dir itself and keeps its state in
    # ``<run_dir>/evidence_store/`` — where the TUI and partial recovery read it.
    (run_dir / "evidence_store").mkdir(parents=True, exist_ok=True)
    config = {
        "mcpServers": {
            "evidence_store": {
                "command": "python3",
                "args": [str(_EVIDENCE_STORE), "--run-dir", str(run_dir)],
            }
        }
    }
    (workspace / ".mcp.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )


__all__ = ["stage_workspace"]
