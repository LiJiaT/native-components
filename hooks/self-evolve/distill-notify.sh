#!/bin/bash
# SessionStart hook：
#   1) 若 queue/HOLD 存在且有任务，尝试唤醒 worker（跨日预算恢复）；
#   2) 有 staged 候选时注入提醒（无候选时静默）。
# 旁路通知失败不得阻塞会话。
SE="$HOME/.claude/self-evolve"
Q="$SE/queue"
IDX="$SE/staging/INDEX.md"

if [ -f "$Q/HOLD" ] && [ -s "$Q/jobs.jsonl" ]; then
  WORKER="$HOME/.claude/skills/session-distiller/scripts/worker.sh"
  [ -f "$WORKER" ] && nohup bash "$WORKER" >> "$Q/worker.log" 2>&1 &
fi

[ -f "$IDX" ] || exit 0
N=$(grep -c "| staged |" "$IDX" 2>/dev/null || true)
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
}))' "$N" "$LIST" || true
exit 0
