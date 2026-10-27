---
name: asset-ai-ize
description: 资产AI化（技能B）：把已批准的工程知识资产（approved asset record，来自 native-assets repo）按其 ai_form 映射生成为具体的 AI 组件实现——Memory/Rule/Skill/Workflow/Hook/Prompt，完成确定性校验与验收测试，产出 implementation package 并生成实现入库申请，由组件 owner 批准后安装或合入 native-assets-build repo。当用户说"把这条资产落地/实现"、"asset record 做成 rule/skill/memory/hook"、"落地资产 EA-xxx"、"实现这个资产"，或提供 approved asset record 要求转化为 AI 组件时使用。不重新判断资产是否成立、不修改资产语义（statement/evidence/mapping）；映射不可行时返回 mapping_issue。不用于从原始材料提炼资产（那是 assetize 技能 A 的职责）。
---

# 资产AI化（asset-ai-ize · 技能 B）

把 **approved asset record** 变成可运行、可验收的 AI 组件实现。输入是技能 A（assetize）入库的已批准资产 + 目标组件环境，输出是 implementation package 与实现入库申请。

**职责边界（规范 §3.4）**：本技能负责"怎么把它做成能跑的 AI 资产"——**不重新判断资产是否成立、不修改资产语义（statement / evidence / mapping）、不直接 push/merge/发布/关闭 issue**。"沉淀什么、放到哪"是技能 A 的事。

## 核心纪律

1. **record 只读**：`## 内容`（statement）与 `## 出处与理由`（evidence）一个字不改；`form/domains/layer` 等分类结论不动。要改 → 回技能 A 走新一轮提案。
2. **映射不可行就返回 mapping_issue**：发现 ai_form 落不了地（如 record 缺关键细节、形态与内容矛盾），不要硬造实现，产出 mapping_issue 报告，由技能 A 或 owner 重新映射。返回 mapping_issue 不是失败，硬造才是。
3. **语义保持**：实现物必须忠实承载 statement 的全部可复用结论，不增不减不演绎；拿不准的扩展内容放"实现备注"，不混入资产语义。
4. **外发由人执行**（R3/R9）：实现申请由人提交，安装/合入由组件 owner 批准；本技能不自动发布到任何公共目录。

## 输入

| 输入 | 说明 |
|---|---|
| **approved asset record** | 资产 repo 本地 clone（`D:\Project\native-assets`）`assets/` 下的 record 文件，或用户直接给出的 record 路径/asset_id。**必须 `status: approved`**，未批准的拒绝消费并提示先走技能 A 入库 |
| **目标组件 profile** | 实现要落地的环境与约束：目标环境（Claude Code 用户级 `~/.claude/` / 项目级 `.claude/` / 其他 AI IDE）、触发期望、命名偏好、已有相关组件（去重与挂接） |

## 输出目录

```
D:\Project\native-assets-build\build\<asset_id>\    # AI Infra repo 本地 clone 的 build 工作区
├── implementation.md       # 实现说明：语义保持对照 + 设计取舍 + 测试结果
├── build-manifest.json     # 机器可读：asset_id / ai_form / artifacts / tests / mapping_issue
├── artifacts/              # 实现物本体（按 ai_form 一或多个文件）
├── tests/                  # 验收测试（触发样例 / lint / 行为断言，至少 1 个文件）
├── review.md               # 评审清单（给组件 owner，必填）
└── install.md              # 安装说明（装到哪、怎么装、如何回滚）
```

`tests/`、`review.md`、`install.md` 是确定性闸门的必查项，缺失即 validate_build.py 失败。

## 流程

### 1 · 读取与验证 record

读 record，校验：`status: approved`、必填字段齐全（见 [`references/record-contract.md`](references/record-contract.md)）。未通过 → 停止并说明缺什么，不消费。

### 2 · 加载 playbook

按 record 的 `ai_form` 读 [`references/playbooks.md`](references/playbooks.md) 对应章节，明确该形态的实现物写法与验收要求。

### 3 · 生成实现物

在 build 目录按 playbook 写 artifacts。写之前先扫目标组件 profile 里的已有组件：语义重复 → 在 implementation.md 标注并给出挂接/替代建议，不重复造。

### 4 · 确定性校验（闸门，不得跳过）

```bash
python -X utf8 ~/.claude/skills/asset-ai-ize/scripts/validate_build.py <build-dir> \
  --assets-repo D:\Project\native-assets
```

校验目录结构（含 tests/review）、build-manifest 对账、record 唯一性与状态、proposal_id/ai_form 一致性、敏感信息模式、artifact 完整度。**exit 非 0 = 不得生成实现申请**（R6）。`--assets-repo` 可指向其他资产 repo clone。

### 5 · 验收测试

按 playbook 的验收要求跑测试（写入 `tests/`）：Rule 跑触发样例；Skill 跑端到端场景；Memory 做独立成立性检查（读者不看 record 也能懂）；Hook/Prompt 跑对应的行为断言。测试结果记入 implementation.md。

### 6 · implementation package 与实现申请

implementation.md 必含：**语义保持对照表**（statement 每个可复用结论 → 实现物中的承载位置）、设计取舍（为什么这么实现）、测试结果。实现申请单字段（对应 AI Infra repo 的 `.github/ISSUE_TEMPLATE/implementation-request.md`）：资产 ID、来源提案 ID、目标组件形态、目标层级/领域/项目、组件 owner、变更内容、验收清单、回滚方式。

### 7 · 人工卡点与写回

- 实现申请由**人**提交到 `native-assets-build`；**组件 owner 评审通过后**分两步落地：① artifacts 从 `build/` 合入 repo 的 `skills/`、`rules/`、`hooks/`、`prompts/`、`components/` 对应目录；② 按 `install.md` 安装到目标运行环境（`~/.claude/` 或项目 `.claude/`）。本技能不自动发布。
- 批准安装后，**写回**资产 repo 中该 record 的 `implementation` 字段（实现位置、日期、package 路径）——这是唯一允许 B 触碰 record 的地方，且只增不改 statement/evidence/mapping。
- push 由人执行。

## mapping_issue 格式

```markdown
# mapping_issue · <asset_id> · <日期>
## 不可行原因：（缺关键细节 / 形态与内容矛盾 / 目标环境不支持 / 与已有组件冲突且无法挂接）
## 影响：（哪条 statement 落不了地）
## 建议动作：（改 ai_form 为 X / 回技能 A 补充 Y / owner 裁决 Z）
```

mapping_issue 也走 build 目录 + validate_build.py（`type: mapping_issue` 分支），产出后交 owner，不视为实现失败。

## 质量线

- 实现物"拿来即用"：Rule 是祈使句规则全文、Skill 是可执行步骤，不是"应该写一个规则"的描述。
- 一条资产一个实现包；多重性质（副标签）原则上按主形态实现，副标签挂接建议写在 implementation.md。
- 宁可返回 mapping_issue，不造语义漂移的实现。
