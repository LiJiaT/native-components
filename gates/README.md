# 确定性门禁（gates）

`gate.py` 是失败关闭的校验入口。**旁路通知 hook 可以 fail-open；本目录的门禁必须 fail-closed。**

## 子命令

| 命令 | 用途 | 失败语义 |
|---|---|---|
| `record --assets-repo <repo> --asset-id EA-... [--require-distributable]` | record 必填字段、状态、审批绑定、不可变正文 hash；可选新分发资格 | exit 1 |
| `asset-registry --assets-repo <repo> [--require-distributable]` | 账册合法性全量对账；`--require-distributable` 额外要求每条可新分发 | exit 1 |
| `component-registry --repo .` | 七字段、路径、依赖、循环、版本 | exit 1 |
| `plan --file plan.json [--require-approval]` | schema + 六要素 + 结构化 AC + 需求卡 hash + 批准 decision/日期/scope_hash | exit 1 |
| `acceptance --file acceptance.json --base-dir <dir>` | 绑定任务包 AC/指定证据/必交付产物、run 身份、reviewer 输入、finding 处置 | exit 1 |
| `external-write` | PreToolUse 外发拦截（shell 选项/MCP 写工具/异常失败关闭）；默认 deny | JSON deny / exit 2 |
| `approve --command ... --by <人> --minutes 30` | 写入人工预批准；配置 allowed_signers 后必须 SSH 签名 | — |
| `security-status` | 显示当前批准是否启用签名 | — |
| `memory --file <md> [--require-provenance]` | 原始记录 / 秘密 / provenance 枚举 / owner / 来源 / scope | exit 1 |
| `promotion --file <json>` | 晋升记录字段/证据 hash/git clean/目标范围检查（只检查，不自动批准） | exit 1 |
| `task-package --file <json> --strict [--tasks-dir]` | 调用 task_packager strict（依赖必须 done、至少一项独立复核） | exit 1 |
| `install --manifest <json> [--repo <src>]` | manifest 与实际文件 hash/唯一目标/范围对账 | exit 1 |

所有判定写 `~/.claude/audit/gates.jsonl`（`AI_GATE_AUDIT_LOG` 可覆盖），含 `rule/input_hash/session_id/decision`；同一输入连续 3 次 deny 会升级提示。安全关键门禁（record/registry/plan/acceptance/memory/promotion/install）审计不可写时失败关闭。

## 挂接（settings.json 片段）

见 [`settings.example.json`](settings.example.json)（POSIX）与 [`settings.windows.example.json`](settings.windows.example.json)（Windows，含解释器绝对路径）。安装器把 `gate.py` 放到 `~/.claude/gates/gate.py`：

```bash
python tools/install.py --component gate-core --component component-schemas
```

matcher 同时覆盖 `Bash|Shell|shell|mcp__.*`：shell 命令检测 `git -C ... push`、`curl/httpx/requests` 写、
云/容器/包发布等语法；MCP 采用**只读白名单**，未知 MCP 能力默认 deny，已知写动词 deny。
hook 输入损坏、缺 `tool_name/command` 或内部异常一律返回 deny（失败关闭）。

人工预批准：

```bash
python ~/.claude/gates/gate.py approve --command "git push origin main" --by <你的名字> --minutes 30
python ~/.claude/gates/gate.py approve --tool mcp__github__push_files --input-json '{"...":"..."}' --by <人>
```

批准按命令/工具输入的完整 hash 生效，到期自动失效。显式设置 `AI_GATE_ALLOWED_SIGNERS` 或 `AI_GATE_REQUIRE_SIGNATURE=1` 即进入严格签名模式；策略文件缺失/不可读时所有批准失败关闭，不再静默降级。若要阻止同权进程伪造批准，由人建立签名批准：

```bash
ssh-keygen -t ed25519 -f ~/.claude/gates/approval_key   # 私钥留给人，带口令
# 把公钥写入 ~/.claude/audit/approvals/allowed_signers：<principal> ssh-ed25519 AAAA...
python ~/.claude/gates/gate.py security-status
```

配置 `allowed_signers` 后，`approve` 必须用私钥签名（无口令/无终端会失败），门禁校验签名；
未配置时是兼容模式（同权进程可伪造批准），状态会明确显示。R02 的真实人工边界依赖人持有私钥。

## 16 类拟议门禁的落地状态

规范 §5.8 列出的 16 类 hook 是"可 Hook 化"的实现方式，不是所有都必须以 hook 形式存在。当前状态：

| 门禁 | 状态 | 落点 |
|---|---|---|
| require-six-elements | 已实现（计划门禁） | `gate.py plan` + grill-me-with-doc |
| plan-schema-gate | 已实现 | `gate.py plan` |
| plan-change-regate | 已实现 | 计划 `scope_hash` 变更即失效 |
| task-package-gate | 已实现（CLI） | `task_packager.py --strict` / `gate.py task-package` |
| checklist-schema-gate | 已实现 | task_packager 验收项 id/expected/evidence_path |
| dependency-order-gate | 已实现（目录内） | task_packager `--tasks-dir` 断链/环/重复 + 依赖任务 status=done |
| model-route-gate | 已实现（任务包层） | sub-agent 模型白名单；Skill 允许语义 judgment，script/hook 必须 deterministic |
| external-write-deny | 已实现（PreToolUse 示例） | `gate.py external-write` + `approve` |
| public-owner-gate | 已实现（registry 层） | 七字段/依赖/路径 + `rules`/`skills/*/SKILL.md`/`agents`/`flows` 公共入口漏登记检测 |
| filelist-sync-gate | **未实现** | 公共库无 RTL；R1 要求等价人工检查，规则不因 hook 缺失失效 |
| acceptance-evidence-gate | 已实现 | `gate.py acceptance` |
| review-independence-gate | 已实现 | acceptance reviewer≠executor；B `review.json` |
| human-gate-verify | 部分实现 | 计划 scope_hash + 外发批准支持 SSH 签名；签名需人持私钥，未配置时为兼容模式；尚无 GitHub 事件级 allowlist |
| memory-write-gate | 部分实现 | `gate.py memory` 已校验 provenance/owner/来源/scope/raw/secret；尚未强制挂到所有 Write/MCP memory 写入 |
| context-watermark-gate | **未实现** | 需要 harness 提供实际使用率输入；当前只有提示注入 |
| subagent-output-gate | **未实现** | 需要 SubagentStop 接线与产物 schema |

未实现项明确标注为缺口，不以"文档已写"冒充已接线。`context-watermark-gate` 与
`subagent-output-gate` 需要 harness 级事件/字段，待确认可用 API 后再实现。
