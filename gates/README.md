# 确定性门禁（gates）

`gate.py` 是失败关闭的校验入口。**旁路通知 hook 可以 fail-open；本目录的门禁必须 fail-closed。**

## 子命令

| 命令 | 用途 | 失败语义 |
|---|---|---|
| `record --assets-repo <repo> --asset-id EA-...` | record 必填字段、状态、审批绑定、内容 hash | exit 1 |
| `asset-registry --assets-repo <repo>` | records / registry / INDEX / approvals 全量对账 | exit 1 |
| `component-registry --repo .` | 七字段、路径、依赖、循环、版本 | exit 1 |
| `plan --file plan.json [--require-approval]` | 计划六要素 + 人工批准 scope_hash | exit 1 |
| `acceptance --file acceptance.json --base-dir <dir>` | 逐项证据、verdict 重算、独立复核 | exit 1 |
| `external-write` | PreToolUse 外发拦截；默认 deny | JSON deny / exit 2 |
| `approve --command ... --by <人> --minutes 30` | 写入人工预批准（短期有效） | — |
| `memory --file <md> [--require-provenance]` | 原始记录 / 秘密 / provenance | exit 1 |
| `task-package --file <json> --strict [--tasks-dir]` | 调用 task_packager strict | exit 1 |
| `install --manifest <json>` | 安装 manifest 字段与组件完整性 | exit 1 |

所有判定写 `~/.claude/audit/gates.jsonl`（`AI_GATE_AUDIT_LOG` 可覆盖）。

## 挂接（settings.json 片段）

见 [`settings.example.json`](settings.example.json)（POSIX）与 [`settings.windows.example.json`](settings.windows.example.json)（Windows，含解释器绝对路径）。安装器把 `gate.py` 放到 `~/.claude/gates/gate.py`：

```bash
python tools/install.py --component gate-core --component component-schemas
```

`PreToolUse` 命中外部写命令时返回 `permissionDecision: deny`。人工预批准：

```bash
python ~/.claude/gates/gate.py approve --command "git push origin main" --by <你的名字> --minutes 30
```

批准按命令全文 hash 生效，30 分钟后自动失效；不同命令需分别批准。

## 16 类拟议门禁的落地状态

规范 §5.8 列出的 16 类 hook 是"可 Hook 化"的实现方式，不是所有都必须以 hook 形式存在。当前状态：

| 门禁 | 状态 | 落点 |
|---|---|---|
| require-six-elements | 已实现（计划门禁） | `gate.py plan` + grill-me-with-doc |
| plan-schema-gate | 已实现 | `gate.py plan` |
| plan-change-regate | 已实现 | 计划 `scope_hash` 变更即失效 |
| task-package-gate | 已实现（CLI） | `task_packager.py --strict` / `gate.py task-package` |
| checklist-schema-gate | 已实现 | task_packager 验收项 id/expected/evidence_path |
| dependency-order-gate | 已实现（目录内） | task_packager `--tasks-dir` 断链/环/重复 |
| model-route-gate | 已实现（任务包层） | sub-agent 模型白名单；确定性任务禁用模型 |
| external-write-deny | 已实现（PreToolUse 示例） | `gate.py external-write` + `approve` |
| public-owner-gate | 已实现（registry 层） | `component-registry` 要求 owner/version/interface/dependencies |
| filelist-sync-gate | **未实现** | 公共库无 RTL；R1 要求等价人工检查，规则不因 hook 缺失失效 |
| acceptance-evidence-gate | 已实现 | `gate.py acceptance` |
| review-independence-gate | 已实现 | acceptance reviewer≠executor；B `review.json` |
| human-gate-verify | 部分实现 | 审批文件/计划 scope_hash；尚无 GitHub 事件级 allowlist |
| memory-write-gate | 部分实现 | `gate.py memory` 可手动/CI 调用；尚未强制挂到所有 Write/MCP memory 写入 |
| context-watermark-gate | **未实现** | 需要 harness 提供实际使用率输入；当前只有提示注入 |
| subagent-output-gate | **未实现** | 需要 SubagentStop 接线与产物 schema |

未实现项明确标注为缺口，不以"文档已写"冒充已接线。`context-watermark-gate` 与
`subagent-output-gate` 需要 harness 级事件/字段，待确认可用 API 后再实现。
