import json

from orchestrator.events import describe_event, parse_line


def _describe(obj: dict) -> str | None:
    event = parse_line(json.dumps(obj))
    assert event is not None
    return describe_event(event)


def test_agent_text_is_not_truncated() -> None:
    text = "word " * 200
    assert _describe({"type": "text", "text": text}) == text.strip()


def test_reasoning_is_not_truncated() -> None:
    text = "step " * 200
    assert _describe({"type": "reasoning", "text": text}) == f"thinking: {text.strip()}"
