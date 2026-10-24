# Striket user-facing skills

These are **operator skills** — guides for a coding agent (Claude Code or
similar) on how to *drive* Striket. They are distinct from
`harness/skills/`, which is the internal vulnerability know-how the Striket agent
itself consults during a run.

They are ported from Strix's user-facing skills and adapted to Striket:

- the CLI is `striket run … --focus … --headless` (not `strix -n -t … --instruction …`);
- artifacts land in `striket_runs/<run>/` (`final.json`, `vulnerabilities.json`,
  `findings.sarif`, `run.json`, `penetration_test_report.md`, `session.id`);
- the exit code is **not** a findings signal (`0` success, `1` fatal, `2` usage /
  out-of-scope) — gate on the artifacts;
- there is **no managed cloud** (`striket cloud` does not exist) and the **`fix`
  phase is intentionally disabled** (Striket reports remediation, never patches).

| Skill | Use it for |
|---|---|
| `penetration-testing-with-striket` | **Base skill** — install, prerequisites, every flag, scan modes, scope, exit codes, artifacts. Read first. |
| `find-security-vulnerabilities-in-code` | White-box review of a codebase/repo — Striket's flagship, matches the current phase. |
| `application-security-testing` | Entry point when the target is not yet a single repo; pick the right review per asset and rank one plan. |
| `owasp-top-10-testing` | Map a review to OWASP Top 10:2025 categories and report coverage honestly. |
| `api-security-testing` | Source review of a REST/GraphQL/gRPC API's authorization model (BOLA/IDOR, mass assignment, function-level authz). |
| `web-app-penetration-testing` | Source review of a web app's routes, templating, session/auth, and access control. |
| `ci-security-scanning` | Gate pull requests in CI (self-hosted; gate on artifacts + SARIF upload). |

## Dropped from the Strix port (do not re-add without a capability change)

- **`fix-security-vulnerabilities-with-strix`** — the `fix` phase is disabled in
  Striket; it never modifies the target, so an automated-fix skill would misrepresent it.
- **`managed-pentesting-with-strix`** — Striket has no managed platform, holds no
  LLM credentials, and exposes no `striket cloud` command.

Both are revisitable if a later milestone adds the capability.
