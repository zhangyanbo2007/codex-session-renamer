#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${SESSION_RENAMER_ENV_FILE:-${PROJECT_DIR}/.env.local}"
if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

LOCAL_PORT="${SESSION_RENAMER_PORT:-8891}"
REMOTE_PORT="${SESSION_RENAMER_REMOTE_PORT:-8887}"
FRP_CONFIG="${SESSION_RENAMER_FRP_CONFIG:-}"
FRP_BIN="${SESSION_RENAMER_FRP_BIN:-frpc}"
FRP_ADMIN="${SESSION_RENAMER_FRP_ADMIN:-}"
PUBLIC_HOST="${SESSION_RENAMER_PUBLIC_HOST:-}"
PROXY_NAME="${SESSION_RENAMER_FRP_PROXY_NAME:-codex-session-renamer}"
MANAGE_CONFIG="${SESSION_RENAMER_FRP_MANAGE_CONFIG:-0}"
LOG_FILE="${SESSION_RENAMER_LOG_FILE:-/tmp/codex-session-renamer.log}"
PID_FILE="${SESSION_RENAMER_PID_FILE:-/tmp/codex-session-renamer.pid}"

log() { printf '[codex-session-renamer] %s\n' "$*"; }
ok() { printf '[codex-session-renamer] %s\n' "$*"; }
err() { printf '[codex-session-renamer] %s\n' "$*" >&2; }

require_value() {
  local variable="$1"
  local value="$2"
  if [[ -z "${value}" ]]; then
    err "Missing required configuration: ${variable}"
    return 1
  fi
}

validate_config() {
  require_value "SESSION_RENAMER_FRP_CONFIG" "${FRP_CONFIG}"
  require_value "SESSION_RENAMER_PUBLIC_HOST" "${PUBLIC_HOST}"
  if [[ ! -f "${FRP_CONFIG}" ]]; then
    err "FRP config does not exist: ${FRP_CONFIG}"
    return 1
  fi
  if ! command -v "${FRP_BIN}" >/dev/null 2>&1 && [[ ! -x "${FRP_BIN}" ]]; then
    err "FRP client is not executable: ${FRP_BIN}"
    return 1
  fi
}

ensure_frp_proxy() {
  if rg -q "name = \"${PROXY_NAME}\"" "${FRP_CONFIG}" 2>/dev/null \
    || grep -q "name = \"${PROXY_NAME}\"" "${FRP_CONFIG}" 2>/dev/null; then
    return
  fi
  if [[ "${MANAGE_CONFIG}" != "1" ]]; then
    err "Proxy ${PROXY_NAME} is absent from ${FRP_CONFIG}."
    err "Add it manually or set SESSION_RENAMER_FRP_MANAGE_CONFIG=1."
    return 1
  fi
  log "Adding proxy ${PROXY_NAME} to configured FRP file"
  cat >> "${FRP_CONFIG}" <<EOF

[[proxies]]
name = "${PROXY_NAME}"
type = "tcp"
localIP = "127.0.0.1"
localPort = ${LOCAL_PORT}
remotePort = ${REMOTE_PORT}
EOF
}

frp_process_pattern() {
  printf 'frpc .*%s' "$(basename "${FRP_CONFIG}")"
}

reload_frpc() {
  local pattern
  pattern="$(frp_process_pattern)"
  if pgrep -f "${pattern}" >/dev/null 2>&1; then
    if [[ -n "${FRP_ADMIN}" ]]; then
      log "Reloading the running FRP client"
      curl -sf -X GET "${FRP_ADMIN%/}/api/reload" >/dev/null
    else
      log "FRP is already running; no admin endpoint configured"
    fi
  else
    log "Starting FRP client"
    setsid nohup "${FRP_BIN}" -c "${FRP_CONFIG}" > "${LOG_FILE}.frpc" 2>&1 < /dev/null &
    sleep 2
  fi
  pgrep -f "${pattern}" >/dev/null 2>&1 || {
    err "FRP client did not start"
    return 1
  }
}

start_local() {
  require_value "SESSION_RENAMER_TOKEN" "${SESSION_RENAMER_TOKEN:-}"
  if curl -sf -m 2 "http://127.0.0.1:${LOCAL_PORT}/health" >/dev/null 2>&1; then
    log "Local service on port ${LOCAL_PORT} is already running"
    lsof -ti TCP:"${LOCAL_PORT}" -sTCP:LISTEN 2>/dev/null | head -n 1 > "${PID_FILE}" || true
    return
  fi
  log "Starting local service on port ${LOCAL_PORT}"
  cd "${PROJECT_DIR}"
  setsid env \
    SESSION_RENAMER_TOKEN="${SESSION_RENAMER_TOKEN}" \
    SESSION_RENAMER_PORT="${LOCAL_PORT}" \
    bash run.sh > "${LOG_FILE}" 2>&1 < /dev/null &
  echo "$!" > "${PID_FILE}"
  disown "$!" 2>/dev/null || true
  sleep 2
  curl -sf -m 3 "http://127.0.0.1:${LOCAL_PORT}/health" >/dev/null
}

cmd_start() {
  validate_config
  ensure_frp_proxy
  start_local
  reload_frpc
  ok "Ready"
  printf 'Local:  http://127.0.0.1:%s/?token=<SESSION_RENAMER_TOKEN>\n' "${LOCAL_PORT}"
  printf 'Public: http://%s:%s/?token=<SESSION_RENAMER_TOKEN>\n' "${PUBLIC_HOST}" "${REMOTE_PORT}"
}

cmd_stop() {
  local pid
  pid="$(lsof -ti ":${LOCAL_PORT}" 2>/dev/null || true)"
  if [[ -n "${pid}" ]]; then
    kill ${pid}
    for _ in {1..20}; do
      lsof -ti ":${LOCAL_PORT}" >/dev/null 2>&1 || break
      sleep 0.2
    done
    ok "Local service stopped"
  else
    log "Local service is not running"
  fi
  ok "FRP client was left running"
}

cmd_status() {
  validate_config
  printf 'Local service: '
  curl -sf -m 3 "http://127.0.0.1:${LOCAL_PORT}/health" >/dev/null 2>&1 && echo running || echo stopped
  printf 'Public health: '
  curl -sf -m 5 "http://${PUBLIC_HOST}:${REMOTE_PORT}/health" >/dev/null 2>&1 && echo reachable || echo unreachable
}

case "${1:-start}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  validate) validate_config && ok "Configuration is valid" ;;
  *) err "Usage: $0 [start|stop|status|validate]"; exit 1 ;;
esac
