#!/bin/bash
# SessionStart hook：有待确认的蒸馏候选时，注入提示让 Claude 提醒用户。
# 输出 hookSpecificOutput.additionalContext（无候选时静默）。
IDX="$HOME/.claude/self-evolve/staging/INDEX.md"
[ -f "$IDX" ] || exit 0
N=$(grep -c "| staged |" "$IDX" 2>/dev/null)
N=${N:-0}
[ "$N" -gt 0 ] || exit 0
LIST=$(grep "| staged |" "$IDX" | awk -F'|' '{printf "%s(%s) ", $2, $5}')
python3 -c '
import json, sys
n, lst = sys.argv[1], sys.argv[2]
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": f"[蒸馏待办] 暂存区有 {n} 条蒸馏候选待确认: {lst}。用户提及整理/确认蒸馏产物时，运行 session-distiller skill 的晋升流程（批准→写入→git commit→更新 INDEX）。"
    }
}))' "$N" "$LIST"
exit 0
