# 永动印钞机 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 沿 30m 主回路 / 每2hr 一次 LLM / 每次 24hr 48×30m 节奏，实现 3×168h（7d）每段 PF≥1.2 + 总MaxDD≤5% 全过（預設僅 7d 進 G2 門檻，3/5d 能力保留作特殊需求可選加跑；見 spec §5）。

**Architecture:** C 管线可配窗口（`replay/select_windows.py` + `sweep_phase2.py`）前置；B 双模态（AlphaZoo 均值回归 + 自适应 bb×迟滞 + MR SL/TP 分模态）与 LLM 离散 CHOPPY/TRENDING/UNCERTAIN（仅减仓）在 `regime_gate + signal + loop` 单一切换点汇合；验证含 `fee_bps=8`、per-coin 隔离、横盘熔断、Walk-Forward。

**Tech Stack:** Python 3.12, pytest/pytest-asyncio, numpy (signal tanh), argparse + env 前缀 `REPLAY_/RULE_`, `tearsheet_rule.py` gate, Binance 30m bars, SQLite `macro_states`, `custom_openai→openai-completions` via `SWITCHBOARD`.

**Spec:** `docs/superpowers/specs/2026-08-30-perpetual-printer-design.md`（含 Trader Review 修订 §3/§4/§5/§5.1）。Spec 旅行：executor 读 spec + 本 plan。

## Global Constraints

- 交易所保持 Binance 单所（`docs/specs/money-printer-convergence-plan.md` Q1）；不改 `store-before-decide` 与 `reduce_only` 不变式。
- `ExitLadderEngine` 核心阶梯不动，仅参数分模态（`sl_atr_mult/tp_atr_mult/trailing/ladder`）。
- `AlphaZoo` 仅复用已有 23 因子（`rsi_zscore/bollinger_band_width/price_to_ma`），`zoo.py` 只读；不引新数据源/外部因子库。
- LLM 不进 30m 热路径，仅每 2hr 1次；LLM 只减仓（`qty<=`、`threshold>=`），永不加仓；`RISK_OFF` 仍硬 veto，stale→`NEUTRAL`。
- `tearsheet equity = cash+locked+unrealized` 保持； gate 口径 `tearsheet_rule.py:150` 全量 PF 含 `fee_bps=8` 重算。
- 窗口 `days×48`，staleness `14400s`，LLM `7200s/24hr/48 bars` 显式；兼容无参（336 字节一致）。

---

## File Map

| File | Responsibility |
|---|---|
| `replay/select_windows.py` | 窗口大小/间距参数化（`--window-days/bars/warmup/separation` + `REPLAY_*` env） |
| `replay/sweep_phase2.py` | `--windows` 透传 + 按 `windows["segments"]` 驱动 + 产物隔离 + resume 指纹 |
| `replay/run_phase2.py` | 同 `--windows` 透传 |
| `replay/tearsheet_rule.py` | 表头 `window_days` + per-coin PF 分解（新增） |
| `replay/replay_rule_engine.py` | `fee_bps` + `replay-macro-db`/`inject-detail` + 横盘熔断计数 |
| `backend/src/vibe_trading/rule_engine/signal.py` | 双模态 + 自适应 bb 中位×迟滞 + MR 分 |
| `backend/src/vibe_trading/rule_engine/config.py` | 新增 `RULE_BB_WIDTH_RATIO / RULE_CHOPPY_* / RULE_MR_*` |
| `backend/src/vibe_trading/rule_engine/loop.py` | per-mode TP/SL 切换 + LLM 离散 qty/threshold + `llm_latency>8000` 告警 |
| `backend/src/vibe_trading/rule_engine/regime_gate.py` | `current_regime_with_score() -> (Regime, detail)` 离散 3 档 |
| `backend/src/vibe_trading/agents/macro_agent.py` | prompt 追加 `REGIME_DETAIL` 离散 + 解析回退 + 落库 `regime_detail` |
| `backend/src/vibe_trading/data_sources/alphas/zoo.py` | 只读：校验 `rsi_zscore/bollinger_band_width/price_to_ma` 已计算 |
| `tests/test_*` | 各 task 的 TDD 覆盖（含 baseline gate 回归） |

