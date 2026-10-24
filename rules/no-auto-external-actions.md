---
name: no-auto-external-actions
description: AI 不自动执行对外上传、推送、提交、发布或外发；对外动作一律由人确认后执行，且不得绕过权限与 hook 拦截
asset_id: EA-20261022-03
ai_form: Rule
provenance_status: source-excerpt
provenance_note: 摘自《AI 公共规范（v0.7 草案）》revision 5267 的强制规则清单，未逐条对照规范全文核验
source_record: assets/20261022-1705-ai-public-rules/EA-20261022-03-no-auto-external-actions.md
release_channel: component-library
source_artifact: build/EA-20261022-03/artifacts/rule-no-auto-external-actions.md
source_artifact_sha256: d137895eaa7ce26cd4306397435b998bf3b464a414ef3befcc777a6556bacb6c
source_revision: '5267'
distribution_note: 2026-10-24 owner 批准分发适配：G 补充 gate 预批准与动作后日志说明；资产语义不变，I 实现仍以 R3 完成标准为准。
---
# 对外动作必须由人确认后执行

## 规则

不自动执行任何对外动作；所有对外动作在人确认后执行。

## 执行要求

1. **按范围识别对外动作**：把向对外仓库上传、推送或提交（含 git push、创建或合并 PR）、对外发布、向外部系统或外部人员发送材料与数据，一律按对外动作处理。
2. **先取得人的确认**：可以准备变更、命令与说明；执行对外动作前取得人的明确确认，未获确认一律不执行。
3. **不绕过拦截**：保持权限与 hook 的双重拦截开启。公共组件库提供 `gates/gate.py external-write` 作为 PreToolUse 拦截器：命中 `git push`、PR/Release、发布、远程复制、HTTP 写请求等模式时默认拒绝；人工预批准（`gates/gate.py approve --command ... --by <人>`）后方可放行。不要为完成动作而修改权限配置、关闭 hook，或改用其他通道绕过拦截。被拦截时如实报告，交人处理。
4. **按结果判定边界**：凡动作结果会离开本地或团队内部环境（对外仓库、外部系统、外部人员），即按对外动作处理；不要因"只是一次 push""只是同步一下"而降级处理。

## 完成标准

对外动作同时满足：

1. 存在人的明确确认记录（批准人、时间、命令/范围）；
2. 拦截器未被绕过（settings 未删除 PreToolUse 规则，未使用其他通道规避）；
3. 动作执行后保留可追溯记录（命令、结果、目标仓库/系统）。

缺少任一项，视为未完成或违规。
