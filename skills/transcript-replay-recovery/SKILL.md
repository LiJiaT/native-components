---
user-invocable: false
name: transcript-replay-recovery
description: 当曾由 Claude 编辑过的工作文件被意外覆盖、回退或损坏且没有 git 历史可恢复时使用：从 ~/.claude/projects 的 transcript JSONL 中挖掘全部 Edit/Write 调用，从已知基线按时间序重放重建文件，并经语法、标记、pyc 三层验证。
metadata:
  provenance: self-improving-skills
---

# transcript-replay-recovery — 从 session transcript 重放重建被覆盖的文件

曾由 Claude Edit/Write 编辑过的文件被外部覆盖/回退/损坏（并行会话、手动 cp、还原脚本等），而所在目录不在 git 管辖、无历史可 checkout 时，transcript JSONL 是唯一可用的"影子历史"：每次 Edit/Write 的完整 old/new 文本都存在 `message.content[]` 里 `type=tool_use` 的 input 中（file_path / old_string / new_string / content）。

## 挖掘与重放

1. **逐行先做字符串预过滤再 json.loads**：`if TARGET not in line: continue`。单条 transcript 可达 10–15MB，全量 loads 必然又慢又爆内存。
2. **glob 全部 \*.jsonl，不要只扫当前 session**——修复常跨多个 session；事件按 timestamp 全局排序后从基线开始重放。
3. **基线**：被覆盖前已知的任意版本（.orig/.bak/任何副本），或文件首次由 Write 创建时的 content。
4. **Edit 重放**：old 唯一 → `replace(old, new, 1)`；`replace_all` → 全换；old 不存在 → 记 NO-MATCH 跳过；出现多次且非 replace_all → 记 AMBIGUOUS 跳过。不要试图"模糊匹配"硬套。
5. **Write 是整文件覆盖**：默认拒绝采纳（会抹掉之前累积的 Edit），仅当其内容明显是更晚的版本（如已知修复标记更多）才当作新基线；每条的采纳/拒绝都打印，便于事后核查。
6. **输出到 `<file>.recovered`**，验证通过前绝不直接覆盖现文件。

## 三层验证（缺一不可）

1. **语法层**：`py_compile`（或对应语言的解析/编译）通过。
2. **标记层**：grep 已知修复的关键标记（端点、常量名、修复特征串），逐个确认在位。
3. **独立交叉层**：若有同文件的编译产物（.pyc），`marshal.loads(pyc_bytes[16:])` 跳过 header 后递归走 `co_consts` 比对字符串常量标记。注意整型字面量和变量名不在字符串常量里，缺失属预期，不要误判成恢复失败。

## 收尾核查

- 对每条 NO-MATCH / AMBIGUOUS：回 transcript 取完整 old/new，确认该修改是否已被后续等价编辑覆盖；是则不用手工补，否则单独补上。
- 全部验证通过后才覆盖工作文件，并留一份 `.bak-recovered`。
- 覆盖事故本身要向用户讲清（来源不明的覆盖必须声明"不是我改的"，并提示若是有意还原请说明）。

实测：2026-10-07 `paper_library_single_file.py` 被覆盖回 `.orig`（12+2 处修复全丢），5 个 transcript 共 42 条 Edit 重放 41 条成功，pyc 交叉验证 4/4 标记一致，恢复后流水线正常启动（session 80e7b1c1）。

<!-- 来源: session 80e7b1c1（2026-10-07 覆盖事故恢复）， 理由: 无 git 目录下 Claude 编辑过的文件被覆盖时，transcript 重放是唯一恢复路径；预过滤、Write 采纳判据、pyc 交叉验证均为实操踩出来的细节 -->
