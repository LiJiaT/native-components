# OpenClaw / Copilot / Claude Code 三工具资产迁移映射

**2026-10-08 真身收敛（方案 A）已执行**：`cc-personal/` 四项目（travel-planner/fitness-coach/alfred/overseer）是唯一真身——openclaw 的 travel 10-08 复盘数据已同步过去，两个子代理定义已改写路径迁入各项目 `.claude/agents/`，fitness xlsx 经 MD5 比对与真身 `~/Documents/fitness/` 一致未迁移；fitness skills/AGENTS/TOOLS 全部改指真身+固定脚本。`~/.openclaw` 保留作回滚保险，**2026-10 下旬到期归档**（skills 7 个与 cc-personal 字节级重复，勿再从它取数）。

三套 AI 工具共享 ~/.openclaw 工作区身份。迁移映射（历史记录）：

- `workspace/{SOUL,IDENTITY,USER,AGENTS,MEMORY}.md` → Claude Code 项目 CLAUDE.md + memory
- 角色代理 → `.claude/agents/*.md`（`name` 字段即 `claude --agent` 参数；现役 agent 在各 cc-personal 项目内）
- skills → `.claude/skills/`（Copilot 侧对应 `.github/skills/`、`.github/agents/*.agent.md`）

迁移要点（复用价值）：
1. 各副本内容新鲜度可能不同，逐类取最新；2026-10-08 后以 cc-personal 为准
2. 排除 19M 归档目录
3. 复制后路径改写（.github/→.claude/）：blanket sed 会误改"禁止引用"类反向描述，逐处检查
4. 裸 python3 pin 到 /opt/homebrew/bin/python3（OpenClaw venv 在 PATH 遮蔽且缺 openpyxl）
5. 三个副本的脚本改完必须 diff 验证 byte-identical 并端到端跑通
6. API key 统一存 ~/.zshrc，脚本带 env var → zshrc 解析 fallback（兼容非 login shell）

<!-- 来源: session 66d73142, cand-8e4f9f, 理由: 已发生两次迁移+一次路径清理的重复需求 -->
