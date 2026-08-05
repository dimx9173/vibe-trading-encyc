#!/bin/bash
# restart_vbt.sh — 優雅重啟 vibe-trade (BTCUSDT 30m testnet)
#
# 用法:
#   ./scripts/restart_vbt.sh           # graceful: SIGTERM → 等 10s → SIGKILL fallback
#   ./scripts/restart_vbt.sh --force   # 立即 SIGKILL
#   SYMBOL=ETHUSDT ./scripts/restart_vbt.sh  # 換交易對
#
# 環境變數覆寫:
#   SYMBOL, INTERVAL, MODE, WEB_PORT
#
# Exit codes:
#   0 = 成功
#   1 = 啟動驗證失敗（新進程掛掉 / port 沒起來）
#   2 = 前置檢查失敗（.env 缺 / LLM_MODEL 對不到 llm.yaml）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

SYMBOL="${SYMBOL:-BTCUSDT}"
INTERVAL="${INTERVAL:-30m}"
MODE="${MODE:-testnet}"
WEB_PORT="${WEB_PORT:-8001}"
PAPER_STATE="${PAPER_STATE:-}"
RESET_PAPER="${RESET_PAPER:-0}"
GRACEFUL_TIMEOUT="${GRACEFUL_TIMEOUT:-10}"

# --- helpers ---
ts() { date +%H:%M:%S; }
log() { printf "[%s] %s\n" "$(ts)" "$*"; }
die() { printf "[%s] ❌ %s\n" "$(ts)" "$*"; exit "${2:-1}"; }

FORCE=false
[[ "${1:-}" == "--force" ]] && FORCE=true

# ============================================================================
# 1. 找現有進程
# ============================================================================
PID=$(pgrep -f "vibe-trade start" | head -1 || true)

if [[ -n "$PID" ]]; then
    log "🔍 找到運行中 vibe-trade: PID $PID (uptime $(ps -o etime= -p "$PID" | tr -d ' ' || echo unknown))"
    if $FORCE; then
        log "⚡ --force: 直接 SIGKILL"
        kill -9 "$PID" 2>/dev/null || true
        sleep 1
    else
        log "📨 SIGTERM (graceful)，最多等 ${GRACEFUL_TIMEOUT}s..."
        kill -TERM "$PID" 2>/dev/null || true
        for ((i=1; i<=GRACEFUL_TIMEOUT; i++)); do
            sleep 1
            if ! kill -0 "$PID" 2>/dev/null; then
                log "✅ PID $PID 在 ${i}s 內退場"
                break
            fi
            if [[ $i -eq $GRACEFUL_TIMEOUT ]]; then
                log "⚠️ 超時，強制 SIGKILL"
                kill -9 "$PID" 2>/dev/null || true
                sleep 1
            fi
        done
    fi
else
    log "ℹ️ 沒有運行中的 vibe-trade（將以全新啟動）"
fi

# ============================================================================
# 2. Port 釋放確認
# ============================================================================
if ss -ltn 2>/dev/null | grep -q ":${WEB_PORT}\b"; then
    log "⚠️ Port ${WEB_PORT} 還被佔用，掃描並清掉..."
    STUCK_PIDS=$(ss -ltnp 2>/dev/null | grep ":${WEB_PORT}\b" | grep -oP 'pid=\K[0-9]+' | sort -u || true)
    for p in $STUCK_PIDS; do
        log "   killing stuck PID $p on port ${WEB_PORT}"
        kill -9 "$p" 2>/dev/null || true
    done
    sleep 2
fi

# ============================================================================
# 3. 前置檢查 — 避免重蹈覆轍（.env 指向已被刪除的 llm.yaml config）
# ============================================================================
[[ -f "$PROJECT_DIR/.env" ]] || die ".env 不存在於 $PROJECT_DIR/.env" 2

# Load .env (project-local)
set -a
# shellcheck disable=SC1091
source "$PROJECT_DIR/.env"
set +a
log "📦 .env loaded"

