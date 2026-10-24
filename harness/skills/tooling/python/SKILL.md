---
name: python
description: Run Python through exec_command in the sandbox. Use requests/httpx from Python scripts for direct-HTTP probing and request replay — no interception proxy involved.
---

# Python In The Sandbox

Use `exec_command` for Python. There is no separate Python executor.

Prefer writing reusable scripts to a `.py` file and running them with
`python3 <name>.py`. For short one-off transformations, `python3 -c` or a
small here-document is fine.

The `shell` parameter on `exec_command` is for swapping POSIX shells
(`bash`/`zsh`/`sh`), not for picking interpreters. Put the interpreter
invocation in `cmd` instead: `cmd="python3 -c '...'"`, not
`shell=python3, cmd="..."`. The `shell=<interpreter>` shortcut breaks
in subtle ways — `python3` works only with `login=False` (because the
SDK adds `-l`/`-i`), and other interpreters (`node`, `ruby`, `perl`)
take `-e` not `-c` so they fail even with `login=False`.

## HTTP Automation From Python

There is no intercepting proxy in this sandbox — issue and replay HTTP
requests directly with `requests` or `httpx` (both pre-installed; see
below). Write the candidate-gathering and replay logic as a normal script
instead of going through a proxy API:

```python
import httpx


def main() -> None:
    candidates = []
    with httpx.Client(timeout=10) as client:
        for path in ("/api/users", "/api/orders", "/api/session"):
            resp = client.get(f"https://target.example/{path}")
            if "id=" in resp.text or "user=" in resp.text:
                candidates.append((path, resp.status_code))

    print(f"{len(candidates)} candidates")
    print(candidates[:10])


if __name__ == "__main__":
    main()
```

Patterns that replace the proxy helpers:

- **List/filter requests of interest**: build the candidate list yourself
  (crawl output, `katana`/`ffuf` results, or a manually curated set of
  endpoints) rather than querying proxy history.
- **View a request/response**: print or log `resp.request` and
  `resp.text`/`resp.headers` directly; persist anything you plan to cite
  as evidence via the `evidence_store` MCP (or a task-local file) instead
  of a proxy's capture store.
- **Replay with modifications**: re-issue the same request with changed
  `url`, `params`, `headers`, `json`/`data`, or `cookies` — `httpx.Client`
  keeps cookies/session state across calls, so a login + replay flow is
  just two client calls.
- **Scope**: enforce scope in your own code (check the target host/path
  against the authorized list before sending), the same way the
  orchestrator validates scope before the agent runs.

For one-off arbitrary requests (e.g. probing a fresh endpoint, hitting an
external API), `exec_command` with `curl` / `httpx` works just as well as
a Python script — pick whichever is less code for the task.

## Workflow

For iterative exploit work, put code in a file:

```text
1. Create or edit a task-unique script (e.g. `poc_<task-id>.py`, so it can't
   clobber a project file or another agent's script) with `apply_patch`.
2. Run it with `exec_command`: `python3 poc_<task-id>.py`.
3. Edit and rerun until the proof-of-concept is reliable.
```

## Installing extra packages

The sandbox's Python lives in `/app/.venv`, and it is the active virtualenv
(`python3` / `pip` already resolve to it). The following common libraries are
**pre-installed** — import them directly, no install step needed:
`requests`, `httpx`, `beautifulsoup4` (`bs4`), `lxml`, `pyjwt` (`jwt`),
`cryptography`.

To add a one-off dependency for an exploit script, use `uv` (already in the
image and much faster than pip):

```bash
uv pip install --python /app/.venv/bin/python <package>
```

Plain `pip install <package>` also works because the venv is active. Install
before you import, so scripts don't fail with `ModuleNotFoundError`.
