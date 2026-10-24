"""Turn the agent's schema-validated ``final.json`` into deterministic artifacts.

Produces three files in the run directory, with fields and structure aligned to
Strix (``strix/report/``) so artifacts are interchangeable:

* ``penetration_test_report.md`` — human-readable executive report.
* ``vulnerabilities.json`` — the findings as Strix-shaped vulnerability records.
* ``findings.sarif`` — SARIF 2.1.0, one run, each finding a result with
  ``ruleId`` / ``level`` / ``locations``.

The final output is validated against ``schemas/final_output.schema.json``
before any artifact is written; findings come only from that validated object,
never from free text. This module hardcodes no payloads or exploits.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .resources import schema_path as _schema_path

# --- Schema validation ------------------------------------------------------

_SCHEMA_PATH = _schema_path()


class FinalOutputError(ValueError):
    """Raised when ``final.json`` is missing, unreadable, or schema-invalid."""


def load_schema(schema_path: Path | None = None) -> dict[str, Any]:
    path = schema_path or _SCHEMA_PATH
    return json.loads(path.read_text(encoding="utf-8"))


def validate_final_output(data: Any, *, schema_path: Path | None = None) -> dict[str, Any]:
    """Validate ``data`` against the final-output schema.

    Uses ``jsonschema`` when installed (full draft 2020-12 validation); falls
    back to a minimal structural check otherwise so the orchestrator still
    refuses obviously malformed output without a hard dependency at import time.
    """
    if not isinstance(data, dict):
        raise FinalOutputError("final output is not a JSON object")

    schema = load_schema(schema_path)
    try:
        import jsonschema  # type: ignore[import-untyped]
    except ImportError:
        _minimal_validate(data)
        return data

    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:  # type: ignore[attr-defined]
        raise FinalOutputError(f"final output failed schema validation: {exc.message}") from exc
    return data


_VALID_STATUS = {"completed", "partial", "failed"}
_VALID_SEVERITY = {"info", "low", "medium", "high", "critical"}
#: Rank for sorting findings most-severe first during partial recovery.
_VALID_SEVERITY_ORDER = {s: i for i, s in enumerate(("info", "low", "medium", "high", "critical"))}


def _minimal_validate(data: dict[str, Any]) -> None:
    status = data.get("status")
    if status not in _VALID_STATUS:
        raise FinalOutputError(f"invalid status: {status!r}")
    scope = data.get("scope")
    if not isinstance(scope, dict) or not isinstance(scope.get("targets"), list):
        raise FinalOutputError("scope.targets missing or not a list")
    findings = data.get("findings")
    if not isinstance(findings, list):
        raise FinalOutputError("findings missing or not a list")
    for finding in findings:
        if not isinstance(finding, dict):
            raise FinalOutputError("a finding is not an object")
        for required in ("id", "title", "severity", "location", "summary"):
            if not finding.get(required):
                raise FinalOutputError(f"finding missing required field: {required}")
        if finding["severity"] not in _VALID_SEVERITY:
            raise FinalOutputError(f"invalid finding severity: {finding['severity']!r}")
    if not isinstance(data.get("coverage", []), list):
        raise FinalOutputError("coverage is not a list")
    if not isinstance(data.get("stats", {}), dict):
        raise FinalOutputError("stats is not an object")


def read_final_output(path: Path, *, schema_path: Path | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise FinalOutputError(f"final output not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FinalOutputError(f"final output unreadable: {exc}") from exc
    return validate_final_output(data, schema_path=schema_path)


# --- Partial recovery from the evidence store -------------------------------

#: Finding fields that belong in final_output.schema.json (additionalProperties: false),
#: mirroring evidence_store.store.FINDING_SCHEMA_FIELDS. Kept here so recovery has no
#: import dependency on the MCP tree (which is not an installed package).
_FINDING_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "severity",
    "cwe",
    "location",
    "summary",
    "evidence",
    "reproduction",
    "remediation",
)


def _read_store_file(run_dir: Path, name: str) -> dict[str, Any]:
    path = run_dir / "evidence_store" / f"{name}.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def recover_partial_final(
    run_dir: Path,
    *,
    targets: list[str],
    phases_completed: list[str] | None = None,
    notes: str | None = None,
    schema_path: Path | None = None,
) -> dict[str, Any] | None:
    """Reconstruct a ``partial`` final output from the run's evidence store.

    Used when the agent never wrote a valid ``final.json`` (e.g. the run was
    interrupted mid-turn) so work already recorded in the evidence store is not
    thrown away. Reads ``<run_dir>/evidence_store/{findings,coverage}.json`` —
    the same files the evidence_store MCP persists — and shapes them to
    ``final_output.schema.json``.

    Returns ``None`` when the store holds nothing to salvage.
    """
    raw_findings = _read_store_file(run_dir, "findings")
    raw_coverage = _read_store_file(run_dir, "coverage")
    if not raw_findings and not raw_coverage:
        return None

    coverage: list[dict[str, Any]] = []
    for row in sorted(
        raw_coverage.values(), key=lambda r: r.get("created_at", "")
    ):
        if not isinstance(row, dict) or "area" not in row or "state" not in row:
            continue
        item = {"area": row["area"], "state": row["state"]}
        if row.get("reason"):
            item["reason"] = row["reason"]
        coverage.append(item)

    findings: list[dict[str, Any]] = []
    for finding in raw_findings.values():
        if not isinstance(finding, dict):
            continue
        item = {k: finding[k] for k in _FINDING_FIELDS if k in finding}
        for optional in ("reproduction", "remediation", "evidence"):
            if not item.get(optional):
                item.pop(optional, None)
        findings.append(item)
    findings.sort(key=lambda f: (-_VALID_SEVERITY_ORDER.get(f.get("severity", ""), 0), f.get("id", "")))

    data: dict[str, Any] = {
        "status": "partial",
        "scope": {"targets": list(targets)},
        "coverage": coverage,
        "findings": findings,
        "stats": {"phases_completed": list(phases_completed or [])},
    }
    if notes:
        data["scope"]["notes"] = notes
    return validate_final_output(data, schema_path=schema_path)


# --- final.json finding -> Strix-shaped vulnerability record ----------------

_LOCATION_RE = re.compile(r"^(?P<file>.+?):(?P<start>\d+)(?:-(?P<end>\d+))?$")


def _parse_location(location: str) -> dict[str, Any]:
    """Split a ``file:line`` location into a code_locations entry.

    Returns ``{}`` for URL/endpoint-style locations, which are carried as the
    finding ``endpoint`` instead of a physical code location.
    """
    match = _LOCATION_RE.match(location.strip())
    if not match:
        return {}
    file_part = match.group("file")
    # A scheme-qualified location (http://...:443) is not a file:line.
    if "://" in location or file_part.lower() in {"http", "https"}:
        return {}
    entry: dict[str, Any] = {"file": file_part, "start_line": int(match.group("start"))}
    if match.group("end"):
        entry["end_line"] = int(match.group("end"))
    return entry


def _render_evidence(evidence: Any) -> str:
    if not isinstance(evidence, list) or not evidence:
        return ""
    lines = []
    for item in evidence:
        if isinstance(item, dict):
            lines.append(f"- [{item.get('type', 'evidence')}] {item.get('ref', '')}".rstrip())
    return "\n".join(lines)


def finding_to_vuln(finding: dict[str, Any], *, timestamp: str) -> dict[str, Any]:
    """Map a final-output finding to a Strix-shaped vulnerability record."""
    location = str(finding.get("location") or "")
    code_loc = _parse_location(location)
    is_code = bool(code_loc)

    vuln: dict[str, Any] = {
        "id": finding["id"],
        "title": finding["title"],
        "severity": finding["severity"],
        "timestamp": timestamp,
        "cwe": finding.get("cwe"),
        "description": finding.get("summary", ""),
        "remediation_steps": finding.get("remediation", ""),
        "poc_description": finding.get("reproduction", ""),
        "evidence": _render_evidence(finding.get("evidence")),
        "location": location,
    }
    if is_code:
        vuln["code_locations"] = [code_loc]
    elif location:
        vuln["endpoint"] = location
        vuln["target"] = location
    return vuln


# --- SARIF 2.1.0 (structure aligned with strix/report/sarif.py) -------------

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
SARIF_VERSION = "2.1.0"
TOOL_NAME = "Striket"
TOOL_INFORMATION_URI = "https://striket.dev"

_SEVERITY_TO_LEVEL = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "note",
    "info": "note",
}
_SEVERITY_TO_SCORE = {
    "critical": "9.5",
    "high": "8.0",
    "medium": "5.5",
    "low": "3.0",
    "info": "1.0",
}
_SYNTHETIC_LOCATION_URI = "SECURITY.md"


def _string_value(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _slugify(value: str) -> str:
    chars = [char.lower() if char.isalnum() else "-" for char in value]
    slug = "-".join(part for part in "".join(chars).split("-") if part)
    return slug or "striket-finding"


def _normalise_cwe(value: str) -> str | None:
    digits = "".join(c for c in value if c.isdigit())
    return f"CWE-{digits}" if digits else None


def _rule_id(report: dict[str, Any]) -> str:
    cwe = _string_value(report.get("cwe"))
    if cwe:
        normalised = _normalise_cwe(cwe)
        if normalised:
            return normalised
    finding_id = _string_value(report.get("id"))
    if finding_id:
        return finding_id
    title = _string_value(report.get("title")) or "striket-finding"
    return _slugify(title)


def _sarif_level(severity: Any) -> str:
    return _SEVERITY_TO_LEVEL.get((_string_value(severity) or "").lower(), "note")


def _security_severity(report: dict[str, Any]) -> str:
    return _SEVERITY_TO_SCORE.get((_string_value(report.get("severity")) or "info").lower(), "1.0")


def _sarif_uri(file_path: str) -> str | None:
    """Return a safe repo-relative POSIX URI, or None for unsafe paths."""
    from pathlib import PurePosixPath

    uri = PurePosixPath(file_path.replace("\\", "/")).as_posix()
    parts = PurePosixPath(uri).parts
    if not uri or uri.startswith("/") or not parts:
        return None
    if ":" in parts[0] or any(part == ".." for part in parts):
        return None
    return uri


def _build_physical_locations(raw_locations: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_locations, list):
        return []
    out: list[dict[str, Any]] = []
    for location in raw_locations:
        if not isinstance(location, dict):
            continue
        file_path = _string_value(location.get("file"))
        start_line = location.get("start_line")
        if not file_path or type(start_line) is not int or start_line < 1:
            continue
        uri = _sarif_uri(file_path)
        if uri is None:
            continue
        region: dict[str, Any] = {"startLine": start_line}
        end_line = location.get("end_line")
        if type(end_line) is int and end_line >= start_line:
            region["endLine"] = end_line
        out.append(
            {"physicalLocation": {"artifactLocation": {"uri": uri}, "region": region}}
        )
    return out


def _build_locations(report: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    physical = _build_physical_locations(report.get("code_locations"))
    is_synthetic = not physical
    locations: list[dict[str, Any]] = list(physical) if physical else [
        {"physicalLocation": {"artifactLocation": {"uri": _SYNTHETIC_LOCATION_URI}}}
    ]
    endpoint = _string_value(report.get("endpoint"))
    if endpoint:
        locations.append(
            {"logicalLocations": [{"fullyQualifiedName": endpoint, "kind": "endpoint"}]}
        )
    elif is_synthetic:
        resource = _string_value(report.get("target")) or _string_value(report.get("title"))
        if resource:
            locations.append(
                {"logicalLocations": [{"fullyQualifiedName": resource, "kind": "resource"}]}
            )
    return locations, is_synthetic


def _build_rule(rule_id: str, report: dict[str, Any]) -> dict[str, Any]:
    title = _string_value(report.get("title")) or rule_id
    full_description = _string_value(report.get("description")) or title
    help_sections = [
        _string_value(report.get("description")),
        _string_value(report.get("remediation_steps")),
    ]
    help_text = "\n\n".join(s for s in help_sections if s) or full_description
    rule: dict[str, Any] = {
        "id": rule_id,
        "name": _rule_id_name(rule_id, title),
        "shortDescription": {"text": title},
        "fullDescription": {"text": full_description},
        "defaultConfiguration": {"level": _sarif_level(report.get("severity"))},
        "help": {"text": help_text, "markdown": help_text},
        "properties": {"security-severity": _security_severity(report)},
    }
    if rule_id.startswith("CWE-"):
        rule["helpUri"] = f"https://cwe.mitre.org/data/definitions/{rule_id[4:]}.html"
    return rule


def _rule_id_name(rule_id: str, title: str) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "", title.title()) or "Finding"
    return f"{rule_id}/{base}" if rule_id.startswith("CWE-") else base


def _build_result(
    rule_id: str, rule_index: int, report: dict[str, Any], locations: list[dict[str, Any]],
    *, is_synthetic: bool,
) -> dict[str, Any]:
    title = _string_value(report.get("title")) or rule_id
    description = _string_value(report.get("description"))
    message_text = f"{title}\n\n{description}" if description else title
    result: dict[str, Any] = {
        "ruleId": rule_id,
        "ruleIndex": rule_index,
        "level": _sarif_level(report.get("severity")),
        "message": {"text": message_text},
    }
    if locations:
        result["locations"] = locations
    properties: dict[str, Any] = {"security-severity": _security_severity(report)}
    if is_synthetic:
        properties["synthetic_location"] = True
    properties["striket"] = {
        key: report[key]
        for key in ("id", "severity", "cwe", "timestamp")
        if report.get(key) is not None
    }
    result["properties"] = properties
    return result


def build_sarif_report(vulnerability_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a SARIF 2.1.0 document (one run) for the findings."""
    rules_by_id: dict[str, dict[str, Any]] = {}
    rule_index_by_id: dict[str, int] = {}
    results: list[dict[str, Any]] = []

    for report in vulnerability_reports:
        locations, is_synthetic = _build_locations(report)
        rule_id = _rule_id(report)
        if rule_id not in rules_by_id:
            rule_index_by_id[rule_id] = len(rules_by_id)
            rules_by_id[rule_id] = _build_rule(rule_id, report)
        results.append(
            _build_result(
                rule_id, rule_index_by_id[rule_id], report, locations,
                is_synthetic=is_synthetic,
            )
        )

    run: dict[str, Any] = {
        "tool": {
            "driver": {
                "name": TOOL_NAME,
                "informationUri": TOOL_INFORMATION_URI,
                "rules": list(rules_by_id.values()),
            }
        },
        "results": results,
    }
    return {"version": SARIF_VERSION, "$schema": SARIF_SCHEMA, "runs": [run]}


