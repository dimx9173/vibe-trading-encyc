#!/bin/bash
# vbt.sh — VBT (Vibe Trading) 一鍵管理腳本
#
# 用法:
#   ./scripts/vbt.sh start [SYMBOL]           # 啟動 (預設 BTCUSDT 30m paper)
#   ./scripts/vbt.sh stop                      # 優雅停止 (SIGTERM → 10s → SIGKILL)
#   ./scripts/vbt.sh restart                   # 重啟
#   ./scripts/vbt.sh status                    # 狀態總覽
#   ./scripts/vbt.sh logs                      # 跟蹤最新日誌 (tail -f)
#   ./scripts/vbt.sh log                       # 顯示最新日誌路徑
#   ./scripts/vbt.sh foreground                # 前台執行 (Ctrl+C 停止, 附關閉通知)
#
# 若偵測到 systemd unit (vbt.service)，start/stop/restart/status/logs
# 自動委託 systemctl / journalctl，避免與 systemd 雙重管理。
#
# 環境變數覆寫:
#   SYMBOL, INTERVAL, MODE (paper|testnet|live), ENABLE_WEB (1|0), WEB_PORT
#   GRACEFUL_TIMEOUT (預設 10), LOG_DIR (預設 <project>/logs)
#
# Exit codes:
#   0 = 成功
#   1 = 啟動驗證失敗
#   2 = 前置檢查失敗 (.env / LLM_MODEL)
#   3 = 用法錯誤

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_DIR/backend"
PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
LOG_DIR="${LOG_DIR:-$PROJECT_DIR/logs}"
PID_FILE="$PROJECT_DIR/data/vbt.pid"

SYMBOL="${SYMBOL:-BTCUSDT}"
INTERVAL="${INTERVAL:-30m}"
MODE="${MODE:-paper}"
ENABLE_WEB="${ENABLE_WEB:-0}"
WEB_PORT="${WEB_PORT:-8000}"
GRACEFUL_TIMEOUT="${GRACEFUL_TIMEOUT:-10}"

# --- helpers ---
ts() { date +%H:%M:%S; }
log() { printf "[%s] %s\n" "$(ts)" "$*"; }
die() { printf "[%s] ❌ %s\n" "$(ts)" "$*"; exit "${2:-1}"; }

# systemd unit 存在且已啟用 → 委託 systemctl (避免與 systemd 雙重管理)
SYSTEMD_UNIT="vbt.service"
systemd_managed() {
    systemctl list-unit-files "$SYSTEMD_UNIT" 2>/dev/null | grep -q "$SYSTEMD_UNIT"
}

# 匹配兩種啟動模式: CLI 入口 (vibe-trade start) 或 python -m (vibe_trading.cli start)
find_vbt_pid() {
    pgrep -f "vibe-trade start|vibe_trading.cli start" | head -1 || true
}

latest_log() {
    ls -t "$LOG_DIR"/trading_*.log 2>/dev/null | head -1 || true
}

# ============================================================================
# 前置檢查 — 避免 .env 指向已刪除的 llm.yaml config
# ============================================================================
preflight() {
    [[ -f "$PROJECT_DIR/.env" ]] || die ".env 不存在於 $PROJECT_DIR/.env" 2

    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env"
    set +a

    LLM_MODEL_NAME="${LLM_MODEL:-}"
    [[ -n "$LLM_MODEL_NAME" ]] || die "LLM_MODEL 未設置於 .env" 2

    LLM_YAML="$BACKEND_DIR/src/vibe_trading/config/llm.yaml"
    [[ -f "$LLM_YAML" ]] || die "llm.yaml 不存在於 $LLM_YAML" 2
    if ! grep -qE "^[[:space:]]+${LLM_MODEL_NAME}:" "$LLM_YAML"; then
        die "LLM_MODEL=$LLM_MODEL_NAME 在 llm.yaml 找不到對應 config block！" 2
    fi
    log "✅ 前置檢查通過 (LLM_MODEL=$LLM_MODEL_NAME)"
}

