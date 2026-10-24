"""Engagement framing in the prompt: white-box vs black-box vs gray-box.

A run that mixes a source tree with a live web target is gray-box — the prompt
must not tell the agent "there is no source tree to read" (the pure black-box
framing), otherwise it ignores the code it was given.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator.cli import _build_prompt
from orchestrator.tui import _engagement_label

_PHASES = ("recon", "mapping", "testing")


def _prompt(*, has_web: bool, has_code: bool) -> str:
    return _build_prompt(
        "SCOPE", "quick", "shallow", _PHASES, None,
        has_web=has_web, has_code=has_code,
    )


def test_code_only_is_white_box() -> None:
    prompt = _prompt(has_web=False, has_code=True)
    assert "BLACK-BOX" not in prompt
    assert "GRAY-BOX" not in prompt


def test_web_only_is_black_box() -> None:
    prompt = _prompt(has_web=True, has_code=False)
    assert "BLACK-BOX WEB RUN" in prompt
    assert "There is no source tree" in prompt
    assert "add_evidence" in prompt


def test_web_plus_code_is_gray_box_not_black_box() -> None:
    prompt = _prompt(has_web=True, has_code=True)
    assert "GRAY-BOX" in prompt
    assert "There is no source tree" not in prompt
    # the source tree must stay in scope ...
    assert "review the source" in prompt.lower()
    # ... while the HTTP evidence mandate still applies to the live work.
    assert "add_evidence" in prompt


def test_engagement_label_distinguishes_runs() -> None:
    assert _engagement_label({"black_box": True}) == " (black-box)"
    mixed = {"targets_info": [{"type": "url"}, {"type": "code"}]}
    assert _engagement_label(mixed) == " (gray-box)"
    assert _engagement_label({"targets_info": [{"type": "code"}]}) == ""
