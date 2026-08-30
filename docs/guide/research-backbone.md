# P3 研究脊梁使用指南

## 概述

P3 研究脊梁提供了完整的研究管理和策略开发框架：

- **P3.1 Hypothesis Registry** - 假设管理和验证
- **P3.2 Memory Upgrade** - FTS5 搜索和上下文压缩
- **P3.4 Swarm Presets** - 管道编排预设

---

## P3.1 Hypothesis Registry

### 创建假设

```python
from vibe_trading.research.registry import HypothesisRegistry

registry = HypothesisRegistry()

# 创建新假设
hypothesis = await registry.create(
    title="BTC 动量策略",
    description="基于 RSI 和 MACD 的比特币动量交易策略",
    tags=["btc", "momentum", "rsi"],
    author="量化团队"
)

print(f"创建假设: {hypothesis.id}")
```

### 假设生命周期

```python
# DRAFT -> ACTIVE
await registry.activate(hypothesis.id)

# ACTIVE -> TESTING
await registry.start_testing(hypothesis.id)

# TESTING -> VALIDATED (添加回测证据)
await registry.validate(
    hypothesis.id,
    evidence={
        "sharpe_ratio": 1.5,
        "win_rate": 0.65,
        "backtest_period": "2024-01-01 to 2024-12-31"
    }
)

# 或者 TESTING -> INVALIDATED
await registry.invalidate(
    hypothesis.id,
    reason="夏普比率低于阈值",
    evidence={"sharpe_ratio": 0.6}
)
```

### 搜索假设

```python
# 按关键词搜索
results = await registry.search("BTC 动量")

# 按状态筛选
active_hypotheses = await registry.get_all(status=HypothesisStatus.ACTIVE)
```

### 链接回测结果

```python
# 添加回测结果
await registry.add_backtest_result(
    hypothesis.id,
    result={
        "sharpe_ratio": 1.5,
        "win_rate": 0.65,
        "max_drawdown": 0.12,
        "total_return": 0.35,
        "trade_count": 150
    }
)
```

---

## P3.2 Memory Upgrade

### FTS5 全文搜索

```python
from vibe_trading.research.database import ResearchDatabase

db = ResearchDatabase("research.db")

# 搜索假设（支持全文搜索）
results = await db.search_hypotheses("比特币动量策略 RSI MACD")

# 搜索研究目标
goals = await db.search_goals("量化策略开发")
```

### 上下文压缩

```python
from vibe_trading.data_sources.compression import ContextCompressor

compressor = ContextCompressor()

# 压缩研究证据
compressed = await compressor.compress(
    evidence_list,
    target_tokens=1000,
    compression_level="auto"  # auto, light, medium, heavy
)
```

---

## P3.4 Swarm Presets

### 获取预设

```python
from vibe_trading.coordinator.presets import PresetLoader

loader = PresetLoader()

# 获取所有内建预设（lightweight / full / risk_only / analysis_only）
presets = loader.load_builtin_presets()
lightweight = presets["lightweight"]
full = presets["full"]
```

### 预设结构

```python
# Investment Committee 预设（full）
# - Phase 1: analyzing（并行）
#   - Technical Analyst / Fundamental Analyst / News Analyst / Sentiment Analyst
# - Phase 2: debating（并行）
#   - Bull Researcher / Bear Researcher
# - Phase 3: assessing_risk（并行）
#   - Aggressive Risk / Neutral Risk / Conservative Risk
# - Phase 4: planning（串行）
#   - Trader / Portfolio Manager
```

### 创建自定义预设

```python
from vibe_trading.coordinator.presets import (
    AgentConfig,
    PhaseConfig,
    PipelinePhase,
    PresetLoader,
    PresetMode,
    SwarmPreset,
)

custom = SwarmPreset(
    name="my_preset",
    description="自定义交易管道",
    mode=PresetMode.FULL,
    phases={
        PipelinePhase.ANALYZING: PhaseConfig(
            enabled=True,
            agents={
                "technical_analyst": AgentConfig(
                    enabled=True, parallel=True, timeout_seconds=600
                ),
                "sentiment_analyst": AgentConfig(
                    enabled=True, parallel=True, timeout_seconds=600
                ),
            },
        ),
        PipelinePhase.PLANNING: PhaseConfig(
            enabled=True,
            agents={"trader": AgentConfig(enabled=True)},
        ),
    },
    global_timeout_seconds=1800,
)

# 校验
loader = PresetLoader()
issues = loader.validate_preset(custom)
assert not issues

# 保存预设（YAML）
path = loader.save_preset(custom)
```

### 加载预设

```python
# 从 YAML 文件加载
preset = loader.load_preset_from_file(path)

# 执行管道（注册阶段处理器后）
from vibe_trading.coordinator.presets import PipelineOrchestrator

orchestrator = PipelineOrchestrator(preset)
orchestrator.register_phase_handler(PipelinePhase.ANALYZING, my_analyze_handler)
results = await orchestrator.execute(context={})
```

---

## 完整工作流示例

### 1. 创建研究目标

```python
from vibe_trading.research.goal_manager import GoalManager

goal_manager = GoalManager()

goal = await goal_manager.create(
    title="开发 BTC 动量策略",
    description="基于技术指标的比特币动量交易策略开发",
    checklist_items=[
        "定义策略假设",
        "回测验证",
        "参数优化",
        "实盘验证"
    ],
    budget_backtests=20,
    tags=["btc", "momentum"]
)
```

### 2. 创建和验证假设

