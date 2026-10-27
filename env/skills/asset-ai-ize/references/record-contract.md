# approved asset record 消费契约（技能 B）

本文件是 SKILL.md 的按需参考。仅在读取 record、判断字段合法性或写回 implementation 时读取。

## 1. record 必填字段（技能 B 消费前提）

| 字段 | 说明 | B 的态度 |
|---|---|---|
| `asset_id` | 全局唯一 `EA-<YYYYMMDD>-<序号>` | 只读，作为实现对账键 |
| `proposal_id` | 来源提案 `<YYYYMMDD-HHmm>-<slug>` | 只读，写入实现申请"来源提案 ID" |
| `status` | 必须 `approved` | 非 approved → 拒绝消费 |
| `title` / `form` / `secondary_tags` | 形态结论 | **只读**（重新分类 = 越权） |
| `domains` / `project` / `layer` | 归属结论 | 只读；决定实现的落位建议 |
| `ai_form` | 映射结论：Memory/Rule/Skill/Workflow/Hook/Prompt | **只读**；落不了地 → mapping_issue，不擅自换 |
| `owner` | 批准入库的 owner | 只读，写入实现申请"组件 owner"（组件 owner 可与其不同，由评审定） |
| `approved_by` / `approved_date` | 审批记录 | 只读 |
| `implementation` | 实现状态；入库时为空 | **唯一可写字段**（见 §3） |
| `## 内容` | statement：提炼后的资产正文 | **只读，一字不改** |
| `## 出处与理由` | evidence：provenance | 只读 |

## 2. 三条红线

1. **statement / evidence / mapping / 分类结论不改**。发现内容有问题（过时、错误、缺细节）→ mapping_issue 或回技能 A，越权修改会让资产库失去单一真源。
2. **不重新判断资产是否成立**。"这条资产不值得做"不是 B 的结论可承载的——那是入库审批（A 的卡点）已经裁决过的事；真有新证据 → 告知 owner 由人裁决。
3. **写回只发生在实现批准后**，且只写 `implementation` 字段。

## 3. implementation 字段写回格式

实现经组件 owner 批准安装后，在资产 repo 该 record 的 frontmatter 写入：

```yaml
implementation:
  ai_infra_repo: eng-asset-ai-components
  package: build/<asset_id>/          # 实现包位置（合入后为最终目录，如 rules/）
  installed: <YYYY-MM-DD>
  installed_by: <组件 owner>
  notes: <一句话说明，可省>
```

多次实现（同 record 换形态重做）时，`implementation` 保留最新一条，历史进 `reviews/`。

## 4. 与两个 repo 的对账

- 资产 repo（eng-knowledge-assets）：record 的唯一来源；`registry.json` 中该 asset_id 的状态应与 record `status`/`implementation` 一致。
- AI Infra repo（eng-asset-ai-components）：实现物落位处；build-manifest.json 的 `asset_id` 必须能在资产 repo 中找到对应 approved record——validate_build.py 会校验。
