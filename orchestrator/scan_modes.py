"""Scan modes: quick vs deep.

A scan mode maps to a wall-clock ``timeout_s``, an analysis ``depth`` hint fed
into the prompt, and the ordered list of ``phases`` the agent is allowed to run.
First-phase scope is white-box code review, so the default phase lists stay in
the recon -> mapping -> testing -> fix progression without browser/HTTP work.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScanMode:
    name: str
    timeout_s: int
    depth: str
    phases: tuple[str, ...]


QUICK = ScanMode(
    name="quick",
    timeout_s=900,
    depth="shallow",
    phases=("recon", "testing"),
)

DEEP = ScanMode(
    name="deep",
    timeout_s=10800,
    depth="deep",
    phases=("recon", "mapping", "testing"),
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


__all__ = ["DEFAULT_SCAN_MODE", "DEEP", "QUICK", "ScanMode", "get_scan_mode", "known_modes"]
