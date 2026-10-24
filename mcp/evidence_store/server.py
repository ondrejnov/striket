"""Stdio MCP server exposing :class:`~.store.EvidenceStore`.

Speaks newline-delimited JSON-RPC 2.0 (the MCP stdio transport) using only the
standard library, so it runs wherever the orchestrator does without the ``mcp`` SDK.
stdout carries protocol messages only; diagnostics go to stderr.

The run directory comes from ``--run-dir`` or ``STRIKET_RUN_DIR``; the store is
created beneath it as ``evidence_store/``. Nothing is hardcoded.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from typing import Any, TextIO

from .store import COVERAGE_STATES, EVIDENCE_TYPES, SEVERITIES, EvidenceStore, StoreError

SERVER_NAME = "striket-evidence-store"
SERVER_VERSION = "0.1.0"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
RUN_DIR_ENV = "STRIKET_RUN_DIR"

_STR = {"type": "string"}


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


_EVIDENCE_ITEM = _obj(
    {"type": {"type": "string", "enum": list(EVIDENCE_TYPES)}, "ref": _STR}, ["type", "ref"]
)
_FINDING_FIELDS: dict[str, Any] = {
    "title": _STR,
    "severity": {"type": "string", "enum": list(SEVERITIES)},
    "cwe": {"type": ["string", "null"], "description": "e.g. CWE-89, or null"},
    "location": {"type": "string", "description": "file:line, URL, or endpoint"},
    "summary": {"type": "string", "description": "What is vulnerable and why"},
    "evidence": {
        "type": "array",
        "description": 'Array of objects, e.g. [{"type": "code", "ref": "evidence:E-0001"}]; '
        "ref must come from add_evidence",
        "items": _EVIDENCE_ITEM,
    },
    "reproduction": {"type": "string", "description": "Verification steps, strictly in-scope"},
    "remediation": _STR,
    "area": {
        "type": "string",
        "description": "Coverage area this finding came from (same string as set_coverage); "
        "this is how findings are linked to coverage rows",
    },
}


def _tool(name: str, description: str, schema: dict[str, Any], fn: Callable[..., Any]) -> tuple[str, dict[str, Any], Callable[..., Any]]:
    return name, {"name": name, "description": description, "inputSchema": schema}, fn


def build_tools(store: EvidenceStore) -> dict[str, tuple[dict[str, Any], Callable[..., Any]]]:
    specs = [
        _tool(
            "add_note",
            "Record a working note (observation, hypothesis, to-do) for the run.",
            _obj(
                {
                    "title": _STR,
                    "content": _STR,
                    "category": _STR,
                    "tags": {
                        "type": "array",
                        "items": _STR,
                        "description": 'JSON array, e.g. ["oauth", "jwt"]; not a comma-separated string',
                    },
                    "agent": _STR,
                },
                ["title", "content"],
            ),
            store.add_note,
        ),
        _tool(
            "list_notes",
            "List notes, optionally filtered by category, tags or text search.",
            _obj(
                {
                    "category": _STR,
                    "tags": {"type": "array", "items": _STR},
                    "search": _STR,
                    "include_content": {"type": "boolean"},
                }
            ),
            store.list_notes,
        ),
        _tool("get_note", "Fetch one note by its note_id (argument is `note_id`, not `id`).", _obj({"note_id": _STR}, ["note_id"]), store.get_note),
        _tool(
            "set_coverage",
            "Create or update the coverage row for an area. States: "
            + ", ".join(COVERAGE_STATES)
            + ". A reason is required for partial and skipped; prior states are kept as history. "
            "Findings are linked by passing `area` to add_finding; there is no finding_ids argument.",
            _obj(
                {
                    "area": {"type": "string", "description": "Component, route, file or risk class"},
                    "state": {"type": "string", "enum": list(COVERAGE_STATES)},
                    "reason": _STR,
                    "agent": _STR,
                },
                ["area", "state"],
            ),
            store.set_coverage,
        ),
        _tool(
            "get_coverage",
            "Get coverage rows (all, one area, or filtered by state) with per-state counts.",
            _obj({"area": _STR, "state": {"type": "string", "enum": list(COVERAGE_STATES)}}),
            store.get_coverage,
        ),
        _tool(
            "coverage_status",
            "Coverage tracking view: state counts, areas still partial/skipped, and findings "
            "not attributable to a coverage row. Check before finishing.",
            _obj({}),
            store.coverage_status,
        ),
        _tool(
            "store_threat_model",
            "Save the threat model (markdown) for a target; a replaced version is kept as a revision.",
            _obj({"target": _STR, "content": _STR, "agent": _STR}, ["target", "content"]),
            store.store_threat_model,
        ),
        _tool(
            "get_threat_model",
            "Get the threat model for a target, or list stored models when target is omitted.",
            _obj({"target": _STR}),
            store.get_threat_model,
        ),
        _tool(
            "add_evidence",
            "Store an evidence artifact (http|code|log|screenshot) and get a ref to cite in findings. "
            "No title/location arguments: use `description`, and put file:line into `content`.",
            _obj(
                {
                    "type": {"type": "string", "enum": list(EVIDENCE_TYPES)},
                    "content": {"type": "string", "description": "Excerpt, transcript or file path"},
                    "description": _STR,
                    "agent": _STR,
                },
                ["type", "content"],
            ),
            store.add_evidence,
        ),
        _tool("get_evidence", "Fetch an evidence artifact by ref.", _obj({"ref": _STR}, ["ref"]), store.get_evidence),
        _tool(
            "add_finding",
            "File a finding. Fields match schemas/final_output.schema.json. Omit `id`: one is "
            "assigned and returned (self-chosen ids collide with other agents). There are no "
            "confidence/counterevidence/status fields; put those into `summary`. "
            "Duplicates (same title and location) are rejected.",
            _obj({**_FINDING_FIELDS, "id": _STR, "agent": _STR}, ["title", "severity", "location", "summary"]),
            store.add_finding,
        ),
        _tool(
            "update_finding",
            "Revise fields of an existing finding by id.",
            _obj({"id": _STR, **_FINDING_FIELDS}, ["id"]),
            store.update_finding,
        ),
        _tool(
            "list_findings",
            "List findings (most severe first), optionally filtered by severity.",
            _obj({"severity": {"type": "string", "enum": list(SEVERITIES)}}),
            store.list_findings,
        ),
        _tool("get_finding", "Fetch one finding in full by `id` as returned by add_finding/list_findings; do not guess ids.", _obj({"id": _STR}, ["id"]), store.get_finding),
        _tool(
            "export_final_parts",
            "Return the `coverage` and `findings` arrays in final_output.schema.json shape, "
            "ready to copy into the final structured output.",
            _obj({}),
            store.export_final_parts,
        ),
    ]
    return {name: (spec, fn) for name, spec, fn in specs}


class McpServer:
    def __init__(self, store: EvidenceStore) -> None:
        self.tools = build_tools(store)

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Process one JSON-RPC message; return a response, or None for notifications."""
        method = message.get("method")
        msg_id = message.get("id")
        is_notification = "id" not in message
        params = message.get("params") or {}
        try:
            if method == "initialize":
                requested = params.get("protocolVersion")
                version = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
                result: Any = {
                    "protocolVersion": version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [spec for spec, _ in self.tools.values()]}
            elif method == "tools/call":
                result = self._call(params)
            elif is_notification:
                return None
            else:
                return self._error(msg_id, -32601, f"Method not found: {method}")
        except (TypeError, AttributeError) as exc:
            return None if is_notification else self._error(msg_id, -32602, f"Invalid params: {exc}")
        return None if is_notification else {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        entry = self.tools.get(name) if isinstance(name, str) else None
        if entry is None:
            return self._tool_result({"error": f"Unknown tool {name!r}"}, is_error=True)
        spec, fn = entry
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return self._tool_result({"error": "arguments must be an object"}, is_error=True)
        allowed = set(spec["inputSchema"]["properties"])
        unknown = sorted(set(arguments) - allowed)
        if unknown:
            return self._tool_result(
                {"error": f"Unknown argument(s) {unknown}; allowed: {sorted(allowed)}"}, is_error=True
            )
        try:
            return self._tool_result(fn(**arguments))
        except StoreError as exc:
            return self._tool_result({"error": str(exc)}, is_error=True)
        except TypeError as exc:
            return self._tool_result({"error": f"Bad arguments: {exc}"}, is_error=True)
        except OSError as exc:
            return self._tool_result({"error": f"Store I/O failure: {exc}"}, is_error=True)

    @staticmethod
    def _tool_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
        return {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
            "isError": is_error,
        }

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

    def serve(self, stdin: TextIO, stdout: TextIO) -> None:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                response: dict[str, Any] | None = self._error(None, -32700, "Parse error")
            else:
                if isinstance(message, dict):
                    response = self.handle(message)
                else:
                    response = self._error(None, -32600, "Invalid Request")
            if response is not None:
                stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="evidence_store", description="Striket evidence_store MCP server (stdio)."
    )
    parser.add_argument(
        "--run-dir",
        default=os.environ.get(RUN_DIR_ENV),
        help=f"Run directory; the store lives in <run-dir>/evidence_store (env: {RUN_DIR_ENV})",
    )
    args = parser.parse_args(argv)
    if not args.run_dir:
        print(f"error: --run-dir or {RUN_DIR_ENV} is required", file=sys.stderr)
        return 2
    try:
        store = EvidenceStore(args.run_dir)
    except OSError as exc:
        print(f"error: cannot open store: {exc}", file=sys.stderr)
        return 1
    McpServer(store).serve(sys.stdin, sys.stdout)
    return 0

