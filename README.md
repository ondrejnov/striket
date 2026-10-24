# Striket

Striket is a **port of [Strix](https://github.com/usestrix/strix)** — the
open-source AI security-testing agent — to the
[`agentiscode`](https://github.com/ondrejnov/agentiscode-cli) CLI runtime. It carries over Strix's *know-how*
(operational doctrine, skill library, output/report formats, sandbox) and
deliberately **drops Strix's own agent engine**. The orchestrator is a thin
wrapper: it validates scope, builds and runs `agentiscode`, streams its events,
and renders reports from the agent's structured final output.

> [!IMPORTANT]
> Only scan targets you are authorized to test. Scope is validated in the
> orchestrator **before** the agent runs; out-of-scope targets are refused.

## What is ported from Strix

| Area | In Striket |
|---|---|
| Operational doctrine | `harness/CLAUDE.md`, derived from Strix's system prompt; the authorization/scope rules are carried verbatim. |
| Agent roles | `harness/agents/{root,recon,mapping,testing,fix}.md`. |
| Skill library | `harness/skills/` — vulnerabilities, frameworks, protocols, cloud, tooling, scan modes, analysis, coordination (incl. `blackbox_web`). |
| Notes, coverage, findings | `mcp/evidence_store/` — a small MCP server replacing Strix's notes/coverage/threat-model/reporting tools; also stores HTTP evidence. |
| Browser | Vercel `agent-browser` CLI, unchanged, driven via Bash. The Caido proxy is not ported; direct HTTP uses `curl` / `httpx`. |
| Run layout and reports | `striket_runs/<run-name>/` in the Strix-compatible layout, with `vulnerabilities.json` in Strix-shaped records. |
| Sandbox | `containers/` (Dockerfile and entrypoint). |

## Advantages over Strix

- **No custom agent engine to maintain.** The agent loop, tool calling, and
  model access come from `agentiscode`; Striket only orchestrates. Engine
  improvements arrive without changes here.
- **Adapter-agnostic.** The model runtime is chosen with `--adapter`
  (`claude`, `opencode`) and isolated in one module, rather than
  tied to a single LLM client layer.
- **Subscription instead of pay-per-token API.** Striket holds no LLM
  credentials and no model client; the agent inherits authentication from the
  environment of the `agentiscode` runtime. If your adapter is signed in with a
  prepaid/flat-rate plan, scans can run on that instead of metered API tokens,
  which is usually much cheaper for long, many-step audits.

  > [!NOTE]
  > Whether a subscription login works depends on `agentiscode` and the chosen
  > adapter, and on the provider's terms of use for automated or headless
  > usage. Check both before relying on it. `--max-budget` tracks streamed
  > cost hints, which may not reflect real spend on a flat-rate plan.

- **Scope enforced before the agent starts.** Targets are validated in
  `orchestrator/scope.py`; out-of-scope targets exit with code `2` and the
  agent never runs. `--focus` narrows attention but never widens scope.
- **Structured, validated output.** The agent must return JSON conforming to
  `schemas/final_output.schema.json`. Findings come from validated
  `final.json`, never from free-text parsing.
- **CI-friendly results.** Besides the Markdown report, every run emits
  **SARIF 2.1.0** (`findings.sarif`) and documented exit codes.
- **Predictable configuration.** One resolution order (defaults < config
  file < environment < CLI flags), no hardcoded values, and no secrets in the
  repo, config, or prompt.
- **Cost ceiling.** `--max-budget` tracks spend against streamed cost hints.
- **Methodology only.** The repo contains no payloads or exploits; file
  contents and command output are treated as data, which limits prompt-injection
  from the scanned code.

## Status

First-phase scope is **M0–M3** — white-box code review (M0–M2) and black-box
web testing (M3) — with adapter **`claude`** only, **headless** only. `claude-p` and `opencode` are accepted as known
adapters but are verified later (M4).

> [!NOTE]
> The `fix` phase is **intentionally disabled**. No phase plan runs it, so Striket
> only reports findings with their proposed remediation and never modifies the
> target. The `fix` role directive (`harness/agents/fix.md`) is kept from Strix
> but is not enabled in `orchestrator/scan_modes.py`.

The phase plan depends on the scan mode and on the classified target types:

| Targets | `quick` | `deep` |
|---|---|---|
| Code (local path) | recon → testing | recon → mapping → testing |
| URL / domain / IP | recon → mapping → testing | recon → mapping → testing |
| Mixed | ordered union of both | ordered union of both |

Black-box runs always include `mapping`, because routes, parameters and the
auth model must be discovered by crawling instead of read from source.

## Install

Global install with [pipx](https://pipx.pypa.io/) (recommended; `striket` is
available from any directory):

```bash
pipx install .              # from the repo root; installs into ~/.local/bin
pipx reinstall striket      # pick up local code changes after editing
pipx uninstall striket      # remove
```

Use `pipx install --editable .` instead if changes in the repo should take
effect without reinstalling.

For development inside a virtualenv:

```bash
pip install -e ".[dev]"     # provides the `striket` console script + dev tools
```

Requires Python 3.12+ and the [`agentiscode`](https://github.com/ondrejnov/agentiscode-cli) CLI on `PATH`. LLM/telemetry keys
live in the environment the sandboxed agent inherits — never in the repo, the
config, or the prompt.

## Usage

```bash
striket run \
  --target ./            \   # authorized target (repeatable): path, URL, domain, IP
  --adapter claude       \   # opencode | claude | claude-p (default: claude)
  --model <model-id>     \   # optional; passed to agentiscode -m
  --effort high          \   # optional
  --scan-mode quick      \   # quick | deep
  --max-budget 10        \   # USD ceiling tracked against streamed cost hints
  --focus "auth, IDOR"   \   # optional: what to prioritise (never widens scope)
  --headless                 # headless run (JSON events); the only supported mode
```

This builds and runs `agentiscode`, reads its `--json` events as they stream,
and writes a run under `striket_runs/<run-name>/`.

### Black-box web testing

A run becomes black-box when any target is a URL, domain or IP
(`orchestrator/scope.py` classifies targets; `scan_modes.is_black_box` decides).

```bash
striket run --target https://staging.example.com --scan-mode quick --headless
```

> [!IMPORTANT]
> Black-box runs send live traffic to the target. Only point Striket at assets
> you are explicitly authorized to test.

For a black-box run the orchestrator:

- selects the black-box phase plan (see [Status](#status)),
- adds a `BLACK-BOX WEB RUN` block to the prompt that tells the agent to use the
  `agent-browser` CLI and direct HTTP (`curl` / `httpx`) via Bash, strictly
  within the authorized scope,
- records `"black_box": true` and the resolved `phases` in `run.json`.

The agent loads the `blackbox-web` coordination skill
(`harness/skills/coordination/blackbox_web/`) plus the `agent_browser` and
`httpx` tooling skills. The mapping and testing roles in `harness/agents/`
carry the black-box methodology alongside the white-box one.

#### HTTP evidence

Every HTTP interaction that backs a finding must be stored as evidence and cited
by the finding:

1. The agent stores the raw request/response pair with
   `mcp__evidence_store__add_evidence` (`type="http"`), using the
   `=== REQUEST ===` / `=== RESPONSE ===` text convention. Secrets are redacted.
2. The tool returns a ref such as `evidence:E-0001`.
3. The finding cites it: `evidence: [{"type": "http", "ref": "evidence:E-0001"}]`.
   Unknown refs are rejected.

The evidence flows into `final.json` and the reports. Details are in
[`mcp/evidence_store/README.md`](mcp/evidence_store/README.md#http-evidence-black-box-runs).

### Configuration

Every tunable has a default in `orchestrator/config.py`. Resolution order:

```
built-in defaults  <  config file  <  environment  <  CLI flags
```

A config file (`striket.toml` / `.striket.toml`, or `$STRIKET_CONFIG`) may set
`adapter`, `model`, `effort`, `scan_mode`, `max_budget`, `focus`, `permission_mode`, and
`disallowed_tools`, optionally under a `[striket]` table. Environment variables
use the `STRIKET_` prefix (e.g. `STRIKET_ADAPTER`, `STRIKET_MODEL`). No value is
hardcoded at a call site, and no secret belongs in this file.

### Focus

`--focus` (or `focus` in the config file, or `STRIKET_FOCUS`) adds operator
guidance on what the scan should prioritise. Each non-empty line becomes one
bullet in a `FOCUS` section of the prompt, explicitly bounded by the validated
scope — focus narrows attention, it never extends the scope. The value is
recorded in `run.json`.

## Artifacts

Each run directory (`striket_runs/<run-name>/`, Strix-compatible) holds:

| File | Contents |
|---|---|
| `run.json` | Run record: status, timings, targets, config, resolved `phases`, `black_box` flag, streamed cost/usage. |
| `final.json` | The agent's structured output, validated against the schema. |
| `evidence_store/` | Notes, coverage, threat models, evidence (including HTTP request/response pairs) and findings recorded during the run. |
| `session.id` | The adapter session id (for resume/telemetry). |
| `penetration_test_report.md` | Human-readable executive report. |
| `vulnerabilities.json` | Findings as Strix-shaped vulnerability records. |
| `findings.sarif` | SARIF 2.1.0 (one run; each finding a result with `ruleId`/`level`/`locations`). |

The final output schema is `schemas/final_output.schema.json` (JSON Schema
draft 2020-12), passed to `agentiscode --output-schema`. Findings are taken from
the validated `final.json`, never from free text.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success — the run completed and reports were written. |
| `1` | Fatal error — launch failed, or `final.json` was missing/invalid. |
| `2` | Usage error — bad arguments, unknown adapter, or out-of-scope target. |

## Design

- **Adapter-agnostic.** `orchestrator/harness.py` isolates every
  adapter-specific detail behind one interface; the rest of the orchestrator
  never branches on the adapter.
- **No payloads or exploits in the repo.** Know-how is methodology; concrete
  actions are the runtime agent's job on an approved, in-scope target.
- **Data, not instructions.** File contents and command output read during a
  run are treated as data.

### Module map

```
orchestrator/
  cli.py          `striket run` entry point; run.json; exit codes
  harness.py      build & run the agentiscode command (adapter validation)
  config.py       defaults + config-file/env loader
  scan_modes.py   quick|deep -> timeout, depth, white-box/black-box phase plans
  scope.py        scope block for the prompt + in-scope-only validation
  events.py       streaming parser for agentiscode --json events
  report.py       final.json -> markdown + vulnerabilities.json + SARIF
harness/
  CLAUDE.md       operational doctrine (white-box + black-box rules)
  agents/         root, recon, mapping, testing, fix role directives
  skills/         ported skill library (incl. coordination/blackbox_web)
mcp/
  evidence_store/ MCP server: notes, coverage, threat models, evidence, findings
schemas/
  final_output.schema.json
tests/            focus, HTTP-evidence capture, SARIF validation
containers/       sandbox image (agent-browser, httpx, scanners)
```
