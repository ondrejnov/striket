# 📚 Striket Skills

## 🎯 Overview

Skills are specialized knowledge packages that give the `agentiscode` agents deep expertise in
specific vulnerability types, technologies, and testing methodologies. Each skill provides advanced
techniques, practical examples, and validation methods that go beyond baseline security knowledge.

This directory is a direct port of Strix's skill library (`strix/strix/skills/**/*.md`) onto the
`agentiscode` harness's native skill format: one `SKILL.md` per skill, under
`<category>/<name>/SKILL.md`, with YAML frontmatter (`name`, `description`) read by the harness's
own skill-loading mechanism — there is no `load_skill` tool or `create_agent(skills=...)` call to
make here, the harness decides what to load from the `description` trigger text directly.

---

## 🏗️ Architecture

### How Skills Work

The harness's native skill mechanism matches a skill's `description` against the current task and
loads the matching `SKILL.md` body into the agent's context — no explicit tool call needed. Keep
`description` written as a trigger (when to load this skill), not a summary of its contents.

---

## 📁 Skill Categories

| Category | Purpose |
|----------|---------|
| **`/vulnerabilities`** | Advanced testing techniques for core vulnerability classes like authentication bypasses, business logic flaws, and race conditions |
| **`/frameworks`** | Specific testing methods for popular frameworks e.g. Django, Express, FastAPI, and Next.js |
| **`/technologies`** | Specialized techniques for third-party services such as Supabase, Firebase, Auth0, and payment gateways |
| **`/protocols`** | Protocol-specific testing patterns for GraphQL, WebSocket, OAuth, and other communication standards |
| **`/tooling`** | Command-line playbooks for core sandbox tools (nmap, nuclei, httpx, ffuf, subfinder, naabu, katana, sqlmap, agent-browser) |
| **`/cloud`** | Cloud provider security testing for AWS, Azure, GCP, and Kubernetes environments |
| **`/reconnaissance`** | Advanced information gathering and enumeration techniques for comprehensive attack surface mapping |
| **`/custom`** | Community-contributed skills for specialized or industry-specific testing scenarios |
| **`/coordination`** | Internal orchestration playbooks (root agent direction, white-box coordination) |
| **`/scan_modes`** | Internal scan-depth playbooks (quick/standard/deep/diff) |
| **`/analysis`** | Internal analysis playbooks (counterevidence, fix verification, severity calibration, source-aware discovery) |

Notable source-aware skills:
- `source_aware_whitebox` (coordination): white-box orchestration playbook
- `source_aware_sast` (custom): semgrep/AST/secrets/supply-chain static triage workflow
- `dependency_cve_scanning` (custom): dependency-scanner-based SCA workflow for reporting known dependency CVEs
- `npx_confusion` (custom): npx/npm exec/bunx fallback and adjacent package-runner identity confusion, with runner-specific registry and reporting gates
- `semantic_confusion` (vulnerabilities): cross-boundary parser, normalization, and representation mismatch analysis
- `agentic_system_security` (vulnerabilities): effective-authority and MCP/tool ecosystem security testing
- `browser_security` (vulnerabilities): browsing-context, postMessage, XS-Leaks, service-worker, and cross-origin state-machine testing
- `azure` (cloud): Azure and Microsoft Entra privilege, PIM, workload identity, and cross-plane escalation analysis
- `infrastructure_lifecycle` (reconnaissance): abandoned or mutable external dependencies such as update endpoints, MX, storage, and control domains
- `argument_injection` (vulnerabilities): shell-free CLI option smuggling, secondary argument-file parsing, and platform-specific argv transformation boundaries
- `electron_desktop_apps` (technologies): Electron renderer-to-native trust boundaries, preload/IPC exposure, and navigation analysis

Notable LLM security skills:
- `llm_applications` (technologies): end-to-end OWASP 2026 LLM01-LLM10 coverage across models, RAG, vectors, agents, tools, outputs, supply chain, and resource controls
- `llm_prompt_injection` (vulnerabilities): deep direct, indirect, multimodal, memory, and tool-result prompt-injection testing

---

## 🔌 Porting notes (Strix → striket)

- Methodology bodies are carried over verbatim — they describe *what* to look for and *how to reason
  about it*, not concrete payloads, so nothing here is Strix-engine-specific.
- `tooling/agent_browser` keeps the Vercel `agent-browser` CLI workflow as-is; it is still the
  sandbox's browser-automation tool under this harness.
- Any guidance that assumed a Caido intercepting proxy (traffic capture/replay via `caido_api`,
  `list_requests`/`repeat_request`/`list_sitemap`/`scope_rules`) was rewritten to the direct-HTTP
  model: issue requests with `curl`/`httpx` (optionally Python's `requests`/`httpx` library) and
  replay-and-modify by re-issuing the request with changed parameters, persisting the
  request/response pair as evidence yourself (e.g. via the `evidence_store` MCP) instead of relying
  on proxy-side history.

---

## 🎨 Creating New Skills

### What Should a Skill Contain?

A good skill is a structured knowledge package that typically includes:

- **Advanced techniques** - Non-obvious methods specific to the task and domain
- **Practical examples** - Working payloads, commands, or test cases with variations
- **Validation methods** - How to confirm findings and avoid false positives
- **Context-specific insights** - Environment and version nuances, configuration-dependent behavior, and edge cases
- **YAML frontmatter** - `name` and `description` fields for skill metadata, `description` written as a trigger

Skills focus on deep, specialized knowledge to significantly enhance agent capabilities. They are
loaded by the harness when their `description` trigger matches the task at hand.

---

> [!NOTE]
> This file documents the skill collection; it is not itself a loadable skill (no `SKILL.md`,
> no frontmatter).
