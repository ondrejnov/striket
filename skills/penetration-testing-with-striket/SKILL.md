---
name: penetration-testing-with-striket
description: Run an authorized security review of a codebase, repository, URL, domain, or IP with Striket — a thin orchestrator that drives an autonomous security agent on the `agentiscode` runtime and returns schema-validated findings with proposed remediation (Markdown report, JSON, SARIF 2.1.0). This is the base skill for every Striket run: install, prerequisites, the full `striket run` flag set, scan modes, scope enforcement, exit codes, and where the artifacts land. Use whenever the user wants to pentest, security-scan, security-audit, or find vulnerabilities in an app, API, website, or repo with Striket, or when another Striket skill tells you to read it first. Read this if `striket --help` fails or you are unsure which flags exist.
---

# Run a Striket security review

Striket is a port of [Strix](https://github.com/usestrix/strix) to the
[`agentiscode`](https://github.com/ondrejnov/agentiscode-cli) CLI runtime. It
keeps Strix's operational doctrine, skill library, and Strix-compatible output,
but **drops Strix's own agent engine**: the agent loop, tool calling, and model
access come from `agentiscode`. The orchestrator validates scope, builds and
runs the agent, streams its events, and renders reports from the agent's
structured final output.

Two consequences follow, and they shape every other skill:

- **There is no managed cloud and no `striket cloud` command.** Striket holds no
  LLM credentials; the agent inherits authentication from the environment of the
  `agentiscode` runtime. If you came from a Strix skill looking for a hosted path,
  there isn't one here — run locally.
- **The `fix` phase is intentionally disabled.** Striket only _reports_ findings
  with proposed remediation; it never modifies the target. Neither scan mode runs
  `fix`. Remediation is a human's job (re-run Striket afterward to confirm the
  finding is gone).

> [!IMPORTANT]
> Only scan targets you are authorized to test. Scope is validated in the
> orchestrator **before** the agent runs; an out-of-scope target exits with code
> `2` and the agent never starts. Confirm authorization yourself if a target
> looks like third-party infrastructure.

## Current scope (read before promising coverage)

First-phase scope is **M0–M2: white-box code review**, adapter **`claude`**,
**headless** only. The scan phases do source analysis (recon → mapping →
testing) with no browser/HTTP exploitation yet, so a live black-box pentest of a
running URL is **not** functional in this phase even though a URL/domain is
accepted as a target. `claude-p` and `opencode` are recognized adapters but are
verified later (M4). Be honest with the user about this instead of implying a
full DAST run.

## Prerequisites

1. **Install Striket** — from the repo root:
   ```bash
   pip install -e .            # provides the `striket` console script (Python 3.12+)
   ```
2. **`agentiscode` on `PATH`** — Striket shells out to it. The agent's model and
   telemetry credentials live in that runtime's environment, **never** in the
   Striket repo, config, or prompt.

Check both with `striket --help` and `agentiscode --version`. If `striket` is
missing, you have not installed the package; fix that before anything else.

## Running a review

Always pass `--headless` — it is the only supported mode. Always set
`--max-budget` unless the user says otherwise.

```bash
# Local working tree (white-box — the current sweet spot)
striket run --target ./ --scan-mode quick --max-budget 10 --headless

# A specific service in a monorepo (scope narrowly, do not point at the whole tree)
striket run --target ./services/checkout --scan-mode deep --max-budget 20 --headless

# Steer attention without widening scope
striket run --target ./services/api --max-budget 15 --headless \
  --focus "authorization layer in src/auth; every route under src/routes/admin;
multi-tenant app, tenant id comes from the JWT; flag any query that filters by
object id without also filtering by tenant"
```

### Flags (`striket run`)

| Flag                                      | Meaning                                                                                                                                                                |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--target`, `-t`                          | Authorized target: local path, URL, repo URL, domain, or IP. **Repeatable.** Scope is the union of these and nothing else.                                             |
| `--adapter`, `-a`                         | Agent runtime: `claude` (default) · `claude-p` · `opencode`. Unknown adapter → exit `2`.                                                                               |
| `--model`, `-m`                           | Model id passed through to `agentiscode` (optional).                                                                                                                   |
| `--effort`, `-e`                          | Reasoning effort hint (optional).                                                                                                                                      |
| `--scan-mode`                             | `quick` or `deep` (see below). There is no `standard` mode.                                                                                                            |
| `--max-budget USD`                        | Budget ceiling tracked against streamed cost hints. On a flat-rate adapter login the hint may not reflect real spend.                                                  |
| `--focus`, `-f`                           | Operator guidance on what to prioritise. Each non-empty line becomes one bullet, **bounded by the validated scope — focus narrows attention, it never extends scope.** |
| `--headless`                              | Headless run (JSON events). Required.                                                                                                                                  |
| `--config`                                | Path to a `striket.toml` / `.striket.toml` (or `$STRIKET_CONFIG`).                                                                                                     |
| `--run-name`                              | Override the run directory name.                                                                                                                                       |
| `--task-id` / `--project-id` / `--run-id` | Telemetry ids (optional).                                                                                                                                              |

There is deliberately **no** `--instruction`, credentials, `--target-list`,
`--workspace-file`, `--resume`, `--scope-mode`, `--diff-base`, or `--fail-on`
flag. Do not invent them. Operator guidance goes through `--focus` only; the repo
carries no payloads or exploits, so there is nowhere to pass a credential block in
this phase.

### Scan modes

| Mode    | Phases                    | Depth   | Timeout    |
| ------- | ------------------------- | ------- | ---------- |
| `quick` | recon → testing           | shallow | ~15 min    |
| `deep`  | recon → mapping → testing | deep    | up to ~3 h |

The `fix` phase exists as a role directive (`harness/agents/fix.md`) but is not
enabled by either mode.

### Configuration

Resolution order is fixed: `built-in defaults < config file < environment < CLI
flags`. A config file may set `adapter`, `model`, `effort`, `scan_mode`,
`max_budget`, `focus`, `permission_mode`, and `disallowed_tools` (optionally under
a `[striket]` table). Environment variables use the `STRIKET_` prefix
(e.g. `STRIKET_ADAPTER`, `STRIKET_MODEL`). No secret belongs in any of these.

## Exit codes

| Code | Meaning                                                                                                                      |
| ---- | ---------------------------------------------------------------------------------------------------------------------------- |
| `0`  | Success — the run completed and reports were written. **This is not a finding signal:** a run with findings still exits `0`. |
| `1`  | Fatal error — launch failed, or `final.json` was missing/invalid.                                                            |
| `2`  | Usage error — bad arguments, unknown adapter, or an out-of-scope target (the agent never ran).                               |

Because `0` says nothing about _whether_ vulnerabilities were found, decide that
by reading the artifacts, not the exit code. See **Reading results**.

## Reading results

Each run writes `striket_runs/<run-name>/` (Strix-compatible layout):

| File                         | Contents                                                                                                                                |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `penetration_test_report.md` | Human-readable executive report — **read this first.**                                                                                  |
| `final.json`                 | The agent's structured output, validated against `schemas/final_output.schema.json`. Findings come only from here.                      |
| `vulnerabilities.json`       | Findings as Strix-shaped records (`id`, `title`, `severity`, `cwe`, `description`, `remediation_steps`, `poc_description`, `evidence`). |
| `findings.sarif`             | SARIF 2.1.0 — one run, each finding a result with `ruleId` / `level` / `locations`. Uploads to GitHub code scanning.                    |
| `run.json`                   | Run record: `status`, `findings_count`, timings, targets, config, streamed cost/usage.                                                  |
| `session.id`                 | Adapter session id (telemetry).                                                                                                         |

Finding severities are `info | low | medium | high | critical`. Run `status` is
`completed`, `partial`, or `failed`.

Before reporting to the user, open each finding and check the `reproduction`
steps actually demonstrate impact; report file and line (the `location`) so the
fix is obvious. A `0` exit with an empty `findings` array means nothing was proven
**in what was analyzed** — not that the code is clean. Check `run.json` `status`
and compare its streamed cost against `--max-budget`: if the run hit the ceiling
it may be `partial`, and an empty result from a truncated run is not a clean bill
of health. Note which paths went unreviewed.

## Next steps

- Scope the review to a codebase → **find-security-vulnerabilities-in-code**.
- Map findings to OWASP categories → **owasp-top-10-testing**.
- Review an API's source and authorization model → **api-security-testing**.
- Don't yet know which test you need → **application-security-testing**.
- Gate pull requests in CI → **ci-security-scanning**.

Remediation is manual (the `fix` phase is off). After a human patches the root
cause, re-run Striket scoped to the changed area to confirm the finding no longer
appears.