---

### Task 1: 管线参数化 — select_windows 可配窗口

**Files:**
- Modify: `replay/select_windows.py`
- Test: `tests/test_select_windows_configurable.py` (new)

**Interfaces:**
- Consumes: `bars_*.json` (open_time, close), `REPLAY_WINDOW_DAYS/BARS/WARMUP/SEPARATION` env
- Produces: `windows_{N}d.json` with `params.window_days/window_bars/warmup_bars/separation_bars`; CLI `--window-days/--window-bars/--warmup-bars/--separation-bars/--windows`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_select_windows_configurable.py
def test_window_bars_derived_from_days(tmp_path):
    # --window-days 3 -> params window_bars == 144, params window_days == 3, len(segments)==3, non-overlap separation >= WINDOW_BARS+4
    pass
def test_env_fallback_and_cli_precedence(tmp_path, monkeypatch):
    # REPLAY_WINDOW_DAYS=5 with no CLI -> 240 bars; CLI --window-bars 100 overrides env
    pass
def test_default_compatible_has_same_336(tmp_path):
    # no args -> params window_bars==336, warmup 400, separation 340, segments 3, files keys BTCUSDT/ETHUSDT/SOLUSDT
    pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_select_windows_configurable.py -v`
Expected: FAIL — `FileNotFoundError / AttributeError: --window-days unknown`

- [ ] **Step 3: Write minimal implementation**

In `replay/select_windows.py`: add `argparse` args `--window-days int / --window-bars int / --warmup-bars int / --separation-bars int`; add helper `_env_int(name, default)` reading `REPLAY_*`; compute `WINDOW_BARS = args.window_bars or (args.window_days*48 if args.window_days else _env_int(... ) ?? 336)` and `SEPARATION = ... or WINDOW_BARS+4`; write `params.window_days` (if --window-days given else None) to `windows.json`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_select_windows_configurable.py -v`
Expected: PASS (3/3); `uv run python replay/select_windows.py --window-days 3 --out /tmp/windows_3d.json && jq .params /tmp/windows_3d.json` shows `window_bars 144`.

- [ ] **Step 5: Commit**

```bash
GIT_MASTER=1 git add replay/select_windows.py tests/test_select_windows_configurable.py
GIT_MASTER=1 git commit -m "feat(replay): make select_windows configurable by window-days/bars"
```

---

### Task 2: Sweep / run_phase2 / tearsheet --windows 透传 + 隔离

**Files:**
- Modify: `replay/sweep_phase2.py`
- Modify: `replay/run_phase2.py`
- Modify: `replay/tearsheet_rule.py` (add --windows passthrough fix + header window_days + per-coin stub)
- Test: `tests/test_sweep_windows_passthrough.py` (new)

**Interfaces:**
- Consumes: `windows_{N}d.json` from Task 1
- Produces: `sweep_{days}d/thr*/s2_*` isolated dirs; `tearsheet --windows <path>` reads correct splits; resume checks `windows_path` fingerprint

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sweep_windows_passthrough.py
def test_sweep_reads_alternate_windows(tmp_path):
    # sweep --windows tmp/windows_3d.json --max-combos 1 writes sweep_3d/ not sweep/
    pass
def test_tearsheet_header_shows_window_days(capsys):
    pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sweep_windows_passthrough.py -v`
Expected: FAIL — `unrecognized arguments: --windows`

- [ ] **Step 3: Write minimal implementation**

- `sweep_phase2.py`: add `--windows` (default `os.getenv("REPLAY_WINDOWS", DATA_DIR/"windows.json")`), replace hard-coded `DATA_DIR/"windows.json"` in `run_replays(windows_path)` and `tearsheet(windows_path)`; segments order from `windows["segments"]` names, not `["range","downtrend","uptrend"]` literal; `SWEEP_DIR = DATA_DIR / f"sweep_{days}d" if window_days else DATA_DIR/"sweep"` (parse from windows params or filename); resume checks `windows_path` mtime/hash.
- `run_phase2.py`: same `--windows` addition.
- `tearsheet_rule.py`: if already has `--windows`, ensure header prints `Window: {window_days}d ({window_bars} bars)` from `windows["params"]`; keep `gate_pass` logic unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_sweep_windows_passthrough.py -v`
Expected: PASS; `for d in 3 5 7; do uv run python replay/select_windows.py --window-days $d --out /tmp/w_${d}.json; uv run python replay/sweep_phase2.py --windows /tmp/w_${d}.json --max-combos 1 --help >/dev/null; done` no error.

