"""Streaming parser for ``agentiscode --json`` output.

``agentiscode --json`` emits one JSON object per line (JSON Lines). The exact
event vocabulary differs across adapters, so this parser stays deliberately
permissive: it never raises on an unknown shape, extracts a few normalized
hints (progress text, cost, token usage, elapsed time), and keeps a running
:class:`EventAggregate` the orchestrator can fold into ``run.json`` as the run
streams. Malformed lines are treated as opaque data and skipped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

# Keys various adapters have used for the same concept. We probe several so the
# orchestrator does not depend on one adapter's vocabulary.
_COST_KEYS = ("cost", "total_cost", "cost_usd", "usd")
_TEXT_KEYS = ("message", "text", "content", "summary", "status")
_ELAPSED_KEYS = ("elapsed_s", "elapsed", "duration_s", "duration")
_TYPE_KEYS = ("type", "event", "kind")


@dataclass(frozen=True)
class Event:
    """One normalized event. ``raw`` keeps the full original object."""

    kind: str
    text: str | None
    cost: float | None
    input_tokens: int | None
    output_tokens: int | None
    elapsed_s: float | None
    raw: dict[str, Any]


@dataclass
class EventAggregate:
    """Running totals folded from the event stream."""

    cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_s: float = 0.0
    events: int = 0
    last_text: str | None = None
    kinds: dict[str, int] = field(default_factory=dict)

    def update(self, event: Event) -> None:
        self.events += 1
        self.kinds[event.kind] = self.kinds.get(event.kind, 0) + 1
        # Cost/usage hints are reported as running totals by the adapters we
        # target, so take the max rather than summing double-counted lines.
        if event.cost is not None:
            self.cost = max(self.cost, event.cost)
        if event.input_tokens is not None:
            self.input_tokens = max(self.input_tokens, event.input_tokens)
        if event.output_tokens is not None:
            self.output_tokens = max(self.output_tokens, event.output_tokens)
        if event.elapsed_s is not None:
            self.elapsed_s = max(self.elapsed_s, event.elapsed_s)
        if event.text:
            self.last_text = event.text

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost": round(self.cost, 6),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "elapsed_s": round(self.elapsed_s, 3),
            "events": self.events,
            "last_text": self.last_text,
            "kinds": dict(self.kinds),
        }


def _first_number(obj: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key in obj:
            value = obj[key]
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value)
                except ValueError:
                    continue
    return None


def _first_int(obj: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    number = _first_number(obj, keys)
    return int(number) if number is not None else None


def _first_text(obj: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _usage(obj: dict[str, Any]) -> dict[str, Any]:
    usage = obj.get("usage")
    return usage if isinstance(usage, dict) else {}


def _truncate(value: str, max_len: int = 160) -> str:
    value = (value or "").strip().replace("\n", " ")
    if len(value) <= max_len:
        return value
    return value[: max_len - 1].rstrip() + "…"


def parse_line(line: str) -> Event | None:
    """Parse one JSON-Lines line into an :class:`Event`, or ``None`` if the
    line is blank or not a JSON object."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None

    usage = _usage(obj)
    merged_for_tokens = {**usage, **obj}
    return Event(
        kind=_first_text(obj, _TYPE_KEYS) or "event",
        text=_first_text(obj, _TEXT_KEYS),
        cost=_first_number(obj, _COST_KEYS) or _first_number(usage, _COST_KEYS),
        input_tokens=_first_int(
            merged_for_tokens, ("input_tokens", "prompt_tokens", "tokens_in")
        ),
        output_tokens=_first_int(
            merged_for_tokens, ("output_tokens", "completion_tokens", "tokens_out")
        ),
        elapsed_s=_first_number(obj, _ELAPSED_KEYS),
        raw=obj,
    )


