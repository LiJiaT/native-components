#!/bin/bash
# 后台蒸馏 worker：消费 queue/jobs.jsonl
# 围栏设计（DESIGN.md §7 二期）：内部 claude -p 只读（Read/Grep/蒸馏脚本），不写盘；
# 解析其 JSON 输出后由本脚本（外围，全权限）写 staging —— 写路径天然受限。
# 环境变量: WORKER_DRY_RUN=1 只做判定不真正调模型；DISTILLER_MODEL 覆盖模型；MAX_JOBS_PER_DAY 默认 3
set -uo pipefail
SELF_EVOLVE="$HOME/.claude/self-evolve"
Q="$SELF_EVOLVE/queue"
SKILL_SCRIPTS="$HOME/.claude/skills/session-distiller/scripts"
LOCK="$Q/.worker.lock"
mkdir "$LOCK" 2>/dev/null || exit 0          # 已有 worker 在跑，直接退出
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

JOBS="$Q/jobs.jsonl"
[ -s "$JOBS" ] || exit 0
MAX_PER_DAY="${MAX_JOBS_PER_DAY:-3}"
TODAY=$(date +%Y-%m-%d)
CNTF="$Q/count-$TODAY"
CNT=$(cat "$CNTF" 2>/dev/null || echo 0)

# 阈值（DESIGN.md §4，与 scan.sh 一致）
TH_TOOL_CALLS=40; TH_FILE_EDITS=3; TH_CORRECTIONS=2
export TH_TOOL_CALLS TH_FILE_EDITS TH_CORRECTIONS

log(){ echo "[$(date '+%F %T')] $*" >> "$Q/worker.log"; }

# --- 用 python 做统计+判定+claude 调用+产物写入 ---
python3 - "$JOBS" "$SELF_EVOLVE" "$SKILL_SCRIPTS" "$CNT" "$MAX_PER_DAY" <<'PYEOF'
import sys, os, json, time, subprocess, re, glob

jobs_file, se, scripts, cnt, max_per_day = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
dry = os.environ.get("WORKER_DRY_RUN") == "1"
TH = (int(os.environ["TH_TOOL_CALLS"]), int(os.environ["TH_FILE_EDITS"]), int(os.environ["TH_CORRECTIONS"]))
CORR = ["不对", "不是这样", "错了", "别用", "不要用", "actually", "wrong", "no, not that", "instead"]
EDITS = ('"name":"Write"', '"name":"Edit"', '"name":"NotebookEdit"')
def log(m): print(f"[{time.strftime('%F %T')}] {m}")

def stats(path):
    raw = open(path, encoding="utf-8", errors="ignore").read()
    tool_calls = raw.count('"type":"tool_use"')
    edits = sum(raw.count(t) for t in EDITS)
    corr = 0
    for line in raw.splitlines():
        try: e = json.loads(line)
        except Exception: continue
        if e.get("type") != "user" or e.get("isMeta"): continue
        c = e.get("message", {}).get("content")
        text = c if isinstance(c, str) else " ".join(
            b.get("text","") for b in c if isinstance(b,dict) and b.get("type")=="text") if isinstance(c,list) else ""
        if not text or text.startswith(("<local-command","<command-name","<system-reminder")): continue
        corr += sum(1 for w in CORR if w.lower() in text.lower())
    return tool_calls, edits, corr

def is_meta_session(path):
    """蒸馏 meta-session 识别（cand-e7091e）：本 worker 起的 claude -p 会话首条 user
    消息即蒸馏 PROMPT，其产生的 Bash 调用会虚高达标，重蒸自身纯浪费配额。"""
    for line in open(path, encoding="utf-8", errors="ignore"):
        try: e = json.loads(line)
        except Exception: continue
        if e.get("type") != "user" or e.get("isMeta"): continue
        c = e.get("message", {}).get("content")
        text = c if isinstance(c, str) else " ".join(
            b.get("text","") for b in c if isinstance(b,dict) and b.get("type")=="text") if isinstance(c,list) else ""
        if not text or text.startswith(("<local-command","<command-name","<system-reminder")): continue
        return ("会话蒸馏" in text) or ("extract.sh" in text and "--level" in text)
    return False