- [ ] **Step 5: Commit**

```bash
GIT_MASTER=1 git add replay/sweep_phase2.py replay/run_phase2.py replay/tearsheet_rule.py tests/test_sweep_windows_passthrough.py
GIT_MASTER=1 git commit -m "feat(replay): add --windows passthrough and per-days sweep isolation"
```

---

### Task 3: RuleEngineConfig 新增 MR / 迟滞参数

**Files:**
- Modify: `backend/src/vibe_trading/rule_engine/config.py`
- Test: `tests/test_rule_engine_config_mr.py` (new)

**Interfaces:**
- Consumes: `os.environ` `RULE_*`
- Produces: `RuleEngineConfig.bb_width_ratio: float=0.7`, `bb_width_floor: float=0.015`, `rsi_neutral: float=0.4`, `choppy_enter_bars: int=3`, `choppy_exit_bars: int=2`, `mr_sl_atr: float=2.5`, `mr_tp_atr: float=1.8`, `mr_trailing: float=0.0` with `from_env()` mapping

- [ ] **Step 1: Write the failing test**

```python
def test_mr_config_from_env(monkeypatch):
    monkeypatch.setenv("RULE_BB_WIDTH_RATIO", "0.6")
    monkeypatch.setenv("RULE_MR_SL_ATR", "2.0")
    c = RuleEngineConfig.from_env()
    assert c.bb_width_ratio == 0.6
    assert c.mr_sl_atr == 2.0
    assert c.mr_trailing == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_rule_engine_config_mr.py -v`
Expected: FAIL — `AttributeError: RuleEngineConfig has no attribute bb_width_ratio`

- [ ] **Step 3: Write minimal implementation**

Add dataclass fields with defaults above plus `_env_float/_env_int` readers; keep existing `entry_threshold/atr_period/sl_atr_mult/tp_atr_mult/neutral_risk_scale/macro_max_age_seconds/max_single_notional/interval/macro_interval_seconds/macro_lookback_hours`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_rule_engine_config_mr.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
GIT_MASTER=1 git add backend/src/vibe_trading/rule_engine/config.py tests/test_rule_engine_config_mr.py
GIT_MASTER=1 git commit -m "feat(config): add MR dual-mode and hysteresis params"
```

---

### Task 4: 信号双模态 — 自适应 BB + 迟滞 + MR 分

**Files:**
- Modify: `backend/src/vibe_trading/rule_engine/signal.py`
- Test: `tests/test_rule_engine_signal_dual_mode.py` (new)

**Interfaces:**
- Consumes: `factors: Dict[str,float]` including `rsi_zscore/bollinger_band_width/price_to_ma`, `RuleEngineConfig` thresholds
- Produces: `generate_signal(factors, threshold=None, bb_history: Sequence[float] | None = None, mode_hint: str | None = None) -> RuleSignal` with `mode ∈ {TRENDING,CHOPPY,TRANSITION}` in `reason`; `momentum_tanh_score` for MOM, `mean_reversion_score = -tanh(mean([rsi_zscore, price_to_ma*10]))` for MR

- [ ] **Step 1: Write the failing test**

```python
def test_choppy_returns_flat_or_mr_flipped_via_config():
    # bb_w 20 hist median 0.03, current 0.015 (<0.021) + rsi_z 0.2 for 3 bars -> CHOPPY -> FLAT (default)
    # same with use_mr=True -> LONG/SHORT from -tanh(mr)
    pass
