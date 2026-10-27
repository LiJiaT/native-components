# env/ — 本机 AI 开发环境快照（可分发部分）

来源：原独立仓库 `claude-code-env`（`https://github.com/LiJiaT/claude-code-env`，2026-10-27 并入本仓库）。
本目录是并入时的快照副本，其中的仓库路径已同步到 `intel-*` / `native-*` 新命名。
本机源目录仍是 `D:\Project\claude-code-env`（保留 30 天，待人工决定是否归档），其内容仍指旧路径；
下次从 `~/.claude/` 重新同步快照前，先完成源侧路径更新，否则会把旧路径重新带回来。

## 收录

| 目录 | 内容 |
|---|---|
| `agents/` | 子代理定义（如 `claude-env-maintainer`） |
| `rules/` | 用户级规则（`~/.claude/rules` 的镜像） |
| `skills/` | 用户级技能（`~/.claude/skills` 的镜像，含 macOS 专属技能） |
| `hooks/` | SessionStart / 蒸馏通知等钩子脚本 |
| `scenarios/` | 跨 session 长期工作线的 `STATE.md` / `HISTORY.md` |

## 排除

以下内容**故意不并入**，留在本机：

- `projects/-Users-lidaonian/memory/`：个人 memory（含本机路径、网络与账号线索），只在本地 `~/.claude/memory/` 维护
- `settings.local.json`：含本机绝对地址与权限白名单
- `self-evolve/`、`bin/`、根目录 `CLAUDE.md` / `AGENTS.md` / `MIGRATE.md`：与具体机器绑定，且本仓库已有自己的规则与流程文档

## 与 `skills/`、`rules/`、`hooks/`、`agents/` 的区别

仓库根目录下的这四类是**公共可分发组件**（经评审、进 `registry.json`、可被 `tools/install.py` 安装）。
`env/` 下的是**个人环境的原样快照**，不进入 registry，也不受安装器管理——只作备份与跨机迁移用。
