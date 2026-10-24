"""Entry point: ``python3 mcp/evidence_store --run-dir <run_dir>`` (run from the repo root).

The repo's ``mcp/`` directory has the same name as the third-party ``mcp`` SDK, so a
``-m mcp.evidence_store`` import can resolve to the wrong package. When executed by
path, this module therefore loads its own directory as the package
``striket_evidence_store`` and never depends on the name ``mcp``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PACKAGE = "striket_evidence_store"


def _load_package() -> None:
    if PACKAGE in sys.modules:
        return
    here = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        PACKAGE, here / "__init__.py", submodule_search_locations=[str(here)]
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load evidence_store package from {here}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)


def run() -> int:
    if __package__:  # imported as a normal package (e.g. python -m <pkg>)
        from .server import main
    else:
        _load_package()
        from striket_evidence_store.server import main  # type: ignore[import-not-found]
    return main()


if __name__ == "__main__":
    raise SystemExit(run())
