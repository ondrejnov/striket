# evidence_store (MCP)

A small stdio MCP server that replaces Strix's `notes`, `coverage`, `threat_model`,
`reporting` and `output_store` tools with one run-scoped store. It persists the agent's
working record and exports `coverage` / `findings` fragments that validate against
`schemas/final_output.schema.json`.

It stores records the runtime agent supplies. It ships no payloads or exploits, makes no
network or target access, and never holds credentials — do not put secrets in notes or
evidence. Scope validation is the orchestrator's job (`orchestrator/scope.py`) and happens
before the agent starts.

## Running

Pure standard library (Python 3.12+), newline-delimited JSON-RPC 2.0 over stdio. Run it by
path from the repo root — the repo's `mcp/` directory shares its name with the third-party
`mcp` SDK, so avoid `-m mcp.evidence_store`:

```
python3 mcp/evidence_store --run-dir <run_dir>      # or: STRIKET_RUN_DIR=<run_dir>
```

State is written to `<run_dir>/evidence_store/` (`notes.json`, `coverage.json`,
`threat_models.json`, `evidence.json`, `findings.json`). Writes take an exclusive file lock
and replace files atomically, so several agent processes can share one run directory, and a
resumed run picks up where the last one stopped.

Example `.mcp.json` entry for the harness (the orchestrator fills in the run directory):

```json
{
  "mcpServers": {
    "evidence_store": {
      "command": "python3",
      "args": ["mcp/evidence_store", "--run-dir", "<run_dir>"]
    }
  }
}
```

## Tools

| Tool | Purpose |
|---|---|
| `add_note` / `list_notes` / `get_note` | Working notes with category, tags, text search. `list_notes` omits content unless `include_content`. |
| `set_coverage` | Upsert the row for an `area` with `state` = `tested` \| `partial` \| `skipped`. `reason` is required for `partial` and `skipped`. Earlier states are kept as history. |
| `get_coverage` | Rows (all, one `area`, or by `state`) plus per-state counts. |
| `coverage_status` | Coverage tracking view: counts, areas still `partial`/`skipped`, findings with no matching coverage row, `fully_tested`. Check before finishing. |
| `store_threat_model` / `get_threat_model` | Markdown threat model per target; replaced versions are retained as revisions. |
| `add_evidence` / `get_evidence` | Store an artifact (`http` \| `code` \| `log` \| `screenshot`, capped at 256k chars) and get a ref like `evidence:E-0001`. For `http`, `content` is one raw request/response pair (see below). |
| `add_finding` / `update_finding` | File or revise a finding. Fields match the schema (`title`, `severity`, `cwe`, `location`, `summary`, `evidence[{type,ref}]`, `reproduction`, `remediation`); `id` is auto-assigned (`F-001`…). Evidence refs must exist; duplicates (same title and location) are rejected; `cwe` is normalized to `CWE-n`. Optional `area` links the finding to its coverage row. |
| `list_findings` / `get_finding` | Findings, most severe first (optionally by `severity`), or one in full. |
| `export_final_parts` | `{coverage, findings}` in exact `final_output.schema.json` shape (internal fields stripped), ready to drop into the final structured output. |

Tool failures return `isError: true` with an `error` message; they never crash the server.

## HTTP evidence (black-box runs)

`http` is a first-class evidence type (no schema or store change is needed for it). The
store does not parse `content`, so a request/response pair is stored as one free-text
string using this canonical convention, so pairs stay machine- and human-readable:

```
=== REQUEST ===
<METHOD> <path> HTTP/x.y
<request headers, one per line>
<blank line>
<request body, if any>

=== RESPONSE ===
HTTP/x.y <status> <reason>
<response headers, one per line>
<blank line>
<response body, if any (truncate large bodies, note the truncation)>
```

Put a one-line human label in `description` (e.g. `POST /api/orders/42 — IDOR: user A reads
user B's order`). The pair is in-session runtime evidence: never store credentials, secrets,
or reusable exploit strings. A finding cites it like any other ref:
`evidence=[{"type": "http", "ref": "evidence:E-0001"}]`.

## Mapping to the final output schema

- Coverage row `{area, state, reason}` ↔ `coverage[]` item; states are identical.
- Finding fields ↔ `findings[]` items; `evidence[].ref` points at `add_evidence` records.
- `scope` and `stats` are not stored here — the orchestrator and the final assembling step
  provide them.