# --- Markdown executive report ---------------------------------------------

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _render_markdown(final: dict[str, Any], vulns: list[dict[str, Any]]) -> str:
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "# Security Penetration Test Report",
        "",
        f"**Generated:** {generated}",
        f"**Status:** {final.get('status', 'unknown')}",
        "",
    ]

    scope = final.get("scope") or {}
    targets = scope.get("targets") or []
    lines.append("## Scope")
    lines.append("")
    for target in targets:
        lines.append(f"- {target}")
    if scope.get("notes"):
        lines += ["", scope["notes"]]
    lines.append("")

    counts: dict[str, int] = {}
    for vuln in vulns:
        counts[vuln["severity"]] = counts.get(vuln["severity"], 0) + 1
    lines.append("## Summary")
    lines.append("")
    if vulns:
        order = sorted(counts, key=lambda s: _SEVERITY_ORDER.get(s, 5))
        lines.append(
            "Findings: " + ", ".join(f"{counts[s]} {s}" for s in order)
        )
    else:
        lines.append("No findings reported.")
    lines.append("")

    coverage = final.get("coverage") or []
    if coverage:
        lines += ["## Coverage", ""]
        for row in coverage:
            reason = f" — {row['reason']}" if row.get("reason") else ""
            lines.append(f"- **{row.get('area', '?')}**: {row.get('state', '?')}{reason}")
        lines.append("")

    lines += ["## Findings", ""]
    if not vulns:
        lines += ["None.", ""]
    for vuln in sorted(vulns, key=lambda v: _SEVERITY_ORDER.get(v["severity"], 5)):
        lines.append(f"### {vuln['title']}")
        lines.append("")
        lines.append(f"**ID:** {vuln['id']}")
        lines.append(f"**Severity:** {vuln['severity'].upper()}")
        if vuln.get("cwe"):
            lines.append(f"**CWE:** {vuln['cwe']}")
        if vuln.get("location"):
            lines.append(f"**Location:** `{vuln['location']}`")
        lines.append("")
        if vuln.get("description"):
            lines += ["#### Description", "", vuln["description"], ""]
        if vuln.get("evidence"):
            lines += ["#### Evidence", "", vuln["evidence"], ""]
        if vuln.get("poc_description"):
            lines += ["#### Reproduction", "", vuln["poc_description"], ""]
        if vuln.get("remediation_steps"):
            lines += ["#### Remediation", "", vuln["remediation_steps"], ""]

    stats = final.get("stats") or {}
    lines += ["## Run Statistics", ""]
    if stats.get("duration_s") is not None:
        lines.append(f"- Duration: {stats['duration_s']}s")
    phases = stats.get("phases_completed") or []
    if phases:
        lines.append(f"- Phases completed: {', '.join(phases)}")
    lines.append("")

    return "\n".join(lines)


# --- Entry point ------------------------------------------------------------


def generate_reports(
    run_dir: Path,
    final: dict[str, Any],
    *,
    timestamp: str | None = None,
) -> dict[str, Path]:
    """Write the three artifacts from a validated ``final`` output.

    Returns a mapping of artifact name to path.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    ts = timestamp or datetime.now(UTC).isoformat()

    findings = final.get("findings") or []
    vulns = [finding_to_vuln(f, timestamp=ts) for f in findings]

    md_path = run_dir / "penetration_test_report.md"
    md_path.write_text(_render_markdown(final, vulns), encoding="utf-8")

    vulns_path = run_dir / "vulnerabilities.json"
    vulns_path.write_text(
        json.dumps(vulns, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    sarif_path = run_dir / "findings.sarif"
    sarif_path.write_text(
        json.dumps(build_sarif_report(vulns), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "penetration_test_report.md": md_path,
        "vulnerabilities.json": vulns_path,
        "findings.sarif": sarif_path,
    }


__all__ = [
    "SARIF_SCHEMA",
    "SARIF_VERSION",
    "FinalOutputError",
    "build_sarif_report",
    "finding_to_vuln",
    "generate_reports",
    "load_schema",
    "read_final_output",
    "validate_final_output",
]
