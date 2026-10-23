---
asset_id: EA-20261022-09
ai_form: Memory
title: HBM3E 修复层级决策：选 stack-level
layer: 领域级
project: HBM
domains:
- DFT
- 设计
approved_date: '2026-10-22'
---

**背景**：HBM3E 堆叠 die 的 MBIST 修复覆盖率上不去，团队就修复动作放在哪一层发生争论——是由 controller 统一控制各 die 的修复资源，还是把修复下沉到 stack 内部完成。当时的环境前提是 V0.9 工具链（`bist_collars` 数量受限）、TSV 通道 repair 仅 2 个 spare row、PHY 侧修复粒度 1:4。

**选项与取舍**：方案 A 为 controller-level repair，由 controller 统一控制堆叠各 die 的修复资源，测试入口单一、控制集中；方案 B 为 stack-level repair，修复在 stack 内部完成，controller 只发起测试。最终选方案 B，判断依据三条：其一，可达性——PHY 侧 spare row 在 controller level 无法访问，方案 A 触达不到这部分修复资源，PHY 侧可修复单元形成覆盖率天花板，方案 A 在结构上就不成立；其二，协议一致性——stack-level 与 base die 的测试协议一致，不需要为 repair 额外引入一套跨层控制协议；其三，既有证据——此前 HBM3 项目走过 stack-level 这条路，修复覆盖率达到 98%+。放弃的是 controller-level 的集中控制与单一测试入口，换来的是对 PHY 侧 spare row 的真实可达性，以及与 base die 测试协议的一致性。

**证据与生效条件**：PHY 侧 spare row 在 controller level 不可访问（结构性限制）；stack-level 路径与 base die 测试协议一致；HBM3 项目 stack-level 实测修复覆盖率 98%+。本决策建立在「PHY 侧 spare row 必须由 stack 自身修复逻辑访问」这一结构前提上；若后续 PHY 修复资源、修复粒度（当前 1:4）或 controller 访问路径发生变化，需重新评估该前提是否仍成立，不得直接沿用本结论。**日期**：2026-10-20（HBM3E DFT debug 复盘会）。

<!-- 来源: asset EA-20261022-09, 2026-10-22 入库 -->
