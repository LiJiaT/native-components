#!/bin/bash
# SessionEnd hook：把 session 排入蒸馏队列。必须快（默认超时 1.5s），不做任何统计。
# stdin JSON: {session_id, transcript_path, cwd, hook_event_name, reason}
input=$(cat)
eval "$(python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
sid = str(d.get("session_id", "")).replace("\"", "")
tp  = str(d.get("transcript_path", "")).replace("\"", "")
print(f"SID={sid}")
print(f"TP={tp}")
' 2>/dev/null <<<"$input")" || exit 0
[ -n "$SID" ] || exit 0
[ -f "$TP" ] || exit 0

# 廉价预过滤：工具调用 < 10 的会话（如蒸馏 worker 自己的内层 claude -p）不入队，
# 防止自指入队烧掉每日预算。grep 计数 10MB 级文件 <100ms。
TOOLN=$(grep -c '"type":"tool_use"' "$TP" 2>/dev/null || echo 0)
[ "$TOOLN" -ge 10 ] || exit 0

Q="$HOME/.claude/self-evolve/queue"
mkdir -p "$Q"
printf '{"session_id":"%s","transcript_path":"%s","enqueued_at":%s}\n' \
    "$SID" "$TP" "$(date +%s)" >> "$Q/jobs.jsonl"

# fire-and-forget 拉起 worker；worker 内部用 mkdir 原子锁自旋去重
nohup "$HOME/.claude/skills/session-distiller/scripts/worker.sh" >> "$Q/worker.log" 2>&1 &
exit 0
