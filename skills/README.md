# skills/

Agent Skill 目录。一个技能一个子目录，目录名即技能名（kebab-case），入口文件为 `SKILL.md`。

## 收录标准

- 有明确的触发条件与职责边界（何时用、何时不用）。
- 可独立安装到目标 AI IDE，不依赖未随仓库分发的文件。
- 带确定性校验或验收方式（脚本、测试用例、检查清单至少一种）。
- 不包含项目私有数据、密钥、个人信息。

## 当前收录

| 技能 | 作用 |
|---|---|
| [`assetize`](assetize/SKILL.md) | 技能 A：原始材料 → 资产提案包 + 入库申请 |
| [`asset-ai-ize`](asset-ai-ize/SKILL.md) | 技能 B：approved asset record → AI 组件实现包 |
| [`ai-infra-feedback`](ai-infra-feedback/SKILL.md) | 组件问题 → 结构化反馈单（默认只落盘，不自动发送） |

## 安装

```bash
cp -r <skill-name> ~/.claude/skills/
```

安装后新开会话生效。技能内部通过相对路径引用 `references/`、`scripts/`、`evals/`，不要拆散目录结构。
