---
name: assetize
description: 工程知识资产化（技能A）：把文档、会议纪要、debug 记录、纯文本、JIRA/GitHub Issue 摘录等输入经「收集→分类→映射」产出可评审的资产提案包（proposal.md + assets/ + manifest.json）并生成入库申请，由 owner 批准后形成 approved asset record 落入资产 repo（native-assets）。当用户说"资产化这个文档/纪要/经验"、"把这段 debug 记录入库"、"提炼成资产"、"这个决策值得沉淀"、"propose 入库"，或提供任何工程材料并要求转化为可复用知识资产时使用。只做提案与入库申请，不写 AI 落地实现（那是 asset-ai-ize 的职责）、不直接 push/merge。不用于普通文档摘要、一次性问答或纯内容整理（无入库意图时不触发）。
---

# 工程知识资产化（assetize · 技能 A）

把工程输入变成资产库的**入库提案**。一次运行 = 一份 proposal package，内含若干**资产本体**与机器可读 manifest。入库与否由 owner 审批决定；批准后形成 approved asset record，成为技能 B（asset-ai-ize，资产AI化）的唯一输入契约。

**职责边界（规范 §3.4）**：本技能负责"沉淀什么、放到哪"——**不写生产实现、不写落地草案、不改组件代码、不直接 push/merge/发布**。"怎么做成能跑的 AI 资产"是技能 B 的事。

## 为什么 A/B 分离

"判断资产是否成立"和"把资产做成实现"是两种上下文：前者需要吃透原始材料与领域语义，后者需要吃透目标组件形态与工程质量。混在一个上下文里两头都做不深。以 approved asset record 为唯一交接契约，两边各自演进互不拖累。

## 何时不用本 skill

- 只要摘要/翻译/改写，无入库意图 → 普通文档处理
- 输入是 Claude Code 会话日志本身 → session-distiller（本 skill 处理外部材料）
- 输入已是 approved asset record、要做 AI 实现 → asset-ai-ize（技能 B）
- 一次性问答、当前任务临时上下文 → 直接用完即弃，不必 propose

## 输出目录

```
~/.claude/asset-proposals/
├── INDEX.md                        # 全局一行索引：日期-slug | 领域 | 一行摘要（去重依据）
└── <YYYYMMDD-HHmm>-<slug>/         # 一次运行一个目录（= proposal_id）
    ├── proposal.md                 # 汇总：资产清单 + 过滤区 + 入库申请 + 审批区
    ├── manifest.json               # 机器可读清单：资产/形态/层级/owner/校验状态
    └── assets/A<n>-<slug>.md       # 资产本体（提案阶段用局部 id A<n>）
```

入库批准后，资产升级为 approved asset record 写入资产 repo 本地 clone（路径由 `ENG_ASSETS_REPO` 或用户显式指定；不要硬编码作者机器路径）的 `assets/<proposal_id>/`，同时更新该 repo 的 `INDEX.md`、`registry.json` 与 `approvals/`；push 由人执行（R3）。

## 流程

### 1 · 接收输入

支持：纯文本、本地文件路径、飞书文档 URL（用 lark-doc `+fetch` 拉取）、JIRA/GitHub Issue 摘录。输入可能含多个知识单元——**一单元一资产**，不要把整份材料打包成一个资产。

### 2 · 收集：切分知识单元

通读输入，找出四类候选：**事实**（spec/接口/版本/环境）、**要求**（必须遵守的约束）、**取舍**（某次决策的来龙去脉）、**方法**（可重复流程）。切分时同步做两道过滤：

- **R8 纪律**：原始记录（会议原文、聊天、调试日志）不直接入库，必须提炼改写成资产正文后才算资产；
- **信息密度**：提不出至少一个可复用结论的片段丢弃。

### 3 · 分类：五问定形态

对每个单元按序问（首个命中定主标签，后续命中进副标签）：

| 问 | 命中 → 主标签 | 默认 ai_form |
|---|---|---|
| 稳定事实？ | 知识库 | Memory |
| 必须遵守的要求？ | 工程规则 | Rule |
| 过去某次取舍的来龙去脉？ | 决策记忆 | Memory |
| 可重复的方法或流程？ | 技能工作流 | Skill / Workflow |
| 仅当前这个任务有效？ | 上下文 | （不入库，进过滤区） |

映射非强制：默认按上表，可按实际组件形态调整为 Memory/Rule/Skill/Workflow/Hook/Prompt 任一，调整理由写进 proposal。判定边界拿不准时读 [`references/asset-schema.md`](references/asset-schema.md)。

### 4 · 四维标注

每个资产打四个正交维度（领域与项目正交，不嵌套）：

| 维度 | 取值 | 判定要点 |
|---|---|---|
| `domains` | 架构/设计/验证/时序/DFT/后仿/Firmware/模拟/后端（多选≤3） | 资产**关于什么**专业 |
| `projects` | LPDDR6 / HBM 的列表（可为空） | 同一资产可同时属于多个项目；空列表=跨项目。项目级必须且只能有一个项目 |
| `layer` | 个人级/项目级/领域级/公共级 | 共享范围：只对自己有用=个人；单项目=项目；跨项目领域通用=领域；全团队=公共 |
| `ai_form` | Memory/Rule/Skill/Workflow/Hook/Prompt 或 null | 第 3 步默认 + 按需调整（给技能 B 的映射建议）。暂不 AI 化时置 null，并写 `mapping_status: unmapped|deferred` 与 `mapping_reason` |

