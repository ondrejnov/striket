import json
from pathlib import Path

import pytest

from orchestrator import workspace


def test_mcp_config_points_store_at_run_dir(tmp_path: Path) -> None:
    if not workspace._EVIDENCE_STORE.exists():
        pytest.skip("evidence_store MCP not bundled")
    run_dir = tmp_path / "run"
    ws = workspace.stage_workspace(run_dir)
    config = json.loads((ws / ".mcp.json").read_text(encoding="utf-8"))
    args = config["mcpServers"]["evidence_store"]["args"]
    # The server appends "evidence_store" itself; passing the nested dir would
    # write to <run>/evidence_store/evidence_store/, which the TUI never sees.
    assert args[args.index("--run-dir") + 1] == str(run_dir)
