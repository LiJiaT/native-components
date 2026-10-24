# 运行时支持矩阵（E04）

当前受测与交付范围：**Claude Code 格式 + Python 3.11+ + Git Bash / Windows 包装器**。其它 IDE/runtime 未声明兼容。

| 能力 | 状态 | 说明 |
|---|---|---|
| Skills/Agents/Rules/Memory 安装 | 已测 | 目标为 `~/.claude/...`；Windows 用 `win/*.cmd` |
| Hooks | 已测（Claude Code 事件格式） | 其它 runtime 需事件/adapter |
| Session transcript 采集 | 仅 Claude Code JSONL | Codex/其它格式未适配 |
| 外发门禁 | CLI + PreToolUse 示例 | 是否真正强制取决于宿主是否调用 hook |
| 计划/验收/安装门禁 | CLI 可执行 | 需显式调用；不是所有 runtime 自动触发 |
| OS 跨日调度 | 仅文档/示例 | 需部署 owner 登记真实任务 |
| 其它操作系统 | 未验证 | 不据 Windows 通过宣称 macOS/Linux 全通过 |

新增 runtime 的条件：有真实使用需求、明确事件/消息格式、安装落点与权限模型；先加 adapter 与正反例，再更新本表。不得把“文件能复制”当作运行时适配完成。
