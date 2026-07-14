# Codex Session Renamer

> Current version: v0.6.2

A local web interface for reviewing, renaming, and cleaning up Codex sessions. The UI is Chinese and is designed for people who maintain many sessions across multiple project directories.

## Features

### Session discovery and review

- Reads both the legacy `~/.codex/session_index.jsonl` index and the current `~/.codex/state_5.sqlite` database.
- Matches active logs under `~/.codex/sessions/**` and archived logs under `~/.codex/archived_sessions/`.
- Groups sessions by working directory and sorts them from most recently updated to oldest.
- Shows session title, update time, ID, message count, preview, and recommendation directly in the list.
- Provides a detail view for reviewing the user and assistant messages in a session.
- Searches by current title, preview, and conversation content.
- Filters sessions that still need a useful name or have changed since their last successful rename.

### Title recommendations and renaming

- Generates a three-level title: current directory, overall summary, and the most recent two-turn summary.
- Uses `qwen3.5-flash` through the DashScope-compatible API, with thinking disabled for low-cost title generation.
- Generates the overall task and recent two-turn state in two model calls, using the overall task as context for the recent-state inference.
- Caps the overall model input at a conservative 100,000-token budget.
- Ignores the first user environment/context record when building title context.
- Updates recommendations only when **一键标题推荐** or **单会话标题推荐** is clicked; normal page loads do not call an AI model.
- Prefills each rename input with its current recommendation without applying the rename automatically.
- Keeps recommendation generation separate from renaming, so generating recommendations does not change session count or current names.
- Supports manual rename directly in the list and filtered bulk rename.
- Uses the Codex `thread/name/set` app-server method for current sessions so names persist after the conversation continues.

### Change tracking and cleanup

- Marks a session as changed when its content differs from the content at the last successful rename.
- Keeps a changed session visible after recommendation generation and clears the state only after a successful rename.
- Deletes sessions from the index/database while moving logs to `~/.codex/session-renamer-trash/` for recovery.
- Creates timestamped backups before modifying the legacy index or current state database.
- Shows temporary success messages after recommendation, rename, bulk rename, and deletion actions.

### Performance and privacy

- Does not send session content anywhere unless Qwen title generation is explicitly configured and triggered.
- Caches recommendations and log metadata to avoid repeatedly parsing unchanged session files.
- Loads full conversation details only for detail pages, content search, changed-session filtering, and title generation.
- Requires an access token for every session-management page and action.
- Sends `Cache-Control: no-store` responses to reduce browser caching of private transcripts.

## Requirements

- Python 3.10 or newer
- A Codex installation with `app-server` support for persistent renaming
- Access to the Codex data directory, normally `~/.codex`

## Install

```bash
git clone https://github.com/zhangyanbo2007/codex-session-renamer.git
cd codex-session-renamer
python3 -m venv .venv
.venv/bin/pip install -e .
```

Create a strong random token and start the local service:

```bash
export SESSION_RENAMER_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
bash run.sh
```

Open:

```text
http://127.0.0.1:8891/?token=<SESSION_RENAMER_TOKEN>
```

The launcher uses `PYTHON` when supplied, then `.venv/bin/python`, then `python3` from `PATH`.

## Configuration

Copy `.env.example` as a reference, but export secrets into the process environment or store them in a protected local file that is not committed.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `SESSION_RENAMER_TOKEN` | Yes | none | Access token for all private pages and actions |
| `CODEX_HOME` | No | `~/.codex` | Codex data directory |
| `SESSION_RENAMER_INDEX_PATH` | No | `$CODEX_HOME/session_index.jsonl` | Legacy index override |
| `SESSION_RENAMER_HOST` | No | `127.0.0.1` | Local bind address |
| `SESSION_RENAMER_PORT` | No | `8891` | Local HTTP port |
| `SESSION_RENAMER_CODEX_BIN` | No | auto-detected | Codex executable with app-server support |
| `SESSION_RENAMER_TITLE_PROVIDER` | No | `qwen` | Use `local` to keep existing titles without recommendations |
| `SESSION_RENAMER_DASHSCOPE_API_KEY` | For Qwen | none | DashScope API key |
| `SESSION_RENAMER_QWEN_MODEL` | No | `qwen3.5-flash` | Title-generation model |
| `SESSION_RENAMER_QWEN_BASE_URL` | No | DashScope compatible endpoint | API endpoint override |
| `SESSION_RENAMER_QWEN_TIMEOUT` | No | `8` | Model request timeout in seconds |
| `SESSION_RENAMER_QWEN_PROXY` | No | detected local proxy or none | HTTP(S) proxy for model requests |
| `SESSION_RENAMER_TITLE_WORKERS` | No | `6` | Maximum parallel title requests |

Title semantics are generated only by Qwen. When no API key is present, the app keeps existing titles instead of applying local title rules.

## Optional FRP exposure

FRP is not required for local use. The included `frp-tunnel.sh` is a generic helper and reads optional machine-specific settings from the ignored `.env.local` file.

Required FRP values:

```bash
export SESSION_RENAMER_FRP_CONFIG=/path/to/frpc.toml
export SESSION_RENAMER_PUBLIC_HOST=example.com
export SESSION_RENAMER_TOKEN='use-a-long-random-value'
bash frp-tunnel.sh start
```

Additional variables include `SESSION_RENAMER_FRP_BIN`, `SESSION_RENAMER_FRP_ADMIN`, `SESSION_RENAMER_FRP_PROXY_NAME`, `SESSION_RENAMER_REMOTE_PORT`, `SESSION_RENAMER_FRP_MANAGE_CONFIG`, `SESSION_RENAMER_LOG_FILE`, and `SESSION_RENAMER_PID_FILE`.

Validate configuration without starting anything:

```bash
bash frp-tunnel.sh validate
```

> FRP TCP forwarding does not add TLS. Codex transcripts can contain source code, credentials, personal information, and system context. Prefer a trusted private network. For public access, place TLS and stronger authentication in front of this service. Never expose it without a strong token.

## Safety notes

- Back up `~/.codex` before first use.
- Review recommendations before bulk rename.
- Deletion changes Codex indexes and moves logs into a local trash directory; verify the selected directory and search filters first.
- A token in a query string may appear in browser history and intermediary logs. Use a private network and rotate the token if it may have been exposed.
- Model-based recommendations send cleaned conversation context to the configured provider only after the recommendation action is triggered.

## Development

Run the complete test suite:

```bash
python3 -m unittest discover -s tests -v
```

Check shell scripts and whitespace:

```bash
bash -n run.sh frp-tunnel.sh
git diff --check
```

See [CHANGELOG.md](./CHANGELOG.md) for release history.

## License

MIT
