---
# https://vitepress.dev/reference/default-theme-home-page
layout: home

hero:
  name: "Vibe Trading"
  text: "AI驱动的多Agent协作量化交易系统"
  tagline: 基于12个专业Agent的4阶段协作架构，结合大语言模型和智能风控，实现加密货币交易的智能化决策
  image:
    src: /logo.png
    alt: Vibe Trading Logo
  actions:
    - theme: brand
      text: 快速开始
      link: /guide/quick-start
    - theme: alt
      text: 系统架构
      link: /guide/architecture
    - theme: alt
      text: GitHub
      link: https://github.com/encyc/vibe-trading

features:
  - title: 🤖 12 Agent 协作
    details: 技术、基本面、新闻、情绪分析师 + 看涨/看跌研究员 + 风控团队 + 交易员 + 投资组合经理，4阶段协作决策
  - title: 🎭 智能辩论系统
    details: 看涨/看跌研究员多轮辩论，论点自动提取和量化裁决，确保决策的全面性和客观性
  - title: 🧠 BM25 记忆系统
    details: 从历史交易经验中学习，持续优化策略，通过BM25算法快速检索相关决策案例
  - title: 📊 Binance 深度集成
    details: 支持永续合约交易，实时K线订阅，23个专业工具涵盖技术分析、基本面、情绪分析等领域
  - title: 🎯 Paper Trading
    details: 模拟交易模式，零风险观察多Agent决策流程，适合先验证Agent输出、风控逻辑和执行计划
  - title: 🔎 K线级追溯
    details: 每根K线持久化保存Agent报告、阶段状态、Runtime Log和最终决策，点击历史K线即可复盘当时发生了什么
---

## 项目定位

Vibe Trading 不是简单的交易机器人，而是一个**面向量化交易的专业AI决策平台**，采用多Agent协作架构，模拟真实交易团队的决策流程。

你可以用它完成这些事情：

- **构建面向业务的量化交易系统**：基于多Agent协作的智能决策流程
- **零风险观察决策**：使用Paper Trading模式检查Agent输出、风控逻辑和最终决策
- **深度分析市场**：23个专业工具涵盖技术、基本面、情绪分析
- **实时监控决策**：Web界面实时展示决策过程和结果
- **持续学习优化**：基于BM25的记忆系统，从历史经验中学习

## 文档入口

### 入门与架构
- [快速开始](/guide/quick-start)：完成环境初始化、系统启动与首次交易
- [项目简介](/guide/intro)：了解整体定位、技术栈与核心能力
- [系统架构](/guide/architecture)：查看三线程架构与Agent协作流程
- [协作流程](/guide/workflow)：深入了解4阶段Agent协作流程
- [Agent团队](/guide/agents)：了解12个专业Agent的职责和功能

### 核心功能指南
- [Web监控](/guide/monitoring)：配置实时 Agent Arena 监控界面
- [外部数据层](/guide/external-data-layer)：核心+插件架构、智能路由与证据门控
- [交易所连接器](/guide/broker-connector)：Binance 与 OKX 双交易所多 Broker 路由
- [记忆系统升级](/guide/memory-upgrade)：FTS5 全文检索 + BM25 混合记忆与 5 级上下文压缩
- [P3 研究脊梁](/guide/research-backbone)：假设注册表、策略导出与 Swarm Presets
- [Telegram 告警通知](/guide/telegram-notifications)：三级优先级告警与 Inline Keyboard 确认机制
- [配置说明](/guide/configuration)：了解系统环境变量与 yaml 配置选项

### 研究与分析
- [竞品深度分析报告](/research/competitive-analysis)：与 HKUDS/Vibe-Trading 及 AlphaGPT 的多维深度对比与演进建议

### 架构与规范
- [系统全览](/architecture/system-overview)：完整的系统组件、生命周期与数据流
- [Agent 核心框架](/architecture/agent-framework)：基于 pi_agent_core 的双循环消息机制
- [平台一致性规范](/architecture/platform-conformance)：开发与架构一致性要求
- [Context 管理](/guide/context-management)：Agent 间状态传递与隔离
- [自定义 Agent](/guide/custom-agent)：开发和集成自定义角色
- [API 参考文档](/guide/api)：查看完整的 API 接口
- [ADR-0001 工具隔离](/adr/0001-replay-tool-isolation)：Replay 模式下的 Tool Isolation 机制
- [ADR-0002 回测与 Replay](/adr/0002-agent-replay-vs-rule-backtest)：Agent Replay 与规则回测边界

### 运维与部署
- [Web 系统状态](/operations/web-system-status)：运行时健康检查与遙測
- [生产部署检查清单](/operations/deployment-checklist)：切入 Live 實盤前的 5 項檢查規範

## 技术栈

- **后端**：Python 3.13+、FastAPI、Asyncio
- **AI/ML**：LangChain、大语言模型、BM25向量检索
- **数据源**：Binance API、实时K线订阅
- **前端**：React、Vite、TypeScript、lightweight-charts
- **部署**：Docker、GitHub Pages

## 下一步

- [安装依赖](/guide/quick-start#安装步骤)：配置环境和API密钥
- [运行系统](/guide/quick-start#运行系统)：启动Paper Trading模式
- [查看文档](/)：探索完整的文档和API
