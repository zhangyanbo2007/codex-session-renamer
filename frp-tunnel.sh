#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCAL_PORT="${SESSION_RENAMER_PORT:-8891}"
REMOTE_PORT="${SESSION_RENAMER_REMOTE_PORT:-8887}"
FRP_TOML="/home/zhangyanbo/frp/frpc.toml"
FRP_ADMIN="http://127.0.0.1:7400"
VPS_HOST="8.163.122.236"
PROXY_NAME="node37-session-renamer"
LOG_FILE="/tmp/session-renamer.log"
PID_FILE="/tmp/session-renamer.pid"

log() { echo -e "\033[1;36m[session-renamer]\033[0m $*"; }
ok()  { echo -e "\033[1;32m[session-renamer]\033[0m $*"; }
err() { echo -e "\033[1;31m[session-renamer]\033[0m $*" >&2; }

ensure_frp_proxy() {
  if ! grep -q "name = \"${PROXY_NAME}\"" "${FRP_TOML}" 2>/dev/null; then
    log "向 frpc.toml 追加隧道 ${PROXY_NAME}..."
    cat >> "${FRP_TOML}" <<EOF

[[proxies]]
name = "${PROXY_NAME}"
type = "tcp"
localIP = "127.0.0.1"
localPort = ${LOCAL_PORT}
remotePort = ${REMOTE_PORT}
EOF
  fi
}

reload_frpc() {
  if pgrep -f 'frpc .*frpc\.toml' >/dev/null 2>&1; then
    log "frpc 已运行，热重载..."
    curl -sf -X GET "${FRP_ADMIN}/api/reload" >/dev/null
  else
    log "frpc 未运行，启动 frpc..."
    cd /home/zhangyanbo/frp
    setsid nohup ./frpc -c frpc.toml > frpc.log 2>&1 < /dev/null &
    sleep 2
  fi
  pgrep -f 'frpc .*frpc\.toml' >/dev/null 2>&1 && ok "frpc 运行中" || { err "frpc 未运行"; return 1; }
}

start_local() {
  if [[ -z "${SESSION_RENAMER_TOKEN:-}" ]]; then
    err "请先设置 SESSION_RENAMER_TOKEN"
    return 1
  fi
  if curl -sf -m 2 "http://127.0.0.1:${LOCAL_PORT}/health" >/dev/null 2>&1; then
    log "本地 :${LOCAL_PORT} 已运行，跳过启动"
    lsof -ti TCP:"${LOCAL_PORT}" -sTCP:LISTEN 2>/dev/null | head -n 1 > "${PID_FILE}" || true
  else
    log "启动本地服务 :${LOCAL_PORT}..."
    cd "${PROJECT_DIR}"
    setsid env SESSION_RENAMER_TOKEN="${SESSION_RENAMER_TOKEN}" SESSION_RENAMER_PORT="${LOCAL_PORT}" bash run.sh > "${LOG_FILE}" 2>&1 < /dev/null &
    echo "$!" > "${PID_FILE}"
    disown "$!" 2>/dev/null || true
    sleep 2
  fi
  curl -sf -m 3 "http://127.0.0.1:${LOCAL_PORT}/health" >/dev/null
}

cmd_start() {
  ensure_frp_proxy
  start_local
  reload_frpc
  echo ""
  ok "已就绪"
  echo "  本机: http://127.0.0.1:${LOCAL_PORT}/?token=<SESSION_RENAMER_TOKEN>"
  echo "  公网: http://${VPS_HOST}:${REMOTE_PORT}/?token=<SESSION_RENAMER_TOKEN>"
  echo "  日志: ${LOG_FILE}"
  echo "  PID:  ${PID_FILE}"
}

cmd_stop() {
  local pid
  pid="$(lsof -ti ":${LOCAL_PORT}" 2>/dev/null || true)"
  if [[ -n "${pid}" ]]; then
    kill ${pid}
    for _ in {1..20}; do
      if ! lsof -ti ":${LOCAL_PORT}" >/dev/null 2>&1; then
        break
      fi
      sleep 0.2
    done
    ok "本地服务 :${LOCAL_PORT} 已停止"
  else
    log "本地服务 :${LOCAL_PORT} 未运行"
  fi
  ok "frpc 保持运行"
}

cmd_status() {
  echo "=== session-renamer 状态 ==="
  echo -n "本地服务 :${LOCAL_PORT}  -> "
  curl -sf -m 3 "http://127.0.0.1:${LOCAL_PORT}/health" >/dev/null 2>&1 && ok "运行中" || err "未运行"
  echo -n "frpc              -> "
  pgrep -f 'frpc .*frpc\.toml' >/dev/null 2>&1 && ok "运行中" || err "未运行"
  echo -n "公网 /health      -> "
  curl -sf -m 5 "http://${VPS_HOST}:${REMOTE_PORT}/health" >/dev/null 2>&1 && ok "可访问" || err "不可达"
}

case "${1:-start}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  *) echo "用法: $0 [start|stop|status]"; exit 1 ;;
esac
