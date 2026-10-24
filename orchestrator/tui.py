"""Read-only live monitor for ``striket run -i``.

The scan itself runs unchanged in :func:`cli._cmd_run` on a background thread;
this module only observes it through :class:`cli.RunObserver` callbacks and by
polling the run's ``evidence_store/findings.json``. It never steers the agent —
the one exception is quitting while the scan is still running, which stops the
``agentiscode`` process exactly like Ctrl+C would without the TUI.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, RichLog, Static

from .events import EventAggregate

_SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")
_SEVERITY_STYLE = {
    "critical": "bold white on red",
    "high": "bold red",
    "medium": "yellow",
    "low": "cyan",
    "info": "dim",
}
_STATUS_STYLE = {
    "running": "bold yellow",
    "completed": "bold green",
    "partial": "bold magenta",
    "failed": "bold red",
}
_FINDINGS_POLL_S = 2.0


def _style_hint(hint: str) -> Text:
    """Colour one progress line by its kind (see ``events.describe_event``)."""
    if hint.startswith("tool-error"):
        return Text(hint, style="red")
    if hint.startswith("tool "):
        return Text.assemble(("tool ", "bold blue"), hint[5:])
    if hint.startswith("thinking:"):
        return Text(hint, style="dim italic")
    if hint.startswith("error:"):
        return Text(hint, style="bold red")
    if hint.startswith(("session ", "done", "error ")):
        return Text(hint, style="green")
    return Text(hint)


def _format_duration(seconds: float) -> str:
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _engagement_label(rec: dict[str, Any]) -> str:
    """Return the engagement-type suffix for the Mode line.

    Pure live-web runs are black-box; a run that also carries a source tree is
    gray-box; code-only runs get no suffix (plain white-box code review).
    """
    if rec.get("black_box"):
        return " (black-box)"
    types = {t.get("type") for t in (rec.get("targets_info") or [])}
    if types & {"url", "domain", "ip"} and "code" in types:
        return " (gray-box)"
    return ""


def _read_findings(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "evidence_store" / "findings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    findings = [f for f in data.values() if isinstance(f, dict)] if isinstance(data, dict) else []

    def rank(finding: dict[str, Any]) -> tuple[int, str]:
        severity = str(finding.get("severity", "")).lower()
        order = _SEVERITY_ORDER.index(severity) if severity in _SEVERITY_ORDER else 99
        return order, str(finding.get("id", ""))

    return sorted(findings, key=rank)


class ScanMonitor(App[None]):
    """Live view of one scan: run info, stats, activity log and findings."""

    TITLE = "Striket"
    CSS = """
    #info { height: auto; padding: 0 1; border: round $primary; }
    #stats { height: 1; padding: 0 1; background: $boost; }
    #body { height: 1fr; }
    #activity { width: 3fr; border: round $secondary; }
    #findings-pane { width: 2fr; border: round $secondary; }
    #findings { height: 1fr; }
    #finding-detail { height: auto; max-height: 12; padding: 0 1; border-top: solid $secondary; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit_monitor", "Quit"),
        Binding("ctrl+c", "quit_monitor", "Quit", show=False, priority=True),
    ]

    def __init__(self, budget: float | None) -> None:
        super().__init__()
        self._budget = budget
        self._run_dir: Path | None = None
        self._record: dict[str, Any] = {}
        self._aggregate = EventAggregate()
        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._status = "starting"
        self._findings: list[dict[str, Any]] = []
        self._findings_mtime: float | None = None
        self._process: subprocess.Popen[str] | None = None
        self._quit_armed = False

    # -- layout -------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Preparing run…", id="info")
        yield Static("", id="stats")
        with Horizontal(id="body"):
            log = RichLog(id="activity", wrap=True, markup=False, highlight=False)
            log.border_title = "Activity"
            yield log
            with Vertical(id="findings-pane") as pane:
                pane.border_title = "Findings (0)"
                table: DataTable[Any] = DataTable(id="findings", cursor_type="row", zebra_stripes=True)
                table.add_columns("ID", "Severity", "Title", "Location")
                yield table
                yield Static("", id="finding-detail")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(1.0, self._refresh_stats)
        self.set_interval(_FINDINGS_POLL_S, self._poll_findings)
        self._refresh_stats()

    # -- updates from the scan thread (always delivered on the UI thread) -----

    def add_log(self, message: str) -> None:
        if message.startswith(("fatal", "scope refused", "error")):
            style = "bold red"
        elif message.startswith(("warning", "interrupted")):
            style = "yellow"
        else:
            style = "bold"
        self.query_one("#activity", RichLog).write(Text(message, style=style))
        if message.startswith(("fatal", "scope refused")):
            self._status = "failed"

    def set_run(self, run_dir: Path, record: dict[str, Any]) -> None:
        self._run_dir = run_dir
        self._record = record
        self._status = "running"
        self._started_at = time.monotonic()
        self.sub_title = record.get("run_name", "")
        self._render_info()

    def set_progress(self, hint: str | None, aggregate: EventAggregate) -> None:
        self._aggregate = aggregate
        if hint:
            self.query_one("#activity", RichLog).write(_style_hint(hint))

    def set_process(self, process: subprocess.Popen[str]) -> None:
        self._process = process

    def set_finished(self, exit_code: int) -> None:
        self._finished_at = time.monotonic()
        self._status = str(self._record.get("status") or ("completed" if exit_code == 0 else "failed"))
        self._poll_findings()
        self._render_info()
        self._refresh_stats()
        artifacts = self._record.get("artifacts") or {}
        log = self.query_one("#activity", RichLog)
        for name, path in artifacts.items():
            log.write(Text.assemble(("report ", "bold green"), f"{name}: {path}"))
        log.write(Text("Scan finished — press q to exit.", style="bold"))

    # -- rendering ----------------------------------------------------------

    def _render_info(self) -> None:
        rec = self._record
        if not rec:
            return
        targets = ", ".join(t.get("original", "?") for t in rec.get("targets_info") or [])
        config = rec.get("config") or {}
        runtime = config.get("adapter", "?") + (f" / {config['model']}" if config.get("model") else "")
        status_style = _STATUS_STYLE.get(self._status, "bold")
        lines = Text.assemble(
            ("Status   ", "dim"), (self._status, status_style), "\n",
            ("Targets  ", "dim"), targets, "\n",
            ("Mode     ", "dim"), f"{rec.get('scan_mode', '?')}"
            f"{_engagement_label(rec)}  ",
            ("phases ", "dim"), " → ".join(rec.get("phases") or []), "\n",
            ("Runtime  ", "dim"), runtime,
        )
        if rec.get("focus"):
            lines.append_text(Text.assemble("\n", ("Focus    ", "dim"), str(rec["focus"])))
        self.query_one("#info", Static).update(lines)

    def _refresh_stats(self) -> None:
        agg = self._aggregate
        if self._started_at is None:
            elapsed = 0.0
        else:
            elapsed = (self._finished_at or time.monotonic()) - self._started_at
        cost = f"${agg.cost:.4f}"
        cost_style = ""
        if self._budget:
            cost += f" / ${self._budget:.2f}"
            if agg.cost > self._budget:
                cost_style = "bold red"
        stats = Text.assemble(
            ("⏱ ", "dim"), _format_duration(elapsed), "   ",
            ("cost ", "dim"), (cost, cost_style), "   ",
            ("tokens ", "dim"), f"{agg.input_tokens:,} in / {agg.output_tokens:,} out", "   ",
            ("events ", "dim"), str(agg.events),
        )
        self.query_one("#stats", Static).update(stats)

    def _poll_findings(self) -> None:
        if self._run_dir is None:
            return
        path = self._run_dir / "evidence_store" / "findings.json"
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if mtime == self._findings_mtime:
            return
        self._findings_mtime = mtime
        self._findings = _read_findings(self._run_dir)
        table = self.query_one("#findings", DataTable)
        table.clear()
        for finding in self._findings:
            severity = str(finding.get("severity", "")).lower()
            table.add_row(
                str(finding.get("id", "")),
                Text(severity, style=_SEVERITY_STYLE.get(severity, "")),
                str(finding.get("title", "")),
                str(finding.get("location", "")),
                key=str(finding.get("id", "")),
            )
        self.query_one("#findings-pane").border_title = f"Findings ({len(self._findings)})"

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        key = event.row_key.value if event.row_key is not None else None
        finding = next((f for f in self._findings if str(f.get("id")) == key), None)
        detail = self.query_one("#finding-detail", Static)
        if finding is None:
            detail.update("")
            return
        body = Text.assemble(
            (str(finding.get("title", "")), "bold"), "\n",
            str(finding.get("cwe") or "no CWE"), "   ",
            ("area ", "dim"), str(finding.get("area") or "—"), "\n",
            str(finding.get("summary", "")),
        )
        detail.update(body)

    # -- quitting -----------------------------------------------------------

    def action_quit_monitor(self) -> None:
        running = self._process is not None and self._process.poll() is None
        if running and not self._quit_armed:
            self._quit_armed = True
            self.notify("Scan is still running. Press q again to stop it and exit.",
                        severity="warning", timeout=5)
            return
        if running and self._process is not None:
            self._process.terminate()
        self.exit()


