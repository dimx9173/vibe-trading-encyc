# 永动印钞机 — 架构设计（Approach A：Minimal Dual-Mode + Configurable Windows + LLM 1+指标）

> **状态**：已按 brainstorming（Architectural）分节确认 6 节，按 writing-plans (8 tasks, G1-G5) 执行中；预设门槛 7d（336 bars×3），3/5d 仅特殊需求时手动加跑（见本文件 §5）。提醒：本文件为 hard gate（切换 AlphaZoo/出场/判定需回測重算，非调阈值可套用）。
> **目标**：沿用 30m 主回路 / 每2hr 一次 LLM / 每次 24hr 48×30m 节奏，实现「严格永动」— 3×168h（7d）每段 PF≥1.2 + 总MaxDD≤5% 全过；預設僅 7d 門檻，3/5天可配能力保留作特殊需求的可選加跑（`REPLAY_WINDOW_DAYS/--window-days`）。
> **约束**：Q2 已授权新因子/新指标/LLM，不必死守 40 组合；Q3 定 B+C（双模态 + 管线前置）；Q4 定 30m/2hr/24hr；末轮定 1+指标（LLM 选项1 Regime 扩展 + AlphaZoo 均值回归接线）。

## §1 目标 / 非目标 / 不变式

**目标**：
- **C 管线**：`select_windows.py` 支持 `--window-days/--window-bars` + `REPLAY_WINDOW_DAYS` env，能力 `3/5/7天可配` 保留，**預設僅 7d（`windows.json` 336 bars×3）進 G2 門檻**；`sweep_phase2.py / run_phase2.py / tearsheet_rule.py` 支持 `--windows` 透传，默认 `windows.json` 兼容。
- **B 双模态**：在 `AlphaZoo 23因子` 内接线均值回归（`rsi_zscore + bollinger_band_width + price_to_ma`）作第二模态；以 `bollinger_band_width` 窄阈 `T_bb` 切换 `动量 / 均值回归 / FLAT`，TP 按模态降档。
- **LLM 1+指标**：沿用 `macro_thread 7200s / macro_lookback 24hr / macro_max_age 14400s`，LLM 離散 `CHOPPY/TRENDING/UNCERTAIN → DISCRETE_QTY/THR`（仅减仓，永不加仓）+ `RISK_ON|NEUTRAL|RISK_OFF` 硬 veto，落库 `MacroState.regime_detail`。
- **门槛**：Q7 `每段 PF≥1.2 + 总MaxDD≤5%（10k/30k）`，**預設僅 7d（`windows.json`）全过即 G2；3/5d 僅特殊需求時手動加跑**，之後 Walk-Forward 90d→30d×3 確認泛化。

**非目标**：不新增交易所/数据源（仍 Binance 单所）、不改 `store-before-decide`、不改 `ExitLadderEngine` 核心阶梯（仅参数）、不引全新外部因子库（仅 AlphaZoo 已有 23 个 + LLM 输出）。

**不变式**：`reduce_only` 绕过 `PreTradeRiskGate` 与 regime gate；`RISK_OFF` 仅挡开仓不挡平仓；`staleness` 无/过期 → `NEUTRAL`；`tearsheet equity = cash+locked+unrealized`。

## §2 管线参数化（Plan C 前置，預設僅 7d 門檻，3/5d 能力保留作可選）

**动机**：`select_windows.py` 写死 `WINDOW_BARS=336`，`sweep/run_phase2` 写死 `windows.json` 与段顺序，无法 3/5/7天随便配；能力保留，但 G2 預設僅 7d。

**改动**：
- `replay/select_windows.py`：新增 `--window-days/--window-bars/--warmup-bars/--separation-bars` + `REPLAY_WINDOW_DAYS/BARS/WARMUP/SEPARATION` env；`WINDOW_BARS = window_bars ?: window_days×48 ?: env ?: 336`，`MIN_SEPARATION = separation ?: WINDOW_BARS+4`，`params` 增 `window_days`。
- `replay/sweep_phase2.py`：新增 `--windows (default REPLAY_WINDOWS ?: DATA_DIR/windows.json)`，透传至 `run_replays(windows_path)` 与 `tearsheet --windows`，段顺序改由 `windows["segments"]` 驱动，产物 `sweep_{days}d/` 隔离，resume 按 `windows_path` 指纹。
- `replay/run_phase2.py`：同 `--windows` 透传。
- `replay/tearsheet_rule.py`：已支持 `--windows`，仅需 sweep 侧修 L55 写死透传；表头可选显示 `window_days`。
- `rule_engine/config.py`：不动（管线参数走 replay 侧 env）。

**兼容**：无参调用仍产出与现 `windows.json` 字节一致的 336 窗口；无 `--windows` 时仍读 `DATA_DIR/windows.json`；`windows_{days}d.json` 隔离不覆盖 7d。

