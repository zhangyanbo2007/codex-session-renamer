# GitHub Release Hardening Design

## Goal

Prepare the project for publication as a self-contained GitHub repository named `codex-session-renamer`, without exposing personal infrastructure details or changing its existing session-management behavior.

## Scope

The release-hardening work will:

- rename the repository directory and public-facing project references from `session-renamer` to `codex-session-renamer`;
- replace the private FRP deployment script with a reusable environment-driven example;
- remove personal usernames, absolute paths, public IP addresses, and private infrastructure layout from the current tree;
- separate public examples from ignored local configuration;
- make the project installable and testable without the parent workspace virtual environment;
- document the privacy and network-exposure risks of operating on Codex session data;
- scan both the final working tree and existing Git history before publication.

The work will not redesign session listing, title generation, renaming, deletion, caching, or the web interface.

The Python import package will remain `session_renamer`. Renaming the import namespace would add compatibility churn without improving the public repository name.

## Public Configuration Boundary

The repository will contain only non-secret defaults and placeholders. Runtime values will be supplied through environment variables. A checked-in `.env.example` will document supported variables without containing usable credentials or infrastructure addresses. `.env` and environment-specific variants will remain ignored.

`CODEX_HOME` will default to the current user's `~/.codex` and remain overridable. The application access token and optional DashScope API key will continue to come from environment variables.

## FRP Example

The current infrastructure-specific FRP script will become a generic example. It will require or accept environment variables for:

- the FRP client binary and configuration path;
- the FRP admin endpoint;
- the public host label used only for display;
- local and remote ports;
- the proxy name;
- runtime log and PID paths.

The example must not contain a real host, public IP, username, home directory, credential, or deployment-specific proxy name. It may append a proxy block only to the explicitly configured FRP configuration path and must fail clearly when required settings are absent.

The README will state that FRP TCP forwarding does not provide TLS by itself. Users must not expose Codex transcripts over unauthenticated or plaintext public transport; they should use a trusted private network or put TLS and stronger access control in front of the service.

## Packaging and Local Execution

The project will gain a minimal Python packaging and dependency declaration suitable for creating its own virtual environment. The launcher will resolve Python in this order:

1. an explicitly supplied `PYTHON` value;
2. the repository-local `.venv/bin/python`;
3. `python3` from `PATH`.

Documentation will use repository-relative commands. Tests will run from the project root without relying on the parent `privacy-engineering` environment.

## Ignore Policy

`.gitignore` will cover:

- Python bytecode and test/tool caches;
- local virtual environments;
- coverage and build artifacts;
- editor and operating-system metadata;
- `.env` and local environment variants while allowing `.env.example`;
- local logs, PID files, and runtime artifacts.

Files already tracked in Git are not protected retroactively by `.gitignore`; any private deployment file being replaced must also be removed from the tracked public surface.

## History and Publication

The existing Git history contains personal paths and infrastructure identifiers even after the working tree is cleaned. Before publishing, the final verification will report the affected historical paths. Publication will require one of these explicit follow-up choices:

- create a new public repository from the sanitized tree with a fresh initial commit; or
- rewrite the local repository history and verify the rewritten history before pushing.

No history rewrite, GitHub repository creation, commit push, or publication is included in this implementation without separate user authorization.

## Error Handling

Launch and FRP example scripts will stop on missing required configuration and print actionable variable names without echoing secret values. Existing application behavior for missing access tokens remains fail-closed.

## Verification

Completion requires:

1. running the full existing test suite in the supported project environment;
2. testing launcher selection and configuration defaults where practical;
3. checking shell syntax for public scripts;
4. confirming ignored local artifacts are not tracked;
5. scanning the final tree for credentials, personal absolute paths, public IPs, and infrastructure-specific identifiers;
6. scanning all existing commits for the same categories and reporting any remaining historical exposure;
7. reviewing the final diff so unrelated user changes are preserved.

## Success Criteria

The sanitized current tree contains no real credential or personal deployment identifier, a new user can install and test the project from the repository alone, the FRP integration is clearly an opt-in generic example, and the remaining Git-history publication decision is explicit rather than hidden.
