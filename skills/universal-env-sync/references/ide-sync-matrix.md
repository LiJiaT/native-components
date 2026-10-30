# AI IDE 同步矩阵（2026-10-22 实测）

主源固定为 Claude Code 用户级目录。其余 IDE 都是生成副本；副本的本地修改只报告，不自动覆盖。

## 1. Skills

| 目标 | 落点 | 格式 | 备注 |
|---|---|---|---|
| Claude（主源） | `~/.claude/skills/<name>/` | `SKILL.md` + 资源目录 | 唯一主源 |
| Qoder CN | `~/.qoder-cn/skills/` | 同上 | 桌面版热加载 |
| Qoder IDE | `~/.qoder/skills/` | 同上 | |
| TRAE CN | `~/.trae-cn/skills/` | 同上 | |
| TRAE | `~/.trae/skills/` | 同上 | |
| Codex | `~/.codex/skills/` | 同上 | |
| 共享 | `~/.agents/skills/` | 同上 | Qoder / TRAE 也会读 |

- 默认排除 macOS 专属 5 个、`lark-*`、`skill-creator`；在 `~/.ai-env-sync/config.json` 的 `exclude_skills` 调整。
- 目录哈希忽略 `.git`、`__pycache__`、`.skill-backups`、`.pyc`、`.DS_Store`。

## 2. Agents

| 目标 | 落点 | 格式 |
|---|---|---|
| Claude（主源） | `~/.claude/agents/<name>.md` | Markdown + frontmatter |
| Qoder CN | `~/.qoder-cn/agents/<name>.md` | Markdown，原样复制 |
| Qoder IDE | `~/.qoder/agents/<name>.md` | Markdown，原样复制 |
| Codex | `~/.codex/agents/<name>.toml` | `name`、`description`、`nickname_candidates`、`developer_instructions` |
| TRAE CN / TRAE | `<项目>/.github/agents/<name>.agent.md` | Markdown + frontmatter；TRAE 只有项目级 |

- Codex / TRAE 的 agent 用语义哈希比较（name、description、body），避免 TOML 字符串转义和空行造成假漂移。
- Qoder / Claude 用原文哈希比较，保留 `descriptionZh`、`argumentHint` 等平台字段。

## 3. Hooks

| 目标 | 配置落点 | 支持事件 | 脚本落点 |
|---|---|---|---|
| Claude（主源） | `~/.claude/settings.json#hooks` | 全部 | `~/.claude/hooks/` |
| Qoder CN | `~/.qoder-cn/settings.json#hooks` | `SessionStart`、`UserPromptSubmit` | `<目标>/.ai-env-sync/hooks/` |
| Codex | `~/.codex/hooks.json#hooks` | `SessionStart`、`UserPromptSubmit`、`SessionEnd` | `<目标>/.ai-env-sync/hooks/` |
| Qoder IDE | 无已验证的用户级 hook | — | 只报告 |
| TRAE CN / TRAE | 无已验证的用户级 hook | — | 只报告 |

- 目标已有同名 hook 时保留目标版本，不重复注册（例如 Qoder CN 已有的 `scenario-inject.cmd`）。
- 本技能管理的命令路径包含 `.ai-env-sync`，便于识别和 prune。
- 脚本复制后重写 `.cmd` 里的 `~/.claude/hooks` 路径；漂移检测对路径做归一化，不会因为落点不同永久报冲突。
- `SessionEnd` 的 `distill-enqueue` 不注册到 Qoder CN，避免跨环境写 Claude 的自进化队列。

## 4. 全局规则与系统提示词

| 目标 | 系统提示词落点 | 规则落点 |
|---|---|---|
| Claude（主源） | `~/.claude/CLAUDE.md` | `~/.claude/rules/*.md`、`~/.claude/AGENTS.md` |
| Qoder CN / Qoder IDE | `~/.qoder/rules/_global_claude.md` 受管区块 | `~/.qoder/rules/*.md` |
| TRAE CN | `~/.trae-cn/user_rules/_global_claude.md` 受管区块 | `~/.trae-cn/user_rules/*.md` |
| TRAE | `~/.trae/user_rules/_global_claude.md` 受管区块 | `~/.trae/user_rules/*.md` |
| Codex | `~/.codex/AGENTS.md` 受管区块（含 CLAUDE.md + rules + AGENTS.md） | 合并进同一区块 |

- 受管区块标记：`<!-- >>> ai-env-sync:prompt >>> -->` / `<!-- <<< ai-env-sync:prompt <<< -->`；memory 用 `memory` 标记。
- 区块外内容原样保留。
- 规则文件保留目标已有的 YAML frontmatter（Qoder 的 `alwaysApply` 等），只同步正文。
- Qoder CN 没有原生规则加载器，仍由现有 SessionStart hook 读取 `~/.qoder/rules/` 注入；Qoder IDE 原生加载同一目录。

## 5. MCP

