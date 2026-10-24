#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# Windows Python 不认 MSYS 的 /tmp 路径；HOME 必须传原生路径
if command -v cygpath >/dev/null 2>&1; then TMP_HOME="$(cygpath -w "$TMP")"; else TMP_HOME="$TMP"; fi
export HOME="$TMP_HOME" USERPROFILE="$TMP_HOME"
mkdir -p "$TMP/.claude/skills/session-distiller/scripts"
printf '#!/bin/bash\nexit 0\n' > "$TMP/.claude/skills/session-distiller/scripts/worker.sh"

Q="$TMP/.claude/self-evolve/queue"
J="$Q/jobs.jsonl"
queue_text() { [ -f "$J" ] && cat "$J"; [ -d "$Q/inbox" ] && cat "$Q"/inbox/*.json 2>/dev/null; }
last_transcript=""

# 生成 transcript：$1=路径 $2=tool 数 $3=tool 名
make_transcript() {
  python3 - "$1" "$2" "$3" <<'PY'
import json, sys
path, n, name = sys.argv[1], int(sys.argv[2]), sys.argv[3]
lines = [json.dumps({"type": "user", "message": {"content": "do it"}})]
for i in range(n):
    lines.append(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": f"t{i}", "name": name, "input": {"x": i}}]}}))
open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
PY
}

winpath() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }
enqueue() { # $1=session id $2=path
  local tp; tp="$(winpath "$2")"
  python3 -c 'import json,sys; print(json.dumps({"session_id": sys.argv[1], "transcript_path": sys.argv[2]}))' \
    "$1" "$tp" | bash "$DIR/../distill-enqueue.sh"
}

# Case 1: 低活跃 session 不应入队
SMALL="$TMP/small.jsonl"; printf '{"type":"user","message":{"content":"hi"}}\n' > "$SMALL"
enqueue sess-small "$SMALL"
if [ -n "$(queue_text)" ]; then echo "FAIL: low-activity session should be filtered"; exit 1; fi
echo "PASS: low-activity session is filtered out"

# Case 2: 40 个 tool_use（单行多工具、JSON 带空格）应入队
BIG="$TMP/big.jsonl"
python3 - "$BIG" <<'PY'
import json, sys
msg = {"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": f"t{i}", "name": "Read", "input": {}} for i in range(40)]}}
open(sys.argv[1], "w", encoding="utf-8").write(
    json.dumps({"type": "user", "message": {"content": "go"}}) + "\n" +
    json.dumps(msg, indent=None) + "\n")
PY
enqueue sess-big "$BIG"
queue_text | grep -q '"session_id": "sess-big"' || { echo "FAIL: qualifying session not enqueued"; exit 1; }
echo "PASS: 40 tools in one spaced-JSON line is enqueued"

# Case 3: 只有 3 次 Edit 也应入队（L0 OR 条件）
EDITS="$TMP/edits.jsonl"; make_transcript "$EDITS" 3 Edit
enqueue sess-edits "$EDITS"
queue_text | grep -q '"session_id": "sess-edits"' || { echo "FAIL: 3 edits should qualify"; exit 1; }
echo "PASS: edits-only session is enqueued"

# Case 4: Windows 反斜杠/空格路径原样入队
SPACE="$TMP/dir with space/t.jsonl"; mkdir -p "$(dirname "$SPACE")"
make_transcript "$SPACE" 40 Read
enqueue sess-space "$SPACE"
queue_text > "$TMP/queue-snapshot.jsonl"
python3 - "$TMP/queue-snapshot.jsonl" "$(winpath "$SPACE")" <<'PY' || { echo "FAIL: space/windows path not preserved"; exit 1; }
import json, os, sys
want = os.path.normcase(os.path.abspath(sys.argv[2]))
for line in open(sys.argv[1], encoding="utf-8"):
    if json.loads(line).get("session_id") == "sess-space":
        got = os.path.normcase(os.path.abspath(json.loads(line)["transcript_path"]))
        assert got == want, (got, want)
        sys.exit(0)
raise SystemExit(1)
PY
echo "PASS: space/backslash path is preserved"

# Case 5: session_id 中的 shell 元字符只当数据
MARKER="$TMP/eval-marker.txt"
enqueue 'safe; printf X > '"$MARKER" "$BIG"
[ ! -e "$MARKER" ] || { echo "FAIL: enqueue evaluated input as shell code"; exit 1; }
echo "PASS: enqueue never evaluates input"

# Case 6: staging 无候选时 notify 静默
mkdir -p "$TMP/.claude/self-evolve/staging"
out_empty=$(printf '{}' | bash "$DIR/../distill-notify.sh")
[ -z "$out_empty" ] || { echo "FAIL: notify should be silent, got: $out_empty"; exit 1; }
echo "PASS: notify is silent without staged candidates"

# Case 7: staging 有候选时 notify 输出提醒
printf '| cand-abc | skill | staged | 测试候选 |\n' > "$TMP/.claude/self-evolve/staging/INDEX.md"
out_staged=$(printf '{}' | bash "$DIR/../distill-notify.sh")
python3 -c 'import json,sys; d=json.load(sys.stdin); assert "蒸馏待办" in d["hookSpecificOutput"]["additionalContext"]' <<<"$out_staged" \
  || { echo "FAIL: notify did not emit staged reminder: $out_staged"; exit 1; }
echo "PASS: notify emits staged reminder"