class _Observer:
    """Bridges :class:`cli.RunObserver` callbacks from the scan thread to the
    app; falls back to stderr once the app has closed."""

    def __init__(self, app: ScanMonitor) -> None:
        self._app = app
        self.active = True

    def _call(self, fn: Callable[..., None], *args: Any) -> bool:
        if not self.active:
            return False
        try:
            self._app.call_from_thread(fn, *args)
        except RuntimeError:
            # App is shutting down or already gone.
            self.active = False
            return False
        return True

    def log(self, message: str) -> None:
        if not self._call(self._app.add_log, message):
            print(f"[striket] {message}", file=sys.stderr, flush=True)

    def run_started(self, run_dir: Path, record: dict[str, Any]) -> None:
        self._call(self._app.set_run, run_dir, record)

    def progress(self, hint: str | None, aggregate: EventAggregate) -> None:
        self._call(self._app.set_progress, hint, aggregate)

    def agent_started(self, process: subprocess.Popen[str]) -> None:
        # Store directly: the app must be able to stop the agent even if the
        # UI thread is busy.
        self._app.set_process(process)


def run_interactive(
    args: argparse.Namespace,
    cmd_run: Callable[[argparse.Namespace, Any], int],
) -> int:
    """Run the scan on a background thread and show :class:`ScanMonitor`.

    Returns the scan's exit code (same contract as non-interactive runs).
    """
    app = ScanMonitor(budget=args.max_budget)
    observer = _Observer(app)
    result: dict[str, int] = {}

    def worker() -> None:
        try:
            result["code"] = cmd_run(args, observer)
        except Exception as exc:  # noqa: BLE001 — report instead of dying silently
            observer.log(f"fatal: {exc}")
            result["code"] = 1
        observer._call(app.set_finished, result["code"])

    thread = threading.Thread(target=worker, name="striket-scan", daemon=True)
    app.call_later(thread.start)
    app.run()
    observer.active = False

    if thread.is_alive():
        print("[striket] waiting for the run to finalize…", file=sys.stderr, flush=True)
        thread.join()

    code = result.get("code", 1)
    record = app._record
    if record:
        print(
            f"[striket] {record.get('run_name')}: status={record.get('status')} "
            f"findings={record.get('findings_count', len(app._findings))} "
            f"cost={app._aggregate.cost:.4f}",
            file=sys.stderr,
        )
        for name, path in (record.get("artifacts") or {}).items():
            print(f"[striket]   {name}: {path}", file=sys.stderr)
    return code


__all__ = ["ScanMonitor", "run_interactive"]