PROMPT = """你在做会话蒸馏。用 Bash 运行 {scripts}/extract.sh {sid} --level 1 查看会话骨架（禁止直接读 transcript 原文件，禁止读 projects 下任何 jsonl 全文）。
对值得深入的小段用 --level 2 --from N --to M 看工具轨迹。最多 3 次 L2 调用。
然后判断本次会话有无值得沉淀的可复用经验（多步流程/反复出现的纠错/环境事实）。
输出且只输出一个 JSON 数组（无其他文字、无 markdown 围栏），每条:
{{"lane": "skill|rules|claude-md|hooks|memory", "title": "一句话", "content": "完整内容（skill 要含步骤；若值得建 skill 给出建议 name 和 description）", "reason": "一句话理由"}}
没有值得沉淀的就输出 []。"""

remaining = []
for line in open(jobs_file, encoding="utf-8"):
    line = line.strip()
    if not line: continue
    try: job = json.loads(line)
    except Exception: continue
    sid, tp = job.get("session_id",""), job.get("transcript_path","")
    if not tp or not os.path.exists(tp):
        log(f"skip {sid[:8]}: transcript 缺失"); continue
    if is_meta_session(tp):
        log(f"skip {sid[:8]}: 蒸馏 meta-session，不参与判定"); continue
    tc, ed, co = stats(tp)
    qualified = tc >= TH[0] or ed >= TH[1] or co >= TH[2]
    if not qualified:
        log(f"skip {sid[:8]}: 未达标 (tools={tc} edits={ed} corr={co})"); continue
    if cnt >= max_per_day and not dry:
        log(f"hold {sid[:8]}: 今日已蒸馏 {cnt}/{max_per_day}，保留在队列"); remaining.append(job); continue
    if dry:
        log(f"DRY {sid[:8]}: 达标 (tools={tc} edits={ed} corr={co})，将调模型蒸馏"); continue
    model = os.environ.get("DISTILLER_MODEL")
    cmd = ["claude", "-p", PROMPT.format(scripts=scripts, sid=sid),
           "--allowedTools", "Read", "Grep", f"Bash({scripts}/*)",
           "--max-turns", "40", "--permission-mode", "default"]
    if model: cmd += ["--model", model]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=1800).stdout
    except Exception as e:
        log(f"error {sid[:8]}: claude -p 失败 {e}"); remaining.append(job); continue
    m = re.search(r"\[.*\]", out, re.S)
    if not m:
        log(f"warn {sid[:8]}: 无 JSON 输出，保留在队列"); remaining.append(job); continue
    try: cands = json.loads(m.group(0))
    except Exception:
        log(f"warn {sid[:8]}: JSON 解析失败，保留在队列"); remaining.append(job); continue
    # 快照围栏：只允许写 staging
    stag = os.path.join(se, "staging")
    idx_path = os.path.join(stag, "INDEX.md")
    ids = ["cand-" + os.urandom(3).hex() for _ in cands[:5]]
    for cid, c in zip(ids, cands[:5]):
        with open(os.path.join(stag, cid + ".md"), "w") as f:
            f.write(f"""---
id: {cid}
created: {time.strftime('%F')}
source_sessions: ["{sid}"]
user: {os.environ.get('USER','')}
scope: user
lane: {c.get('lane','memory')}
status: staged
supersedes: null
recurrence: 1
---
{c.get('title','')}
{c.get('content','')}
<!-- 理由: {c.get('reason','')} -->
""")
    with open(idx_path, "a") as f:
        for cid_, c in zip(ids, cands[:5]):
            f.write(f"| {cid_} | {c.get('lane','')} | staged | {c.get('title','')[:40]} |\n")
    cnt += 1
    log(f"ok {sid[:8]}: 蒸馏出 {len(cands[:5])} 条候选 → staging（今日 {cnt}/{max_per_day}）")

with open(jobs_file, "w") as f:
    for job in remaining:
        f.write(json.dumps(job) + "\n")
open(os.path.join(os.path.dirname(jobs_file), f"count-{time.strftime('%Y-%m-%d')}"), "w").write(str(cnt))
PYEOF