# ============================================================================
# 優雅停止
# ============================================================================
do_stop() {
    local PID
    PID=$(find_vbt_pid)
    if [[ -z "$PID" ]]; then
        log "ℹ️ 沒有運行中的 VBT"
        rm -f "$PID_FILE"
        return 0
    fi

    log "📨 SIGTERM (graceful) → PID $PID (uptime $(ps -o etime= -p "$PID" | tr -d ' ' || echo unknown))"
    kill -TERM "$PID" 2>/dev/null || true
    for ((i=1; i<=GRACEFUL_TIMEOUT; i++)); do
        sleep 1
        if ! kill -0 "$PID" 2>/dev/null; then
            log "✅ PID $PID 在 ${i}s 內退場 (關閉通知已發送)"
            rm -f "$PID_FILE"
            return 0
        fi
    done
    log "⚠️ ${GRACEFUL_TIMEOUT}s 超時，強制 SIGKILL"
    kill -9 "$PID" 2>/dev/null || true
    rm -f "$PID_FILE"
}

# ============================================================================
# 啟動
# ============================================================================
do_start() {
    local PID
    PID=$(find_vbt_pid)
    if [[ -n "$PID" ]]; then
        die "VBT 已在運行: PID $PID (uptime $(ps -o etime= -p "$PID" | tr -d ' '))。先用 stop 再 start" 1
    fi

    preflight

    mkdir -p "$LOG_DIR"
    local TIMESTAMP LOG_FILE
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    LOG_FILE="$LOG_DIR/trading_${SYMBOL}_${TIMESTAMP}.log"

    local WEB_ARGS=()
    if [[ "$ENABLE_WEB" == "1" ]]; then
        WEB_ARGS+=(--web --web-port "$WEB_PORT")
    fi

    log "🚀 啟動 VBT: $SYMBOL $INTERVAL mode=$MODE ${WEB_ARGS[*]:+${WEB_ARGS[*]}}"
    log "   log: $LOG_FILE"

    # setsid: 獨立 session, 避免 shell 退出時被 SIGTERM 波及
    cd "$BACKEND_DIR"
    PYTHONPATH="$BACKEND_DIR/src" setsid nohup "$PYTHON_BIN" -m vibe_trading.cli start "$SYMBOL" \
        --interval "$INTERVAL" \
        --mode "$MODE" \
        --save-logs \
        "${WEB_ARGS[@]}" \
        > "$LOG_FILE" 2>&1 &
    local NEW_PID=$!
    echo "$NEW_PID" > "$PID_FILE"
    disown

    # 啟動驗證: 等進程存活 + Telegram 啟動通知
    sleep 8
    if ! kill -0 "$NEW_PID" 2>/dev/null; then
        die "啟動失敗 — 進程已退出。檢查: $LOG_FILE" 1
    fi
    if ! grep -qE "startup notification sent|System initialization complete" "$LOG_FILE" 2>/dev/null; then
        log "⚠️ 進程存活但尚未確認初始化完成，檢查: $LOG_FILE"
    else
        log "✅ VBT 啟動完成 (PID $NEW_PID)，啟動通知已發送"
    fi
    log "   日誌: tail -f $LOG_FILE"
}

