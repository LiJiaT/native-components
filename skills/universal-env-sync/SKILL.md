---
name: universal-env-sync
description: 在 Claude Code 主源与 Qoder、TRAE、Codex 等所有已安装 AI IDE 之间同步 skills、agents、hooks、全局规则/系统提示词、MCP 与 memory，并报告冲突。当用户说“同步所有 AI IDE”“同步环境”“把 skill/hook/memory/MCP/系统提示词同步过去”“各个 IDE 对齐”“从任意 IDE 同步全部环境”“检查环境漂移/冲突”，或定期做环境对齐时，必须使用本技能。也用于把某个 IDE 的本地修改采纳回 Claude 主源。
---

# Universal Env Sync

把 Claude Code 的用户级环境当作唯一主源，把其余 AI IDE 当作生成副本。
同步时只更新“无漂移”的副本；任何本地修改都报告为冲突，绝不自动覆盖或自动反向提升。

## 核心模型

- **主源**：`~/.claude`，由 git 维护（`<ENV_SNAPSHOT_DIR>` 是快照）。
- **生成副本**：Qoder CN / Qoder IDE / TRAE CN / TRAE / Codex / 共享 `~/.agents`。
- **基线**：`~/.ai-env-sync/state.json`，记录上次同步时主源与各副本的哈希。
- **无漂移副本**：内容仍等于基线，可安全更新。
- **漂移副本**：内容被本地改过，只报告；用 `adopt` 显式采纳回 Claude。
- **首跑**：只扫描、建基线、出报告，不写任何 IDE 文件。再跑一次才会创建缺失副本。
- **密钥**：不写明文密钥；能转成 `${ENV_VAR}` 的自动转，不能转的拦截并报告。

## 快速开始

在任意 IDE 中调用本技能，然后：

```bash
python ~/.claude/skills/universal-env-sync/scripts/envsync.py detect
python ~/.claude/skills/universal-env-sync/scripts/envsync.py status
python ~/.claude/skills/universal-env-sync/scripts/envsync.py sync --dry-run
python ~/.claude/skills/universal-env-sync/scripts/envsync.py sync
```

如果 `python` 不在 PATH，用 `py -3` 替代；Windows 下也可以直接调用已安装到各 IDE 的同一脚本。

## 命令

| 命令 | 作用 |
|---|---|
| `detect` | 列出已安装目标、各资产落点与数量 |
| `status` | 对比主源与副本，输出冲突报告，不写基线 |
| `sync --dry-run` | 预览本次同步计划，不写任何文件 |
| `sync` | 首跑只报告；之后创建缺失副本、更新无漂移副本、报告漂移 |
| `sync --prune` | 额外删除主源已删除且副本无本地修改的资产 |
| `sync --only PATTERN` | 只处理 key/名称/目标匹配的资产，便于分步验证 |
| `sync --force --only PATTERN` | 用主源覆盖匹配范围内的漂移副本（先备份）；必须与 `--only` 同用 |
| `adopt KEY` | 把某个漂移/目标独有资产采纳回 Claude 主源（先备份） |
| `adopt-mcp [--from codex]` | 把 Codex 用户级 MCP 采纳进 Claude 用户级 MCP |
| `install-self` | 把本技能复制到所有已安装 IDE 的 skills 根目录 |

`KEY` 形如 `skill:foo@qoder-cn`、`agent:engineering-agent@codex`、`memory:windows-workstation@qoder-cn`、`mcp:node_repl@codex`。报告里会直接给出可复制的 key。

## 同步资产与落点

### Skills

- 主源：`~/.claude/skills/<name>/`
- 副本：`~/.qoder-cn/skills/`、`~/.qoder/skills/`、`~/.trae-cn/skills/`、`~/.trae/skills/`、`~/.codex/skills/`、`~/.agents/skills/`
- 默认排除：macOS 专属 5 个、`lark-*`、`skill-creator`（Qoder 插件已提供）。
- 排除列表可在 `~/.ai-env-sync/config.json` 的 `exclude_skills` 中调整，支持 glob。

### Agents

