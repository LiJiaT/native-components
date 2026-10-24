# 资产化提案契约（assetize · 技能 A 字段与判定细节）

本文件是 SKILL.md 的按需参考。仅在需要确认字段含义、枚举取值或判定边界时读取。

## 1. 资产本体 frontmatter 字段

| 字段 | 必填 | 取值 | 说明 |
|---|---|---|---|
| `id` | ✅ | `A<序号>`（如 `A1`） | proposal 内唯一；入库时升级为全局 `asset_id`（`EA-<YYYYMMDD>-<序号>`） |
| `title` | ✅ | 一句话 | ≤30 字，动宾或名词短语，不用泛词（"某项目的经验"❌） |
| `form` | ✅ | `知识库` \| `工程规则` \| `决策记忆` \| `技能工作流` | 形态主标签，五问判出 |
| `secondary_tags` | ✅ | 上述枚举的列表 | 副标签，0..n；承载资产的多重性质 |
| `domains` | ✅ | 9 领域的列表 | 多选 ≤3；**空列表仅当 `layer=公共级`**（治理/AI 协作类资产跨领域，不硬挂专业领域，由审批人裁决是否扩展枚举） |
| `projects` | ✅（可为空列表） | `LPDDR6` / `HBM` 的列表 | 空列表 = 跨项目；同一资产可同时属于多个项目（兼容旧字段 `project` 单值） |
| `layer` | ✅ | `个人级` \| `项目级` \| `领域级` \| `公共级` | 共享范围 |
| `ai_form` | ✅（可为 null） | `Memory` \| `Rule` \| `Skill` \| `Workflow` \| `Hook` \| `Prompt` \| `null` | **建议 AI 形态**；暂不 AI 化时置 null，并写 `mapping_status: unmapped|deferred` + 非空 `mapping_reason` |
| `source` | ✅ | 字符串 | 输入材料名 + 日期，如 `HBM DFT debug 纪要 2026-10-22` |
| `suggested_owner` | ✅ | 字符串 | 按层级推导，见 §3 |

注意：`ai_form` 枚举里**没有 Context**——"仅当前任务有效"的单元（五问第 5 问命中）根本不成案，直接进过滤区。

## 2. 分类五问的判定边界

五问按顺序问，第一个命中即定主标签；后续仍命中的进 `secondary_tags`。

| # | 问题 | 命中样例 | 主标签 | 默认 ai_form |
|---|---|---|---|---|
| 1 | 它是稳定事实吗？ | RTL repo、IP spec、接口/寄存器定义、时序要求、协议规范、工具版本、PVT、仿真环境、coding standard | 知识库 | Memory |
| 2 | 它是必须被遵守的要求吗？ | clock crossing 模式、reset 禁忌、coding style 约束 | 工程规则 | Rule |
| 3 | 它记录了过去某次取舍的来龙去脉吗？ | 方案对比 + 当时的约束 + 选了什么 + 为什么；**Decision History 是最值钱的资产** | 决策记忆 | Memory |
| 4 | 它是一段可重复的方法或流程吗？ | RTL 提交前 review + stage flow | 技能工作流 | Skill / Workflow |
| 5 | 它只对当前这个任务有效吗？ | 当次临时参数、一次性调试上下文 | 上下文 | 不入库，进过滤区 |

判定要点：
- **稳定 vs 取舍**：内容若含"为什么这么做"，即使主体是事实也挂 `决策记忆` 副标签。
- **规则 vs 事实**：规则带强制语气（"必须/禁止/一律"），事实只是陈述。语气模糊时问：违反它会不会出事？会 → 工程规则。
- **方法 vs 规则**：规则约束结果（"必须过 stage flow"），方法描述步骤（"怎么做 stage flow"）。二者常成对出现，拆成两个资产互挂副标签。
- **ai_form 选型**：需要"每次都自动强制"→ Rule 或 Hook（确定性动作）；"按需检索的背景知识"→ Memory；"成流程的方法"→ Skill 或 Workflow；"可复用的指令模板"→ Prompt。

## 3. 层级与 owner 推导

| 层级 | 判定 | suggested_owner |
|---|---|---|
| 个人级 | 只有提交人自己会用到（个人偏好、个人工作法） | 提交人 |
| 项目级 | 仅 LPDDR6 或仅 HBM 内有效（项目规格、项目流程、项目环境） | 对应项目负责人 |
| 领域级 | 某专业领域内跨项目通用（DV 方法学、DFT 实践、时序方法） | 对应领域 owner |
| 公共级 | 全团队任何领域都适用（AI 协作规范、公共流程） | AI 平台团队 |

- `projects` 与 `layer` 一致性：`layer=项目级` 时 `projects` 必须恰好一个具体项目；空列表时 `layer` 不得为项目级；多项目资产只能标领域级或公共级。validate.py 会校验。
- 领域级资产的 `projects` 通常为空，除非它源于某项目但对领域有普适价值（此时 `projects` 标来源项目，`layer` 仍为领域级——来源不等于归属，不限制消费范围）。

## 4. 入库升级：approved asset record

owner 批准入库后，提案资产升级为 approved asset record（技能 B 的唯一输入契约）：

- frontmatter 增加：`asset_id`（全局 `EA-<YYYYMMDD>-<序号>`，同批递增）、`proposal_id`、`status: approved`、`approved_by`、`approved_date`；`suggested_owner` 落定为 `owner`。
- frontmatter 增加 `provenance_status` 与一句话 `provenance_note`，标明内容来源的可信度：
  - `verified`：已对照原始来源逐条核验（note 写明核验对象与方式）。
  - `source-excerpt`：摘自真实来源的节选/摘要，尚未全文逐条核验。
  - `synthetic`：由构造材料生成，仅用于验证流程，不代表真实事实。
  - 缺省不得视为 `verified`；`registry.json` 同步写入同一字段。
- 正文（`## 内容` / `## 出处与理由`）**原样迁移，不得改写**——改写需走新一轮提案。
- 写入资产 repo 本地 clone `$ENG_ASSETS_REPO/assets/<proposal_id>/`，同步更新 `INDEX.md`、`registry.json` 与 `approvals/<asset_id>.json`，评审结论存 `reviews/`。
- record 的 `implementation` 字段此时为空，由技能 B 实现通过后回写。

record 的消费契约（statement / evidence / mapping 不得被 B 修改）详见技能 B 的 `references/record-contract.md`。

## 5. 过滤区（R8 纪律）

原始记录（会议原文、聊天记录、调试日志）**不得**入库——入库的必须是提炼后的资产正文。以下进 proposal 的"已过滤"区并给理由：
- 判定为主标签=上下文的单元
- 信息密度过低、无法独立成条的片段（<1 个可复用结论）
- 与已有资产重复的单元（先查本地 INDEX.md 与资产 repo INDEX，语义去重；重复则标 `duplicate-of:<已有asset_id>`）