LLM_MODEL_NAME="${LLM_MODEL:-}"
[[ -n "$LLM_MODEL_NAME" ]] || die "LLM_MODEL 未設置於 .env" 2

LLM_YAML="$PROJECT_DIR/backend/src/vibe_trading/config/llm.yaml"
if [[ ! -f "$LLM_YAML" ]]; then
    die "llm.yaml 不存在於 $LLM_YAML" 2
fi
# 檢查 yaml 裡有沒有這個 config block
if ! grep -qE "^[[:space:]]+${LLM_MODEL_NAME}:" "$LLM_YAML"; then
    die "LLM_MODEL=$LLM_MODEL_NAME 在 llm.yaml 找不到對應 config block！請檢查 .env 是否指向已刪除的 config（例如 nvidia_deepseek_v4_flash）" 2
fi
log "✅ LLM_MODEL=$LLM_MODEL_NAME 在 llm.yaml 內已確認存在"

# ============================================================================
# 4. 啟動
# ============================================================================
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/vbt_restart_${TIMESTAMP}.log"

log "🚀 啟動新 vibe-trade..."
log "   args: --start $SYMBOL --interval $INTERVAL --mode $MODE --web --web-port $WEB_PORT $([ "$RESET_PAPER" = 1 ] && echo '--reset-paper') $([ -n "$PAPER_STATE" ] && echo "--paper-state $PAPER_STATE")"
log "   log:  $LOG_FILE"

# 組 paper 持久化參數
PAPER_ARGS=()
if [[ -n "$PAPER_STATE" ]]; then
    PAPER_ARGS+=(--paper-state "$PAPER_STATE")
fi
if [[ "$RESET_PAPER" == "1" ]]; then
    PAPER_ARGS+=(--reset-paper)
    log "♻️  RESET_PAPER=1: 將重置 paper 帳戶（忽略狀態檔）"
else
    log "💾 Paper 帳戶狀態將自動還原（帶 RESET_PAPER=1 才重置）"
fi

cd "$PROJECT_DIR"
# 用 setsid 讓 vibe-trade 進入自己的 session，避免 exec session 清理時被 SIGTERM 波及
setsid nohup "$PROJECT_DIR/backend/.venv/bin/vibe-trade" start "$SYMBOL" \
    --interval "$INTERVAL" \
    --mode "$MODE" \
    --web \
    --web-port "$WEB_PORT" \
    "${PAPER_ARGS[@]}" \
    > "$LOG_FILE" 2>&1 &

NEW_PID=$!
disown
log "🆕 New PID: $NEW_PID"

# ============================================================================
# 5. 啟動驗證
# ============================================================================
sleep 8
if ! kill -0 "$NEW_PID" 2>/dev/null; then
    log "❌ 新進程在 8s 內已退場！"
    log "--- log tail ---"
    tail -30 "$LOG_FILE" | sed 's/^/    /'
    die "啟動驗證失敗" 1
fi

if ! ss -ltn 2>/dev/null | grep -q ":${WEB_PORT}\b"; then
    log "⚠️ 進程活著但 port ${WEB_PORT} 沒 listen"
    log "--- log tail ---"
    tail -30 "$LOG_FILE" | sed 's/^/    /'
    die "Port 驗證失敗" 1
fi

# ============================================================================
# 6. 成功
# ============================================================================
UPTIME=$(ps -o etime= -p "$NEW_PID" | tr -d ' ')
log ""
log "═══════════════════════════════════════════════════════════════"
log "✅ VBT 重啟成功"
log "   PID:    $NEW_PID"
log "   Port:   ${WEB_PORT}"
log "   Log:    $LOG_FILE"
log "   Uptime: $UPTIME"
log ""
log "📊 觀察指令:"
log "   tail -f $LOG_FILE"
log "   ps -p $NEW_PID"
log "═══════════════════════════════════════════════════════════════"