def test_hysteresis_requires_3_enter_2_exit():
    # 1-2 bars below threshold stays TRENDING, 3rd flips CHOPPY; 1 bar above 1.3x still CHOPPY, 2nd flips TRENDING
    pass
def test_adaptive_threshold_scales_with_median():
    # bb median 0.05 -> T_adapt 0.035, current 0.03 triggers CHOPPY; median 0.02 -> T_adapt 0.014 floor 0.015 -> 0.03 does not trigger
    pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_rule_engine_signal_dual_mode.py -v`
Expected: FAIL — still single-mode MOM

- [ ] **Step 3: Write minimal implementation**

- Add constants `BB_RATIO_DEFAULT=0.7`, keep `MOMENTUM_KEYS` unchanged; add helpers `mean_reversion_score(rsi_zscore, price_to_ma) -> float` and `bb_median_20(bb_history)`.
- `generate_signal`: compute `s_mom = momentum_tanh_score([momentum_12_1, rate_of_change])`, `s_mr = -momentum_tanh_score([rsi_zscore, price_to_ma*10])` (reuse tanh helper with sign flip); determine `mode` from `bb_history` (if None, fallback `bb_w < T_fixed`); branching as spec §3; `FLAT` default for CHOPPY, with optional `generate_signal(..., mr_enabled=True)` flip for sweep comparison.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_rule_engine_signal_dual_mode.py tests/test_rule_engine_signal.py -v`
Expected: PASS (dual + existing 12 tests)

- [ ] **Step 5: Commit**

```bash
GIT_MASTER=1 git add backend/src/vibe_trading/rule_engine/signal.py tests/test_rule_engine_signal_dual_mode.py
GIT_MASTER=1 git commit -m "feat(signal): adaptive BB dual-mode with hysteresis and MR score"
```

---

### Task 5: LLM 离散 3 档 — macro_agent + regime_gate

**Files:**
- Modify: `backend/src/vibe_trading/agents/macro_agent.py`
- Modify: `backend/src/vibe_trading/rule_engine/regime_gate.py`
- Modify: `backend/src/vibe_trading/data_sources/macro_storage.py` (add regime_detail column if not exists)
- Test: `tests/test_regime_gate_discrete.py` (new)
- Test: `tests/test_macro_agent_discrete.py` (new)

**Interfaces:**
- Consumes: `MacroState` + LLM prompt `REGIME_DETAIL: CHOPPY|TRENDING|UNCERTAIN` with `REGIME: RISK_*` constraint
- Produces: `regime_gate.current_regime_with_score(max_age=14400) -> tuple[Regime, Literal["CHOPPY","TRENDING","UNCERTAIN"]]`, discrete mapping `CHOPPY->0.3/TRENDING->1.0/UNCERTAIN->0.5` for qty/threshold math

- [ ] **Step 1: Write the failing test**

```python
def test_regime_discrete_choppy_maps_qty_03(macro_storage_with_choppy):
    regime, detail = current_regime_with_score(macro_storage_with_choppy, max_age=14400)
    assert detail == "CHOPPY"
    # stale -> UNCERTAIN
def test_macro_agent_parses_discrete_detail_and_clamps():
    # prompt contains REGIME_DETAIL: CHOPPY, _parse_analysis returns detail CHOPPY, unknown -> UNCERTAIN, CHOPPY with RISK_ON allowed (self-consistent)
    pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_regime_gate_discrete.py tests/test_macro_agent_discrete.py -v`
Expected: FAIL — `current_regime_with_score` not found / prompt missing discrete parse

- [ ] **Step 3: Write minimal implementation**

