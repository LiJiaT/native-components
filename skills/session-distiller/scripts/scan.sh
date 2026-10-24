#!/bin/bash
# L0 筛选：扫描所有 session transcript，按蒸馏价值排序
# 用法: scan.sh [--project <slug前缀>] [--top N] [--days N] [--all]
#   --project  只扫项目目录名含该前缀的（如 -Users-<user>）
#   --top      只输出前 N 个（默认 20）
#   --days     只看最近 N 天修改的（默认不限）
#   --all      不过滤阈值，输出全部（默认只输出达标的）
set -euo pipefail
exec python3 - "$@" <<'PYEOF'
import sys, os, json, time, glob

# 入选阈值（DESIGN.md §4；参考 SIS 0.18.0 教训）
TH_TOOL_CALLS = 40
TH_FILE_EDITS = 3
TH_CORRECTIONS = 2
CORRECTION_WORDS = ["不对", "不是这样", "错了", "别用", "不要用", "actually", "wrong", "no, not that", "instead"]
EDIT_TOOLS = {'Write', 'Edit', 'NotebookEdit'}

args = sys.argv[1:]
project, top, days, show_all = None, 20, None, False
i = 0
while i < len(args):
    if args[i] == "--project": project = args[i+1]; i += 2
    elif args[i] == "--top": top = int(args[i+1]); i += 2
    elif args[i] == "--days": days = int(args[i+1]); i += 2
    elif args[i] == "--all": show_all = True; i += 1
    else: i += 1

base = os.path.expanduser("~/.claude/projects")
now = time.time()
rows = []
for d in sorted(os.listdir(base)):
    if project and project not in d: continue
    dpath = os.path.join(base, d)
    if not os.path.isdir(dpath): continue
    for f in glob.glob(os.path.join(dpath, "*.jsonl")):
        st = os.stat(f)
        if days and (now - st.st_mtime) > days * 86400: continue
        tool_calls = edits = corrections = 0
        first_user = ""
        with open(f, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                for b in (e.get("message") or {}).get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        tool_calls += 1
                        if b.get("name") in EDIT_TOOLS:
                            edits += 1
                if e.get("type") != "user" or e.get("isMeta"): continue
                c = e.get("message", {}).get("content")
                text = c if isinstance(c, str) else " ".join(
                    b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"
                ) if isinstance(c, list) else ""
                if not text or text.startswith(("<local-command", "<command-name", "<system-reminder")):
                    continue
                corrections += sum(1 for w in CORRECTION_WORDS if w.lower() in text.lower())
                if not first_user:
                    first_user = text[:80].replace("\t", " ").replace("\n", " ")
        qualified = tool_calls >= TH_TOOL_CALLS or edits >= TH_FILE_EDITS or corrections >= TH_CORRECTIONS
        score = tool_calls + edits * 10 + corrections * 20
        rows.append((score, qualified, os.path.basename(f)[:-6], d, time.strftime("%Y-%m-%d", time.localtime(st.st_mtime)), tool_calls, edits, corrections, first_user))

rows.sort(reverse=True)
print(f"{'score':>6}  {'session-id':<38} {'date':<10} {'tools':>5} {'edits':>5} {'corr':>4}  project / 首条用户消息")
shown = 0
for score, q, sid, proj, date, tc, ed, co, fu in rows:
    if not show_all and not q: continue
    if shown >= top: break
    flag = "" if q else "  (未达标)"
    print(f"{score:>6}  {sid:<38} {date:<10} {tc:>5} {ed:>5} {co:>4}  {proj} / {fu}{flag}")
    shown += 1
if shown == 0:
    print("(没有达标的 session；用 --all 查看全部)")
PYEOF
