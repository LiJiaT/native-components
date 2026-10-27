---
name: excel-xlsx
description: Create, inspect, and edit Microsoft Excel workbooks and XLSX files with reliable formulas, dates, types, formatting, recalculation, and template preservation. Use this whenever the user mentions Excel, 工作簿, 表格, spreadsheets, or files ending in .xlsx, .xlsm, .xls, .csv, or .tsv — or asks to process, merge, summarize, or fill in tabular data, add formulas, fix broken formulas, or keep an existing workbook's formatting intact — even if they never say "Excel" explicitly.
---

# Excel / XLSX 工作簿操作

核心原则：**先判断这是哪种工作**。读数据做分析、保住一个活的工作簿、从零建一个模型，是三件不同的事，工具选择和交付标准都不同。

## 本机环境（macOS）

- `openpyxl`（3.1.5）已安装；`pandas` 未安装，需要做数据分析/透视类任务时先 `pip3 install pandas` 征得用户同意再装。
- 本机没有 LibreOffice，`openpyxl` 写入的公式**没有缓存值**——不含缓存的文件在 Numbers/部分预览器里可能显示为空。
- 公式重算通道：本机装有 Microsoft Excel，用捆绑脚本驱动它打开→全量重算→保存：
  ```bash
  bash scripts/recalc_with_excel.sh "/绝对路径/文件.xlsx"
  ```
  脚本会请求"控制 Microsoft Excel"的自动化授权，首次运行需用户点允许。

## 工具选择

- `pandas`：分析、重塑、CSV 式批量处理。它读的是值，不保格式——交付物是数据结论而不是文件时用它。
- `openpyxl`：涉及公式、样式、合并单元格、批注、工作簿结构或保留既有模板时用它。注意它**只写公式字符串，不做计算**。
- CSV/TSV 是纯数据交换格式，没有样式、多表、公式概念，不要把它当"简化版 Excel"处理。

## 核心规则

### 日期是带历史包袱的序列号

Excel 用序列号存日期，1900 日期系统含虚构的 1900-02-29，部分旧工作簿用 1904 系统。写日期一律用 `datetime` 对象配显式 `number_format`，不写字符串冒充日期——日期对了但显示格式不对，用户看到的仍是错的。

### 工作簿要"活"，就别把计算写死

- 派生结果写公式，不把 Python 算出的数硬编码进单元格。
- 公式引用参数单元格，不在公式里埋魔法数字。
- openpyxl 读到的缓存值可能是过期的，编辑后不要盲信。
- 复制/填充公式前先在 2-3 个代表单元格上验证：相对引用错位、跨表引用错 sheet、区域偏移一位，这些错误"看起来还能跑"。
- 交付标准是零公式错误：不允许留下 `#REF!`、`#DIV/0!`、`#VALUE!`、`#NAME?` 或循环引用。
- 模型类工作簿里，非显而易见的硬编码假设用批注或旁注写明，让下一个编辑者能审计。

### 交付前先保类型，再保结构

- 手机号、身份证号、长编号、前导零编号一律按文本存储；Excel 对超 15 位数字静默截断精度，这类损坏不可逆。
- 混合文本/数字列在读写两端都要显式处理。
- 既有模板优先于任何通用审美：保留 sheet 顺序、列宽、冻结窗格、筛选、打印设置、数据验证和视觉惯例，除非任务明确要求改。
- 合并区域只有左上角单元格存值；隐藏行列、命名区域、条件格式都可能承载业务逻辑，快速扫一眼看不出来。
- 新填充的单元格匹配周边已有样式，不要悄悄引入一套新视觉体系。

### 交付前重算并核验

1. 用 `scripts/check_workbook.py` 扫描错误值和结构变化。
2. 需要让收件人直接看到数值时，用 `scripts/recalc_with_excel.sh` 重算并保存。
3. 布局敏感的交付物，重算后让用户在 Excel 里过目一眼再定稿。

小心读模式：以"只取值"方式打开再保存，会把整个工作簿的公式压平成静态值，悄悄毁掉活模型。

## 常见陷阱

- 类型推断读入时把编号变数字、数字留成文本；列索引在不同工具间从 0 或 1 起算，差一位很常见。
- 单元格内换行需要 wrap text 才显示正常。
- 外部引用随源文件移动而断裂；旧格式工作簿的"密码保护"不是真的安全边界。
- `FILTER`、`XLOOKUP`、`SEQUENCE` 等新函数在旧版 Excel/WPS/Numbers 里会失败或降级。
- 筛选、条件格式、打印区域、数据验证被悄悄剥掉时，工作簿数值全对但交付仍是失败的。
- 大文件先考虑流式读取（`read_only=True`）、指定列和 dtype，整表载入容易内存失控或踩到大量补齐的空行。
