"""The terminal UI is the default for ``striket run`` on a TTY."""

import sys

import pytest

from orchestrator.cli import _use_tui, build_parser


def _args(*extra: str):
    return build_parser().parse_args(["run", "--target", "./", *extra])


def _tty(monkeypatch: pytest.MonkeyPatch, value: bool) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: value)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: value)


def test_tui_is_default_on_tty(monkeypatch):
    _tty(monkeypatch, True)
    assert _use_tui(_args())


def test_no_tui_without_tty(monkeypatch):
    _tty(monkeypatch, False)
    assert not _use_tui(_args())


def test_headless_disables_tui(monkeypatch):
    _tty(monkeypatch, True)
    assert not _use_tui(_args("--headless"))
    assert not _use_tui(_args("--headless", "-i"))


def test_interactive_forces_tui_without_tty(monkeypatch):
    _tty(monkeypatch, False)
    assert _use_tui(_args("-i"))
