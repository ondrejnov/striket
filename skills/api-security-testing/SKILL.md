---
name: api-security-testing
description: Security-review a REST, GraphQL, or gRPC API with Striket — a white-box review that reads the API's source and reasons about the authorization model to find the API-specific vulnerability classes in the OWASP API Security Top 10 (2023): broken object-level authorization (BOLA/IDOR), broken object property level authorization (excessive data exposure and mass assignment), broken function-level authorization, unrestricted resource consumption, SSRF, injection, and auth/token flaws. Use when the user asks to security-test, audit, or find vulnerabilities in an API, endpoint, or backend service.
---

# Security-review an API

APIs fail differently from web UIs: the interesting bugs are authorization-shaped
rather than injection-shaped, and the same endpoint behaves differently per
caller. Striket's current phase reviews those specifics **from the source** —
reading the route handlers, the authorization middleware, and the serializers —
using the [OWASP API Security Top 10 (2023)](https://owasp.org/API-Security/editions/2023/en/0x11-t10/)
as the coverage checklist.

Install, prerequisites, the full flag set, scope rules, and exit codes are in
**penetration-testing-with-striket**. Read it if `striket --help` fails.

> [!NOTE]
> Live black-box API exploitation (sending real requests with two tenants'
> tokens) is **not** in Striket's current phase — there is no credential/instruction
> flag and the scan phases do no HTTP work yet. What Striket does now is reason
> about the authorization code: whether a handler enforces object ownership,
> whether a serializer over-exposes fields, whether an admin route checks role.
> That is where most high-impact API bugs actually live. Frame findings as
> source-reasoned, and recommend a request-level retest by a human for the ones
> that matter.

## 1. Point at the API source and name the model

The biggest coverage win is telling the agent the tenancy and trust model it
cannot infer, via `--focus` (which narrows attention but never widens scope):

```bash
striket run --target ./services/api --scan-mode deep --max-budget 20 --headless \
  --focus "OWASP API Top 10 (2023) review.
Multi-tenant: org id is on the JWT; every object belongs to an org.
API1 (BOLA): flag any handler that loads an object by id without also checking it
belongs to the caller's org.
API3: flag serializers that return fields the caller should not see, and PATCH/PUT
handlers that bind request fields straight onto the model (mass assignment).
API5: flag admin-only routes that do not check role server-side.
API4: flag endpoints with no pagination/rate limit on unbounded queries.
Note where object ids come from and whether they are guessable."
```

- **Add the schema to the tree if you have one.** An OpenAPI/GraphQL schema or a
  `.proto` committed in the repo gives the agent the full endpoint list to reason
  against — make sure the subtree you target includes it. (Striket has no separate
  spec-upload flag; the schema is reviewed as part of the source.)
- **GraphQL:** in `--focus`, call out per-field authorization, and
  batching/aliasing and depth/complexity limits as the resource-consumption angle.
- **Many services:** `--target` is repeatable — pass each service path.

## 2. Verify findings

`striket_runs/<run>/penetration_test_report.md` first, then the findings in
`final.json` / `vulnerabilities.json` — each carries the `location` (file:line or
endpoint) and `remediation_steps`. For an authorization finding, trace the code
path yourself to confirm the missing check is really reachable, and recommend a
two-token request-level retest (tenant A's object with tenant B's token) before
reporting it as confirmed.

`findings.sarif` uploads to GitHub code scanning; `vulnerabilities.json` is the
structured index for ticketing.

## 3. Fix and re-review

Fix the authorization _helper_, not the single endpoint — the same missing check
usually spans many handlers. The `fix` phase is disabled, so patch it yourself,
then re-run Striket scoped to the API subtree to confirm the finding is gone.
Wire it into pull-request CI with **ci-security-scanning** so new endpoints get
reviewed as they ship. For a whole-product plan, see
**application-security-testing**; for category mapping, **owasp-top-10-testing**.
