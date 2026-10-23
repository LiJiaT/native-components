---
name: ai-infra-feedback
description: "把使用中遇到的组件问题整理成结构化反馈单（问题现象/影响范围/期望行为/复现路径/涉及组件/优先级，外加证据、环境、建议动作），落盘 Markdown + JSON、生成 self-evolve staging 候选，并可按需发送给 AI Infra 团队。当用户明确说“提反馈”“上报问题”“反馈给 AI Infra”“记录组件问题”“这个 skill 有问题”“这个组件不好用”“把刚才 session 里的问题整理成反馈单”，或要求把当次会话中的报错结构化上报时使用。只处理明确的反馈/上报意图；普通 bug 修复、代码调试、写代码、询问用法不要触发，也不要替用户自动上报。"
---

# AI Infra Feedback（反馈技能）

把「使用者主动描述的问题」或「当次 session 中出现的问题」结构化成反馈单，写入 self-evolve outbox，并生成 staging 候选供 AI Infra 评估组件升级。**默认只落盘，不发送、不晋升。**

字段规范、脱敏规则、staging 格式、发送配置见 `references/feedback-schema.md`。

## 硬规则

1. **不自动发送**：默认 dry-run。只有用户在当轮对话中明确确认「发吧 / 确认发送」后，才可加 `--yes`。测试、演示、脚本自检一律不得使用真实群。
2. **不编造**：拿不到的字段写 `（待补充：…）` 并向用户要，不要猜影响范围、期望行为或复现步骤。
3. **落盘前脱敏**：脚本统一处理 API key/token/密码/手机号/邮箱/私钥/Authorization 等；不要绕过脚本手写反馈单。
4. **遵守 R8**：不把原始会议、聊天、调试日志写入反馈单或长期记忆。证据只保留结论 + 文件:行/命令/transcript 行号指针 + 极短摘录。
5. **不自动晋升**：staging 候选保持 `status: staged`，不改 INDEX 状态、不搬进正式资产库；晋升由既有批处理/人工确认流程负责。
6. **最小必要**：只收集与问题相关的信息；不附无关的聊天记录、个人文件、完整环境变量。

## 工作流

### Step 1 · 明确问题来源

- 用户主动描述：直接采用其原话，必要时追问缺失字段。
- 当次 session：定位 transcript JSONL（通常在 `~/.claude/projects/<项目slug>/<session-id>.jsonl`）。不确定路径时问用户，或取该项目最新文件并**向用户确认**：
  ```bash
  ls -t ~/.claude/projects/*/*.jsonl | head -5
  ```
- 二者都有时：以用户描述为准，session 只补证据与复现路径。

### Step 2 · 结构化六个必填字段

| 字段 | 要求 | 常见错误 |
|---|---|---|
| 问题现象 | 可观察的事实：报错文本、错误行为、发生时机 | 写成解决方案或猜测 |
| 影响范围 | 谁/哪些场景受影响、是否阻断、有无绕行 | 只写「影响很大」 |
| 期望行为 | 用户期望发生什么（可验收） | 与现象重复 |
| 复现路径 | 从初始状态到问题出现的最小步骤；命令要可复制 | 只写「再试一次」 |
| 涉及组件 | skill / CLI / hook / 模型网关 / 具体文件或服务 | 写「系统」 |
| 优先级 | P0–P3，按下表判定 | 一律填 P0 |

优先级判据（默认 P2，缺省时脚本会告警）：

- **P0**：完全阻断使用、数据损坏/丢失、安全问题，且无绕行。
- **P1**：核心功能不可用，或绕行成本很高/需要人工介入。
- **P2**：功能缺陷或明显体验问题，有合理绕行。
- **P3**：建议、小瑕疵、文档/提示语问题。

另外补齐：**证据**（`文件:行`、命令、日志指针、transcript 行号）、**环境信息**、**建议动作**、**来源 session**、**时间戳**（脚本自动生成）。

### Step 3 · 生成反馈单

推荐用 `--input` 传结构化 JSON（字段多时最稳），简单问题直接用参数。命令里的 `SKILL_DIR` 按实际安装位置取：

```bash
SKILL_DIR=~/.claude/skills/ai-infra-feedback      # Qoder 环境用 ~/.agents/skills/ai-infra-feedback

python "$SKILL_DIR/scripts/feedback.py" \
  --problem "调用 /ai-infra-feedback 后只生成 JSON，没有 Markdown" \
  --impact "使用者无法直接阅读反馈单，需要手工转换" \
  --expected "同目录同时生成 .md 与 .json" \
  --repro "1. 运行 /ai-infra-feedback --problem test
2. 查看 outbox 目录" \
  --component ai-infra-feedback \
  --priority P2 \
  --evidence "file:scripts/feedback.py:520 - 只写了 JSON" \
  --evidence "cmd:python scripts/feedback.py --problem test" \
  --suggested-action "补 Markdown 渲染并加回归测试"
```

