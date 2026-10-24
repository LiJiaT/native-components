# hooks/

确定性钩子脚本与配置示例。一个钩子组一个子目录，包含脚本、示例配置与测试。

## 当前收录

| 目录 | 事件 | 作用 |
|---|---|---|
| [`orchestrator`](orchestrator/README.md) | `SessionStart` / `UserPromptSubmit` | 注入编排模式标识、做复杂度预分类 |
| [`self-evolve`](self-evolve/README.md) | `SessionEnd` / `SessionStart` | `enqueue.py` 安全入队（无 eval）、提醒待确认候选、跨日唤醒 |

## 要求

- 脚本必须可从 stdin 读取事件 JSON，且有超时保护；不要做重活。
- 在 `README.md` 写清：触发事件、匹配器、输入、输出、失败策略、如何回滚。
- 提供至少一个最小测试输入与期望结果。
- 不包含凭证；需要凭证时从环境变量或宿主配置读取。
- 安装示例只写入受管区块，避免覆盖用户已有配置。

## 失败语义

- **旁路通知/上下文注入**（本目录现有 hooks）：可 fail-open，异常静默退出，不阻塞会话。
- **强制门禁**：必须 fail-closed，放在 [`gates/`](../gates/README.md)，异常/超时/缺 schema 都拒绝并写 audit。`gates/gate.py external-write` 是 PreToolUse 外发拦截示例，默认 deny。

不要把门禁逻辑写成"异常 exit 0 放行"。规范 §5.8 的 16 类门禁落地状态见 [`gates/README.md`](../gates/README.md)。
