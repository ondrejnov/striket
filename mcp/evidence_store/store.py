"""Run-scoped persistence for the evidence_store MCP.

State lives in JSON files under ``<run_dir>/evidence_store/``. Several agent
processes may each spawn their own server against the same run directory, so every
mutation is a read-modify-write under an exclusive ``flock`` and files are replaced
atomically. Coverage states and finding fields mirror
``schemas/final_output.schema.json`` so :meth:`EvidenceStore.export_final_parts`
yields fragments that validate as-is.

The store holds methodology records and evidence supplied by the runtime agent. It
carries no payloads of its own and performs no network or target access; scope
validation happens in the orchestrator before the agent runs.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import tempfile
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

COVERAGE_STATES: tuple[str, ...] = ("tested", "partial", "skipped")
SEVERITIES: tuple[str, ...] = ("info", "low", "medium", "high", "critical")
EVIDENCE_TYPES: tuple[str, ...] = ("http", "code", "log", "screenshot")

#: Fields of a finding that belong to final_output.schema.json (additionalProperties: false).
FINDING_SCHEMA_FIELDS: tuple[str, ...] = (
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

MAX_EVIDENCE_CHARS = 256_000
_CWE_RE = re.compile(r"^(?:CWE-)?(\d{1,5})$", re.IGNORECASE)
_STATES_NEEDING_REASON = frozenset({"partial", "skipped"})
_FILES = ("notes", "coverage", "threat_models", "evidence", "findings")


class StoreError(ValueError):
    """A request the store rejects; the message is safe to show the calling agent."""


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clean(value: Any, field: str, *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise StoreError(f"{field} must be a string")
    value = value.strip()
    if required and not value:
        raise StoreError(f"{field} cannot be empty")
    return value


def _norm(value: str) -> str:
    return " ".join(value.lower().split())


class EvidenceStore:
    """File-backed store for notes, coverage, threat models, evidence and findings."""

    def __init__(self, run_dir: str | os.PathLike[str]) -> None:
        self.root = Path(run_dir) / "evidence_store"
        self.root.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.RLock()
        self._lock_path = self.root / ".lock"

    # -- persistence -------------------------------------------------------------

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.json"

    def _read(self, name: str) -> dict[str, Any]:
        path = self._path(name)
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"{path.name} is unreadable: {exc}") from exc
        return data if isinstance(data, dict) else {}

    def _write(self, name: str, data: dict[str, Any]) -> None:
        path = self._path(name)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(self.root),
            prefix=f".{name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            json.dump(data, tmp, ensure_ascii=False, indent=2, default=str)
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock, self._lock_path.open("a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    @staticmethod
    def _next_id(prefix: str, existing: dict[str, Any], width: int = 3) -> str:
        highest = 0
        for key in existing:
            match = re.fullmatch(rf"{re.escape(prefix)}-(\d+)", key)
            if match:
                highest = max(highest, int(match.group(1)))
        return f"{prefix}-{highest + 1:0{width}d}"

    # -- notes -------------------------------------------------------------------

    def add_note(
        self,
        title: str,
        content: str,
        category: str = "general",
        tags: list[str] | None = None,
        agent: str = "",
    ) -> dict[str, Any]:
        title = _clean(title, "title", required=True)
        content = _clean(content, "content", required=True)
        if tags is not None and not (isinstance(tags, list) and all(isinstance(t, str) for t in tags)):
            raise StoreError("tags must be a list of strings")
        with self._locked():
            notes = self._read("notes")
            note_id = self._next_id("N", notes)
            stamp = _now()
            notes[note_id] = {
                "note_id": note_id,
                "title": title,
                "content": content,
                "category": _clean(category, "category") or "general",
                "tags": sorted({t.strip() for t in (tags or []) if t.strip()}),
                "agent": _clean(agent, "agent"),
                "created_at": stamp,
                "updated_at": stamp,
            }
            self._write("notes", notes)
        return {"note_id": note_id, "total_notes": len(notes)}

    def list_notes(
        self,
        category: str | None = None,
        tags: list[str] | None = None,
        search: str | None = None,
        include_content: bool = False,
    ) -> dict[str, Any]:
        wanted_tags = {t.strip().lower() for t in tags or [] if isinstance(t, str)}
        needle = _norm(search) if search else ""
        out: list[dict[str, Any]] = []
        with self._locked():
            notes = self._read("notes")
        for note in notes.values():
            if category and note.get("category") != category:
                continue
            if wanted_tags and not wanted_tags & {t.lower() for t in note.get("tags", [])}:
                continue
            if needle and needle not in _norm(f"{note['title']} {note['content']}"):
                continue
            item = {k: v for k, v in note.items() if include_content or k != "content"}
            out.append(item)
        return {"notes": out, "count": len(out), "total_notes": len(notes)}

    def get_note(self, note_id: str) -> dict[str, Any]:
        with self._locked():
            note = self._read("notes").get(_clean(note_id, "note_id", required=True))
        if note is None:
            raise StoreError(f"No note {note_id!r}; call list_notes to find it")
        return note

    # -- coverage ----------------------------------------------------------------

    def set_coverage(
        self,
        area: str,
        state: str,
        reason: str = "",
        agent: str = "",
    ) -> dict[str, Any]:
        """Upsert one coverage row keyed by *area*; earlier states are kept as history."""
        area = _clean(area, "area", required=True)
        state = _clean(state, "state", required=True).lower()
        reason = _clean(reason, "reason")
        if state not in COVERAGE_STATES:
            raise StoreError(f"state must be one of {list(COVERAGE_STATES)}, got {state!r}")
        if state in _STATES_NEEDING_REASON and not reason:
            raise StoreError(
                f"reason is required for state '{state}' - say what remains unexamined or why"
            )
        key = _norm(area)
        with self._locked():
            rows = self._read("coverage")
            stamp = _now()
            row = rows.get(key)
            if row is None:
                row = {"area": area, "finding_ids": [], "history": [], "created_at": stamp}
                rows[key] = row
                created = True
            else:
                created = False
                row["history"].append(
                    {
                        "state": row["state"],
                        "reason": row.get("reason", ""),
                        "agent": row.get("agent", ""),
                        "recorded_at": row.get("updated_at", row["created_at"]),
                    }
                )
            row.update(
                {"state": state, "reason": reason, "agent": _clean(agent, "agent"), "updated_at": stamp}
            )
            self._write("coverage", rows)
        return {"area": row["area"], "state": state, "created": created, "rows": len(rows)}

    def get_coverage(self, area: str | None = None, state: str | None = None) -> dict[str, Any]:
        if state is not None and state.lower() not in COVERAGE_STATES:
            raise StoreError(f"state must be one of {list(COVERAGE_STATES)}")
        with self._locked():
            rows = self._read("coverage")
        if area:
            rows = {k: v for k, v in rows.items() if k == _norm(area)}
            if not rows:
                raise StoreError(f"No coverage row for area {area!r}")
        selected = [r for r in rows.values() if not state or r["state"] == state.lower()]
        return {"coverage": selected, "count": len(selected), "summary": self._coverage_counts(rows)}

    def coverage_status(self) -> dict[str, Any]:
        """Coverage tracking view: counts plus every row an honest report must caveat."""
        with self._locked():
            rows = self._read("coverage")
            findings = self._read("findings")
        open_rows = [
            {"area": r["area"], "state": r["state"], "reason": r.get("reason", "")}
            for r in rows.values()
            if r["state"] != "tested"
        ]
        unlinked = sorted(
            fid for fid, f in findings.items() if not f.get("area") or _norm(f["area"]) not in rows
        )
        return {
            "summary": self._coverage_counts(rows),
            "findings_filed": len(findings),
            "open_areas": open_rows,
            "findings_without_coverage_row": unlinked,
            "fully_tested": bool(rows) and not open_rows,
        }

    @staticmethod
    def _coverage_counts(rows: dict[str, Any]) -> dict[str, int]:
        counts = dict.fromkeys(COVERAGE_STATES, 0)
        for row in rows.values():
            counts[row["state"]] += 1
        return counts

    # -- threat model ------------------------------------------------------------

    def store_threat_model(self, target: str, content: str, agent: str = "") -> dict[str, Any]:
        """Save the model for *target*; a replaced version is retained as a revision."""
        target = _clean(target, "target", required=True)
        content = _clean(content, "content", required=True)
        key = _norm(target)
        with self._locked():
            models = self._read("threat_models")
            stamp = _now()
            model = models.get(key)
            if model is None:
                model = {"target": target, "revisions": [], "created_at": stamp}
                models[key] = model
            else:
                model["revisions"].append(
                    {
                        "content": model["content"],
                        "agent": model.get("agent", ""),
                        "recorded_at": model["updated_at"],
                    }
                )
            model.update({"content": content, "agent": _clean(agent, "agent"), "updated_at": stamp})
            self._write("threat_models", models)
        return {"target": target, "revision": len(model["revisions"]) + 1}

    def get_threat_model(self, target: str | None = None) -> dict[str, Any]:
        with self._locked():
            models = self._read("threat_models")
        if target:
            model = models.get(_norm(target))
            if model is None:
                known = [m["target"] for m in models.values()]
                raise StoreError(f"No threat model for {target!r}; stored targets: {known}")
            return model
        return {"threat_models": [{**m, "revisions": len(m["revisions"])} for m in models.values()]}

    # -- evidence artifacts ------------------------------------------------------

    def add_evidence(
        self, type: str, content: str, description: str = "", agent: str = ""
    ) -> dict[str, Any]:
        """Store an evidence artifact and return its ``ref`` for use in findings."""
        type = _clean(type, "type", required=True).lower()
        if type not in EVIDENCE_TYPES:
            raise StoreError(f"type must be one of {list(EVIDENCE_TYPES)}, got {type!r}")
        content = _clean(content, "content", required=True)
        truncated = len(content) > MAX_EVIDENCE_CHARS
        if truncated:
            content = content[:MAX_EVIDENCE_CHARS]
        with self._locked():
            items = self._read("evidence")
            evidence_id = self._next_id("E", items, width=4)
            items[evidence_id] = {
                "ref": f"evidence:{evidence_id}",
                "type": type,
                "description": _clean(description, "description"),
                "content": content,
                "truncated": truncated,
                "agent": _clean(agent, "agent"),
                "created_at": _now(),
            }
            self._write("evidence", items)
        return {"ref": f"evidence:{evidence_id}", "type": type, "truncated": truncated}

    def get_evidence(self, ref: str) -> dict[str, Any]:
        ref = _clean(ref, "ref", required=True)
        with self._locked():
            item = self._read("evidence").get(ref.removeprefix("evidence:"))
        if item is None:
            raise StoreError(f"No evidence {ref!r}")
        return item

    # -- findings ----------------------------------------------------------------

    def add_finding(
        self,
        title: str,
        severity: str,
        location: str,
        summary: str,
        cwe: str | None = None,
        evidence: list[dict[str, str]] | None = None,
        reproduction: str = "",
        remediation: str = "",
        area: str = "",
        id: str | None = None,
        agent: str = "",
    ) -> dict[str, Any]:
        title = _clean(title, "title", required=True)
        severity = _clean(severity, "severity", required=True).lower()
        if severity not in SEVERITIES:
            raise StoreError(f"severity must be one of {list(SEVERITIES)}, got {severity!r}")
        location = _clean(location, "location", required=True)
        summary = _clean(summary, "summary", required=True)
        cwe_norm = self._normalize_cwe(cwe)
        refs = self._validate_evidence_refs(evidence)
        area = _clean(area, "area")
        with self._locked():
            findings = self._read("findings")
            finding_id = _clean(id, "id") if id else self._next_id("F", findings)
            if finding_id in findings:
                raise StoreError(f"Finding {finding_id!r} already exists")
            duplicate = next(
                (
                    fid
                    for fid, f in findings.items()
                    if _norm(f["location"]) == _norm(location) and _norm(f["title"]) == _norm(title)
                ),
                None,
            )
            if duplicate:
                raise StoreError(
                    f"Finding {duplicate} already records '{title}' at {location}; "
                    "use update_finding instead of filing a duplicate"
                )
            missing = [e["ref"] for e in refs if e["ref"].removeprefix("evidence:") not in self._read("evidence")]
            if missing:
                raise StoreError(f"Unknown evidence ref(s) {missing}; store them with add_evidence first")
            stamp = _now()
            findings[finding_id] = {
                "id": finding_id,
                "title": title,
                "severity": severity,
                "cwe": cwe_norm,
                "location": location,
                "summary": summary,
                "evidence": refs,
                "reproduction": _clean(reproduction, "reproduction"),
                "remediation": _clean(remediation, "remediation"),
                "area": area,
                "agent": _clean(agent, "agent"),
                "created_at": stamp,
                "updated_at": stamp,
            }
            self._write("findings", findings)
            linked = self._link_to_coverage(area, finding_id) if area else False
        result: dict[str, Any] = {"id": finding_id, "total_findings": len(findings)}
        if area and not linked:
            result["warning"] = (
                f"No coverage row for area {area!r}; record it with set_coverage so the finding "
                "is attributable to examined scope"
            )
        return result

    def update_finding(self, id: str, **changes: Any) -> dict[str, Any]:
        """Revise an existing finding. Only schema fields (plus ``area``) may change."""
        allowed = set(FINDING_SCHEMA_FIELDS) - {"id"} | {"area"}
        unknown = sorted(set(changes) - allowed)
        if unknown:
            raise StoreError(f"Cannot update field(s) {unknown}; allowed: {sorted(allowed)}")
        with self._locked():
            findings = self._read("findings")
            finding = findings.get(_clean(id, "id", required=True))
            if finding is None:
                raise StoreError(f"No finding {id!r}; call list_findings")
            for name, value in changes.items():
                if name == "severity":
                    value = _clean(value, name, required=True).lower()
                    if value not in SEVERITIES:
                        raise StoreError(f"severity must be one of {list(SEVERITIES)}")
                elif name == "cwe":
                    value = self._normalize_cwe(value)
                elif name == "evidence":
                    value = self._validate_evidence_refs(value)
                    known = self._read("evidence")
                    missing = [e["ref"] for e in value if e["ref"].removeprefix("evidence:") not in known]
                    if missing:
                        raise StoreError(f"Unknown evidence ref(s) {missing}")
                else:
                    value = _clean(value, name, required=name in {"title", "location", "summary"})
                finding[name] = value
            finding["updated_at"] = _now()
            self._write("findings", findings)
            if changes.get("area"):
                self._link_to_coverage(finding["area"], finding["id"])
        return {"id": finding["id"], "updated": sorted(changes)}

    def list_findings(self, severity: str | None = None) -> dict[str, Any]:
        if severity is not None and severity.lower() not in SEVERITIES:
            raise StoreError(f"severity must be one of {list(SEVERITIES)}")
        with self._locked():
            findings = self._read("findings")
        selected = [
            {k: f[k] for k in ("id", "title", "severity", "cwe", "location", "area")}
            for f in findings.values()
            if not severity or f["severity"] == severity.lower()
        ]
        selected.sort(key=lambda f: (-SEVERITIES.index(f["severity"]), f["id"]))
        return {"findings": selected, "count": len(selected), "total_findings": len(findings)}

    def get_finding(self, id: str) -> dict[str, Any]:
        with self._locked():
            finding = self._read("findings").get(_clean(id, "id", required=True))
        if finding is None:
            raise StoreError(f"No finding {id!r}; call list_findings")
        return finding

    # -- export ------------------------------------------------------------------

    def export_final_parts(self) -> dict[str, Any]:
        """``coverage`` and ``findings`` fragments exactly in final_output.schema.json shape."""
        with self._locked():
            rows = self._read("coverage")
            findings = self._read("findings")
        coverage = []
        for row in sorted(rows.values(), key=lambda r: r["created_at"]):
            item = {"area": row["area"], "state": row["state"]}
            if row.get("reason"):
                item["reason"] = row["reason"]
            coverage.append(item)
        exported = []
        for finding in findings.values():
            item = {k: finding[k] for k in FINDING_SCHEMA_FIELDS if k in finding}
            for optional in ("reproduction", "remediation"):
                if not item.get(optional):
                    item.pop(optional, None)
            if not item.get("evidence"):
                item.pop("evidence", None)
            exported.append(item)
        exported.sort(key=lambda f: (-SEVERITIES.index(f["severity"]), f["id"]))
        return {"coverage": coverage, "findings": exported}

    # -- helpers -----------------------------------------------------------------

    def _link_to_coverage(self, area: str, finding_id: str) -> bool:
        """Attach a finding to its coverage row. Caller must hold the store lock."""
        rows = self._read("coverage")
        row = rows.get(_norm(area))
        if row is None:
            return False
        if finding_id not in row["finding_ids"]:
            row["finding_ids"].append(finding_id)
            self._write("coverage", rows)
        return True

    @staticmethod
    def _normalize_cwe(cwe: Any) -> str | None:
        if cwe is None or (isinstance(cwe, str) and not cwe.strip()):
            return None
        if not isinstance(cwe, str):
            raise StoreError("cwe must be a string like 'CWE-89' or null")
        match = _CWE_RE.match(cwe.strip())
        if not match:
            raise StoreError(f"cwe {cwe!r} is not a CWE identifier (expected 'CWE-<number>')")
        return f"CWE-{int(match.group(1))}"

    @staticmethod
    def _validate_evidence_refs(evidence: Any) -> list[dict[str, str]]:
        if evidence is None:
            return []
        if not isinstance(evidence, list):
            raise StoreError("evidence must be a list of {type, ref} objects")
        refs: list[dict[str, str]] = []
        for item in evidence:
            if not isinstance(item, dict):
                raise StoreError("each evidence item must be an object with type and ref")
            etype = _clean(item.get("type"), "evidence.type", required=True).lower()
            ref = _clean(item.get("ref"), "evidence.ref", required=True)
            if etype not in EVIDENCE_TYPES:
                raise StoreError(f"evidence.type must be one of {list(EVIDENCE_TYPES)}")
            refs.append({"type": etype, "ref": ref})
        return refs
