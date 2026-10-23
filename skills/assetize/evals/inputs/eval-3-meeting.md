<!--
来源：Claude Code 旧 session a084969d-f319-4aec-bd1b-960de997d1c5 的 transcript（...\D--Project\a084969d-f319-4aec-bd1b-960de997d1c5.jsonl）第 321 行；该行 assistant 消息内 Agent tool_use，id=call_8ed9dfba8278472b8dde8ca3，description="测试3：会议纪要资产化"。同一 prompt 在 subagents/agent-a57ef44f0d6d382e1.jsonl 第 1 行 user 消息中可见。
截取边界：仅取该 prompt 第 2 步「输入材料（纯文本，会议纪要/debug 记录类）：」之后、一对 --- 定界符之间的纪要正文（含标题与第 1–5 条）；已剔除角色说明、执行步骤 1/3/4/5、输出路径、validate 命令、返回格式等包装。
说明：第 5 条「其他讨论：下周团建去哪儿没定，改天再说」属于原始材料中的无关干扰项，按原文完整保留，未删改。
-->

会议纪要 2026-10-20 HBM3E DFT debug 复盘
参加人：DFT 组、验证组
议题：HBM 堆叠 die 的 MBIST 修复覆盖率上不去的问题

1. 环境现状：当前用 V0.9 工具链，bist_collars 数量受限，HBM TSV 通道 repair 只有 2 个 spare row，PHY 侧修复粒度 1:4。
2. debug 过程回顾：一开始怀疑是修复算法问题，跑了一周 fault sim 没结论；后来发现是 repair clock 和 scan clock 有冲突，OCC 期间 bist 部分失效。结论：HBM 的 DFT 时序约束里 bist_en 与 scan_en 不能同周期拉高。
3. 决策：controller-level repair 还是 stack-level repair 争论后定了 stack-level。理由：PHY 侧 spare row 在 controller level 无法访问；stack-level 与 base die 测试协议一致，之前 HBM3 项目验证过这条路（修复覆盖率 98%+）。
4. 行动项：把 bist_en/scan_en 冲突约束写进 DFT 时序 checklist；coding standard 第 5 章同步更新。
5. 其他讨论：下周团建去哪儿没定，改天再说。
