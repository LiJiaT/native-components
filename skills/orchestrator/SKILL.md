---
name: orchestrator
description: 编排智能体的入口垫片。仅在用户显式触发 /orchestrator 时使用；命中后直接委派 orchestrator agent，不重复判断复杂度、不重复澄清。本 skill 的 references/ 与 scripts/ 是 agent 的支撑资源。简单单步任务不要触发。
---

# Orchestrator（编排智能体）

本 skill 是 orchestrator agent 的入口垫片。实际执行由 `orchestrator` agent 负责，
本 skill 的 `references/` 和 `scripts/` 目录是 agent 的支撑资源库。

当用户需要编排复杂任务时，**直接委派给 orchestrator agent** 即可。

## 支撑资源

- `references/architecture.md` — 详细架构与组件关系图
- `references/task-package-schema.md` — 任务包完整 schema 定义
- `references/hook-integration.md` — 可实现为 hook 的环节分析
- `references/quick-start.md` — 快速上手指南
- `scripts/task_packager.py` — 任务包生成/验证/列表 CLI 工具
