#!/usr/bin/env bash
# ============================================================
# vbt.sh — Vibe Trading 統一進程管理 (start/stop/restart/status)
#
# 所有 vbt 啟動/停止/重啟一律透過此腳本, 以 pidfile 追蹤 + 監控 pid。
#
# 用法:
#   ./scripts/vbt.sh start            # 啟動 vbt (paper, --reset-paper)
#   ./scripts/vbt.sh stop             # 優雅停止 (SIGTERM → SIGKILL)
#   ./scripts/vbt.sh restart          # stop + start
#   ./scripts/vbt.sh status           # 顯示 pid/運行時長/健康
#   ./scripts/vbt.sh pid              # 輸出 pid (或空)
#   ./scripts/vbt.sh log [N]          # 顯示最新 log 尾部 (N 行, 預設 20)
#
# 環境變數覆寫 (非必須, 有預設值):
#   VBT_MODE        paper|live      (預設 paper)
#   VBT_SYMBOL                       (預設 BTCUSDT)
#   VBT_INTERVAL                     (預設 30m)
#   VBT_RESET       0|1             (預設 0 — 不重置 paper 本金)
#   VBT_LOG_LEVEL    DEBUG|INFO|... (預設 DEBUG)
# ============================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$PROJECT_ROOT/.venv/bin/python"
SRC_PATH="$PROJECT_ROOT/backend/src"
PIDFILE="$PROJECT_ROOT/.vbt/vbt.pid"
LOGDIR="$PROJECT_ROOT/logs"
CMD_ARGS=(start "${VBT_SYMBOL:-BTCUSDT}"
  --mode "${VBT_MODE:-paper}"
  --interval "${VBT_INTERVAL:-30m}"
  --log-level "${VBT_LOG_LEVEL:-DEBUG}"
  --save-logs)
if [[ "${VBT_RESET:-0}" == "1" ]]; then
  CMD_ARGS+=(--reset-paper)
fi

mkdir -p "$LOGDIR" "$(dirname "$PIDFILE")"

_logfile() { ls -t "$LOGDIR"/trading_*.log 2>/dev/null | head -1 || true; }

_pid_alive() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

_pid() { [[ -f "$PIDFILE" ]] && cat "$PIDFILE" || echo ""; }

read_pid() { _pid; }

start() {
  local pid
  pid="$(_pid)"
  if _pid_alive "$pid"; then
    echo "vbt 已在運行 (pid=$pid)。若需重啟請用: $0 restart"
    return 0
  fi

  echo "啟動 vbt: ${CMD_ARGS[*]}"
  export PYTHONPATH="$SRC_PATH"
  nohup "$VENV_PY" -m vibe_trading.cli "${CMD_ARGS[@]}" \
    >"$LOGDIR/vbt_$(date +%Y%m%d_%H%M%S).log" 2>&1 &
  local new_pid=$!
  echo "$new_pid" > "$PIDFILE"
  echo "vbt 已啟動 (pid=$new_pid)"

  # 等待就緒 (最多 60s), 檢查進程存活 + log banner
  local t=0
  while (( t < 60 )); do
    if ! _pid_alive "$new_pid"; then
      echo "✗ vbt 啟動後立即退出 (pid=$new_pid)。檢查 log:"; echo "  $(_logfile)"
      rm -f "$PIDFILE"
      return 1
    fi
    if grep -qE "MultiThreadedTradingSystem initialized|initialized for BTCUSDT" \
        "$(_logfile)" 2>/dev/null; then
      echo "✓ vbt 就緒 (pid=$new_pid)"
      return 0
    fi
    sleep 2; t=$((t+2))
  done
  echo "⚠ 啟動 60s 仍未就緒, 但進程存活 (pid=$new_pid)"
  return 0
}

stop() {
  local pid
  pid="$(_pid)"
  if ! _pid_alive "$pid"; then
    echo "vbt 未在運行 (pid=$pid 不存在或已死)"
    rm -f "$PIDFILE"
    return 0
  fi
  echo "停止 vbt (pid=$pid, SIGTERM)..."
  kill -TERM "$pid"
  local t=0
  while (( t < 20 )); do
    if ! _pid_alive "$pid"; then
      echo "✓ vbt 已停止 (pid=$pid)"
      rm -f "$PIDFILE"
      return 0
    fi
    sleep 1; t=$((t+1))
  done
  echo "⚠ SIGTERM 20s 未退出, 強制 SIGKILL (pid=$pid)"
  kill -KILL "$pid" 2>/dev/null || true
  sleep 1
  rm -f "$PIDFILE"
  echo "✓ vbt 已強制停止"
}

restart() {
  echo "=== 重啟 vbt ==="
  stop
  start
}

status() {
  local pid
  pid="$(_pid)"
  if _pid_alive "$pid"; then
    local etime
    etime="$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')"
    local cmd
    cmd="$(ps -o cmd= -p "$pid" 2>/dev/null)"
    echo "狀態: RUNNING"
    echo "  pid:    $pid"
    echo "  uptime: $etime"
    echo "  cmd:    $cmd"
    local logf; logf="$(_logfile)"
    if [[ -n "$logf" ]]; then
      echo "  log:    $logf"
      local errs; errs="$(grep -ciE 'Traceback|ERROR' "$logf" 2>/dev/null || echo 0)"
      echo "  錯誤:   $errs 行 (最新 log)"
    fi
  else
    echo "狀態: STOPPED"
    [[ -f "$PIDFILE" ]] && echo "  (pidfile 殘留 pid=$(_pid), 進程已死)" || true
  fi
  return 0
}

pid() { _pid; }

logtail() {
  local n="${1:-20}"
  local logf; logf="$(_logfile)"
  if [[ -z "$logf" ]]; then echo "無 log 檔"; return 0; fi
  tail -n "$n" "$logf"
}

case "${1:-status}" in
  start)   start ;;
  stop)    stop ;;
  restart) restart ;;
  status)  status ;;
  pid)     pid ;;
  log)     shift; logtail "${1:-20}" ;;
  *) echo "用法: $0 {start|stop|restart|status|pid|log [N]}"; exit 1 ;;
esac
