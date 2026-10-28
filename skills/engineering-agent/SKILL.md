---
name: engineering-agent
description: 工程智能体的入口垫片。当用户触发 /engineering-agent 或要求"按工程化流程处理"时，委派给 Engineering Agent（真正的工程主体）执行；本 skill 的 references/ 与 scripts/ 是 agent 的支撑资源。简单单步任务不要触发。
---

# Engineering Agent（工程智能体）

本 skill 是 Engineering Agent 的入口垫片。实际执行由 `engineering-agent` 负责，
本 skill 的 `references/` 和 `scripts/` 目录是 agent 的支撑资源库。

当用户需要编排复杂任务时，**直接委派给 Engineering Agent** 即可。

## 支撑资源

- `references/architecture.md` — 详细架构与组件关系图
- `references/task-package-schema.md` — 任务包完整 schema 定义
- `references/hook-integration.md` — 可实现为 hook 的环节分析
- `references/quick-start.md` — 快速上手指南
- `scripts/task_packager.py` — 任务包生成/验证/列表 CLI 工具
