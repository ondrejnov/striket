---
name: owasp-top-10-testing
description: Review an application against the OWASP Top 10 with Striket — map each finding from a white-box code review to its category in the current OWASP Top 10:2025 (broken access control including SSRF, security misconfiguration, software supply chain failures, cryptographic failures, injection, insecure design, authentication failures, integrity failures, logging and alerting failures, mishandling of exceptional conditions), and report coverage category-by-category and honestly. Also references the OWASP API Security Top 10 (2023). Use when the user asks for an OWASP Top 10 assessment, OWASP compliance testing, or a security review mapped to OWASP categories.
---

# Review against the OWASP Top 10

The OWASP Top 10 is a taxonomy of risk categories, not a test suite — an "OWASP
Top 10 review" means exercising each category against the real application and
reporting what is actually present. Striket's current phase does this as a
**white-box code review**: it reasons about the source and reports findings
mapped back to the category. This skill covers running it category-by-category
and reporting coverage honestly.

Install, prerequisites, flags, and exit codes: **penetration-testing-with-striket**.

**Use the current edition: [OWASP Top 10:2025](https://owasp.org/Top10/)** (8th
installment, superseding 2021). Ask the user before targeting an older edition —
some compliance checklists still reference 2021, and a report labelled with the
wrong edition is misleading. Key differences from 2021: **SSRF is folded into
A01**, **A03 Software Supply Chain Failures** expands the old "Vulnerable and
Outdated Components", and **A10 Mishandling of Exceptional Conditions** is new;
A02 Security Misconfiguration moved 5→2.

## What a white-box review can and cannot assess

Be straight with the user — a source review reaches some categories well and
others not at all. Live, runtime-only exploitation (browser/HTTP phases) is not
in Striket's current phase, so phrase every result as "found by reasoning about
the source", not "exploited against a running system".

| Category (2025)                           | Coverage from a source review                                                                                                                                                           |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A01 Broken Access Control (incl. SSRF)    | **Strong** — missing object-level/tenant checks, IDOR, privilege-escalation paths, and SSRF sinks are visible in the authorization code and request-building code.                      |
| A02 Security Misconfiguration             | **Partial** — debug flags, permissive CORS config, default credentials, and missing hardening are visible where they live in source/config; deployed-only misconfig needs infra review. |
| A03 Software Supply Chain Failures        | **Partial** — vulnerable/outdated dependency review from manifests (pair with SCA); build-system and distribution compromise is out of scope.                                           |
| A04 Cryptographic Failures                | **Partial** — weak algorithms, hardcoded keys, and secrets/tokens handled unsafely in code; key-management and at-rest posture need infra review.                                       |
| A05 Injection                             | **Strong** — SQL/NoSQL/command/template injection and XSS sinks with attacker-controlled input are traceable in source.                                                                 |
| A06 Insecure Design                       | **Partial** — business-logic flaws (price/quantity tampering, workflow skipping, race windows) are found where reachable in code; design intent still needs human threat modelling.     |
| A07 Authentication Failures               | **Strong** — auth-bypass logic, weak session/token handling, password-reset and MFA flaws are visible in the auth code.                                                                 |
| A08 Software or Data Integrity Failures   | **Partial** — insecure deserialization and unsigned-update paths where reachable; CI/CD trust boundaries are not in a source review.                                                    |
| A09 Security Logging & Alerting Failures  | **Weak** — you can note where logging is absent in code, but the alerting pipeline cannot be assessed. State this rather than reporting it as passed.                                   |
| A10 Mishandling of Exceptional Conditions | **Partial** — fail-open error handling and swallowed exceptions are visible in code; exhaustive coverage of internal error paths still needs careful review.                            |

For APIs, run the same exercise against the **OWASP API Security Top 10 (2023)** —
API1 BOLA, API3 Broken Object Property Level Authorization, API5 broken
function-level authorization — using the **api-security-testing** skill.

## Run it

Give the agent the source and a `--focus` that names the 2025 categories to
prioritise and tells it to map each finding to its category id:

```bash
striket run --target ./ --scan-mode deep --max-budget 30 --headless \
  --focus "OWASP Top 10:2025 assessment. Cover every category systematically and
map each finding to its 2025 category id.
Multi-tenant app: tenant id comes from the JWT.
Prioritise A01 (cross-tenant access, privilege escalation, SSRF), A02, A05, A07, A10.
Out of scope: anything under src/vendor."
```

- `--scan-mode deep` matters here — systematically walking ten categories is not
  a quick scan.
- `--focus` narrows attention; it never widens the validated scope.

## Report honestly

From `striket_runs/<run>/`, group the findings in `final.json` /
`vulnerabilities.json` by category and state, per category: what was reviewed,
what was found, and what could not be assessed from source (A09 always;
A02/A03/A04/A06/A08/A10 partially). Label the report with the edition used.
Verify each finding's reproduction reasoning before it goes in front of the user.

A `0` exit with no findings means nothing was proven **in what was analyzed** —
check `run.json` `status` and streamed cost against `--max-budget`; a capped
(`partial`) run is not a completed assessment.

## Then fix and re-review

Remediation is manual (the `fix` phase is disabled). After each root cause is
patched, re-run Striket scoped to the change to confirm the finding is gone. For
ongoing coverage as the app changes, gate pull requests with
**ci-security-scanning**.