**验证（預設僅 7d）**：`python replay/select_windows.py --window-days 7 --out replay/data/windows.json`（默認）；`uv run python replay/sweep_phase2.py --windows replay/data/windows.json --max-combos 20 --fee-bps 8 && uv run python replay/tearsheet_rule.py --windows replay/data/windows.json --json | jq .gate_pass`；`uv run python replay/walk_forward.py --windows replay/data/windows.json`（90d→30d×3）；`3/5d` 僅特殊需求時手動 `for d in 3 5; do select_windows --window-days $d --out windows_${d}d.json; done`。

## §3 双模态信号（AlphaZoo 23 因子内）— Trader Review 修订

**现状**：`signal.py:16 MOMENTUM_KEYS=("momentum_12_1","rate_of_change")` → `tanh(mean/max|mean|)`，40 组合证伪纯动量在 range。`T_bb=0.025` 绝对阈值在牛熊波动率 2-3 倍下失效、无迟滞会导致模态抖动。

**设计**（`signal.py + config.py`，`zoo.py` 不动）：
- **动量模态**：`s_mom` 沿用。
- **均值回归模态**：`rsi_zscore + price_to_ma*scale → -tanh(mean)`，`scale=10`，`bollinger_band_width` 作切换门。
- **切换（自适应 + 迟滞，防抖动）**：
  ```python
  # 自适应：相对阈值，非绝对 0.025
  bb_median_20 = median(bb_w[-20:])  # 20 周期中位數
  T_bb_adapt = bb_median_20 * 0.7     # 擠壓 = 當前寬度 < 20周期中位數×0.7
  T_bb = max(T_bb_adapt, 0.015)       # 下限 0.015 防極端低波動過度 FLAT
  # 迟滞：进/出需持续 N 根
  if bb_w < T_bb_adapt for 3 bars and abs(rsi_z) < T_rsi:  mode = CHOPPY  # 進橫盤 3 根確認
  elif bb_w > T_bb_adapt * 1.3 for 2 bars:                mode = TRENDING # 出橫盤 2 根確認
  # 执行
  if mode == CHOPPY: signal = FLAT 或 s_mr（二選一 sweep 對比，默認 FLAT）
  elif mode == TRANSITION: composite = 0.7*s_mr + 0.3*s_mom
  else: composite = s_mom
  ```
  - `RULE_BB_WIDTH_THRESHOLD=0.025` 保留作**相对系数** `0.7` 的覆盖 env（`RULE_BB_WIDTH_RATIO`），`RULE_RSI_NEUTRAL=0.4` 不变；新增 `RULE_CHOPPY_ENTER_BARS=3 / RULE_CHOPPY_EXIT_BARS=2`。
  - 默认 **FLAT 小倉試探**：`CHOPPY → qty *= neutral_risk_scale * 0.3` 而非 0，保留樣本統計意義，非直接 0 交易。
- **TP/SL 分模態（P1 强建议）**：
  - `if MR/CHOPPY: sl_atr_mult = 2.5, tp_atr_mult = min(tp, 1.8), trailing=0, ladder 50/30/20 或 70/30/0`（寬止損窄止盈，無 trailing，橫盤波幅有限 1.5R 足夠）；
  - `if MOM/TRENDING: sl 1.5-2.0 / tp 2.5-3.0 / trailing 1.0×ATR / 30/40/30` 維持。
  - `config.py` 新增 `RULE_MR_SL_ATR=2.5 / RULE_MR_TP_ATR=1.8 / RULE_MR_TRAILING=0`（replay 侧 env 可扫）。
- **Sweep**：先固定 `thr0.6/sl2/tp3` 扫 `T_bb_ratio×T_rsi×{FLAT,MR}=18`，择优后再与 `sl/tp`（含 `RULE_MR_*`）正交。

## §4 LLM Regime 扩展（选项1，30m/2hr/24hr，1+指标）— Trader Review 修订

**节奏**：`loop.py on_bar` 每 30m 8 步；`macro_thread 7200s` 每 2hr 1次 `KlineQuery(30m, limit=48)` 注入 `market_data.klines_24h`；`macro_max_age 14400s` 容忍一次失败。

**改动**：
- `agents/macro_agent.py`：prompt 追加 `REGIME_DETAIL: CHOPPY|TRENDING|UNCERTAIN`（**離散 3 檔，非連續 0..1**，防 LLM 連續分不穩定）+ 自洽約束（`CHOPPY→qty↓ threshold↑`，`TRENDING→維持`）；`_parse_analysis` 離散解析回退 + 自洽降級；`create_macro_state` 新增 `regime_detail/llm_model/latency` 落库（`range_score` 欄位保留作离散映射 `CHOPPY=0.3/TRENDING=1.0/UNCERTAIN=0.5`，非 LLM 直出）。
  - **成本**：1.5-2K in/次，18-24K/天；**風控鐵律**：LLM 只做減倉（`qty <= 原 qty`、`threshold >= 原 threshold`），永不加倉，幻覺不重倉。
