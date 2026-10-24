---
name: no-raw-records-in-memory
description: 不把原始记录（会议原文、聊天记录、调试日志、命令输出、临时文件内容）写入长期记忆；长期记忆只写提炼后的结论并注明出处，便于回溯
asset_id: EA-20261022-06
ai_form: Rule
provenance_status: source-excerpt
provenance_note: 摘自《AI 公共规范（v0.7 草案）》revision 5267 的强制规则清单，未逐条对照规范全文核验
source_record: assets/20261022-1705-ai-public-rules/EA-20261022-06-no-raw-records-in-memory.md
release_channel: component-library
source_artifact: build/EA-20261022-06/artifacts/rule-no-raw-records-in-memory.md
source_artifact_sha256: 1670c92c5e5a214699f807c28e11b5d71f404a7ec249485b8bc665c4b1732545
source_revision: '5267'
distribution_note: 正文与实现产物一致；仅补充来源指针与当前 revision。
---
# 原始记录不得写入长期记忆

## 规则

不把原始记录写入长期记忆。写入长期记忆的每一段内容都写成提炼后的结论，并注明出处。

## 执行要求

1. **认准长期记忆载体**：会被长期保留、并能被后续任务读取的载体都按长期记忆处理，包括 CLAUDE.md、rules 文件、memory 条目与知识资产正文。
2. **认准原始记录**：会议原文与逐字稿、聊天记录、调试日志、命令输出、临时文件内容，一律不写入上述载体。
3. **按"结论 + 出处引用"写**：只写提炼后的结论（事实、要求、决策及其理由），并注明出处（材料名 + 日期或位置）；让结论可回溯到原始记录，而原始记录本身仍留在原载体。
4. **不留"先粘贴再补结论"的口子**：先把原始记录粘贴进正文、再补一句结论，同样属于违规；"只摘录一小段"不构成豁免。
5. **限定当次使用**：原始记录可以在当前任务或会话内作为工作输入使用，但不要沉淀为长期记忆。

## 完成标准

长期记忆载体的每一段内容都能回答"这是提炼后的结论吗"，原始记录仅以出处引用（材料名 + 日期/位置）形式出现。
