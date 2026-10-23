# hooks/

确定性钩子脚本与配置示例。一个钩子组一个子目录，包含脚本、示例配置与测试。

## 当前收录

| 目录 | 事件 | 作用 |
|---|---|---|
| [`orchestrator`](orchestrator/README.md) | `SessionStart` / `UserPromptSubmit` | 注入编排模式标识、做复杂度预分类 |
| [`self-evolve`](self-evolve/README.md) | `SessionEnd` / `SessionStart` | transcript 入队、提醒待确认的蒸馏候选 |

## 要求

- 脚本必须可从 stdin 读取事件 JSON，且有超时保护；不要做重活。
- 在 `README.md` 写清：触发事件、匹配器、输入、输出、失败策略、如何回滚。
- 提供至少一个最小测试输入与期望结果。
- 不包含凭证；需要凭证时从环境变量或宿主配置读取。
- 安装示例只写入受管区块，避免覆盖用户已有配置。

## 约束

本目录现有 hooks 都是**旁路上下文注入**，异常时静默放行。规范 §5.8 要求的审批/校验闸门（`require-six-elements`、`plan-schema-gate` 等）需要 fail-closed 实现，不能直接复用这些脚本；目前这些闸门尚未在本仓库落地。