# ============================================================================
# 狀態
# ============================================================================
do_status() {
    local PID
    PID=$(find_vbt_pid)
    echo "═══════════════════════════════════════════════"
    echo " VBT 狀態"
    echo "═══════════════════════════════════════════════"
    if [[ -n "$PID" ]]; then
        echo "  狀態:   ✅ 運行中 (PID $PID)"
        echo "  啟動:   $(ps -o lstart= -p "$PID" | tr -d ' ')"
        echo "  運行:   $(ps -o etime= -p "$PID" | tr -d ' ')"
        echo "  CPU:    $(ps -o %cpu= -p "$PID" | tr -d ' ')%"
        echo "  記憶體: $(ps -o rss= -p "$PID" | awk '{printf "%.0f MB", $1/1024}')"
        if [[ "$ENABLE_WEB" == "1" ]] && ss -ltn 2>/dev/null | grep -q ":${WEB_PORT}\b"; then
            echo "  Web:    http://localhost:${WEB_PORT}"
        fi
    else
        echo "  狀態:   ⛔ 未運行"
    fi
    local LLOG
    LLOG=$(latest_log)
    if [[ -n "$LLOG" ]]; then
        echo "  最新日誌: $LLOG"
        echo "  最後更新: $(stat -c '%y' "$LLOG" | cut -d. -f1)"
    fi
    echo "═══════════════════════════════════════════════"
}

# ============================================================================
# 主選單
# ============================================================================
usage() {
    cat <<EOF
用法: ./scripts/vbt.sh <command> [SYMBOL]

Commands:
  start [SYMBOL]     啟動 VBT (SYMBOL 預設 $SYMBOL)
  stop               優雅停止 (SIGTERM → ${GRACEFUL_TIMEOUT}s → SIGKILL)
  restart            重啟 (stop + start)
  status             顯示運行狀態
  logs               跟蹤最新日誌 (tail -f)
  log                僅顯示最新日誌路徑
  foreground         前台執行 (Ctrl+C 停止)

環境變數: SYMBOL, INTERVAL, MODE, ENABLE_WEB, WEB_PORT, GRACEFUL_TIMEOUT

範例:
  ./scripts/vbt.sh start ETHUSDT
  SYMBOL=ETHUSDT INTERVAL=1h ./scripts/vbt.sh start
  MODE=testnet ENABLE_WEB=1 ./scripts/vbt.sh restart
EOF
}

CMD="${1:-}"
shift || true
if [[ -n "${1:-}" && "$CMD" == "start" ]]; then
    SYMBOL="$1"
fi

case "$CMD" in
    start)
        if systemd_managed; then
            log "🔧 偵測到 systemd ($SYSTEMD_UNIT)，委託 systemctl start"
            sudo systemctl start "$SYSTEMD_UNIT"
        else
            do_start
        fi
        ;;
    stop)
        if systemd_managed; then
            log "🔧 偵測到 systemd ($SYSTEMD_UNIT)，委託 systemctl stop"
            sudo systemctl stop "$SYSTEMD_UNIT"
        else
            do_stop
        fi
        ;;
    restart)
        if systemd_managed; then
            log "🔧 偵測到 systemd ($SYSTEMD_UNIT)，委託 systemctl restart"
            sudo systemctl restart "$SYSTEMD_UNIT"
        else
            do_stop; do_start
        fi
        ;;
    status)
        if systemd_managed; then
            sudo systemctl status "$SYSTEMD_UNIT" --no-pager
        else
            do_status
        fi
        ;;
    logs)
        if systemd_managed; then
            sudo journalctl -u "$SYSTEMD_UNIT" -f
        else
            LLOG=$(latest_log); [[ -n "$LLOG" ]] && tail -f "$LLOG" || die "無日誌可看"
        fi
        ;;
    log)
        if systemd_managed; then
            echo "journalctl -u $SYSTEMD_UNIT (systemd 日誌)"
        else
            LLOG=$(latest_log); [[ -n "$LLOG" ]] && echo "$LLOG" || die "無日誌"
        fi
        ;;
    foreground) preflight; cd "$BACKEND_DIR"; PYTHONPATH="$BACKEND_DIR/src" exec "$PYTHON_BIN" -m vibe_trading.cli start "$SYMBOL" --interval "$INTERVAL" --mode "$MODE" ;;
    ""|-h|--help|help) usage ;;
    *)          die "未知指令: $CMD" 3 ;;
esac
