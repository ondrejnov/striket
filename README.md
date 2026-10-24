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
| Skill library | `harness/skills/` — vulnerabilities, frameworks, protocols, cloud, tooling, scan modes, analysis. |
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

First-phase scope is **M0–M2** (white-box code review), adapter **`claude`**
only, **headless** only. `claude-p` and `opencode` are accepted as known
adapters but are verified later (M4).

> [!NOTE]
> The `fix` phase is **intentionally disabled**. Neither scan mode runs it
> (`quick`: recon → testing; `deep`: recon → mapping → testing), so Striket
> only reports findings with their proposed remediation and never modifies the
> target. The `fix` role directive (`harness/agents/fix.md`) is kept from Strix
> but is not enabled in `orchestrator/scan_modes.py`.

## Install

```bash
pip install -e .            # provides the `striket` console script
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
| `run.json` | Run record: status, timings, targets, config, streamed cost/usage. |
| `final.json` | The agent's structured output, validated against the schema. |
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
  scan_modes.py   quick|deep -> timeout, depth, allowed phases
  scope.py        scope block for the prompt + in-scope-only validation
  events.py       streaming parser for agentiscode --json events
  report.py       final.json -> markdown + vulnerabilities.json + SARIF
schemas/
  final_output.schema.json
```
