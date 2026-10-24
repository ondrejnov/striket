"""M3 acceptance: an HTTP request/response pair is first-class evidence.

Proves the black-box capture path end-to-end without any network access or
embedded exploit: a raw request/response pair is stored as ``http`` evidence,
cited by a finding, and carried through ``export_final_parts`` in the exact
``schemas/final_output.schema.json`` shape — both via the :class:`EvidenceStore`
API and over the MCP ``tools/call`` wire path through :class:`McpServer`.

The ``http`` evidence type needs no store or schema change to be first-class
(it is already in ``EVIDENCE_TYPES`` and the schema's ``evidence[].type`` enum);
this test guards that it stays that way.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "http_exchange.txt"
SCHEMA = ROOT / "schemas" / "final_output.schema.json"

# The repo's ``mcp/`` directory shares its name with the third-party ``mcp`` SDK,
# so load the package by path under a private name (as mcp/evidence_store/__main__
# does) rather than ``import mcp.evidence_store``.
_PACKAGE = "striket_evidence_store"


def _load_package() -> None:
    if _PACKAGE in sys.modules:
        return
    here = ROOT / "mcp" / "evidence_store"
    spec = importlib.util.spec_from_file_location(
        _PACKAGE, here / "__init__.py", submodule_search_locations=[str(here)]
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_PACKAGE] = module
    spec.loader.exec_module(module)


_load_package()
from striket_evidence_store.server import McpServer  # noqa: E402
from striket_evidence_store.store import (  # noqa: E402
    EVIDENCE_TYPES,
    EvidenceStore,
    StoreError,
)


@pytest.fixture
def exchange() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def store(tmp_path: Path) -> EvidenceStore:
    return EvidenceStore(tmp_path)


def test_http_is_a_first_class_evidence_type() -> None:
    """The contract: 'http' is already legal at the store and schema layers."""
    assert "http" in EVIDENCE_TYPES
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    evidence_type = schema["properties"]["findings"]["items"]["properties"]["evidence"][
        "items"
    ]["properties"]["type"]
    assert "http" in evidence_type["enum"]


def test_store_http_evidence_and_cite_it(store: EvidenceStore, exchange: str) -> None:
    result = store.add_evidence(
        type="http",
        content=exchange,
        description="GET /api/orders/42 — IDOR: user A reads user B's order",
        agent="web-tester",
    )
    assert result == {"ref": "evidence:E-0001", "type": "http", "truncated": False}

    stored = store.get_evidence(result["ref"])
    assert stored["type"] == "http"
    assert "=== REQUEST ===" in stored["content"]
    assert "=== RESPONSE ===" in stored["content"]

    finding = store.add_finding(
        title="IDOR on order lookup",
        severity="high",
        location="https://app.example.test/api/orders/{id}",
        summary="Any authenticated user can read another user's order by id.",
        cwe="CWE-639",
        evidence=[{"type": "http", "ref": result["ref"]}],
    )
    assert finding["id"] == "F-001"

    exported = store.export_final_parts()
    (exported_finding,) = exported["findings"]
    assert exported_finding["evidence"] == [{"type": "http", "ref": "evidence:E-0001"}]


def test_add_finding_rejects_unknown_http_ref(store: EvidenceStore) -> None:
    with pytest.raises(StoreError, match="Unknown evidence ref"):
        store.add_finding(
            title="IDOR on order lookup",
            severity="high",
            location="https://app.example.test/api/orders/{id}",
            summary="cites evidence that was never stored",
            evidence=[{"type": "http", "ref": "evidence:E-0001"}],
        )


def test_large_http_body_is_truncated(store: EvidenceStore) -> None:
    from striket_evidence_store.store import MAX_EVIDENCE_CHARS

    big = "=== REQUEST ===\nGET / HTTP/1.1\n\n=== RESPONSE ===\n" + ("A" * (MAX_EVIDENCE_CHARS + 10))
    result = store.add_evidence(type="http", content=big)
    assert result["truncated"] is True
    assert len(store.get_evidence(result["ref"])["content"]) == MAX_EVIDENCE_CHARS


def _call(server: McpServer, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    response = server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": name, "arguments": arguments}}
    )
    assert response is not None
    result = response["result"]
    payload = json.loads(result["content"][0]["text"])
    return {"payload": payload, "isError": result["isError"]}


def test_http_evidence_over_the_mcp_wire(tmp_path: Path, exchange: str) -> None:
    """Drive the same path through tools/call to prove the MCP wire carries http."""
    server = McpServer(EvidenceStore(tmp_path))

    added = _call(server, "add_evidence", {
        "type": "http",
        "content": exchange,
        "description": "GET /api/orders/42 — IDOR evidence",
    })
    assert added["isError"] is False
    ref = added["payload"]["ref"]
    assert ref == "evidence:E-0001"
    assert added["payload"]["type"] == "http"

    filed = _call(server, "add_finding", {
        "title": "IDOR on order lookup",
        "severity": "high",
        "location": "https://app.example.test/api/orders/{id}",
        "summary": "Any authenticated user can read another user's order by id.",
        "evidence": [{"type": "http", "ref": ref}],
    })
    assert filed["isError"] is False

    exported = _call(server, "export_final_parts", {})
    assert exported["isError"] is False
    (finding,) = exported["payload"]["findings"]
    assert finding["evidence"] == [{"type": "http", "ref": ref}]


def test_exported_http_finding_validates_against_schema(
    store: EvidenceStore, exchange: str
) -> None:
    """The exported finding with http evidence validates as a full final output."""
    jsonschema = pytest.importorskip("jsonschema")

    ref = store.add_evidence(type="http", content=exchange)["ref"]
    store.set_coverage("order access control", "tested")
    store.add_finding(
        title="IDOR on order lookup",
        severity="high",
        location="https://app.example.test/api/orders/{id}",
        summary="Any authenticated user can read another user's order by id.",
        cwe="CWE-639",
        evidence=[{"type": "http", "ref": ref}],
        area="order access control",
    )
    parts = store.export_final_parts()

    final_output = {
        "status": "completed",
        "scope": {"targets": ["https://app.example.test"]},
        "coverage": parts["coverage"],
        "findings": parts["findings"],
        "stats": {"phases_completed": ["recon", "testing", "reporting"]},
    }
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(instance=final_output, schema=schema)

    assert final_output["findings"][0]["evidence"] == [
        {"type": "http", "ref": "evidence:E-0001"}
    ]
