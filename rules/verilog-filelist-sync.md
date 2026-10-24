---
name: verilog-filelist-sync
description: 模块内 Verilog 文件新增或更新时，在同一次变更中同步更新该模块的 filelist，并使清单与目录实际文件集合一致
asset_id: EA-20261022-02
ai_form: Rule
provenance_status: source-excerpt
dependency_status: partial (filelist hook 未实现；规则要求等价人工检查)
provenance_note: 摘自《AI 公共规范（v0.7 草案）》revision 5267 的强制规则清单，未逐条对照规范全文核验
paths:
  - "**/*.v"
---

# Verilog 文件变更同步 filelist

## 规则

新增或更新模块的 Verilog 文件时，必须在同一次变更中同步更新该模块的 filelist。

## 执行要求

1. **判定触发**：本次变更触及模块内任一 Verilog 文件的新增或更新时，执行本规则。
2. **同一次变更**：把 filelist 的更新与代码变更放在同一次变更里完成；不要拆成两次提交，也不要先提交代码、稍后补 filelist。
3. **清单一致**：让更新后的 filelist 与目录中实际存在的 Verilog 文件集合一致；把新增的 Verilog 文件登记进清单，把已不存在于目录的文件从清单中删除。
4. **提交前校验**：优先通过 filelist 一致性 hook 校验。当前公共组件库尚未提供该 hook，此时必须执行等价检查：列出目录中实际存在的 Verilog 文件集合与 filelist 的差异（新增/缺失/多余），把检查命令与结果写入交付说明。校验不通过时，先补齐 filelist 再提交，并视本次变更为未完成。
5. **判定不适用**：本次变更完全不涉及 Verilog 文件时（例如只改文档或脚本），不套用本规则。

## 完成标准

filelist 与目录实际文件集合一致，且有可复核的检查记录：

- 有 hook 时：hook 校验通过（记录 hook 名称/版本与 exit code）；
- 无 hook 时：人工或脚本等价检查通过，交付说明中包含检查命令与差异清单。

缺少检查记录，或检查不通过，均视为未完成。本规则不因 hook 缺失而失效。
