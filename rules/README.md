# rules/

可复用的工程规则（Rule）。一条规则一个 Markdown 文件，按需被 AI IDE 加载。

## 规则要求

- 全文使用祈使句，一条规则一个可判定动作。
- 写明触发条件与不触发条件，避免“视情况”类模糊表述。
- frontmatter 至少包含 `asset_id`、`ai_form: Rule`；按文件类型触发时给 `paths`。
- 规则只约束结果，不写大段操作步骤（步骤属于 skill / workflow）。
- 不重复已有规则；新增前先做语义去重。

## 领域子目录

领域级规则按 [`docs/domain-taxonomy.md`](../docs/domain-taxonomy.md) 的 slug 放在对应子目录：

`architecture/`、`design/`、`verification/`、`timing/`、`dft/`、`post-sim/`、`firmware/`、`analog/`、`backend/`

项目私有规则仍放对应项目的 `.claude/rules/`，不进这里。
