# agents/

子代理（Subagent）定义。一个代理一个 Markdown 文件；复杂代理可以带同名资源目录。

## 当前收录

| Agent | 作用 | 依赖 |
|---|---|---|
| [`orchestrator`](orchestrator.md) | 复杂任务的统一入口与调度层：澄清、规划、任务分解分发、验收、资产写回 | [`skills/orchestrator`](../skills/orchestrator/SKILL.md)、[`skills/grill-me-with-doc`](../skills/grill-me-with-doc/SKILL.md)、[`hooks/orchestrator`](../hooks/orchestrator/README.md) |

## 要求

- 写清职责边界、可调用工具、输入输出、何时不使用。
- 与 skill 的分工明确：代理负责编排与上下文隔离，技能负责具体流程。
- 提供安装位置说明（Claude Code / Qoder / Codex / TRAE 等差异）。
- 不包含项目私有提示词或凭证。

## 安装

```bash
mkdir -p ~/.claude/agents ~/.claude/skills
cp agents/orchestrator.md ~/.claude/agents/
cp -r skills/orchestrator ~/.claude/skills/
cp -r skills/grill-me-with-doc ~/.claude/skills/
```

`orchestrator.md` 引用的 `references/` 与 `scripts/task_packager.py` 在 `skills/orchestrator/` 下，两者要一起安装。自动激活还需要 `hooks/orchestrator`。

## 入口提示

把以下条目加入 `~/.claude/CLAUDE.md`，让主 agent 在复杂任务时主动委派：

```markdown
# Orchestrator 入口
- 复杂任务（多步骤、多产出、需求不清）先委派 orchestrator agent；简单单步任务直接做。
- 不确定是否复杂时，先按 orchestrator Step 0 判断，不要强行套流程。
```
