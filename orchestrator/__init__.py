"""Striket orchestrator — a thin, adapter-agnostic wrapper over the
``agentiscode`` CLI for *authorized* security testing.

The orchestrator never runs an agent loop of its own. It validates scope,
builds the ``agentiscode`` command, streams its JSON-Lines events, and turns
the agent's schema-validated final output into reports. Know-how (doctrine,
skills, output formats) is ported from Strix; the agent engine is not.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
