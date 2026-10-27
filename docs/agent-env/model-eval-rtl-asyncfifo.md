---
name: model-eval-rtl-asyncfifo
description: 模型质量/Token/耗时标准测试用例（异步 FIFO RTL 生成）的位置、判据与首轮结论
metadata: 
  node_type: memory
  type: project
  originSessionId: d740de14-e373-487a-9865-0da055c16504
  modified: 2026-10-17T16:30:08.194Z
---

用户的标准模型测试用例（2026-10-17 建）：`~/model-eval/rtl-async-fifo/`。输入 = GitHub 公开课程 HLDS spec（含故意保留的原文矛盾）+ 固定 prompt；判据 = iverilog lint + 共享功能 TB（556 读/10 阻塞写）+ 矛盾识别 + token/耗时。运行器 `stream_eval.py <model> <label> [max_tokens] [temp]`（长生成必须流式）。

首轮结论：DeepSeek-V4.1-Flash 3/3 稳定完成（22–29k tok / 92–131s / 全过仿真）；GLM-5.3 需 128k 满额预算才完成（55k tok / 593s），65k 预算下思考失控整段白烧。详细数据见该目录 REPORT.md；模型行为差异已沉淀进 llm-access skill。

**How to apply:** 后续换新模型（或方舟同步 1017 快照后）用同一用例跑对比；跑前看 [[volces-ark-config]] 与 llm-access skill 的坑清单。
