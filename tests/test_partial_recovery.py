"""An interrupted run salvages partial results from the evidence store.

When the agent never writes a valid ``final.json`` (e.g. a turn is refused
mid-stream by the model provider), the orchestrator must not discard the whole
run. ``recover_partial_final`` rebuilds a ``partial`` final output from the
evidence-store files the MCP already persisted, shaped to
``schemas/final_output.schema.json`` so the normal report path renders it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator.report import recover_partial_final, validate_final_output


def _seed_store(run_dir: Path) -> None:
    es = run_dir / "evidence_store"
    es.mkdir(parents=True)
    (es / "findings.json").write_text(
        json.dumps(
            {
                "F1": {
                    "id": "F1",
                    "title": "Default credentials accepted on /login",
                    "severity": "high",
                    "location": "https://target.example/login",
                    "summary": "The login form accepted a documented default account.",
                    "cwe": "CWE-521",
                    "reproduction": "",
                    "evidence": [],
                }
            }
        ),
        encoding="utf-8",
    )
    (es / "coverage.json").write_text(
        json.dumps(
            {
                "C1": {
                    "area": "authentication",
                    "state": "partial",
                    "reason": "run interrupted before completion",
                    "created_at": "2026-01-01 00:00:00 UTC",
                }
            }
        ),
        encoding="utf-8",
    )


def test_recovers_partial_from_evidence_store(tmp_path: Path) -> None:
    _seed_store(tmp_path)
    out = recover_partial_final(
        tmp_path,
        targets=["https://target.example"],
        phases_completed=["recon", "auth"],
        notes="interrupted",
    )
    assert out is not None
    # Must be schema-valid on its own so generate_reports accepts it unchanged.
    validate_final_output(out)
    assert out["status"] == "partial"
    assert out["scope"]["targets"] == ["https://target.example"]
    assert out["scope"]["notes"] == "interrupted"
    assert out["stats"]["phases_completed"] == ["recon", "auth"]
    assert [f["id"] for f in out["findings"]] == ["F1"]
    assert out["coverage"][0]["area"] == "authentication"


def test_no_evidence_returns_none(tmp_path: Path) -> None:
    # No evidence_store directory at all -> nothing to salvage.
    assert recover_partial_final(tmp_path, targets=["https://target.example"]) is None
