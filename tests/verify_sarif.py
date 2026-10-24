#!/usr/bin/env python3
"""Run report.py on sample_final.json and check findings.sarif is valid SARIF 2.1.0.

Validation uses the official OASIS schema when it can be loaded (``--schema PATH``,
or fetched from schemastore unless ``--offline``); otherwise a built-in structural
check of the required SARIF 2.1.0 properties is used.

Usage: python3 tests/verify_sarif.py [--final PATH] [--schema PATH] [--offline]
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator import report  # noqa: E402

SCHEMA_URL = "https://json.schemastore.org/sarif-2.1.0.json"
LEVELS = {"none", "note", "warning", "error"}


def load_official_schema(path: str | None, offline: bool) -> dict[str, Any] | None:
    try:
        if path:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        if offline:
            return None
        with urllib.request.urlopen(SCHEMA_URL, timeout=15) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"note: official schema unavailable ({exc}); using structural check")
        return None


def structural_errors(doc: Any) -> list[str]:
    errs: list[str] = []
    if not isinstance(doc, dict):
        return ["root is not an object"]
    if doc.get("version") != "2.1.0":
        errs.append("version must be '2.1.0'")
    runs = doc.get("runs")
    if not isinstance(runs, list) or not runs:
        return errs + ["runs must be a non-empty array"]
    for i, run in enumerate(runs):
        driver = (run.get("tool") or {}).get("driver")
        if not isinstance(driver, dict) or not driver.get("name"):
            errs.append(f"runs[{i}].tool.driver.name is required")
            driver = driver or {}
        rule_ids = {r.get("id") for r in driver.get("rules", []) if isinstance(r, dict)}
        for j, res in enumerate(run.get("results", [])):
            p = f"runs[{i}].results[{j}]"
            msg = res.get("message")
            if not isinstance(msg, dict) or not (msg.get("text") or msg.get("id")):
                errs.append(f"{p}.message.text is required")
            if "level" in res and res["level"] not in LEVELS:
                errs.append(f"{p}.level invalid: {res['level']!r}")
            if rule_ids and res.get("ruleId") not in rule_ids:
                errs.append(f"{p}.ruleId {res.get('ruleId')!r} not defined in driver.rules")
            for k, loc in enumerate(res.get("locations", [])):
                art = (loc.get("physicalLocation") or {}).get("artifactLocation")
                if art is not None and not art.get("uri"):
                    errs.append(f"{p}.locations[{k}] artifactLocation.uri missing")
                region = (loc.get("physicalLocation") or {}).get("region") or {}
                if "startLine" in region and (
                    not isinstance(region["startLine"], int) or region["startLine"] < 1
                ):
                    errs.append(f"{p}.locations[{k}] region.startLine must be int >= 1")
    return errs


def schema_errors(doc: Any, schema: dict[str, Any]) -> list[str]:
    from jsonschema import Draft7Validator  # imported lazily; optional dependency

    validator = Draft7Validator(schema)
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in validator.iter_errors(doc)
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--final", default=str(ROOT / "tests/fixtures/sample_final.json"))
    ap.add_argument("--schema", help="path to a local sarif-2.1.0 JSON schema")
    ap.add_argument("--offline", action="store_true", help="skip fetching the official schema")
    args = ap.parse_args()

    final = report.read_final_output(Path(args.final))
    with tempfile.TemporaryDirectory() as tmp:
        report.generate_reports(Path(tmp), final)
        sarif_path = Path(tmp) / "findings.sarif"
        if not sarif_path.is_file():
            print("FAIL: findings.sarif was not produced")
            return 1
        doc = json.loads(sarif_path.read_text(encoding="utf-8"))

    errors = structural_errors(doc)
    schema = load_official_schema(args.schema, args.offline)
    if schema is not None:
        try:
            errors += schema_errors(doc, schema)
        except ImportError:
            print("note: jsonschema not installed; official schema check skipped")

    results = doc["runs"][0].get("results", []) if not errors else []
    if len(final["findings"]) != len(results) and not errors:
        errors.append(f"expected {len(final['findings'])} results, got {len(results)}")

    if errors:
        print("FAIL: findings.sarif is not valid SARIF 2.1.0")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK: findings.sarif is valid SARIF 2.1.0 ({len(results)} result(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
