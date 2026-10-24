"""Focus guidance: config resolution and prompt rendering."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from orchestrator.cli import _build_prompt
from orchestrator.config import load_config


def _prompt(focus: str | None) -> str:
    return _build_prompt("SCOPE", "quick", "shallow", ("recon", "testing"), focus)


def test_no_focus_adds_no_section() -> None:
    assert "FOCUS" not in _prompt(None)
    assert "FOCUS" not in _prompt("  \n ")


def test_focus_lines_become_bullets_after_scope() -> None:
    prompt = _prompt("auth and sessions\n\n  file uploads ")
    assert "- auth and sessions\n- file uploads\n" in prompt
    assert "within the authorized scope" in prompt
    assert prompt.index("SCOPE") < prompt.index("FOCUS")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.delenv("STRIKET_FOCUS", raising=False)
    monkeypatch.delenv("STRIKET_CONFIG", raising=False)
    return tmp_path


def test_focus_precedence(clean_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert load_config(cwd=clean_env).focus is None
    (clean_env / "striket.toml").write_text('focus = "from file"\n', encoding="utf-8")
    assert load_config(cwd=clean_env).focus == "from file"
    monkeypatch.setenv("STRIKET_FOCUS", "from env")
    assert load_config(cwd=clean_env).focus == "from env"
    cfg = load_config(cwd=clean_env, overrides={"focus": "from cli"})
    assert cfg.focus == "from cli"
    assert cfg.to_dict()["focus"] == "from cli"
