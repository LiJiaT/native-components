#!/bin/bash
# 用本机 Microsoft Excel 打开工作簿，全量重算公式并保存。
# openpyxl 只写公式字符串不算数，收件人需要看到数值时用本脚本补缓存值。
# 用法: bash recalc_with_excel.sh "/绝对路径/文件.xlsx"
# 首次运行 macOS 会弹「"终端/宿主"想要控制"Microsoft Excel"」授权框，点允许。
set -euo pipefail

FILE="${1:?用法: recalc_with_excel.sh <xlsx绝对路径>}"
if [ ! -f "$FILE" ]; then
  echo "文件不存在: $FILE" >&2
  exit 2
fi
case "$FILE" in
  *.xlsx|*.xlsm|*.xls) ;;
  *) echo "仅支持 .xlsx/.xlsm/.xls，收到: $FILE" >&2; exit 2 ;;
esac

osascript <<EOF
set f to POSIX file "$FILE"
tell application "Microsoft Excel"
    set display alerts to false
    open f
    set savedCalc to calculation
    set calculation to calculation automatic
    calculate active workbook
    save active workbook
    set calculation to savedCalc
    close active workbook
    set display alerts to true
end tell
EOF

echo "OK: 已由 Microsoft Excel 重算并保存 $FILE"
