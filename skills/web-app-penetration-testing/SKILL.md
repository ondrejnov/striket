---
name: web-app-penetration-testing
description: Security-review a web application with Striket — a white-box, source-driven review of the app's routes, request handling, templates, session/auth code, and access-control logic that surfaces auth bypass, broken access control, IDOR, injection, XSS, SSRF, and business-logic flaws with a location and proposed remediation. Use when the user asks to pentest, security-test, or audit their web app, website, web application, or the code behind a staging site. (Live black-box DAST against a running URL is not in Striket's current phase — this reviews the source.)
---

# Security-review a web application

Striket reviews a web app from its **source**: the agent reads the route
handlers, input parsing, templating, session and auth code, and access-control
checks, and reports reasoned findings with a location and proposed remediation.

Install, prerequisites, the full flag set, scope rules, and exit codes are in
**penetration-testing-with-striket** — read it if `striket --help` fails.

> [!NOTE]
> This is **not** a live black-box pentest. Striket's current phase has no
> browser/HTTP exploitation and no way to pass login credentials, so it does not
> crawl a running site or send exploit payloads. A URL/domain is accepted as a
> target and recorded as scope, but the actual review reasons about code. Point
> Striket at the app's repository (or the subtree that serves the web surface),
> and frame findings as source-reasoned — recommend a human request-level retest
> for the high-impact ones. Live DAST is on the roadmap (M4+), not this phase.

## 1. Confirm authorization and scope

- **The target is the user's**, or they are explicitly authorized to review it.
- **Point at the right source** — the repo or the subtree that serves the web
  surface (routes, controllers, templates, auth), not the whole monorepo.
- **Out-of-scope paths** — note anything vendored or third-party so `--focus` can
  steer attention away from it.

Scope is validated before the agent runs; an out-of-scope or non-existent path
exits `2` and the agent never starts.

## 2. Run the review

```bash
striket run --target ./ --scan-mode deep --max-budget 20 --headless \
  --focus "Web app review. Session auth; user identity comes from the signed cookie.
Focus on access control between the two tenant orgs, IDOR on object routes,
and any server-rendered template that interpolates request input without escaping.
Treat everything under /public as unauthenticated attacker input.
Out of scope: anything under src/vendor."
```

What matters for web apps specifically:

- **Access control is the top class.** Multi-tenant IDOR and broken-access-control
  bugs are consistently the highest-impact findings — tell the agent in `--focus`
  how identity and tenancy are established so it can spot a missing object-ownership
  check. `--focus` narrows attention; it never widens the validated scope.
- **Point at the subtree that matters** rather than the whole tree, so the budget
  goes to the web surface. `--target` is repeatable if the frontend and backend
  live in separate paths.
- **`--scan-mode quick`** for a fast dev-loop pass (recon → testing); `deep`
  (recon → mapping → testing) for a thorough pre-release review. Always set
  `--max-budget`.

## 3. Review results

Read `striket_runs/<run>/penetration_test_report.md` first, then the findings in
`final.json` / `vulnerabilities.json` — each carries the `location` and
`remediation_steps`. Trace each finding's code path yourself to confirm the issue
is reachable before reporting it; for access-control findings, recommend a
request-level retest with two accounts as the ground-truth confirmation.

A `0` exit with no findings is not proof of full coverage — if the budget was hit
the run may be `partial`, so check `run.json` `status` and streamed cost against
`--max-budget` before calling the app clean.

## 4. Fix and re-review

The `fix` phase is disabled — Striket never modifies the app. Patch the root
cause (the shared authorization/escaping helper, not the single route), then
re-run Striket scoped to the changed area to confirm the finding no longer
appears. To keep the app reviewed on every change rather than once, wire it into
CI with **ci-security-scanning**. For category mapping, see **owasp-top-10-testing**.