```python
hypothesis = await registry.create(
    title="RSI 超卖反弹策略",
    description="当 RSI < 30 时买入，RSI > 70 时卖出"
)

# 激活假设
await registry.activate(hypothesis.id)

# 开始测试
await registry.start_testing(hypothesis.id)

# 添加回测结果
await registry.add_backtest_result(
    hypothesis.id,
    result={
        "sharpe_ratio": 1.8,
        "win_rate": 0.68,
        "max_drawdown": 0.15
    }
)

# 验证假设
await registry.validate(hypothesis.id)

# 链接到研究目标
await goal_manager.link_hypothesis(goal.id, hypothesis.id)
```

### 3. 应用预设

```python
# 应用 Investment Committee 预设
preset = manager.get_preset("investment_committee")
await pipeline.apply_preset(preset)

# 运行管道
await pipeline.run()
```

---

## 数据库管理

### 备份数据库

```bash
# 备份研究数据库
cp research.db research.db.backup.$(date +%Y%m%d)
```

### 清理旧数据

```python
# 删除已归档的假设
archived = await registry.get_all(status=HypothesisStatus.ARCHIVED)
for hyp in archived:
    await registry.delete(hyp.id)

# 删除已完成的目标
completed = await goal_manager.get_all(status=GoalStatus.COMPLETED)
for goal in completed:
    await goal_manager.delete(goal.id)
```

---

## 性能优化

### 批量操作

```python
# 批量创建假设
hypotheses = await asyncio.gather(*[
    registry.create(title=f"策略 {i}", description=f"测试策略 {i}")
    for i in range(10)
])

# 批量验证
await asyncio.gather(*[
    registry.validate(hyp.id)
    for hyp in hypotheses
])
```

### 缓存优化

```python
# 启用假设缓存
registry.enable_cache(ttl=300)  # 5 分钟缓存

# 清除缓存
registry.clear_cache()
```

---

## 故障排除

### 问题：假设创建失败

**原因**：数据库连接问题

**解决方案**：
```python
# 检查数据库文件
import os
if not os.path.exists("research.db"):
    print("数据库文件不存在")

# 重新初始化
db = ResearchDatabase("research.db")
```

### 问题：导出代码为空

**原因**：交易计划格式不正确

**解决方案**：
```python
# 验证交易计划格式
assert "symbol" in trading_plan
assert "action" in trading_plan
assert "indicators" in trading_plan
```

### 问题：预设加载失败

**原因**：YAML 文件格式错误

**解决方案**：
```python
import yaml

# 验证 YAML 格式
with open("preset.yaml", "r") as f:
    data = yaml.safe_load(f)
    
# 检查必需字段
assert "name" in data
assert "type" in data
assert "stages" in data
```

---

## API 参考

### HypothesisRegistry

- `create(title, description, tags, author)` - 创建假设
- `get(hypothesis_id)` - 获取假设
- `update(hypothesis)` - 更新假设
- `activate(hypothesis_id)` - 激活假设
- `start_testing(hypothesis_id)` - 开始测试
- `validate(hypothesis_id, evidence)` - 验证假设
- `invalidate(hypothesis_id, reason, evidence)` - 作废假设
- `archive(hypothesis_id)` - 归档假设
- `search(query)` - 搜索假设
- `get_all(status)` - 获取所有假设
- `delete(hypothesis_id)` - 删除假设

### GoalManager

- `create(title, description, checklist_items, budget_backtests, tags)` - 创建目标
- `get(goal_id)` - 获取目标
- `update(goal)` - 更新目标
- `start(goal_id)` - 开始目标
- `complete_item(goal_id, item_id, evidence)` - 完成清单项
- `use_budget(goal_id, backtests, capital)` - 使用预算
- `link_hypothesis(goal_id, hypothesis_id)` - 链接假设
- `complete(goal_id, notes)` - 完成目标
- `cancel(goal_id, notes)` - 取消目标
- `get_all(status)` - 获取所有目标
- `delete(goal_id)` - 删除目标

### TemplateLibrary

- `get_all_templates()` - 获取所有模板
- `get_template(name)` - 获取特定模板
- `create_custom_template(...)` - 创建自定义模板
- `export_template(name, format)` - 导出模板

### PresetManager

- `get_all_presets()` - 获取所有预设
- `get_preset(name)` - 获取特定预设
- `save_preset(preset)` - 保存预设
- `load_preset(filepath)` - 加载预设
- `create_custom_preset(...)` - 创建自定义预设

---

## 最佳实践

### 假设管理

1. **明确标题** - 使用描述性标题，如"BTC RSI 超卖反弹策略"
2. **详细文档** - 在描述中包含策略逻辑和参数
3. **标签分类** - 使用标签组织假设（如"btc", "momentum", "rsi"）
4. **证据追踪** - 记录所有回测和实盘结果
5. **定期清理** - 归档已完成或无效的假设

### 预设使用

1. **选择合适预设** - 根据策略复杂度选择预设
2. **自定义调整** - 根据需要调整预设参数
3. **测试验证** - 在应用前测试预设
4. **文档记录** - 记录预设配置和修改

---

## 更新日志

### v1.0.0 (2026-08-14)

- ✅ P3.1 Hypothesis Registry
- ✅ P3.2 Memory Upgrade
- ✅ ~~P3.3 策略导出器~~（策略导出功能已移除）
- ✅ P3.4 Swarm Presets
- ✅ 完整单元测试（48 个测试）
- ✅ 使用文档
