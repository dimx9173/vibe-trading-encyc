# 永动印钞机 — 架构设计（Approach A：Minimal Dual-Mode + Configurable Windows + LLM 1+指标）

> **状态**：已按 brainstorming（Architectural）分节确认 6 节，待 writing-plans 转执行计划。批准前不写代码。
> **目标**：沿用 30m 主回路 / 每2hr 一次 LLM / 每次 24hr 48×30m 节奏，实现「严格永动」— 3×168h 每段 PF≥1.2 + 总MaxDD≤5% 全过，之後以 3/5/7天可配窗口泛化验证。
> **约束**：Q2 已授权新因子/新指标/LLM，不必死守 40 组合；Q3 定 B+C（双模态 + 管线前置）；Q4 定 30m/2hr/24hr；末轮定 1+指标（LLM 选项1 Regime 扩展 + AlphaZoo 均值回归接线）。

## §1 目标 / 非目标 / 不变式

**目标**：
- **C 管线**：`select_windows.py` 支持 `--window-days/--window-bars` + `REPLAY_WINDOW_DAYS` env，产物 `windows_{3,5,7}d.json` 与 `sweep_{d}d/` 隔离；`sweep_phase2.py / run_phase2.py / tearsheet_rule.py` 支持 `--windows` 透传，默认 `windows.json` (336 bars/168h) 兼容。
- **B 双模态**：在 `AlphaZoo 23因子` 内接线均值回归（`rsi_zscore + bollinger_band_width + price_to_ma`）作第二模态；以 `bollinger_band_width` 窄阈 `T_bb` 切换 `动量 / 均值回归 / FLAT`，TP 按模态降档。
- **LLM 1+指标**：沿用 `macro_thread 7200s / macro_lookback 24hr / macro_max_age 14400s`，LLM 输出扩为 `RISK_ON|NEUTRAL|RISK_OFF + RANGE_SCORE 0..1 + REGIME_DETAIL TRENDING_UP|TRENDING_DOWN|CHOPPY|UNCERTAIN`，落库 `MacroState`，`regime_gate.current_regime_with_score()` 供 `loop.py` 作 `qty *= lerp` 与 `entry_threshold` 动态，`RISK_OFF` 仍硬 veto。
- **门槛**：Q7 `每段 PF≥1.2 + 总MaxDD≤5%（10k/30k）`，先 3×168h 至少一组全过，再 3/5/7天可配窗口泛化。

**非目标**：不新增交易所/数据源（仍 Binance 单所）、不改 `store-before-decide`、不改 `ExitLadderEngine` 核心阶梯（仅参数）、不引全新外部因子库（仅 AlphaZoo 已有 23 个 + LLM 输出）。

**不变式**：`reduce_only` 绕过 `PreTradeRiskGate` 与 regime gate；`RISK_OFF` 仅挡开仓不挡平仓；`staleness` 无/过期 → `NEUTRAL`；`tearsheet equity = cash+locked+unrealized`。

## §2 管线参数化（Plan C 前置）

**动机**：`select_windows.py` 写死 `WINDOW_BARS=336`，`sweep/run_phase2` 写死 `windows.json` 与段顺序，无法 3/5/7天随便配。

**改动**：
- `replay/select_windows.py`：新增 `--window-days/--window-bars/--warmup-bars/--separation-bars` + `REPLAY_WINDOW_DAYS/BARS/WARMUP/SEPARATION` env；`WINDOW_BARS = window_bars ?: window_days×48 ?: env ?: 336`，`MIN_SEPARATION = separation ?: WINDOW_BARS+4`，`params` 增 `window_days`。
- `replay/sweep_phase2.py`：新增 `--windows (default REPLAY_WINDOWS ?: DATA_DIR/windows.json)`，透传至 `run_replays(windows_path)` 与 `tearsheet --windows`，段顺序改由 `windows["segments"]` 驱动，产物 `sweep_{days}d/` 隔离，resume 按 `windows_path` 指纹。
- `replay/run_phase2.py`：同 `--windows` 透传。
- `replay/tearsheet_rule.py`：已支持 `--windows`，仅需 sweep 侧修 L55 写死透传；表头可选显示 `window_days`。
- `rule_engine/config.py`：不动（管线参数走 replay 侧 env）。

