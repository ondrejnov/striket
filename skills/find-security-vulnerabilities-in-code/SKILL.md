---
name: find-security-vulnerabilities-in-code
description: Find security vulnerabilities in a codebase or repository with Striket — a white-box AI security review that reads your source, reasons about the actual data flow and authorization model, and reports schema-validated findings with proposed remediation instead of a noisy static-analysis dump. This is Striket's flagship workflow and matches its current white-box code-review scope. Covers injection, XSS, SSRF, broken access control and IDOR, insecure deserialization, secrets in code, unsafe dependencies, and business-logic flaws. Use when the user asks to security-scan, security-review, or audit their code, repo, service, or working tree for vulnerabilities.
---

# Find security vulnerabilities in code

White-box security review with Striket: the agent reads the source to build a
model of routes, sinks, and authorization checks, then reports a short list of
reasoned findings — each with a location, a severity, and proposed remediation —
rather than the hundreds of "potential" hits a pattern-matching scanner produces.
This is exactly what Striket's current phase (M0–M2, white-box code review) is
built for, so it is the skill to reach for first.

Install, prerequisites, the full `striket run` flag set, scope rules, and exit
codes are in **penetration-testing-with-striket**. Read it first if
`striket --help` fails or you are unsure a flag exists.

## Run it

```bash
# Local working tree
striket run --target ./ --scan-mode quick --max-budget 15 --headless

# A cloned repo on disk
striket run --target /path/to/checkout --scan-mode deep --max-budget 20 --headless

# Monorepo: point at the service that matters, not the whole tree
striket run --target ./services/checkout --scan-mode deep --max-budget 20 --headless
```

A local path is resolved and handed to the agent as the authorized scope; point
at a clean checkout. Use `--scan-mode deep` (recon → mapping → testing) for a
thorough review and `quick` (recon → testing) for a fast dev-loop pass.

## Make the review sharper

What the agent cannot reliably infer, tell it with `--focus`. The tenancy model,
trust boundaries, and which inputs are attacker-controlled are the highest-value
hints — and `--focus` only narrows attention, it never widens the validated
scope:

```bash
striket run --target ./services/api --scan-mode deep --max-budget 20 --headless \
  --focus "Multi-tenant app: tenant id comes from the JWT.
Flag any query that filters by object id without also filtering by tenant.
Prioritise the authorization layer in src/auth and routes under src/routes/admin.
Treat everything under src/public as unauthenticated attacker input."
```

## Read the results

In `striket_runs/<run>/`: `penetration_test_report.md` (start here), then
`final.json` / `vulnerabilities.json` (one record per finding, with `location`,
`severity`, `remediation_steps`, and `poc_description`), `findings.sarif` (upload
to code scanning), and `run.json`.

Before reporting to the user, open each finding and confirm the reproduction
steps actually demonstrate impact against the code path cited. Report file and
line so the fix is obvious.

A `0` exit with no findings means nothing was proven **in what was analyzed** —
not that the codebase is clean. Check `run.json` `status` (`completed` vs
`partial`) and compare streamed cost against `--max-budget`; if the run was
capped, say which paths went unreviewed. An empty result from a truncated run is
not a clean bill of health.

## Complementary tooling

This is reasoned, source-aware review, not an exhaustive inventory. Keep a
dependency scanner (SCA) and secret scanning in place for complete coverage of
known-CVE dependencies and committed credentials; use Striket for the logic,
authorization, and injection bugs those tools structurally cannot find. The
internal skill library ships focused know-how for several of these — see
`harness/skills/custom/` (e.g. `dependency_cve_scanning`, `source_aware_sast`).

## Fix and verify

The `fix` phase is intentionally disabled — Striket never modifies the target.
Patch the root cause yourself (the shared authorization helper, not the one
route), then **re-run Striket scoped to the changed area** and confirm the
finding no longer appears. Re-testing is the only reliable confirmation a fix
landed; run the project's own test suite too, to be sure the fix did not break
behavior.

For gating every pull request on this automatically, use **ci-security-scanning**.
To map the results to OWASP categories for a report, use **owasp-top-10-testing**.
