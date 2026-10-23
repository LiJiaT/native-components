#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/.claude/skills/session-distiller/scripts"
printf '#!/bin/bash\nexit 0\n' > "$TMP/.claude/skills/session-distiller/scripts/worker.sh"
chmod +x "$TMP/.claude/skills/session-distiller/scripts/worker.sh"

# Case 1: 少于 10 个 tool_use 的 session 不应入队
SMALL="$TMP/small.jsonl"
printf '{"type":"user"}\n' > "$SMALL"
printf '{"session_id":"sess-small","transcript_path":"%s"}\n' "$SMALL" \
  | HOME="$TMP" bash "$DIR/../distill-enqueue.sh"
if [ -s "$TMP/.claude/self-evolve/queue/jobs.jsonl" ]; then
  echo "FAIL: session with <10 tool_use should be filtered out"
  exit 1
fi
echo "PASS: low-activity session is filtered out"

# Case 2: 达到 10 个 tool_use 的 session 应入队
BIG="$TMP/big.jsonl"
for i in $(seq 1 10); do printf '{"type":"tool_use","id":"t%d"}\n' "$i"; done > "$BIG"
printf '{"session_id":"sess-big","transcript_path":"%s"}\n' "$BIG" \
  | HOME="$TMP" bash "$DIR/../distill-enqueue.sh"
if ! grep -q '"session_id":"sess-big"' "$TMP/.claude/self-evolve/queue/jobs.jsonl"; then
  echo "FAIL: qualifying session was not enqueued"
  exit 1
fi
echo "PASS: qualifying session is enqueued"

# Case 3: staging 无候选时 notify 静默
mkdir -p "$TMP/.claude/self-evolve/staging"
out_empty=$(printf '{}' | HOME="$TMP" bash "$DIR/../distill-notify.sh")
if [ -n "$out_empty" ]; then
  echo "FAIL: notify should be silent without staged candidates, got: $out_empty"
  exit 1
fi
echo "PASS: notify is silent without staged candidates"

# Case 4: staging 有候选时 notify 输出提醒
printf '| cand-abc | skill | staged | 测试候选 |\n' > "$TMP/.claude/self-evolve/staging/INDEX.md"
out_staged=$(printf '{}' | HOME="$TMP" bash "$DIR/../distill-notify.sh")
if ! python3 -c 'import json,sys; d=json.load(sys.stdin); assert "蒸馏待办" in d["hookSpecificOutput"]["additionalContext"]' <<<"$out_staged"; then
  echo "FAIL: notify did not emit staged reminder, got: $out_staged"
  exit 1
fi
echo "PASS: notify emits staged reminder"
