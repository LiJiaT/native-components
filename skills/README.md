# skills/

Agent Skill 目录。一个技能一个子目录，目录名即技能名（kebab-case），入口文件为 `SKILL.md`。

## 收录标准

- 有明确的触发条件与职责边界（何时用、何时不用）。
- 可独立安装到目标 AI IDE，不依赖未随仓库分发的文件。
- 带确定性校验或验收方式（脚本、测试用例、检查清单至少一种）。
- 不包含项目私有数据、密钥、个人信息。

## 当前收录

| 技能 | 作用 | 备注 |
|---|---|---|
| [`assetize`](assetize/SKILL.md) | 技能 A：原始材料 → 资产提案包 + 入库申请 | 支持多项目 `projects[]`、未映射 `mapping_status`；校验空值/原始日志/决策五要素 |
| [`asset-ai-ize`](asset-ai-ize/SKILL.md) | 技能 B：approved asset record → AI 组件实现包 | 结构层 + `--release` 发布层；record/审批 hash、范围、隐藏文件、原始记录、语法与独立复核 |
| [`ai-infra-feedback`](ai-infra-feedback/SKILL.md) | 组件问题 → 结构化反馈单 | 默认只落盘，不自动发送 |
| [`orchestrator`](orchestrator/SKILL.md) | orchestrator agent 的入口垫片与支撑资源（references / task_packager.py） | 需与 `agents/orchestrator.md` 一起安装 |
| [`grill-me-with-doc`](grill-me-with-doc/SKILL.md) | 六维需求澄清：目标、约束、输入、输出、边界、验证标准 | orchestrator 澄清阶段的专用技能 |
| [`session-distiller`](session-distiller/SKILL.md) | 从历史 session 日志蒸馏可复用资产 | 自进化流程的蒸馏入口 |

## 安装

```bash
python -X utf8 tools/install.py --component <skill-name>
# 或一次安装全部
python -X utf8 tools/install.py --all
```

安装器自动创建 `~/.claude/skills/<name>/`、复制 `references/scripts/evals` 全部资源并写安装 manifest。技能内部通过相对路径引用资源，不要拆散目录结构。

`orchestrator` 是 agent 的支撑资源，必须与 `agents/orchestrator.md` 配套安装；`session-distiller` 的自动闭环还需要 `hooks/self-evolve` 与 `flows/self-evolution`。
