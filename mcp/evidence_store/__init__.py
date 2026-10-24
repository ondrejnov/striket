"""Striket evidence_store: a small stdio MCP server persisting a run's working record.

Replaces Strix's notes / coverage / threat_model / reporting / output_store tools with
one run-scoped store (notes, coverage, threat models, evidence artifacts, findings)
whose coverage and finding shapes match ``schemas/final_output.schema.json``.
"""

from .store import EvidenceStore, StoreError

__all__ = ["EvidenceStore", "StoreError"]
