# AI Native Basic Component

AI Native 工程流程的可复用基础组件库。组件按类型分目录存放，可独立评审、版本化、安装；本仓库只放组件本体与说明，不放项目私有数据。

相关仓库：

- [`eng-knowledge-assets`](https://github.com/LiJiaT/eng-knowledge-assets)：approved asset records、INDEX、registry。
- [`eng-asset-ai-components`](https://github.com/LiJiaT/eng-asset-ai-components)：资产实现包与构建历史。
- 本仓库：公共基础组件的分发与安装源。

## 目录结构

| 目录 | 放什么 | 当前内容 |
|---|---|---|
| [`skills/`](skills/README.md) | Agent Skill（Claude Code 等） | `assetize`、`asset-ai-ize`、`ai-infra-feedback`、`orchestrator`、`grill-me-with-doc`、`session-distiller` |
| [`flows/`](flows/README.md) | 多组件编排的端到端流程 | [`self-evolution`](flows/self-evolution/README.md) |
| [`memory/`](memory/README.md) | 可复用的 memory 条目模板与公共记忆 | `asset-taxonomy.md`、`dft/hbm3e-stack-level-repair-decision.md` |
| [`rules/`](rules/README.md) | 可复用的工程规则（Rule） | 5 条公共规则（R1/R3/R4/R7/R8）+ `dft/bist-scan-same-cycle-exclusion.md` |
| [`prompts/`](prompts/README.md) | 可复用的提示词模板（Prompt） | 待补充 |
| [`hooks/`](hooks/README.md) | 确定性钩子脚本与配置示例（Hook） | `orchestrator`、`self-evolve` |
| [`agents/`](agents/README.md) | 子代理定义（Agent） | `orchestrator` |
| [`docs/`](docs/README.md) | 使用指南、设计说明、规范链接 | [领域目录映射](docs/domain-taxonomy.md) |

领域级组件按 9 个领域分目录存放：`memory/<domain>/`、`rules/<domain>/`，slug 映射见 [docs/domain-taxonomy.md](docs/domain-taxonomy.md)。公共级规则与记忆直接放 `rules/`、`memory/` 根目录。

## 组件总览

| 组件 | 类型 | 作用 |
|---|---|---|
| [`orchestrator`](agents/orchestrator.md) | Agent | 复杂任务的统一入口与调度层：澄清、规划、分解分发、验收、写回 |
| [`orchestrator`](skills/orchestrator/SKILL.md) | Skill | agent 的入口垫片与支撑资源（references / `task_packager.py`） |
| [`grill-me-with-doc`](skills/grill-me-with-doc/SKILL.md) | Skill | 六维需求澄清，作为 orchestrator 澄清阶段 |
| [`session-distiller`](skills/session-distiller/SKILL.md) | Skill | 从历史 session 日志蒸馏可复用资产 |
| [`self-evolution`](flows/self-evolution/README.md) | Flow | 采集 → 蒸馏 → 分诊 → 人工确认 → 晋升 → 卫生 |
| [`assetize`](skills/assetize/SKILL.md) | Skill（A） | 原始材料 → 资产提案包 + 入库申请 |
| [`asset-ai-ize`](skills/asset-ai-ize/SKILL.md) | Skill（B） | approved asset record → AI 组件实现包 |
| [`ai-infra-feedback`](skills/ai-infra-feedback/SKILL.md) | Skill | 组件问题 → 结构化反馈单，默认只落盘 |
| [公共规则](rules/README.md) | Rule | 规范 §3.4 中已实现的 R1/R3/R4/R7/R8 |
| [`asset-taxonomy`](memory/asset-taxonomy.md) | Memory | 9 领域 + 2 项目 + 四维正交的分类决策 |

## 核心流程

### 资产化 A/B 双技能

两个阶段以 **approved asset record** 为唯一交接契约：

```text
原始材料 → 技能 A assetize → proposal package → owner 批准 → approved asset record
         → 技能 B asset-ai-ize → implementation package → 组件 owner 批准 → 合入/安装
```

- **技能 A**：收集、分类、映射，产出 proposal package 与入库申请；不写实现、不 push。
- **技能 B**：按 record 的 `ai_form` 生成 Memory / Rule / Skill / Workflow / Hook / Prompt，完成确定性校验与验收；不改资产语义、不自动发布。
- **确定性闸门**：`validate.py`（A）、`validate_build.py`（B），退出码即结论。

### Orchestrator

```text
用户请求 → 分类（简单直接做 / 复杂走流程）
        → 澄清（grill-me-with-doc 六维）
        → 规划（目标/约束/输入/输出/验收/人工卡点）
        → 任务包 → 按依赖分发
        → 执行 → 自查 + 独立验收
        → 人工验收 → 写回资产
```

`hooks/orchestrator` 在会话启动时注入编排模式标识，在用户提交 prompt 时做复杂度预分类；两者都是上下文注入，不是审批闸门。

### 自进化

```text
SessionEnd → 入队（预过滤）→ 后台 worker（L0→L1→L2→L3）
           → 五车道分诊 → staging 去重 → 人工确认
           → 写入正式资产（provenance）→ git commit（若启用）
           → 定期 curator（三期）
```

完整设计、阶段契约与卡点见 [`flows/self-evolution`](flows/self-evolution/README.md)。

### 澄清与公共规则

- `grill-me-with-doc` 一次问清目标、约束、输入、输出、边界、验证标准；任一项未明确不进入执行。
- 公共规则直接对应规范 §3.4 的 R1/R3/R4/R7/R8；领域规则放 `rules/<domain>/`。

## 安装

Claude Code 用户级安装：

```bash
# 资产化与反馈
cp -r skills/assetize skills/asset-ai-ize skills/ai-infra-feedback ~/.claude/skills/

# Orchestrator
mkdir -p ~/.claude/agents ~/.claude/skills ~/.claude/hooks/orchestrator
cp agents/orchestrator.md ~/.claude/agents/
cp -r skills/orchestrator skills/grill-me-with-doc ~/.claude/skills/
cp hooks/orchestrator/*.py ~/.claude/hooks/orchestrator/
# 再把 hooks/orchestrator/settings.example.json 的 hooks 配置合并进 ~/.claude/settings.json

# 自进化
mkdir -p ~/.claude/hooks/self-evolve ~/.claude/self-evolve/{queue,staging,distill-state}
cp -r skills/session-distiller ~/.claude/skills/
cp hooks/self-evolve/*.sh ~/.claude/hooks/self-evolve/
# 再把 hooks/self-evolve/settings.example.json 的 hooks 配置合并进 ~/.claude/settings.json

# 公共规则
cp rules/verilog-filelist-sync.md rules/no-auto-external-actions.md \
   rules/verify-or-review-before-delivery.md rules/subtask-acceptance-checklist.md \
   rules/no-raw-records-in-memory.md ~/.claude/rules/
```

安装前先检查目标环境是否已有同名组件；更新时覆盖对应目录，并保留旧版本以便回滚。`settings.example.json` 只包含 hooks 配置，不含任何凭证。

## 使用

```text
资产化 <材料>                     # 技能 A：产出 proposal package
把 EA-YYYYMMDD-NN 实现成 ...       # 技能 B：产出 implementation package
提反馈：<问题描述>                 # 反馈技能：产出结构化反馈单
复杂任务 ...                       # orchestrator：澄清 → 规划 → 分发 → 验收
蒸馏 session <id>                  # session-distiller：历史会话 → 候选资产
```

技能与组件默认只生成“申请 + 校验材料”；push / merge / 安装由人执行，符合“外发由人执行”规则。

## 边界与缺口

- 本库只收公共、可复用组件。个人环境规则（如 `auto-mode-classifier`、`telegram-bot-handlers`）、个人 agent（`claude-env-maintainer`）、外部工具技能（`lark-*` 等）不在此列。
- 规范 §5.8 的审批/校验闸门（`require-six-elements`、`plan-schema-gate`、`acceptance-evidence-gate` 等）尚未实现；本库现有 hooks 是 fail-open 的上下文注入，不能当作审批门禁。
- `PDF2MD` 在参考环境中未找到实现，待 owner 提供后收录。
- 公共规则 EA-20261022-02..06 的源记录在 `eng-knowledge-assets`，构建历史在 `eng-asset-ai-components`；本库是公共分发副本，变更仍走资产化流程。
- 自进化 worker 尚未接入 `distill-state` 游标，长 session 可能重复全量蒸馏；详见 [`flows/self-evolution/README.md`](flows/self-evolution/README.md)。

## 目录约定

- 一个组件一个子目录（agent 可以是单文件），目录名用 kebab-case。
- 技能目录以 `SKILL.md` 为入口；其他组件目录至少包含 `README.md`，说明用途、输入输出、安装/回滚与验收方式。
- 不存放项目私有材料、密钥、个人信息；`provenance_status=synthetic` 的示例必须明确标注。
