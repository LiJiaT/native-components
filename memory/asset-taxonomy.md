---
asset_id: EA-20261022-01
ai_form: Memory
provenance_status: source-excerpt
provenance_note: 摘自《AI 公共规范（v0.7 草案）》revision 5267 的 1.2 节，未逐条对照规范全文核验
title: 资产分类体系：9 领域平铺 + 2 固定项目 + 四维正交
layer: 公共级
project: 无
domains: []
owner: AI 平台团队
source: AI 公共规范 §1.2/§3.4
scope: 公共级
approved_date: '2026-10-22'
source_record: assets/20261022-1705-decision-domain-taxonomy/EA-20261022-01-asset-domain-taxonomy.md
release_channel: component-library
source_artifact: build/EA-20261022-01/artifacts/memory-entry.md
source_artifact_sha256: dc9d0ea54edfdc1339bfe481a6b334a72dfdcb4bd70cb31aa2333ede2fccfda1
source_revision: '5267'
distribution_note: 正文与实现产物一致；仅补充来源指针与当前 revision。
---
**决策**：工程知识资产化体系的分类元数据采用自建结构——「9 个专业领域平铺 + 2 个固定项目 + 四维正交」，不引入外部知识收集项目的细粒度标签体系。**背景**：设计领域划分时，最初方案是复用外部知识收集项目（论文库、公众号、GitHub radar 三个项目共享）的统一标签体系——8 个顶层主题加 72 个子标签，期望收集端与资产治理端共用一套标签。

当时有两个选项。选项一是复刻外部统一标签体系：与收集侧天然一致，检索粒度最细。选项二是自建平铺结构：9 个专业领域（架构、设计、验证、时序、DFT、后仿、Firmware、模拟、后端）平铺；项目固定为 LPDDR6、HBM 两个；领域与项目正交，项目横跨多个领域、不做父子嵌套；资产维度四维正交——形态 ⊥ 领域 ⊥ 项目 ⊥ 层级。**取舍**：选方案二。外部体系是「知识收集视角」而不是「资产治理视角」，照其细分没有意义；72 个子标签粒度过细，维护成本高、owner 难以指派；细粒度子标签理论上检索更准，但检索收益不及维护成本；团队自定的平铺结构 owner 好指派、好演进。代价是让出细粒度检索精度，换取治理上的可维护与可演进。

**证据**：该 9 领域划分已写入《AI 公共规范 v0.5》1.2 节，2026-10-22 由团队负责人直接在文档中改定，属团队级既定结构。**日期**：2026-10-22，评审结论、最终决策与规范落定同日完成。

<!-- 来源: asset EA-20261022-01, 2026-10-22 入库 -->
