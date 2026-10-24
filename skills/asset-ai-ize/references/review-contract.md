# 实现评审契约（可供上下游调用的 review 接口）

本文件补齐技能 B 的 review 接口：谁审、审什么、输入输出是什么、拒绝如何表达。
适用于组件 owner、独立 reviewer、消费方与 CI；语义判断仍由 reviewer 负责，脚本只做
可确定性重算的部分。

## 1. 输入

reviewer 接收一个 build 目录（或一份打包后的 review bundle）：

| 输入 | 必填 | 说明 |
|---|---|---|
| `build-manifest.json` | 是 | schema v2；含 asset_id/proposal_id/layer/projects/domains/owner/provenance/install_target/release_channel |
| `artifacts/**` | 是 | 实际实现物；reviewer 必须按文件 hash 审，不接受"目录大概一样" |
| `tests/results.json` | 发布时必填 | 命令、exit_code、tested_at/tested_by、artifact_sha256 |
| `implementation.md` | 是 | 语义保持对照表、设计取舍 |
| `install.md` | 是 | 安装范围、目标路径、回滚步骤 |
| approved record | 是 | 由 `--assets-repo` 指向；reviewer 核对 record hash 与审批绑定 |

reviewer 不得修改 artifacts 或 record；发现问题只写 review 结论与拒绝原因。

## 2. 输出

在 build 目录写 `review.json`（机器可读）并同步 `review.md`（人读摘要）：

```json
{
  "schema_version": "1",
  "asset_id": "EA-20261022-02",
  "reviewer": "<独立 reviewer 标识>",
  "reviewer_role": "component owner / independent reviewer",
  "executor": "<执行方标识>",
  "independent": true,
  "decision": "approved | rejected | needs-revision",
  "reviewed_at": "2026-10-24",
  "artifact_sha256": {"规则文件.md": "<sha256>"},
  "checklist": [
    {"id": "record-binding", "result": "pass", "note": "record/审批 hash 匹配"},
    {"id": "scope", "result": "pass", "note": "install_target 与 layer 一致"},
    {"id": "semantics", "result": "pass", "note": "statement 每条都有承载位置"}
  ],
  "rejection_reasons": [],
  "basis": "审批依据/评审范围"
}
```

约束：

- `reviewer != executor`，且 `independent: true`；同一 run 自审不算独立复核。
- `artifact_sha256` 必须与当前 artifacts 完全一致；任何文件变化都要重新评审。
- `decision=approved` 要求所有 checklist 项 `result=pass`；拒绝时把逐项原因写进
  `rejection_reasons`（机器可读）和 `review.md`（人读）。
- 发布前运行 `validate_build.py --release`；`review.json` 不满足上述约束即失败。

## 3. checklist 来源

按顺序合并，去重后逐项执行：

1. approved record 的验收要求（record 正文/出处中的完成条件）；
2. `build-manifest.json.review.checklist`（若提供）；
3. 本契约的固定项：`record-binding`、`scope`、`artifact-metadata`、`sensitive-scan`、
   `syntax`、`semantics`、`consumer-test`；
4. 消费方追加项（如目标项目的加载验证）。

固定项均为可复验项；语义项由 reviewer 给出判断与证据位置，不要求脚本裁决。

## 4. 拒绝返回

拒绝不是异常，是合法结果：

- `decision: rejected`：存在 blocker 级问题（语义漂移、范围扩大、synthetic 进生产、
  secret、缺关键证据），不得合入/安装；
- `decision: needs-revision`：可修复问题，返回给执行方，修复后必须重新绑定 hash 再审；
- 实现不可行（ai_form 与内容矛盾、缺关键细节）→ 不走 review，返回 B 的 `mapping_issue`。

## 5. 消费方调用方式

下游（安装器、组件库 CI、项目侧）只消费 `review.json` + `tests/results.json` +
`validate_build.py --release` 的 exit code，不解析 `review.md` 的自然语言。
任何一项缺失或 hash 不匹配，视为未通过，不得安装/分发。
