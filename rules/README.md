# rules/

可复用的工程规则（Rule）。一条规则一个 Markdown 文件，按需被 AI IDE 加载。

## 公共级规则

公共级规则跨项目、跨领域生效，直接放在 `rules/` 根目录。当前收录的是规范 §3.4 强制规则清单中已实现的部分：

| 规则 | 对应条款 | 作用 |
|---|---|---|
| [`verilog-filelist-sync`](verilog-filelist-sync.md) | R1 | Verilog 文件变更同步更新 filelist；filelist hook 未实现，需等价人工检查（experimental） |
| [`no-auto-external-actions`](no-auto-external-actions.md) | R3 | 对外上传/提交/发布必须由人确认 |
| [`verify-or-review-before-delivery`](verify-or-review-before-delivery.md) | R4 | 交付前执行方自查 + 独立复核；两类证据必须同时存在，不能用单一评审替代 |
| [`subtask-acceptance-checklist`](subtask-acceptance-checklist.md) | R7 | 子任务必须携带可逐项判定的验收清单 |
| [`no-raw-records-in-memory`](no-raw-records-in-memory.md) | R8 | 原始记录不得写入长期记忆 |

这些规则由 `native-assets` 的 EA-20261022-02..06 资产化，本库是公共分发副本；实现包与构建记录仍在 `native-assets-build`。R3/R4/R7/R8 已有配套确定性工具（`gates/gate.py`、`task_packager.py`），R1 的 filelist hook 仍是缺口。

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