从 session 提取（会自动摘取用户陈述、失败命令、错误行号指针）：

```bash
SKILL_DIR=~/.claude/skills/ai-infra-feedback
python "$SKILL_DIR/scripts/feedback.py" \
  --session ~/.claude/projects/-Users-me-proj/<session-id>.jsonl \
  --component lark-cli --priority P1
```

脚本会打印 Markdown/JSON/staging 三个路径。默认输出：

- outbox：`~/.claude/self-evolve/queue/feedback/`（`--outbox` 或 `AI_INFRA_FEEDBACK_OUTBOX` 可改）
- staging 候选：`~/.claude/self-evolve/staging/cand-<hash>.md` + `INDEX.md` 追加一行（`--staging-dir` / `AI_INFRA_FEEDBACK_STAGING` 可改；`--no-staging` 跳过）

> Windows 执行提示：上述示例是 Git Bash 语法，优先用 Bash 工具执行。若用 PowerShell，请直接写完整脚本路径，不要照搬 `SKILL_DIR=...` 赋值语法（PowerShell 会把 `$SKILL_DIR` 当表达式解析，已实测会报 `Command contains expandable strings with embedded expressions`）。

### Step 4 · 向用户汇报

给出：反馈单 ID、优先级、标题、产物路径（Markdown/JSON/staging）、缺失字段、脱敏命中数。把 Markdown 的六段要点贴给用户确认；不要贴完整环境变量或原始日志。

### Step 5 · 可选发送（必须二次确认）

1. 先 dry-run（**不传 `--yes`**）：
   ```bash
   SKILL_DIR=~/.claude/skills/ai-infra-feedback
   python "$SKILL_DIR/scripts/feedback.py" --problem "..." --component ... --send
   ```
   脚本只打印「将发送的内容」和「将执行的命令」，不发起网络请求。
2. 把内容给用户看，明确问「是否发送到 AI Infra 群」。
3. 用户当轮明确确认后，才加 `--yes`：
   ```bash
   SKILL_DIR=~/.claude/skills/ai-infra-feedback
   python "$SKILL_DIR/scripts/feedback.py" --problem "..." --component ... --send --yes
   ```
4. 目标群：`--chat-id oc_xxx` 或环境变量 `AI_INFRA_FEISHU_CHAT_ID`。**未配置就停下问用户**，不要搜索群、不要猜 chat_id、不要发给个人。
5. 发送失败时如实报告 lark-cli 的 stderr；反馈单已落盘，不要重复刷屏重试。

### Step 6 · 收尾

- 若用户说「这个 skill 本身有问题」，正常生成反馈单，组件填 `ai-infra-feedback`，并在建议动作里写清期望的修改。
- 不要顺手修改 self-evolve 的 worker/queue 结构；反馈只新增 `queue/feedback/` 与 staging 候选。

## 常用参数

| 参数 | 说明 |
|---|---|
| `--problem / --impact / --expected` | 三个核心文本字段 |
| `--repro` | 复现步骤，可重复或用换行分隔 |
| `--component` | 涉及组件，可重复或逗号分隔 |
| `--priority` | P0/P1/P2/P3，默认 P2 |
| `--evidence` | 可重复；`file:path:12 - 摘要`、`cmd:...`、`log:...`、`pointer:...` |
| `--session` | transcript JSONL，自动提取问题与证据 |
| `--input` | 结构化 JSON（支持中文键名），CLI 参数优先 |
| `--outbox` / `--staging-dir` | 覆盖输出位置 |
| `--send` / `--yes` | 发送；只有两者同时出现才真正调用 lark-cli |
| `--json-summary` | stdout 输出机器可读摘要 |

退出码：`0` 成功（含 dry-run）；`2` 参数/输入错误；`3` 发送失败（反馈单仍已落盘）。

## 环境前提

- Python 3（仅标准库；本机 3.14.3 实测通过）。
- 发送需要本机 `lark-cli` 已登录且有目标群发消息权限；脚本按 `LARK_CLI` 环境变量 → `PATH` → 插件缓存顺序查找。
- 未配置 `AI_INFRA_FEISHU_CHAT_ID` 时只能生成与 dry-run，不能真实发送。
