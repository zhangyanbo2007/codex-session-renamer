# Public GitHub Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a privacy-safe, self-contained `codex-session-renamer` repository with a clear feature list and a fresh public Git history.

**Architecture:** Keep the existing `session_renamer` package and behavior, but move all machine-specific paths and FRP values behind environment variables. Add standard Python packaging, generic launch/deployment examples, release documentation, and automated configuration tests before exporting the sanitized tree into a new repository.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, Jinja2, unittest, Bash, Git

---

### Task 1: Add Portable Configuration And Packaging

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Modify: `session_renamer/store.py`
- Modify: `session_renamer/qwen_title.py`
- Modify: `run.sh`
- Modify: `.gitignore`
- Test: `tests/test_store.py`
- Test: `tests/test_qwen_title.py`

- [ ] Add failing tests proving `CODEX_HOME` and index paths can be supplied without personal absolute paths.
- [ ] Run the focused tests and confirm they fail against hard-coded defaults.
- [ ] Read runtime paths from environment variables while retaining `~/.codex` defaults.
- [ ] Remove parent-workspace `.env` discovery and use process environment only.
- [ ] Add package metadata and runtime/test dependencies to `pyproject.toml`.
- [ ] Make `run.sh` select `PYTHON`, then `.venv/bin/python`, then `python3`.
- [ ] Run focused tests and confirm they pass.

### Task 2: Replace Private FRP Deployment With A Generic Example

**Files:**
- Modify: `frp-tunnel.sh`
- Create: `tests/test_scripts.py`

- [ ] Add tests that reject missing FRP configuration and scan script output for secret values.
- [ ] Run the script tests and confirm the current infrastructure-specific script fails them.
- [ ] Parameterize FRP binary, config, admin endpoint, proxy name, public host, ports, logs, and PID path.
- [ ] Ensure the script never prints the access token and fails with actionable variable names.
- [ ] Run `bash -n run.sh frp-tunnel.sh` and the script tests.

### Task 3: Publish A Complete README Feature List

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] Replace personal paths and IP addresses with portable examples.
- [ ] Document the feature list: multi-source discovery, directory grouping, search, detail view, recommendation generation, manual and bulk rename, change tracking, safe deletion, caching, backups, and notifications.
- [ ] Document local-only startup first and generic FRP as an optional deployment.
- [ ] Add privacy, plaintext transport, backup, and destructive-operation warnings.
- [ ] Document all supported environment variables and test commands.

### Task 4: Release Verification

**Files:**
- Modify only files implicated by verification failures.

- [ ] Run the complete unittest suite and record the pass count.
- [ ] Run `git diff --check` and shell syntax checks.
- [ ] Scan tracked files for tokens, API keys, usernames, absolute home paths, public IPs, private proxy names, logs, caches, and session content.
- [ ] Review the full diff for behavioral regressions and unrelated changes.
- [ ] Perform an independent code review and resolve Critical or Important findings.

### Task 5: Create A Fresh Public Repository

**Files:**
- Export the verified working tree to a sibling `codex-session-renamer` directory.

- [ ] Copy only the sanitized tracked release files, excluding `.git`, caches, logs, local environment files, and runtime artifacts.
- [ ] Initialize a new Git repository with branch `main`.
- [ ] Repeat the tracked-tree sensitive-data scan in the new repository.
- [ ] Commit the sanitized tree as the initial release commit.
- [ ] Create the public GitHub repository and push only after verifying GitHub authentication and repository-name availability.