def _error_summary(err: str) -> str:
    """Reduce a tool error payload to one meaningful line.

    MCP servers (ours included) often return the error as pretty-printed JSON
    such as ``{\n  "error": "..."\n}``, whose first line is a bare ``{``. Pull
    the ``error``/``message`` field out when the payload is JSON, otherwise
    collapse the whole text onto one line.
    """
    try:
        obj = json.loads(err)
    except (json.JSONDecodeError, ValueError):
        obj = None
    if isinstance(obj, dict):
        for key in ("error", "message", "detail"):
            value = obj.get(key)
            if isinstance(value, dict):
                value = value.get("message") or json.dumps(value, ensure_ascii=False)
            if isinstance(value, str) and value.strip():
                return value
        return json.dumps(obj, ensure_ascii=False)
    return " ".join(err.split())


def describe_event(
    event: Event, tool_names: dict[str, str] | None = None
) -> str | None:
    """Render a human-readable one-line progress hint, or ``None`` when the
    event carries nothing worth logging.

    This is deliberately richer than :attr:`Event.text`. For the common
    ``tool`` events the adapter only reports a bare ``status`` (``running`` at
    the start of a tool call, ``completed``/``error`` at the end), so the raw
    text is just that word — the uninformative "running"/"completed" stream the
    operator sees. Here we instead name the tool and its target (``Read(login.py)``,
    ``Bash(run tests)``), surface agent prose, tool errors, and the closing
    cost/usage line, mirroring agentiscode's own text renderer.

    ``tool_names`` is an optional caller-owned map of tool-call id → tool name.
    Error events only carry the call id, so pass the same dict for the whole
    stream to get ``tool-error <name>`` instead of a generic ``tool-error tool``.
    """
    raw = event.raw
    kind = event.kind

    if kind == "tool":
        status = raw.get("status")
        call_id = raw.get("id")
        name = raw.get("name")
        if tool_names is not None and isinstance(call_id, str):
            if name:
                tool_names[call_id] = name
            else:
                name = tool_names.get(call_id)
        name = name or "tool"
        if status == "running":
            title = raw.get("title")
            tool_input = raw.get("input")
            if (not title or title == name) and isinstance(tool_input, dict):
                # Older agentiscode builds don't derive a title for Skill calls.
                title = tool_input.get("skill") or title
            label = f"{name}({title})" if title and title != name else name
            return f"tool {label}"
        if status == "error":
            err = (raw.get("error") or raw.get("output") or "").strip()
            summary = _error_summary(err) if err else "error"
            return f"tool-error {name}: {_truncate(summary, 300)}"
        # "completed" snapshots just mirror a "running" we already logged.
        return None

    if kind == "text":
        text = _truncate(raw.get("text") or "")
        return text or None

    if kind == "reasoning":
        text = _truncate(raw.get("text") or "")
        return f"thinking: {text}" if text else None

    if kind == "session":
        parts = [str(raw.get("adapter") or "agent")]
        if raw.get("model"):
            parts.append(f"model={raw['model']}")
        if raw.get("session_id"):
            parts.append(f"session={raw['session_id']}")
        return "session " + " ".join(parts)

    if kind == "result":
        bits: list[str] = []
        usage = _usage(raw)
        inp, out = usage.get("input_tokens"), usage.get("output_tokens")
        if inp is not None or out is not None:
            bits.append(f"tokens in={inp or 0} out={out or 0}")
        cost = raw.get("cost_usd")
        if isinstance(cost, (int, float)):
            bits.append(f"cost=${cost:.4f}")
        state = "error" if raw.get("is_error") else "done"
        return state + (("  " + "  ".join(bits)) if bits else "")

    if kind == "error":
        return f"error: {_truncate(str(raw.get('message') or 'error'))}"

    # step (usage snapshot), rate_limit, stderr — folded in elsewhere or noise.
    return None


def parse_events(lines: Iterable[str]) -> Iterator[Event]:
    """Yield :class:`Event` objects from an iterable of JSON-Lines strings,
    skipping blank and unparseable lines."""
    for line in lines:
        event = parse_line(line)
        if event is not None:
            yield event


__all__ = ["Event", "EventAggregate", "describe_event", "parse_events", "parse_line"]