| 目标 | 用户级落点 | 顶层 key | 项目级落点 |
|---|---|---|---|
| Claude（主源） | `~/.claude.json` | `mcpServers` | `<项目>/.mcp.json#mcpServers` |
| Qoder CN | `~/.qoder-cn/settings.json` | `mcpServers` | 直接读 `<项目>/.mcp.json`，无需复制 |
| Qoder IDE | `~/.qoder/mcp.json` | `mcpServers` | 未验证，只报告 |
| TRAE CN | `%APPDATA%\Trae CN\User\mcp.json` | `mcpServers` | `<项目>/.trae/mcp.json#mcpServers` |
| TRAE | `%APPDATA%\Trae\User\mcp.json` | `mcpServers` | `<项目>/.trae/mcp.json#mcpServers` |
| Codex | `~/.codex/config.toml` | `mcp_servers` | 未验证，只报告 |

关键差异：

- **TRAE 的 `mcpServers` 每项只允许** `command` / `args` / `env` / `cwd` / `disabled` / `fromGalleryId`（stdio）或 `url` / `headers` / `oauth` 等（HTTP）；**不允许 `type`**，写入时必须剥掉。
- **TRAE 只支持 `${workspaceFolder}` 变量**，不支持 `${ENV_VAR}`。因此 `env` 里的 `${KEY}` 和明文密钥都会被移除，依赖父进程的系统环境变量。
- **Codex 不支持 `${ENV_VAR}` 插值**，同样移除 `env` 引用，依赖系统环境变量。
- **Claude / Qoder 支持 `${ENV_VAR}`**，明文密钥会转成 `${KEY}` 引用。
- `headers.Authorization` 等无法用环境变量表达的值：整条服务器拦截并报告，不写入任何目标。
- Codex 的 MCP 写在 `config.toml` 受管区块：

```toml
# >>> ai-env-sync:mcp >>>
[mcp_servers.name]
command = "npx"
args = ["-y", "some-mcp"]

[mcp_servers.name.env]
KEY = "${KEY}"
# <<< ai-env-sync:mcp <<<
```

- Codex 已有非受管同名服务器时不覆盖；内容一致视为 clean，内容不同报告冲突。
- `adopt-mcp --from codex` 把 Codex `mcp_servers` 写入 `~/.claude.json` 的 `mcpServers`；先备份，不自动 git commit。

## 6. Memory

| 目标 | 全局 | 当前项目 |
|---|---|---|
| Claude（主源） | `~/.claude/projects/<编码家目录>/memory/` | `~/.claude/projects/<编码项目>/memory/` |
| Qoder CN | `~/.qoder-cn/memory/` 逐文件 | `~/.qoder-cn/projects/<编码项目>/memory/` 逐文件 |
| TRAE CN | `~/.trae-cn/memory/user_profile.md` 受管区块 | 应用自有目录，只报告 |
| TRAE | `~/.trae/memory/user_profile.md` 受管区块 | 应用自有目录，只报告 |
| Qoder IDE | `~/.qoder/memories/` 应用自有格式 | 只报告 |
| Codex | `~/.codex/memories_1.sqlite` | 只报告 |

- 路径编码：`%USERPROFILE%` → `C--Users-<user>`，`<PROJECT_ROOT>` → `D--Project`。
- 只同步 `*.md`；不解析 SQLite。
- 目标独有的 memory 文件报告为冲突，可用 `adopt memory:<name>@<target>` 采纳回 Claude。

## 7. 状态与报告

- 状态：`~/.ai-env-sync/state.json`
- 配置：`~/.ai-env-sync/config.json`
- 报告：`~/.ai-env-sync/reports/latest.md`、`latest.json`、`<时间戳>.json`
- 备份：`~/.ai-env-sync/backups/<时间戳>/...`
- 报告只包含路径、哈希、状态与脱敏后的 findings，不包含密钥值。

## 8. 已验证 / 未验证

已验证：

- 首跑不写 IDE，只建基线。
- 二次同步创建缺失副本、更新无漂移副本。
- 本地修改 skill / MCP 后 `status` 报冲突，`sync` 不覆盖。
- 删除主源 skill 后 `--prune` 删除无漂移副本；删除主源 hook 后删除受管 hook 项。
- TRAE 用户级 / 项目级 MCP 写 `mcpServers`，不带 `type`。
- Codex MCP 受管区块、hooks 合并、AGENTS.md 区块。
- Qoder CN settings.json 合并时保留 `providers` 与已有 hooks。
- `adopt skill:<name>@<target>` 与 `adopt-mcp --from codex`。
- `sync --force --only PATTERN` 在备份后以主源覆盖指定范围内的漂移副本；不接受全量 `--force`，首跑不可用。

未验证 / 保守处理：

- Qoder CN 桌面版是否热加载 `settings.json` 的 `mcpServers`（CLI 运行时确认读全局 settings，桌面版未做启动实测）。
- Qoder IDE 项目级 MCP 路径。
- TRAE 项目级 MCP 需要在 UI 里开启“项目级 MCP”后才会加载。
- Qoder IDE / TRAE 的用户级 hooks（当前判定为不支持）。
- TRAE / Codex 的系统环境变量是否已设置；密钥移除后需用户自行保证环境变量存在。