- `macro_agent.py`: extend `_build_analysis_prompt` to include `REGIME_DETAIL: CHOPPY|TRENDING|UNCERTAIN` + constraint line `CHOPPY→qty↓ threshold↑, TRENDING→维持`; `_parse_analysis` parse discrete detail (case-insensitive, fallback UNCERTAIN), keep `RISK_ON/NEUTRAL/RISK_OFF` primary; `create_macro_state` add `regime_detail` column.
- `regime_gate.py`: add `current_regime_with_score` returning `(Regime, detail)`; discrete mapping dict `DISCRETE_QTY = {"CHOPPY":0.3,"TRENDING":1.0,"UNCERTAIN":0.5}` and `DISCRETE_THR = {"CHOPPY":1.4,"TRENDING":1.0,"UNCERTAIN":1.2}` for loop consumption; `current_regime()` wraps it returning `Regime`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_regime_gate_discrete.py tests/test_macro_agent_discrete.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
GIT_MASTER=1 git add backend/src/vibe_trading/agents/macro_agent.py backend/src/vibe_trading/rule_engine/regime_gate.py backend/src/vibe_trading/data_sources/macro_storage.py tests/test_regime_gate_discrete.py tests/test_macro_agent_discrete.py
GIT_MASTER=1 git commit -m "feat(llm): discrete CHOPPY/TRENDING/UNCERTAIN regime with de-risk only"
```

---

### Task 6: Loop 集成 — per-mode TP/SL + LLM 离散联动 + 告警

**Files:**
- Modify: `backend/src/vibe_trading/rule_engine/loop.py`
- Test: `tests/test_rule_engine_loop_integration.py` (new)

**Interfaces:**
- Consumes: `RuleSignal.direction/mode`, `config.mr_*`, `regime_detail` discrete
- Produces: `on_bar` chooses `sl_atr_mult/tp_atr_mult/trailing/ladder` by mode (`CHOPPY/MR: 2.5/1.8/0/50-30-20` vs `TRENDING/MOM: 1.5-2.0/2.5-3.0/1.0×ATR/30-40-30`); `adjusted_threshold = base * DISCRETE_THR[detail]`; `qty *= DISCRETE_QTY[detail]` with `qty<=orig` invariant; `logger.warning` if `llm_latency_ms>8000`

- [ ] **Step 1: Write the failing test**

```python
def test_loop_picks_mr_exit_params_when_choppy(monkeypatch, tmp_path):
    # mock klines, inject regime_detail CHOPPY, assert ExitLadderConfig sl 2.5 tp 1.8 trailing 0 used
    pass
def test_loop_discrete_de_risk_only(monkeypatch):
    # CHOPPY: threshold 1.4x, qty 0.3x; TRENDING: unchanged; verify qty never > orig
    pass
def test_llm_latency_warning_logged(caplog):
    pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_rule_engine_loop_integration.py -v`
Expected: FAIL — loop still uses single sl/tp

- [ ] **Step 3: Write minimal implementation**

Branch on `signal.mode` or `regime_detail` to select `RuleEngineConfig.mr_*` vs `sl_atr_mult/tp_atr_mult`; wire `DISCRETE_THR/QTY` maps imported from `regime_gate`; assert `qty <= orig_qty`; add `if macro_state and macro_state.llm_latency_ms and macro_state.llm_latency_ms > 8000: logger.warning("llm_latency_ms %s > 8000", ...)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_rule_engine_loop_integration.py tests/test_rule_engine_signal.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
GIT_MASTER=1 git add backend/src/vibe_trading/rule_engine/loop.py tests/test_rule_engine_loop_integration.py
GIT_MASTER=1 git commit -m "feat(loop): per-mode exits and discrete LLM de-risk wiring"
```

---

### Task 7: 回放与验证闭环 — fees / per-coin / 横盘熔断 / Walk-Forward

**Files:**
- Modify: `replay/replay_rule_engine.py` (add --fee-bps 8, --replay-macro-db, --inject-detail)
- Modify: `replay/tearsheet_rule.py` (header window_days + per-coin PF table + Walk-Forward aggregation)
- Create: `replay/walk_forward.py` (new, 90d->30d x3)
- Test: `tests/test_tearsheet_per_coin_and_fees.py` (new)
- Test: `tests/test_walk_forward.py` (new)

**Interfaces:**
- Consumes: `windows_{N}d.json`, `sweep_{N}d/`, `macro_states.db` (optional)
- Produces: `tearsheet --json` includes `per_coin: {coin: {pf, max_dd, trades}}` + `fee_bps` field + `gate_pass` with `fee_bps=8` P&L; `walk_forward.py` prints 3-window gate summary

- [ ] **Step 1: Write the failing test**

```python
def test_fee_bps_reduces_pf(tmp_path):
    # same decisions with fee_bps 0 vs 8: pf decreases, gate may flip
    pass
