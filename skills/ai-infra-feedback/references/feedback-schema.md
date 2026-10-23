# 反馈单数据规范

`scripts/feedback.py` 的输入/输出契约。JSON 与 Markdown 同源生成；所有落盘、预览、发送内容都先经过统一脱敏。

## 1. 输入（`--input` JSON）

键名支持英文或中文（`问题现象`/`影响范围`/`期望行为`/`复现路径`/`涉及组件`/`优先级`/`证据`/`建议动作`/`环境信息`/`标题`）。CLI 参数优先于文件。

```json
{
  "title": "lark-cli 发送超时后无错误详情",
  "problem": "执行 lark-cli im +messages-send 时超时，只返回 exit 1",
  "impact": "反馈单无法送达 AI Infra，需人工复制内容",
  "expected": "失败时输出可诊断的错误码与请求 ID",
  "repro": ["运行 feedback.py --send --yes", "在网络受限环境下等待 90s"],
  "component": ["lark-cli", "ai-infra-feedback"],
  "priority": "P1",
  "priority_rationale": "核心投递路径不可用，但有复制粘贴绕行",
  "evidence": [
    "file:scripts/feedback.py:610 - 只记录 exit code",
    "cmd:lark-cli im +messages-send --chat-id oc_xxx --text hi",
    {"kind": "log", "summary": "timeout after 90s", "pointer": "C:/logs/lark.log:88", "excerpt": "ETIMEDOUT"}
  ],
  "suggested_actions": ["捕获 stderr 并写入 delivery.error", "增加 --timeout 参数"],
  "environment": {"network": "corp-proxy", "lark_cli": "1.0.87"},
  "source_session": "C:/Users/me/.claude/projects/-proj/session.jsonl",
  "outbox": "D:/tmp/feedback-outbox",
  "staging_dir": "D:/tmp/staging"
}
```

## 2. 输出 JSON

```json
{
  "schema_version": "1.0",
  "feedback_id": "fb-20261022-163000-a1b2c3",
  "created_at": "2026-10-22T16:30:00+08:00",
  "timestamp": "2026-10-22T16:30:00+08:00",
  "title": "…",
  "source": {
    "mode": "problem | session | problem+session",
    "session_id": "…",
    "transcript_path": "…",
    "extraction": {"lines_scanned": 0, "complaint_messages": 0, "error_evidence": 0, "note": "…"}
  },
  "reporter": {"user": "…", "skill": "ai-infra-feedback", "skill_version": "0.1.0"},
  "issue": {
    "phenomenon": "问题现象",
    "impact": "影响范围",
    "expected": "期望行为",
    "repro_steps": ["步骤 1", "步骤 2"],
    "components": ["组件 A"],
    "priority": "P2",
    "priority_rationale": "…"
  },
  "evidence": [{"id": "E1", "kind": "file|command|log|pointer", "summary": "…", "pointer": "…", "excerpt": "…"}],
  "environment": {"os": "…", "python": "…", "cwd": "…", "git_branch": "…", "git_head": "…",
                   "claude_version": "…", "lark_cli_version": "…", "extra": {}},
  "suggested_actions": ["…"],
  "source_session": {"session_id": "…", "transcript_path": "…", "pointer_note": "…"},
  "completeness": {"complete": true, "missing_fields": [], "warnings": []},
  "redaction": {"applied": true, "hits": {"api_key": 1}, "total": 1},
  "delivery": {"requested": false, "mode": "none|dry_run|send", "status": "pending|not_requested|dry_run|sent|failed",
                "chat_id_masked": "oc_...abcd", "identity": "", "command": "…", "body_preview": "…",
                "sent_at": null, "error": ""},
  "paths": {"outbox": "…", "markdown": "…", "json": "…", "staging_candidate": "…", "staging_index": "…"},
  "r8": {"raw_logs_written": false, "note": "…"}
}
```

六个必填字段的机读键：`issue.phenomenon` / `issue.impact` / `issue.expected` / `issue.repro_steps` / `issue.components` / `issue.priority`。缺失时字段仍存在，值为 `（待补充：需反馈人确认）`，并在 `completeness.missing_fields` 中列出。

## 3. Markdown 模板

