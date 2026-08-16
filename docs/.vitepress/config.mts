import { defineConfig } from 'vitepress'
import { withMermaid } from 'vitepress-plugin-mermaid'
import markdownItTaskCheckbox from 'markdown-it-task-checkbox'

// https://vitepress.dev/reference/site-config
export default withMermaid(defineConfig({
  lang: 'zh-CN',
  title: "Vibe Trading",
  description: "AI驱动的多Agent协作加密货币量化交易系统",
  base: '/vibe-trading/',
  ignoreDeadLinks: [
    /localhost/,
    /CONTRIBUTING$/,
    /docker-compose\.yml$/
  ],
  markdown: {
    config: (md) => {
      md.use(markdownItTaskCheckbox)
    }
  },
  themeConfig: {
    // https://vitepress.dev/reference/default-theme-config
    logo: "/logo.png",
    nav: [
      { text: '快速开始', link: '/guide/quick-start' },
      { text: '系统架构', link: '/guide/architecture' },
      { text: 'Agent团队', link: '/guide/agents' }
    ],

    sidebar: [
      {
        text: '入门与架构',
        items: [
          { text: '快速开始', link: '/guide/quick-start' },
          { text: '项目简介', link: '/guide/intro' },
          { text: '系统架构', link: '/guide/architecture' },
          { text: 'Agent团队', link: '/guide/agents' },
          { text: '协作流程', link: '/guide/workflow' }
        ]
      },
      {
        text: '核心功能指南',
        items: [
          { text: 'Web监控', link: '/guide/monitoring' },
          { text: '数据提供者', link: '/guide/data-provider' },
          { text: '外部数据层', link: '/guide/external-data-layer' },
          { text: '交易所连接器', link: '/guide/broker-connector' },
          { text: '记忆系统基础', link: '/guide/memory' },
          { text: '记忆系统升级', link: '/guide/memory-upgrade' },
          { text: 'P3 研究脊梁', link: '/guide/research-backbone' },
          { text: 'Telegram告警通知', link: '/guide/telegram-notifications' },
          { text: '配置说明', link: '/guide/configuration' }
        ]
      },
      {
        text: '研究与竞品分析',
        items: [
          { text: '竞品深度分析报告', link: '/research/competitive-analysis' },
          { text: '技术演进路线图 (Roadmap)', link: '/research/evolution-roadmap' },
          { text: '398-Bar Replay 回测分析报告', link: '/research/replay-analysis-398bars' },
          { text: '架构与策略改善计划书', link: '/research/vbt-architecture-strategy-improvement-plan' }
        ]
      },
      {
        text: '架构与规范',
        items: [
          { text: '系统全览', link: '/architecture/system-overview' },
          { text: 'Agent核心框架', link: '/architecture/agent-framework' },
          { text: '平台一致性规范', link: '/architecture/platform-conformance' },
          { text: 'Context管理', link: '/guide/context-management' },
          { text: '自定义Agent', link: '/guide/custom-agent' },
          { text: 'API文档', link: '/guide/api' },
          { text: 'ADR-0001 工具隔离', link: '/adr/0001-replay-tool-isolation' },
          { text: 'ADR-0002 回测与Replay', link: '/adr/0002-agent-replay-vs-rule-backtest' },
          { text: '策略重构与双向交易规范', link: '/specs/vbt-architecture-strategy-improvement-spec' }
        ]
      },
      {
        text: '运维与部署',
        items: [
          { text: 'Web系统状态', link: '/operations/web-system-status' },
          { text: '生产部署检查清单', link: '/operations/deployment-checklist' }
        ]
      },
      {
        text: '开发指南',
        items: [
          { text: '参与贡献', link: '/develop/contributing' },
          { text: '开发路线图', link: '/develop/roadmap' },
          { text: '版本变更记录', link: '/develop/changelog' }
        ]
      }
    ],

    socialLinks: [
      { icon: 'github', link: 'https://github.com/encyc/vibe-trading' }
    ],

    footer: {
      message: '本项目基于 MIT License 开源，欢迎使用和贡献。',
      copyright: 'Copyright © 2026-present Vibe Trading'
    },

    editLink: {
      pattern: 'https://github.com/encyc/vibe-trading/edit/main/docs/:path',
      text: '在 GitHub 上编辑此页'
    },

    lastUpdated: {
      text: '最后更新时间',
      formatOptions: {
        dateStyle: 'full',
        timeStyle: 'medium'
      }
    },

    search: {
      provider: 'local'
    },

    docFooter: {
      prev: '上一页',
      next: '下一页'
    }
  },
}))
