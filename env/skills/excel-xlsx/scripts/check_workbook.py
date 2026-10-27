#!/usr/bin/env python3
"""检查 xlsx 工作簿的公式错误值和结构信息，交付前跑一遍。

用法: python3 check_workbook.py <文件.xlsx> [更多文件.xlsx ...]
退出码: 0 = 未发现错误值; 1 = 发现错误值或读取失败; 2 = 用法错误
"""
import re
import sys
from pathlib import Path

from openpyxl import load_workbook

ERROR_RE = re.compile(r"^#(REF!|DIV/0!|VALUE!|NAME\?|N/A|NULL!|NUM!)$")


def check(path: Path) -> int:
    print(f"\n=== {path.name} ===")
    try:
        wb_f = load_workbook(path, data_only=False)   # 公式视图
        wb_v = load_workbook(path, data_only=True)    # 缓存值视图
    except Exception as e:
        print(f"  [FAIL] 无法读取: {e}")
        return 1

    problems = []
    for sheet in wb_f.sheetnames:
        ws_f, ws_v = wb_f[sheet], wb_v[sheet]
        formulas = cached = missing_cache = errors = 0
        for row_f, row_v in zip(ws_f.iter_rows(), ws_v.iter_rows()):
            for cf, cv in zip(row_f, row_v):
                if isinstance(cf.value, str) and cf.value.startswith("="):
                    formulas += 1
                    if cv.value is None:
                        missing_cache += 1
                    elif isinstance(cv.value, str) and ERROR_RE.match(cv.value):
                        errors += 1
                        if errors <= 10:
                            print(f"  [错误值] {sheet}!{cf.coordinate}: {cf.value} -> {cv.value}")
                elif cf.value is not None and isinstance(cv.value, str) and ERROR_RE.match(cv.value):
                    # 静态单元格被存成了错误值（罕见但存在）
                    errors += 1
                    if errors <= 10:
                        print(f"  [错误值] {sheet}!{cf.coordinate}: {cv.value}")
        cached = formulas - missing_cache
        note = []
        if missing_cache:
            note.append(f"{missing_cache} 个公式无缓存值（未经 Excel/LibreOffice 重算，预览器里可能显示为空）")
        if ws_f.merged_cells.ranges:
            note.append(f"合并单元格 {len(ws_f.merged_cells.ranges)} 处")
        print(f"  [{sheet}] 公式 {formulas} 个（含缓存值 {cached}，错误 {errors}）"
              + (f"；{'；'.join(note)}" if note else ""))
        if missing_cache:
            problems.append(f"{sheet}: 有公式缺缓存值，建议跑 recalc_with_excel.sh")

    if wb_f.defined_names:
        print(f"  命名区域: {', '.join(list(wb_f.defined_names)[:10])}"
              + (" ..." if len(wb_f.defined_names) > 10 else ""))
    ext = getattr(wb_f, "_external_links", [])
    if ext:
        print(f"  [注意] 含 {len(ext)} 个外部链接，源文件移动后会断裂")

    if errors:
        print("  结论: 存在公式错误值，禁止直接交付")
        return 1
    if problems:
        for p in problems:
            print(f"  [提示] {p}")
    print("  结论: 无错误值")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    rc = 0
    for arg in sys.argv[1:]:
        p = Path(arg).expanduser()
        if not p.exists():
            print(f"文件不存在: {p}")
            rc = 1
            continue
        rc = check(p) or rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
