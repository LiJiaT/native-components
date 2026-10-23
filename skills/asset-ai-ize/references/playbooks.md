# 六形态实现 playbook（技能 B）

本文件是 SKILL.md 的按需参考。**只读当前 ai_form 对应的章节**，不预读全文。

所有形态共同要求：忠实承载 statement 的全部可复用结论（语义保持，不增不减不演绎）；artifact 是"拿来即用"的实现物，不是描述。对账键 `asset_id` 的写法按文件类型区分：组件文档类（`.md`/`.yaml`）放 frontmatter；脚本类（`.py`）在文件头写 `# asset_id: <id>` 注释——两者都由 validate_build.py 校验。

## Memory

- **产物**：memory 条目正文（1-3 段）；合入 repo 后，由 `install.md` 指明装进目标环境的 memory 载体（`~/.claude/projects/<slug>/memory/`、CLAUDE.md 条目或 memory 文件）。
- **写法**：正文独立成立——读者不看 record 也能懂；保留决策类资产的五要素（背景/选项/取舍/证据/日期）；结尾带 provenance 注释（`来源: asset <asset_id>, <approved_date> 入库`）。
- **验收**：独立成立性检查（遮住 record 读条目，可复用结论无丢失）；不重复目标环境已有条目。

## Rule

- **产物**：rules markdown 全文，合入 repo `rules/`；`install.md` 指明装进 `~/.claude/rules/`（用户级）或项目 `.claude/rules/`。
- **写法**：祈使句，一条规则一个可判定动作；只对特定文件类型生效时带 `paths:` frontmatter（如 `paths: ["**/*.v"]`）。
- **验收**：每条规则配触发样例（什么输入应命中、什么输入不该命中），写进 `tests/`。

## Skill

- **产物**：SKILL.md 章节草案（触发条件 + 步骤 + 停止规则），合入 repo `skills/<name>/`；`install.md` 指明装进 `~/.claude/skills/<name>/`。
- **写法**：description 写清触发词（中英皆可，用户实际会说的词）；步骤可执行、可验收；含"何时不适用"节防误触发。
- **验收**：端到端场景测试——构造一个应触发的输入与一个不应触发的输入，结果记入 `tests/`。

## Workflow

- **产物**：流程步骤清单（触发→执行→验收→停止），作为组件文档或脚本化流程合入 repo `components/`；`install.md` 指明运行位置。
- **写法**：每步可判定完成与否；确定性步骤标注"脚本/hook 实现"，判断性步骤标注"人工/AI 裁决"。
- **验收**：步骤完整性检查（有触发、有停止、有验收标准三要素）。

## Hook

- **产物**：hook 脚本 + `settings.json` 挂接配置片段（不直接改 settings.json——配置片段放 artifacts，安装由人执行或经授权）。
- **写法**：脚本幂等、带超时与失败静默策略（hook 崩溃不能拖垮会话）；配置片段写明事件名（PreToolUse/PostToolUse/SessionStart 等）与 matcher。
- **验收**：脚本语法检查（`python -X utf8 -m py_compile`）；dry-run 一次记入 `tests/`。
- **注意**：Hook 形态的实质是"必须每次自动强制"的规则——若 statement 只是需要被"知道"而非被"强制"，返回 mapping_issue 建议改 Rule/Memory。

## Prompt

- **产物**：可复用指令模板（`.md` 或嵌入组件的 prompt 段），合入 repo `prompts/`；`install.md` 指明接入方式。
- **写法**：模板参数化（`<占位符>`），使用说明给一行示例；不绑定单一模型/工具的专有语法。
- **验收**：代入示例参数渲染一次，检查无未填占位符。

## 形态间换算参考（仅供 mapping_issue 建议，不供 B 直接改映射）

| statement 特征 | 更合适的 ai_form |
|---|---|
| 需要每次自动强制、违反会出事 | Rule → 更强触发场景 Hook |
| 背景知识、按需检索 | Memory |
| 成流程的方法 | Skill（人机交互型）/ Workflow（步骤清单型） |
| 反复使用的指令模板 | Prompt |
