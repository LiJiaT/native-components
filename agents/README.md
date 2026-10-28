# agents/

子代理（Subagent）定义。一个代理一个 Markdown 文件；复杂代理可以带同名资源目录。

## 当前收录

| Agent | 作用 | 依赖 |
|---|---|---|
| [`engineering-agent`](engineering-agent.md) | 复杂任务的统一入口与调度层：澄清、规划、任务分解分发、验收、资产写回 | [`skills/engineering-agent`](../skills/engineering-agent/SKILL.md)、[`skills/grill-me-with-doc`](../skills/grill-me-with-doc/SKILL.md)、[`hooks/engineering-agent`](../hooks/engineering-agent/README.md) |

## 要求

- 写清职责边界、可调用工具、输入输出、何时不使用。
- 与 skill 的分工明确：代理负责编排与上下文隔离，技能负责具体流程。
- 提供安装位置说明（Claude Code / Qoder / Codex / TRAE 等差异）。
- 不包含项目私有提示词或凭证。

## 安装

```bash
python -X utf8 tools/install.py --component engineering-agent   --component engineering-agent-skill --component grill-me-with-doc   --component engineering-agent-hooks --component gate-core --component component-schemas
```

`engineering-agent.md` 引用的 `references/`、`scripts/task_packager.py` 在 `skills/engineering-agent/` 下，安装器会一起复制。自动激活还需要 `hooks/engineering-agent`；计划/验收/外发门禁需要 `gates/gate.py` 与 schemas。不要只复制 `agents/engineering-agent.md` 单文件。

## 入口提示

把以下条目加入 `~/.claude/CLAUDE.md`，让主 agent 在复杂任务时主动委派：

```markdown
# Engineering Agent 入口
- 复杂任务（多步骤、多产出、需求不清）先委派 Engineering Agent；简单单步任务直接做。
- 不确定是否复杂时，先按 engineering-agent Step 0 判断，不要强行套流程。
```