`suggested_owner` 按层级推导：公共级→AI 平台团队；领域级→对应领域 owner；项目级→项目负责人；个人级→提交人。

### 5 · 产出资产本体

**`assets/A<n>-<slug>.md`**：

```markdown
---
id: A1
title: <一句话标题>
form: 决策记忆            # 知识库|工程规则|决策记忆|技能工作流
secondary_tags: []        # 副标签列表
domains: [DFT]            # 多选≤3；空列表仅当 layer=公共级
projects: [HBM]           # LPDDR6/HBM 列表；空列表=跨项目
layer: 领域级              # 个人级|项目级|领域级|公共级
ai_form: Memory           # Memory|Rule|Skill|Workflow|Hook|Prompt；或 null + mapping_status
source: <输入材料名 日期>
suggested_owner: <owner>
---
## 内容
<提炼后的资产正文，不是原文粘贴；决策记忆须含 背景/选项/取舍/证据/日期>

## 出处与理由
<!-- provenance: 为什么值得入库；来源: <材料>, <日期> -->
```

### 6 · proposal.md 汇总 + manifest.json

proposal.md 必含四节：资产清单表（#/标题/形态/领域/项目/层级/建议 ai_form/建议 owner）、已过滤区（内容摘要+理由）、**入库申请**（批次级字段，见下）、审批区。

manifest.json（机器可读，供入库审批与追溯；技能 B 通过 record 的 `proposal_id` 关联本提案，不直接读 manifest）：

```json
{
  "proposal_id": "<YYYYMMDD-HHmm>-<slug>",
  "date": "<YYYY-MM-DD>",
  "source_material": "<输入材料名>",
  "assets": [
    {"id": "A1", "title": "...", "form": "...", "ai_form": "...",
     "layer": "...", "domains": ["..."], "projects": ["..."], "suggested_owner": "..."}
  ],
  "filtered": [{"summary": "...", "reason": "..."}]
}
```

**入库申请单必填字段**（对应资产 repo 的 issue 模板 `.github/ISSUE_TEMPLATE/asset-intake.md`）：

| 字段 | 来源 |
|---|---|
| 资产 ID | 本批资产局部 id（入库时升级为全局 `EA-<日期>-<序号>`） |
| 来源提案 ID | proposal_id |
| 目标层级/领域/项目 | 各资产 frontmatter |
| owner | suggested_owner（审批人可改） |
| 变更内容 | 本批新增/修改的资产清单 |
| 验收清单 | 质量门校验项 + 决策记忆完整度等提示项 |
| 回滚方式 | revert 对应 PR / 删除 assets/<proposal_id>/ 并回退 INDEX 与 registry |

### 7 · 确定性校验（闸门，不得跳过）

```bash
python -X utf8 ~/.claude/skills/assetize/scripts/validate.py <proposal-dir>
```

（`-X utf8` 防止 Windows GBK 控制台编码异常；脚本内部已自带 UTF-8 重配置，双保险。）

脚本校验目录结构、字段枚举、manifest 与资产一致、proposal 覆盖、正文提炼度。**exit 非 0 = 不得 propose**，先修复再跑。模型不得口头宣布通过来替代脚本（R6）。校验通过后向用户呈现 proposal 路径、清单与入库申请草稿。

### 8 · 入库申请与人工卡点

- 入库申请由**人**提交到资产 repo（或人明确授权的自动化提交）；本技能只产出申请内容与校验材料。技能不得自行关闭 issue、批准 PR 或合并（R3/R9）。
- **owner 批准后**：把本批资产升级为 approved asset record——frontmatter 增加 `asset_id`（全局 `EA-<YYYYMMDD>-<序号>`）、`proposal_id`、`status: approved`、`approved_by`、`approved_date`，把 `suggested_owner` 落定为 `owner`，并写入空的 `implementation:` 字段；正文原样——写入 `$ENG_ASSETS_REPO/assets/<proposal_id>/`（未设置时先询问用户仓库根，不要硬编码作者机器路径），更新该 repo 的 `INDEX.md`、`registry.json` 与 `approvals/<asset_id>.json`，并留一份评审记录到 `reviews/`。push 由人执行。
- 通过审批入库时，把一行摘要追加进 `~/.claude/asset-proposals/INDEX.md`。下次运行第 2 步前先查两个 INDEX（本地 + 资产 repo）：语义重复的单元不重复提案，标 `duplicate-of:<已有 asset_id>` 进过滤区——资产库膨胀比缺失更伤（灾难性记忆教训）。

## 质量线

- 提炼而非搬运：资产正文必须能脱离原输入独立成立，读者不需要看过原始材料。
- 决策记忆是最值钱的资产（"我们为什么这么做"只有自己知道），宁可多提决策类候选交给审批人筛，不要漏。
- 拿不准形态/层级时，宁可标副标签并在 proposal 里注明待审批人裁决，不要硬塞单一标签。
- ai_form 是建议映射不是承诺：技能 B 发现不可行会返回 mapping_issue，由本技能或 owner 重新映射，不视为 B 的失败。