**兼容**：无参调用仍产出与现 `windows.json` 字节一致的 336 窗口；无 `--windows` 时仍读 `DATA_DIR/windows.json`；`windows_{days}d.json` 隔离不覆盖 7d。

**验证**：`for d in 3 5 7; do select_windows --window-days $d --out windows_${d}d.json; sweep --windows windows_${d}d.json --max-combos 20; tearsheet --windows windows_${d}d.json --json; done`；`sweep --max-combos 2` 回归仍 9 档。

## §3 双模态信号（AlphaZoo 23 因子内）

**现状**：`signal.py:16 MOMENTUM_KEYS=("momentum_12_1","rate_of_change")` → `tanh(mean/max|mean|)`，40 组合证伪纯动量在 range。

**设计**（`signal.py + config.py`，`zoo.py` 不动）：
- **动量模态**：`s_mom` 沿用。
- **均值回归模态**：`rsi_zscore + price_to_ma*scale → -tanh(mean)`，`scale=10`，`bollinger_band_width` 作切换门。
- **切换**（`RULE_BB_WIDTH_THRESHOLD=0.025, RULE_RSI_NEUTRAL=0.4` 可调）：
  ```python
  if bb_w < T_bb and abs(rsi_z) < T_rsi:  return FLAT  # 默认保守：少做
  elif bb_w < T_bb:  composite = 0.7*s_mr + 0.3*s_mom
  else: composite = s_mom
  ```
  默认 FLAT，`s_mr` 作第二分岔与 sweep 对比择优。
- **TP 降档**：`loop.py` 若 `signal_source==MR: tp_atr_mult = min(tp, 2.0)`，动量维持原值。
- **Sweep**：先固定 `thr0.6/sl2/tp3` 扫 `T_bb×T_rsi×{FLAT,MR}=18`，择优后再与 `sl/tp` 正交。

## §4 LLM Regime 扩展（选项1，30m/2hr/24hr，1+指标）

**节奏**：`loop.py on_bar` 每 30m 8 步；`macro_thread 7200s` 每 2hr 1次 `KlineQuery(30m, limit=48)` 注入 `market_data.klines_24h`；`macro_max_age 14400s` 容忍一次失败。

**改动**：
- `agents/macro_agent.py`：prompt 追加 `RANGE_SCORE 0..1 + REGIME_DETAIL TRENDING_UP|DOWN|CHOPPY|UNCERTAIN`（与 `REGIME RISK_*` 自洽约束，成本 1.5-2K in/次，18-24K/天）；`_parse_analysis` clamp 回退 + 自洽降级；`create_macro_state` 新增 `range_score/detail/llm_model/latency` 落库。
- `rule_engine/regime_gate.py`：新增 `current_regime_with_score(max_age=14400) -> (Regime,float,str)`，stale→`(NEUTRAL,0.5,UNCERTAIN)`，保留 `current_regime()` 兼容。
- `rule_engine/loop.py`：Step4 `RISK_OFF` 仍硬 veto；Step5 `adjusted_threshold = base*(1+(1-score)*0.5)`；Step6 `qty *= regime_scale * lerp(0.5,1.0,score)`；回测 `replay_rule_engine --inject-range-score/--inject-detail/--replay-macro-db` 重放真 2hr 节奏。

## §5 验证

- 单窗口门槛 `每段 PF≥1.2 + 总MaxDD≤5%` 与 `tearsheet` 现 gate 一致；流程 `§2 windows_{3,5,7}d → §3 扫 T_bb/T_rsi×{FLAT/MR} → 择优正交 §3+§4 → tearsheet --json --windows`；防过拟合 3/5/7 各自独立，`7d` 过门槛再以 `3d/5d` hold-out。

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