- 主源：`~/.claude/agents/*.md`
- Qoder CN / Qoder IDE：原样 Markdown
- Codex：转换为 `~/.codex/agents/<name>.toml`
- TRAE CN / TRAE：项目级 `.github/agents/<name>.agent.md`（TRAE 没有已验证的用户级 agent 目录）

### Hooks

- 主源：`~/.claude/settings.json` 的 `hooks` + `~/.claude/hooks/`
- Qoder CN：合并到 `~/.qoder-cn/settings.json`，只注册已验证的 `SessionStart`、`UserPromptSubmit`
- Codex：合并到 `~/.codex/hooks.json`，支持 `SessionStart`、`UserPromptSubmit`、`SessionEnd`
- Qoder IDE / TRAE：没有用户级 hook 机制，报告为不支持
- 目标已有同名 hook 时保留目标版本，不重复注册；本技能管理的脚本放在 `<target>/.ai-env-sync/hooks/`

### 全局规则与系统提示词

- 主源：`~/.claude/CLAUDE.md` + `~/.claude/rules/*.md`
- Qoder：写入共享 `~/.qoder/rules/`（Qoder CN 由 SessionStart hook 注入，Qoder IDE 原生加载）
- TRAE CN / TRAE：写入 `~/.trae-cn/user_rules/`、`~/.trae/user_rules/`
- Codex：写入 `~/.codex/AGENTS.md`
- 系统提示词写在受管区块内，区块外的平台专属内容原样保留；规则按同名文件镜像。

### MCP

- 主源：`~/.claude.json` 的用户级 `mcpServers` + 当前项目 `.mcp.json`
- Qoder CN：`~/.qoder-cn/settings.json` 的 `mcpServers`
- Qoder IDE：`~/.qoder/mcp.json` 的 `mcpServers`
- TRAE CN / TRAE：`%APPDATA%\Trae CN\User\mcp.json`、`%APPDATA%\Trae\User\mcp.json` 的 `mcpServers`（不写 `type`）
- Codex：`~/.codex/config.toml` 的 `mcp_servers`（受管区块）
- TRAE 项目级：当前项目 `.trae/mcp.json` 的 `mcpServers`
- Claude 用户级 MCP 为空时，用 `adopt-mcp` 显式把 Codex 的 `node_repl`、`web-search` 采纳进来；不自动提交 git。

### Memory

- 全局主源：`~/.claude/projects/<编码后的家目录>/memory/`
- 项目主源：`~/.claude/projects/<编码后的项目路径>/memory/`
- Qoder CN：`~/.qoder-cn/memory/` 与 `~/.qoder-cn/projects/<编码项目>/memory/`，逐文件同步
- TRAE CN / TRAE：全局记忆合并进 `memory/user_profile.md` 的受管区块
- Qoder IDE：`~/.qoder/memories/` 为应用自有格式，只报告
- Codex：`~/.codex/memories_1.sqlite`，只报告

## 首跑与冲突处理

1. 首次 `sync` 只写 `~/.ai-env-sync/state.json` 和报告，不改 IDE。
2. 阅读报告里的冲突、目标独有项、密钥拦截项。
3. 对确认要保留的本地修改，执行 `adopt KEY`；对确认要以主源为准的，用 `sync --force --only PATTERN` 覆盖该批漂移（写入前自动备份）。
4. 再次 `sync` 创建缺失副本并更新无漂移副本。
5. 主源删除资产默认只报告；确认后执行 `sync --prune`。

## 安全约束

- 每次写目标前备份到 `~/.ai-env-sync/backups/<时间戳>/`。
- 不打印、不写回任何密钥值；报告里只出现掩码。
- 不自动 `git commit`；采纳只改 Claude 工作区，交给用户 review。
- 不修改目标 IDE 的应用自有格式（SQLite、插件缓存、`memories/` 二进制）——只报告。
- 不删除目标独有资产；`--prune` 只删除“主源已删且副本无本地修改”的副本。

## 参考

- 完整落点、schema 与已知差异见 [references/ide-sync-matrix.md](references/ide-sync-matrix.md)。
- 相关技能：`universal-skill-creator`、`universal-agent-creator`。
