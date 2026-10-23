# ai-infra-feedback

把使用中遇到的组件问题整理成结构化反馈单的 Agent Skill。默认只在本地落盘，不自动发送。

## 什么时候用

- 组件报错、行为不符合预期或流程卡住，需要向上游反馈。
- 想把当前 session 里出现的问题整理成一份可直接转交的反馈单。
- 不适用：普通 bug 修复、代码调试、询问用法，直接处理即可。

## 输入与输出

输入是一段问题描述，或当前 session 的 transcript。技能会引导补齐六个必填字段：问题现象、影响范围、期望行为、复现路径、涉及组件、优先级。

输出包括：

- Markdown + JSON 反馈单，落盘前统一脱敏；
- self-evolve staging 候选（`status: staged`，不自动晋升）；
- 可选的群消息投递：默认 dry-run，只有使用者当轮明确确认后才发送。

## 安装

```bash
cp -r skills/ai-infra-feedback ~/.claude/skills/
```

读取 `~/.agents/skills/` 的环境（如 Qoder）复制到对应目录。更新时覆盖同名目录，保留旧版本以便回滚。安装后新开会话生效。

## 使用

```text
提反馈：<问题描述>
把刚才 session 里的问题整理成反馈单
```

详细字段、脱敏规则与发送配置见 [`SKILL.md`](SKILL.md) 和 [`references/feedback-schema.md`](references/feedback-schema.md)。

## 验收

```bash
python scripts/feedback.py \
  --problem "test" \
  --component ai-infra-feedback \
  --outbox ./outbox-test \
  --no-staging
```

预期：退出码为 0；`outbox-test/` 下同时生成 Markdown 与 JSON；六个必填字段存在；敏感信息被替换为 `[REDACTED:类型]`。未加 `--yes` 时不得发起任何网络请求。

## 边界

- 只做问题结构化与转交，不做根因修复，不自动晋升资产。
- 不写原始日志、聊天或会议记录；证据只保留结论 + 指针 + 极短摘录。
- 发送失败不重试刷屏；反馈单已落盘，如实报告错误即可。
