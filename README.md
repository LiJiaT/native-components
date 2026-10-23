# AI Native Basic Component

AI Native 工程流程的可复用基础组件库。组件按类型分目录存放，可独立评审、版本化、安装；本仓库只放组件本体与说明，不放项目私有数据。

## 目录结构

| 目录 | 放什么 | 当前内容 |
|---|---|---|
| [`skills/`](skills/README.md) | Agent Skill（Claude Code 等） | `assetize`（技能 A）、`asset-ai-ize`（技能 B） |
| [`flows/`](flows/README.md) | 多组件编排的端到端流程：阶段、卡点、交接契约 | 待补充 |
| [`memory/`](memory/README.md) | 可复用的 memory 条目模板与公共记忆 | 待补充 |
| [`rules/`](rules/README.md) | 可复用的工程规则（Rule） | 待补充 |
| [`prompts/`](prompts/README.md) | 可复用的提示词模板（Prompt） | 待补充 |
| [`hooks/`](hooks/README.md) | 确定性钩子脚本与配置示例（Hook） | 待补充 |
| [`agents/`](agents/README.md) | 子代理定义（Agent） | 待补充 |
| [`docs/`](docs/README.md) | 使用指南、设计说明、规范链接 | 待补充 |

## 当前组件：资产化 A/B 双技能

两个阶段以 **approved asset record** 为唯一交接契约：

```
原始材料 → 技能 A assetize → proposal package → owner 批准 → approved asset record
         → 技能 B asset-ai-ize → implementation package → 组件 owner 批准 → 合入/安装
```

- **技能 A [`skills/assetize`](skills/assetize/SKILL.md)**：收集、分类、映射，产出 proposal package 与入库申请；不写实现、不 push。
- **技能 B [`skills/asset-ai-ize`](skills/asset-ai-ize/SKILL.md)**：按 record 的 `ai_form` 生成 Memory / Rule / Skill / Workflow / Hook / Prompt，完成确定性校验与验收，产出实现包；不改资产语义、不自动发布。
- **确定性闸门**：`validate.py`（A）、`validate_build.py`（B），退出码即结论。
- **相关仓库**：[eng-knowledge-assets](https://github.com/LiJiaT/eng-knowledge-assets)（approved asset records）、[eng-asset-ai-components](https://github.com/LiJiaT/eng-asset-ai-components)（实现物）。

## 安装

Claude Code 用户级安装：

```bash
cp -r skills/assetize ~/.claude/skills/
cp -r skills/asset-ai-ize ~/.claude/skills/
```

安装前先检查目标环境是否已有同名 skill；更新时覆盖对应目录，并保留旧版本以便回滚。

## 使用

```text
资产化 <材料>                  # 技能 A：产出 proposal package
把 EA-YYYYMMDD-NN 实现成 ...    # 技能 B：产出 implementation package
```

两个技能都只生成「申请 + 校验材料」；push / merge / 安装由人执行，符合“外发由人执行”规则。

## 目录约定

- 一个组件一个子目录，目录名用 kebab-case。
- 每个组件目录至少包含 `README.md`，说明用途、输入输出、安装/回滚与验收方式。
- 不存放项目私有材料、密钥、个人信息；`provenance_status=synthetic` 的示例必须明确标注。
