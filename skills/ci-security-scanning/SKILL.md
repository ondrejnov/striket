---
name: ci-security-scanning
description: Add Striket security scanning to CI/CD — GitHub Actions, GitLab CI, or any pipeline — so every pull request gets a white-box security review that can block a merge when high-severity findings appear, with SARIF uploaded to code scanning. Self-hosted: Striket runs in your runner on the `agentiscode` runtime; there is no managed platform. Use when the user asks to add security scanning, SAST, pentesting, vulnerability checks, or automated security review to their CI pipeline, pre-merge gate, or PR workflow.
---

# Set up Striket in CI/CD

Striket is self-hosted: it runs in your own runner and drives the `agentiscode`
agent. There is **no managed platform and no `striket cloud`** — if you came from
a Strix CI skill looking for the hosted app, there isn't one here. Every run
emits SARIF 2.1.0, so results upload to GitHub code scanning.

Install, prerequisites, flags, scope rules, and the artifact layout are in
**penetration-testing-with-striket**. Read it first if `striket --help` fails.

## The one thing that is different from Strix CI

Striket's **exit code is not a findings signal.** `0` means the run completed and
reports were written — _even when it found critical vulnerabilities_; `1` is a
fatal error; `2` is a usage error (bad args / out-of-scope target). There is no
`--fail-on` flag. So you cannot gate a build on the exit code the way Strix does.

Instead, gate on the **artifacts**: after a `0` exit, read
`striket_runs/<run>/run.json` (`status`, `findings_count`) and
`vulnerabilities.json` (per-finding `severity`), and fail the job yourself when a
finding at or above your threshold appears. The helper step below does exactly
that.

There is also no diff-scoping flag (`--scope-mode` / `--diff-base` do not exist
yet), so a PR scan reviews the target you point it at. Point `--target` at the
service or subtree that the PR touches to keep the run fast and focused.

## GitHub Actions

Create `.github/workflows/security.yml`:

```yaml
name: Security Scan

on:
  pull_request:

jobs:
  striket-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install Striket and the agentiscode runtime
        run: |
          pip install -e .
          # Install the agentiscode CLI onto PATH per your runtime's install docs,
          # and make its model/telemetry credentials available as CI secrets in the
          # job environment — Striket itself holds no credentials.

      - name: Run Striket
        env:
          # The agent inherits auth from the agentiscode runtime's environment.
          # Put whatever that runtime needs here as repository secrets.
          AGENTISCODE_TOKEN: ${{ secrets.AGENTISCODE_TOKEN }}
        run: |
          striket run --target ./ --scan-mode quick --max-budget 10 --headless \
            --run-name "ci-${{ github.run_id }}"

      - name: Gate on findings and completion
        run: |
          run_json=$(ls -t striket_runs/*/run.json | head -1)
          run_dir=$(dirname "$run_json")
          status=$(jq -r .status "$run_json")

          # Don't fail open: a capped run reports "partial", not "completed".
          if [ "$status" = "failed" ]; then
            echo "Striket run failed — see the report." >&2
            exit 1
          fi
          if [ "$status" = "partial" ]; then
            echo "Striket run is 'partial' (budget likely exhausted) — coverage is incomplete. Raise --max-budget." >&2
            exit 1
          fi

          # Fail the build on any high/critical finding (tune the set to taste).
          high=$(jq '[.[] | select(.severity=="high" or .severity=="critical")] | length' \
                   "$run_dir/vulnerabilities.json")
          echo "High/critical findings: $high"
          if [ "$high" -gt 0 ]; then
            echo "Striket found $high high/critical finding(s) — blocking merge." >&2
            exit 1
          fi

      - name: Upload SARIF
        if: always()
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: striket_runs
```

Tell the user to add whatever secrets the `agentiscode` runtime needs (for
example its auth token) as repository secrets. **Do not create those values
yourself.** Striket stores no LLM key — the agent authenticates through the
runtime's environment, which on a subscription login can avoid metered API spend.

## Other CI systems

The pattern is identical — install, make the runtime's auth available, run
headless, then gate on the artifacts:

```bash
pip install -e .
# install the agentiscode CLI onto PATH per its docs

striket run --target ./ --scan-mode quick --max-budget 10 --headless --run-name "ci-$CI_JOB_ID"

run_json=$(ls -t striket_runs/*/run.json | head -1)
run_dir=$(dirname "$run_json")
[ "$(jq -r .status "$run_json")" = "completed" ] || { echo "run not completed — raise --max-budget" >&2; exit 1; }
high=$(jq '[.[] | select(.severity=="high" or .severity=="critical")] | length' "$run_dir/vulnerabilities.json")
[ "$high" -eq 0 ] || { echo "high/critical findings present — failing build" >&2; exit 1; }
```

## Size the budget so the scan completes

A completed run with no high findings is only trustworthy if the review actually
finished. `--max-budget` caps spend; if the cap is hit, `run.json` `status`
becomes `partial` and coverage is incomplete. The gate step above refuses to pass
a `partial` run, which keeps the pipeline from failing open. Give the scan real
headroom — compare `run.json`'s streamed cost against `--max-budget`, and raise
the budget if a run keeps ending `partial`. For a focused `quick` PR scan on a
single service, `--max-budget 10` is usually ample; raise it for large subtrees
or `deep` scans.

Schedule `deep` scans (`--scan-mode deep`) nightly or for release candidates,
where the longer wall-clock budget is acceptable.

## Remediation

The `fix` phase is disabled — Striket never modifies code. A failing gate means a
human patches the root cause, then the next PR run re-reviews it. To fix
findings from an existing run, see **find-security-vulnerabilities-in-code**.