固定十个编号小节，便于 AI Infra 按节处理：

```
# [P2] 标题
- 反馈单 ID / 时间 / 上报人 / 来源
## 1. 问题现象
## 2. 影响范围
## 3. 期望行为
## 4. 复现路径        （有序列表）
## 5. 涉及组件
## 6. 优先级          （P2 — 理由）
## 7. 证据            （表格：ID/类型/摘要/指针 + 极短摘录）
## 8. 环境信息
## 9. 建议动作
## 10. 来源 session   （session_id / transcript 指针 / 提取范围）
## 投递               （仅 --send 时出现：状态/目标群/命令/错误）
```

## 4. staging 候选

写入 `<staging>/cand-<sha1(feedback_id+title)[:8]>.md`，遵循 self-evolve DESIGN §6.1；`lane` 使用扩展值 `feedback`，并附 `feedback_id/component/priority` 供 AI Infra 消费。既有按五车道过滤的工具会安全忽略它。同时在 `INDEX.md` 追加一行 `| cand-xxx | feedback | staged | 摘要 |`；已存在同 id 不重复追加。**不修改 status，不自动晋升。**

```markdown
---
id: cand-a1b2c3d4
created: 2026-10-22
source_sessions: ["…"]
user: …
scope: user
lane: feedback
status: staged
supersedes: null
recurrence: 1
feedback_id: fb-…
component: ["…"]
priority: P2
---
# [P2] 标题
**问题现象**: …
…（六字段 + 证据指针 + 建议动作 + 本地反馈单路径）
<!-- 理由: 使用者反馈的组件问题，供 AI Infra 升级评估；来源: session …, 2026-10-22, 反馈单 fb-… -->
```

## 5. 脱敏规则

按顺序替换为 `[REDACTED:类型]`：

| 类型 | 覆盖 |
|---|---|
| `private_key` | PEM 私钥块 |
| `api_key` | `sk-…`、`sk-ant-…` |
| `github_token` | `ghp_/gho_/ghu_/ghs_/ghr_…` |
| `aws_key` | `AKIA…` |
| `bearer` / `auth_header` / `cookie` | Authorization/Cookie 头与 Bearer token |
| `secret` | `token/password/passwd/pwd/api_key/secret/app_secret/client_secret` 后跟 `:` 或 `=` 的值 |
| `url_userinfo` | `https://user:pass@host` |
| `id_card` / `phone_cn` / `email` | 18 位身份证、中国大陆手机号、邮箱 |

脱敏在 `doc` 构建完成后、写文件前统一执行，命中数写入 `redaction`。**不要**在调用脚本前手工拼装含密钥的内容；也不要在 skill 里另写未脱敏的日志。

## 6. 发送

- 目标群：`--chat-id oc_xxx` 或 `AI_INFRA_FEISHU_CHAT_ID`。
- 默认 dry-run：只打印正文与命令，不启动子进程、不发网络请求。
- `--send --yes` 才执行：`lark-cli im +messages-send --chat-id … --markdown <正文> --idempotency-key <feedback_id> [--as user|bot]`。
- 正文会压成**单行**（分号分隔各段），避免 Windows `.cmd` 启动器在换行处截断参数；完整排版见本地 Markdown。
- 正文超过 `--max-send-chars`（默认 3500）会截断并提示查看本地反馈单。
- 发送结果解析 lark-cli JSON 的 `ok`/`message_id`；失败写 `delivery.status=failed` 与 `delivery.error`，退出码 3。
- `lark-cli` 查找顺序：`LARK_CLI` → `PATH` → Qoder/Claude 插件缓存；Windows 上若是 POSIX 脚本则通过 `bash` 调用，若是原生 `lark-cli.exe` 则直接调用。

## 7. R8 与证据最小化

- transcript 提取只做 L0：扫描行数、用户陈述（最近 6 条）、错误摘要（最多 12 条）、`transcript#L<行号>` 指针。
- 摘录上限 240 字符，且只取首条匹配错误行；不落完整 tool_result、不落聊天/会议原文。
- 反馈单与 staging 候选都只保留结论 + 指针；原始 transcript 留在原位。
- 字段 `r8.raw_logs_written` 恒为 `false`，作为自检标记。
