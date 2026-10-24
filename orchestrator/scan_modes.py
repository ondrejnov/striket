"""Scan modes: quick vs deep.

A scan mode maps to a wall-clock ``timeout_s``, an analysis ``depth`` hint fed
into the prompt, and the ordered list of phases the agent is allowed to run.
Both modes default to ``timeout_s=0`` (no wall-clock limit): a security audit
runs to completion rather than being hard-killed mid-step. A cap can still be
imposed per run with ``--timeout`` / ``STRIKET_TIMEOUT`` / the config file.

Each mode carries two phase plans selected by the dominant target type:

* ``phases`` — white-box code review (Bash + skills, no browser/HTTP), the
  recon -> mapping -> testing progression used for ``code`` targets.
* ``web_phases`` — black-box live-target web work (recon = live surface/port/
  tech/subdomain discovery, mapping = crawl routes/params/auth/session,
  testing = per-vuln-class with browser + HTTP) used for ``url``/``domain``/
  ``ip`` targets.

:func:`phases_for` resolves the plan for a concrete set of target types and
unions both when a run mixes code and live targets, so the merged plan still
reads recon -> mapping -> testing. The orchestrator stays adapter-agnostic: it
only asks which phases a classified target set should run.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

# Target types that require live black-box web work (browser + direct HTTP)
# instead of white-box code review.
WEB_TARGET_TYPES = frozenset({"url", "domain", "ip"})

# Canonical ordering used when unioning white-box and black-box phase lists for
# a mixed run, so the merged plan still reads recon -> mapping -> testing (-> fix).
_PHASE_ORDER = ("recon", "mapping", "testing", "fix")


@dataclass(frozen=True)
class ScanMode:
    name: str
    timeout_s: int
    depth: str
    phases: tuple[str, ...]
    web_phases: tuple[str, ...]


QUICK = ScanMode(
    name="quick",
    timeout_s=0,  # no wall-clock limit; override per run with --timeout
    depth="shallow",
    phases=("recon", "testing"),
    # Black-box needs a mapping/crawl phase to discover routes/params/auth even
    # in quick, where white-box code review skips it.
    web_phases=("recon", "mapping", "testing"),
)

DEEP = ScanMode(
    name="deep",
    timeout_s=0,  # no wall-clock limit; override per run with --timeout
    depth="deep",
    phases=("recon", "mapping", "testing"),
    web_phases=("recon", "mapping", "testing"),
)

_MODES: dict[str, ScanMode] = {QUICK.name: QUICK, DEEP.name: DEEP}

DEFAULT_SCAN_MODE = QUICK.name


def known_modes() -> tuple[str, ...]:
    return tuple(_MODES)


def get_scan_mode(name: str) -> ScanMode:
    """Return the :class:`ScanMode` for ``name``.

    Raises :class:`ValueError` on an unknown mode so the CLI can map it to a
    usage error.
    """
    try:
        return _MODES[name]
    except KeyError:
        raise ValueError(
            f"unknown scan mode {name!r}; known modes: {', '.join(known_modes())}"
        ) from None


def is_black_box(target_types: Iterable[str]) -> bool:
    """True when any target is a live web asset (url/domain/ip).

    A black-box run drives the agent through live web work (browser + HTTP) and
    must capture HTTP evidence; a run with only ``code`` targets stays white-box.
    """
    return any(t in WEB_TARGET_TYPES for t in target_types)


def phases_for(mode: ScanMode, target_types: Iterable[str]) -> tuple[str, ...]:
    """Resolve the ordered phase plan for ``mode`` given classified targets.

    * Only ``code`` targets -> the mode's white-box ``phases`` (unchanged from
      M0-M2; no regression).
    * Any live web target (url/domain/ip) -> the mode's black-box ``web_phases``.
    * A mix -> the ordered union of both, so recon -> mapping -> testing holds.

    Falls back to white-box ``phases`` when no target type is recognised.
    """
    types = list(target_types)
    has_web = is_black_box(types)
    has_code = any(t == "code" for t in types)

    selected: set[str] = set()
    if has_code:
        selected.update(mode.phases)
    if has_web:
        selected.update(mode.web_phases)
    if not selected:
        selected.update(mode.phases)
    return tuple(phase for phase in _PHASE_ORDER if phase in selected)


__all__ = [
    "DEEP",
    "DEFAULT_SCAN_MODE",
    "QUICK",
    "WEB_TARGET_TYPES",
    "ScanMode",
    "get_scan_mode",
    "is_black_box",
    "known_modes",
    "phases_for",
]