- `rule_engine/regime_gate.py`：新增 `current_regime_with_score(max_age=14400) -> (Regime, detail)`（`detail` 離散 3 檔），stale→`(NEUTRAL, UNCERTAIN)`，保留 `current_regime()` 兼容。
- `rule_engine/loop.py`：Step4 `RISK_OFF` 仍硬 veto；Step5 `adjusted_threshold = base * {1.4 if CHOPPY else 1.2 if UNCERTAIN else 1.0}`；Step6 `qty *= {0.3 if CHOPPY else 0.5 if UNCERTAIN else 1.0}`（僅減倉）；回测 `replay_rule_engine --inject-detail/--replay-macro-db` 重放真 2hr 节奏；新增 `llm_latency_ms > 8000` 告警（`switchboard` 代理监控）。

## §5 验证 — Trader Review 修订（預設僅 7d）

- 单窗口门槛 `每段 PF≥1.2 + 总MaxDD≤5%` 与 `tearsheet` 现 gate 一致；**新增 `fee_bps=8`（Binance taker 4bps + 滑點 3-5bps，往返 8-10bps）進 `replay_rule_engine` → `tearsheet` gate**，現 PF 1.14 未扣費為虛值，扣費後真實 PF 需重算。
- **預設流程（僅 7d）**：`§2 windows.json (336×3) → §3 扫 T_bb/T_rsi×{FLAT/MR} 18 組合 → 择优正交 §3+§4 → tearsheet --windows windows.json --json` 判定 G2；**Walk-Forward 90d→30d×3 確認泛化**（`walk_forward.py`）；**3/5d 僅特殊需求時手動加跑**（`select_windows --window-days 3/5`），不進預設門檻。
- **新增單幣隔離**（`gate_pass` 現 `all(seg pf≥1.2)` 跨幣綁定，實盤應幣種隔離倉位，`tearsheet` 增 `per-coin PF` 分解表）。

## §5.1 保命规则（新增，P2）

1. **橫盤熔斷**：`detail==CHOPPY` 連續 3 個 2hr 周期（6hr）且期間 PF<0.9 → `RULE_BB_WIDTH_THRESHOLD=0` 關雙模態，回退純 FLAT 48hr。
2. **單幣隔離倉位**：`tearsheet` 輸出 `per-coin PF`，實盤 `loop.py` 按幣種隔離 `qty`，SOL 橫盤虧不拖 BTC。

## §6 风险 / 回滚 / 成本

- 风险：LLM 幻觉 → clamp+回退；双模态 2 阈值已控 18 组合。
- 回滚：`RULE_BB_WIDTH_THRESHOLD=0` 关双模态；`RULE_MACRO_MAX_AGE_SECONDS` fail-safe 退 NEUTRAL；管线默认 `windows.json` 336 回归。
- 成本：每2hr 1次 1.5-2K in，无 30m 热路径增延时。

## 附录

**文件清单**：`replay/select_windows.py, sweep_phase2.py, run_phase2.py, tearsheet_rule.py, replay_rule_engine.py` + `backend/src/vibe_trading/rule_engine/{signal,config,loop,regime_gate}.py` + `agents/macro_agent.py, threads/macro_thread.py, data_sources/alphas/zoo.py (只读)` + 产物流 `windows_{3,5,7}d.json / sweep_{d}d/`。

**Env 清单**：`REPLAY_WINDOW_DAYS/BARS/WARMUP/SEPARATION/REPLAY_WINDOWS`（管线）+ `RULE_BB_WIDTH_THRESHOLD/RULE_RSI_NEUTRAL/RULE_ENTRY_THRESHOLD/RULE_SL_ATR_MULT/RULE_TP_ATR_MULT/RULE_MACRO_*`（信号/出场/LLM）。

**Gate 定义**：`tearsheet_rule.py:150` `gate_pass = all(seg pf≥1.2 & trades>0 & coinDD≤5%) & totalDD≤5%`。

## 自检

- [x] 无 TBD/TODO，占位已填（T_bb/T_rsi/scale 均给初值与 env）。
- [x] 内部一致：LLM 不进 30m 热路径，`RISK_OFF` 硬 veto 与 `range_score` 连续调节分层；双模态与 LLM 在 `regime_gate+signal+loop` 单一切换点汇合。
- [x] 范围聚焦：单规约可交付（管线→信号→LLM→验证闭环），B 的 IC 接线与 C 的 LLM 主信号已排除。
- [x] 无二义：窗口 `days×48`、staleness `14400s`、LLM 节奏 `7200s/24hr/48 bars` 均显式。
