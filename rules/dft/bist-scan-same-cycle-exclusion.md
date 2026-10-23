---
name: bist-scan-same-cycle-exclusion
description: 在同时含 MBIST(bist) 与 scan 的 DFT 时序约束中，bist_en 与 scan_en 不得同周期拉高，必须周期级互斥；在 OCC 使能窗口内逐条检查
asset_id: EA-20261022-08
ai_form: Rule
---

# bist_en 与 scan_en 禁止同周期拉高

## 规则

在同时包含 MBIST（bist）与 scan 的 DFT 时序约束中，保持 `bist_en` 与 `scan_en` 周期级互斥：不要在同一周期同时拉高这两路使能。

## 适用范围

对 OCC（on-chip clock controller）切换窗口内需要并存 repair/MBIST 时钟与 scan 时钟的 DFT 设计，一律执行本条。来源场景是 HBM 堆叠 die 的 MBIST 修复，但该机制不依赖具体项目，按 DFT 设计范围执行，不要按项目名收窄。

## 违反后果

同周期拉高会让 repair clock 与 scan clock 在 OCC 期间发生冲突，导致该窗口内 bist 部分失效，表现为 MBIST 结果异常、修复覆盖率上不去。该症状与"修复算法有缺陷"高度相似，会把排查引向错误方向，代价是大量无效的 fault sim。

## 检查方式

1. 在 OCC 使能窗口内检查 `bist_en` / `scan_en` 波形，确认两者不存在同周期高电平重叠。
2. 新增或修改 DFT 时序约束时，把该互斥关系列为必检项，逐条确认。

## 边界

只约束"同周期拉高"，不禁止 bist 与 scan 在时间上分段使用；需要二者交替工作时，由 OCC 时序保证切换边界落在不同周期。
