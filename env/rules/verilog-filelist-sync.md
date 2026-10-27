---
name: verilog-filelist-sync
description: 模块内 Verilog 文件新增或更新时，在同一次变更中同步更新该模块的 filelist，并使清单与目录实际文件集合一致
asset_id: EA-20261022-02
ai_form: Rule
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
4. **提交前校验**：提交前通过 hook 对 filelist 与目录一致性的校验；校验不通过时，先补齐 filelist 再提交，并视本次变更为未完成。
5. **判定不适用**：本次变更完全不涉及 Verilog 文件时（例如只改文档或脚本），不套用本规则。

## 完成标准

hook 一致性校验通过，即为本规则的完成标准。
