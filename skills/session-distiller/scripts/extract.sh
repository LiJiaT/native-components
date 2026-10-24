#!/bin/bash
# 三级视图提取（DESIGN.md §4）
# 用法:
#   extract.sh <session-id前缀> --level 1                     # 骨架：用户原话+助手结论
#   extract.sh <session-id前缀> --level 2 --from N --to M     # 序号窗口内的工具轨迹
#   extract.sh <session-id前缀> --level 3 --tool-id toolu_xx  # 按 tool_use_id 取完整调用+返回
#   extract.sh <session-id前缀> --level 3 --tool-id toolu_xx --full  # 不截断（受终端内存限制）
#   extract.sh --find <session-id前缀>                        # 只定位文件
set -euo pipefail
exec python3 - "$@" <<'PYEOF'
import sys, os, json, glob

args = sys.argv[1:]
sid = level = None
frm = to = None
tool_id = None
find_only = False
full = False
max_input, max_result = 4000, 20000
i = 0
while i < len(args):
    a = args[i]
    if a == "--level": level = int(args[i+1]); i += 2
    elif a == "--from": frm = int(args[i+1]); i += 2
    elif a == "--to": to = int(args[i+1]); i += 2
    elif a == "--tool-id": tool_id = args[i+1]; i += 2
    elif a == "--find": find_only = True; sid = args[i+1]; i += 2
    elif a == "--full": full = True; i += 1
    elif a == "--max-input": max_input = int(args[i+1]); i += 2
    elif a == "--max-result": max_result = int(args[i+1]); i += 2
    elif sid is None: sid = a; i += 1
    else: i += 1

base = os.path.expanduser("~/.claude/projects")
matches = sorted(glob.glob(os.path.join(base, "*", f"{sid}*.jsonl")),
                 key=os.path.getmtime, reverse=True)
if not matches:
    sys.exit(f"错误: 找不到 session {sid}")
if find_only:
    for m in matches: print(m)
    sys.exit(0)
path = matches[0]
if len(matches) > 1:
    print(f"# 注意: {len(matches)} 个匹配，使用最新: {path}\n", file=sys.stderr)

def bounded(text, limit, label):
    """保留上限但绝不静默截断：打印截断标记、原始大小与完整内容定位。"""
    text = str(text)
    if full or len(text) <= limit:
        return text
    return (text[:limit] +
            f"\n[TRUNCATED {label}: {len(text)} chars -> {limit}; "
            f"full content: transcript={path} tool_id={tool_id or '-'}; "
            f"use --full or --max-{label}={len(text)}]")

SKIP_PREFIX = ("<local-command", "<command-name", "<command-message", "<system-reminder")

def user_text(entry):
    c = entry.get("message", {}).get("content")
    if isinstance(c, str): return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""

def block_str(c, limit=None):
    if isinstance(c, str): s = c
    elif isinstance(c, list):
        s = "\n".join(b.get("text", json.dumps(b, ensure_ascii=False))
                      for b in c if isinstance(b, dict))
    else: s = json.dumps(c, ensure_ascii=False)
    return s if limit is None else s[:limit]

seq = 0
lines = open(path, encoding="utf-8", errors="ignore").readlines()

if level == 1:
    in_range = frm is not None
    for raw in lines:
        try: e = json.loads(raw)
        except Exception: continue
        t = e.get("type")
        if t not in ("user", "assistant"): continue
        if e.get("isSidechain"): continue  # 跳过子 agent 内部消息
        seq += 1
        if t == "user":
            if e.get("isMeta"): continue
            text = user_text(e).strip()
            if not text or text.startswith(SKIP_PREFIX): continue
            print(f"[{seq}] 👤 USER: {text[:1200]}")
        else:
            c = e.get("message", {}).get("content")
            texts = [b.get("text", "") for b in (c or [])
                     if isinstance(b, dict) and b.get("type") == "text"]
            text = "\n".join(x for x in texts if x).strip()
            if not text: continue
            print(f"[{seq}] 🤖 ASST: {text[:800]}")

elif level == 2:
    if frm is None: sys.exit("错误: --level 2 需要 --from/--to（L1 输出的序号范围）")
    to = to if to is not None else frm + 1
    for raw in lines:
        try: e = json.loads(raw)
        except Exception: continue
        t = e.get("type")
        if t not in ("user", "assistant"): continue
        if e.get("isSidechain"): continue
        seq += 1
        if not (frm <= seq <= to): continue
        if t == "assistant":
            for b in (e.get("message", {}).get("content") or []):
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    inp = json.dumps(b.get("input", {}), ensure_ascii=False)[:150]
                    tid = b.get("id", "")
                    print(f"[{seq}] 🔧 {b.get('name')} {inp}  (id={tid})")
        else:
            for b in (e.get("message", {}).get("content") or []):
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    flag = "❌ERR" if b.get("is_error") else "✅OK"
                    print(f"[{seq}]    ↳ {flag} {block_str(b.get('content'), 250)!r}")

elif level == 3:
    if not tool_id: sys.exit("错误: --level 3 需要 --tool-id")
    done_call = False
    for raw in lines:
        try: e = json.loads(raw)
        except Exception: continue
        if e.get("type") == "assistant":
            for b in (e.get("message", {}).get("content") or []):
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id") == tool_id:
                    print(f"=== TOOL CALL {tool_id} ===")
                    print(f"name: {b.get('name')}")
                    print("input:\n" + bounded(
                        json.dumps(b.get('input', {}), ensure_ascii=False, indent=2),
                        max_input, "input"))
                    done_call = True
        elif e.get("type") == "user" and done_call:
            for b in (e.get("message", {}).get("content") or []):
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") == tool_id:
                    print(f"\n=== RESULT ({'ERROR' if b.get('is_error') else 'OK'}) ===")
                    print(bounded(block_str(b.get("content")), max_result, "result"))
                    sys.exit(0)
    if not done_call: sys.exit(f"错误: 找不到 tool_use id={tool_id}")
else:
    sys.exit("用法见脚本头注释")
PYEOF