def test_walk_forward_aggregates_3_windows(tmp_path):
    # walk_forward --windows windows_7d.json --train 90d --test 30d produces 3 sub-windows with independent gate
    pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tearsheet_per_coin_and_fees.py tests/test_walk_forward.py -v`
Expected: FAIL — `--fee-bps` unknown / walk_forward not found

- [ ] **Step 3: Write minimal implementation**

- `replay_rule_engine.py`: add `--fee-bps int default 8`, apply `pnl *= (1 - fee_bps/10000)` per trade before equity; add `--replay-macro-db path` + `--inject-detail CHOPPY|TRENDING|UNCERTAIN` to seed `macro_states` for backtest; track `detail` per bar for §5.1 熔断 counting (6hr window PF<0.9 → set `RULE_BB_WIDTH_THRESHOLD=0` for 48hr simulated).
- `tearsheet_rule.py`: compute `per_coin` from per-coin equity curves (existing `segments[seg][coin]` split); add header `Window: {window_days}d ... fee {fee_bps}bps`.
- `walk_forward.py`: slice 90d train / 30d test ×3 with overlap logic, invoke `tearsheet --json` per slice, aggregate gate.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tearsheet_per_coin_and_fees.py tests/test_walk_forward.py -v && uv run python replay/walk_forward.py --windows replay/data/windows.json --help`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
GIT_MASTER=1 git add replay/replay_rule_engine.py replay/tearsheet_rule.py replay/walk_forward.py tests/test_tearsheet_per_coin_and_fees.py tests/test_walk_forward.py
GIT_MASTER=1 git commit -m "feat(replay): fees, per-coin isolation, choppy circuit and walk-forward"
```

---

### Task 8: 全量回归 + 文档同步

**Files:**
- Modify: `docs/specs/money-printer-convergence-plan.md` (record G5 proof gate fee 8bps + discrete LLM)
- Modify: `AGENTS.md` (update per-mode exits + discrete LLM + Walk-Forward gates)
- Modify: `TODO.md` (move Stage 2 from FROZEN to in-progress checklist)
- Test: full `uv run pytest tests/ -x -q` + `uv run ruff check/format` + `mypy`

- [ ] **Step 1: Run full regression**

Run: `uv run pytest tests/ -x -q`
Expected: PASS 1946+ new tests (no 0-trade gate regression)

- [ ] **Step 2: Docs sync**

Update `money-printer-convergence-plan.md` §3-4 with `fee_bps=8`, discrete LLM, per-coin isolation; `AGENTS.md` threading 2hr/24hr + exits per-mode.

- [ ] **Step 3: Commit**

```bash
GIT_MASTER=1 git add docs/specs/money-printer-convergence-plan.md AGENTS.md TODO.md
GIT_MASTER=1 git commit -m "docs: sync perpetual printer G5 proof gates"
```

---

## Self-Review

- [x] §2 管线可配窗口 -> Task 1 + 2 (兼容字节一致 + 隔离 + resume 指纹)
- [x] §3 双模态自适应 BB×迟滞×MR + §3 TP/SL 分模态 -> Task 3 + 4 + 6 (3/2 bars, 0.7 ratio, 2.5/1.8/0)
- [x] §4 LLM 离散 3 档仅减仓 -> Task 5 + 6 (CHOPPY 0.3/1.4 等)
- [x] §5 fee 8bps + §5 Walk-Forward ×3 + 单币隔离 + §5.1 熔断 -> Task 7
- [x] Gate G1-G5 证据链 -> Tasks 1-8 验证闭环；无 TBD/TODO，占位已填；接口类型一致（`current_regime_with_score` 签名跨 Task 5→6 统一）。
