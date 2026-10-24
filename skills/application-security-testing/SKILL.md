---
name: application-security-testing
description: Application security testing (AppSec) across a whole product with Striket — decide which asset needs which review, run it, and turn the results into one ranked remediation plan ordered by proven impact. Use when the user asks for an application security review or audit, an appsec assessment, vulnerability scanning across their stack, a security review before a launch or a customer security questionnaire, or does not yet know which kind of security test they need. This is the entry point when the target is not yet a single repo or URL.
---

# Application security testing

Entry point for "make my application secure" requests, where the target is not
yet a single repo or URL. The job is to pick the right review per asset, run it,
and produce one ranked plan — not to run everything at maximum depth.

Install, prerequisites, flags, scope rules, and exit codes live in
**penetration-testing-with-striket**. Read it first if `striket --help` fails.

> [!IMPORTANT]
> Only test assets the user owns or is authorized to test. Scope is validated in
> the orchestrator before the agent runs; out-of-scope targets are refused.
> Striket's current phase is white-box code review — it reports findings and
> proposed remediation and never modifies the target.

## 1. Map the assets

Ask (or read from the repo) and write the answers down before scanning:

- **Source** — one repo, a monorepo, several services? Which languages/frameworks?
- **APIs** — REST, GraphQL, gRPC? Where does the authorization logic live?
- **Authentication model** — how is identity established, and how is tenancy
  enforced? Most high-impact bugs are authorization-shaped.
- **Constraints** — out-of-scope paths, budget and wall-clock limits.

Striket's current scope is white-box: it reasons about the source. A live
black-box pentest of a running deployment is **not** in this phase (see
**penetration-testing-with-striket**), so if the user expected DAST against a
URL, say so early and plan a source review instead.

## 2. Pick the review per asset

| Asset                                                | Skill to use                              |
| ---------------------------------------------------- | ----------------------------------------- |
| Repository or working tree                           | **find-security-vulnerabilities-in-code** |
| REST/GraphQL/gRPC API source and authz model         | **api-security-testing**                  |
| Web app source (routes, templates, session handling) | **web-app-penetration-testing**           |
| Assessment mapped to OWASP categories                | **owasp-top-10-testing**                  |
| Every pull request, continuously                     | **ci-security-scanning**                  |

Those skills carry the flags, focus hints, and result-reading details — do not
duplicate them here.

Sequence for a first assessment:

1. Review the code. It is the cheapest run and it maps the authorization model.
2. Re-run with a tighter `--focus` on the risky subtrees the first pass surfaced.
3. Add CI scanning so later regressions are caught without another manual pass.

Run one asset at a time and read each report before starting the next — findings
from an early pass make the next `--focus` sharper.

## 3. Consolidate into one plan

Findings arrive per run in `striket_runs/<run>/`. Merge them into a single list
and rank by **impact**, not by alphabetized severity:

1. Findings reachable without authentication.
2. Cross-tenant or privilege-escalation issues.
3. Issues needing an authenticated account.
4. Hardening and configuration notes — flag as such; never present them as
   confirmed exploitable vulnerabilities.

Deduplicate: the same root cause often surfaces across two services.

## 4. Be honest about coverage

State plainly what was _not_ reviewed — assets not pointed at, categories a
source review cannot reach (runtime-only behavior, logging/alerting pipelines,
supply-chain integrity), and any run that hit its budget before finishing. Check
each `run.json` `status` (`completed` vs `partial`) and streamed cost against
`--max-budget`. An empty result set from a truncated scan is not a clean bill of
health.

Remediation is manual — the `fix` phase is disabled. After the team patches each
root cause, re-run Striket scoped to the change to confirm the finding is gone.
