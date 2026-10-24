#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后台蒸馏 worker：消费 ~/.claude/self-evolve/queue/jobs.jsonl。

可靠性约定：
  - 队列 append-only；worker 在共享锁内做快照与最终压缩，producer 也持同一把锁，
    因此不会出现"读到旧队列后覆盖掉新任务"。
  - 模型子进程必须 returncode=0 且输出为合法 JSON 数组才计成功；失败保留任务，
    记录 stderr，连续失败 3 次进 dead-letter，不伪装成"没有资产"。
  - dry-run 不调模型、不改队列、不写 staging、不消耗预算。
  - 游标绑定 transcript 的路径/大小/mtime/sha256，已蒸馏且未变化的会话不重复处理。
  - 候选落盘前做 lane/非空/秘密/原始记录检查；候选 ID 由内容 hash 决定，重复出现
    时累加 recurrence 而不是生成重复候选。

环境变量：
  WORKER_DRY_RUN=1        dry-run
  MAX_JOBS_PER_DAY=3      每日成功蒸馏上限
  DISTILLER_MODEL=...     覆盖 claude 模型
  DISTILLER_CMD=/path.py  测试用：python 脚本，prompt 从 stdin 读、stdout 输出 JSON 数组
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

HOME = Path.home()
SELF_EVOLVE = HOME / ".claude" / "self-evolve"
QUEUE = SELF_EVOLVE / "queue"
STAGING = SELF_EVOLVE / "staging"
STATE_DIR = SELF_EVOLVE / "distill-state"
SKILL_SCRIPTS = HOME / ".claude" / "skills" / "session-distiller" / "scripts"
JOBS = QUEUE / "jobs.jsonl"
INDEX = STAGING / "INDEX.md"
LOCK = QUEUE / ".worker.lock"
HOLD = QUEUE / "HOLD"
TH_TOOLS, TH_EDITS, TH_CORR = 40, 3, 2
CORR_WORDS = ["不对", "不是这样", "错了", "别用", "不要用", "actually", "wrong",
              "no, not that", "instead"]
EDIT_TOOLS = {"Write", "Edit", "NotebookEdit"}
LANES = {"skill", "rules", "claude-md", "hooks", "memory"}
SECRET_PATTERNS = [
    re.compile(r"\b(ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"(?i)(password|passwd|pwd|api[_-]?key|secret|token)\s*[:=]\s*\S{6,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
RAW_PATTERNS = [
    re.compile(r"^\s*\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s+"
               r"(?:DEBUG|TRACE|INFO|WARN(?:ING)?|ERROR|FATAL)\b", re.I),
    re.compile(r"^\s*(?:Speaker\s*[A-Z0-9]+|说话人\s*[A-Z0-9一二三四五六七八九十]+)\s*[:：]", re.I),
]
PROMPT = """你在做会话蒸馏。用 Bash 运行 {scripts}/extract.sh {sid} --level 1 查看会话骨架（禁止直接读 transcript 原文件，禁止读 projects 下任何 jsonl 全文）。
对值得深入的小段用 --level 2 --from N --to M 看工具轨迹。最多 3 次 L2 调用。
然后判断本次会话有无值得沉淀的可复用经验（多步流程/反复出现的纠错/环境事实）。
输出且只输出一个 JSON 数组（无其他文字、无 markdown 围栏），每条:
{{"lane": "skill|rules|claude-md|hooks|memory", "title": "一句话", "content": "完整内容（skill 要含步骤；若值得建 skill 给出建议 name 和 description）", "reason": "一句话理由"}}
没有值得沉淀的就输出 []。"""


def log(msg):
    try:
        QUEUE.mkdir(parents=True, exist_ok=True)
        with open(QUEUE / "worker.log", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%F %T')}] {msg}\n")
    except Exception:
        pass


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text")
    return ""


def analyze(path):
    tools = edits = corr = 0
    first_user = ""
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            content = (event.get("message") or {}).get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tools += 1
                        if block.get("name") in EDIT_TOOLS:
                            edits += 1
            if event.get("type") == "user" and not event.get("isMeta"):
                text = text_of(content)
                if not first_user and text and not text.startswith(
                        ("<local-command", "<command-name", "<system-reminder")):
                    first_user = text
                if text and not text.startswith(("<local-command", "<command-name",
                                                 "<system-reminder")):
                    corr += sum(1 for w in CORR_WORDS if w.lower() in text.lower())
    return tools, edits, corr, first_user


def is_meta(first_user):
    return ("会话蒸馏" in first_user) or ("extract.sh" in first_user and "--level" in first_user)


def scan_secret(text):
    return [p.pattern for p in SECRET_PATTERNS if p.search(text)]


def scan_raw(text):
    return sum(1 for line in text.splitlines() if any(p.search(line) for p in RAW_PATTERNS))


def _lock(fh, blocking=True):
    if os.name == "nt":
        import msvcrt
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX if blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB))


def _unlock(fh):
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass


class WorkerLock:
    """目录锁 + owner 元数据；陈旧锁（PID 不存在或超时）可安全恢复。"""
    def __init__(self, path, stale_seconds):
        self.path = Path(path)
        self.stale = stale_seconds
        self.owner_file = self.path / "owner.json"
        self.acquired = False

    def _owner(self):
        try:
            return json.load(open(self.owner_file, encoding="utf-8"))
        except Exception:
            return None

    def _alive(self, owner):
        if not owner:
            return False
        if owner.get("host") != socket.gethostname():
            return time.time() - float(owner.get("started_at", 0)) < self.stale
        pid = int(owner.get("pid", -1))
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except OSError:
            return False

    def acquire(self):
        for _ in range(2):
            try:
                self.path.mkdir(parents=True)
                atomic_write(self.owner_file, json.dumps({
                    "pid": os.getpid(), "host": socket.gethostname(),
                    "started_at": time.time()}, ensure_ascii=False))
                self.acquired = True
                return True
            except FileExistsError:
                owner = self._owner()
                age = time.time() - float((owner or {}).get("started_at", 0))
                if self._alive(owner) and age < self.stale:
                    return False
                log(f"recover stale lock: {owner} age={age:.0f}s")
                shutil.rmtree(self.path, ignore_errors=True)
        return False

    def release(self):
        if not self.acquired:
            return
        owner = self._owner() or {}
        if int(owner.get("pid", -1)) == os.getpid():
            shutil.rmtree(self.path, ignore_errors=True)
        self.acquired = False


def read_jobs():
    jobs = []
    if not JOBS.exists():
        return jobs
    for line in open(JOBS, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            job = json.loads(line)
        except Exception:
            log(f"drop malformed queue line: {line[:120]}")
            continue
        if not job.get("session_id") or not job.get("transcript_path"):
            log(f"drop queue line missing fields: {line[:120]}")
            continue
        jobs.append(job)
    return jobs


def job_key(job):
    return f"{job.get('session_id')}|{job.get('transcript_path')}|{job.get('enqueued_at')}"


def load_state():
    try:
        return json.load(open(QUEUE / "state.json", encoding="utf-8"))
    except Exception:
        return {"jobs": {}}


def save_state(state):
    atomic_write(QUEUE / "state.json", json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def count_path():
    return QUEUE / f"count-{time.strftime('%Y-%m-%d')}"


def read_count():
    try:
        return int((count_path()).read_text().strip())
    except Exception:
        return 0


def write_count(n):
    atomic_write(count_path(), str(n))


def cursor_path(sid):
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", sid)
    return STATE_DIR / f"{safe}.json"


def cursor_done(job):
    p = cursor_path(job["session_id"])
    try:
        cur = json.load(open(p, encoding="utf-8"))
    except Exception:
        return False
    tp = Path(job["transcript_path"])
    try:
        st = tp.stat()
    except OSError:
        return False
    return (cur.get("status") == "done"
            and cur.get("size") == st.st_size
            and abs(float(cur.get("mtime", 0)) - st.st_mtime) < 1e-6
            and cur.get("sha256") == sha256_file(tp))


def write_cursor(job, status, candidates=0, error=""):
    tp = Path(job["transcript_path"])
    try:
        st = tp.stat(); digest = sha256_file(tp)
    except OSError:
        st = None; digest = ""
    data = {
        "session_id": job["session_id"],
        "transcript_path": job["transcript_path"],
        "status": status,
        "size": st.st_size if st else None,
        "mtime": st.st_mtime if st else None,
        "sha256": digest,
        "enqueued_at": job.get("enqueued_at"),
        "updated_at": time.strftime("%F %T"),
        "candidates": candidates,
        "error": error,
    }
    atomic_write(cursor_path(job["session_id"]),
                 json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def candidate_hash(lane, title, content):
    return hashlib.sha256(f"{lane}\x00{title}\x00{content}".encode("utf-8")).hexdigest()


def split_frontmatter(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m or yaml is None:
        return None, text
    try:
        return yaml.safe_load(m.group(1)) or {}, m.group(2)
    except yaml.YAMLError:
        return None, text


def write_candidate(cand, sid, today):
    lane, title, content, reason = cand["lane"], cand["title"], cand["content"], cand["reason"]
    digest = candidate_hash(lane, title, content)
    cid = "cand-" + digest[:8]
    path = STAGING / f"{cid}.md"
    existing = None
    if path.exists():
        existing, _ = split_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    if existing and existing.get("content_hash") == digest:
        sessions = list(existing.get("source_sessions") or [])
        if sid not in sessions:
            sessions.append(sid)
        existing["source_sessions"] = sessions
        existing["recurrence"] = int(existing.get("recurrence") or 1) + 1
        existing["last_seen"] = today
        if yaml:
            body = path.read_text(encoding="utf-8", errors="replace").split("---", 2)[-1].lstrip("\n")
            atomic_write(path, "---\n" + yaml.safe_dump(existing, allow_unicode=True, sort_keys=False).rstrip()
                         + "\n---\n" + body)
        return cid, True
    fm = {
        "id": cid,
        "created": today,
        "last_seen": today,
        "source_sessions": [sid],
        "user": os.environ.get("USER", os.environ.get("USERNAME", "")),
        "scope": "user",
        "lane": lane,
        "title": title,
        "status": "staged",
        "supersedes": None,
        "recurrence": 1,
        "content_hash": digest,
        "quality": {
            "nonempty": True,
            "secret_scan": "pass",
            "raw_record_scan": "pass",
            "schema": 2,
        },
    }
    if yaml:
        text = ("---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).rstrip()
                + "\n---\n" + title + "\n\n" + content + f"\n\n<!-- 理由: {reason} -->\n")
    else:
        text = (f"---\nid: {cid}\ncreated: {today}\nlane: {lane}\nstatus: staged\n"
                f"recurrence: 1\ncontent_hash: {digest}\n---\n{title}\n\n{content}\n")
    atomic_write(path, text)
    return cid, False


def append_index(cid, lane, title):
    clean = str(title).replace("|", "\\|").replace("\n", " ")
    row = f"| {cid} | {lane} | staged | {clean[:60]} |\n"
    with open(INDEX, "a", encoding="utf-8") as f:
        f.write(row)


def parse_model_output(out):
    text = (out or "").strip()
    if not text:
        return None, "空输出"
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return None, "无 JSON 数组"
    try:
        data = json.loads(m.group(0))
    except Exception as e:
        return None, f"JSON 解析失败: {e}"
    if not isinstance(data, list):
        return None, "输出不是数组"
    return data, None


def run_model(prompt, timeout, model):
    if os.environ.get("DISTILLER_CMD"):
        cmd = [sys.executable, os.environ["DISTILLER_CMD"]]
        return subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    cmd = ["claude", "-p", prompt, "--allowedTools", "Read", "Grep",
           f"Bash({SKILL_SCRIPTS}/*)", "--max-turns", "40",
           "--permission-mode", "default"]
    if model:
        cmd += ["--model", model]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def process_candidates(raw, sid, today):
    """返回 (written_ids, invalid_count, error)。"""
    valid, invalid = [], 0
    for c in raw[:5]:
        if not isinstance(c, dict):
            invalid += 1; continue
        lane = c.get("lane")
        title = c.get("title")
        content = c.get("content")
        reason = c.get("reason")
        if (lane not in LANES or not isinstance(title, str) or not title.strip()
                or not isinstance(content, str) or len(content.strip()) < 20
                or not isinstance(reason, str) or not reason.strip()):
            invalid += 1
            log(f"reject candidate {sid[:8]}: lane/字段/长度不合法 lane={lane!r}")
            continue
        blob = f"{title}\n{content}\n{reason}"
        secrets = scan_secret(blob)
        if secrets:
            invalid += 1
            log(f"reject candidate {sid[:8]}: 疑似秘密（{len(secrets)} 模式）")
            continue
        if scan_raw(content) >= 2:
            invalid += 1
            log(f"reject candidate {sid[:8]}: content 疑似原始记录")
            continue
        valid.append({"lane": lane, "title": title.strip(), "content": content.strip(),
                      "reason": reason.strip()})
    if invalid and not valid:
        return [], invalid, "全部候选未通过落盘前检查"
    STAGING.mkdir(parents=True, exist_ok=True)
    if not INDEX.exists():
        atomic_write(INDEX, "| id | lane | status | title |\n|---|---|---|---|\n")
    written = []
    for c in valid:
        cid, existed = write_candidate(c, sid, today)
        if not existed:
            append_index(cid, c["lane"], c["title"])
        written.append(cid)
    return written, invalid, None


def finalize_jobs(remaining_keys, snapshot_keys):
    """在共享锁内压缩队列：保留未完成/失败/预算保留任务与处理期间新追加的任务。"""
    with FileLock(QUEUE / ".queue.lock"):
        current = read_jobs()
        seen, keep = set(), []
        for job in current:
            key = job_key(job)
            if key in seen:
                continue
            # 快照内已完成/丢弃的任务不保留；快照外的新任务必须保留
            if key in snapshot_keys and key not in remaining_keys:
                continue
            keep.append(job); seen.add(key)
        atomic_write(JOBS, "".join(json.dumps(j, ensure_ascii=False) + "\n" for j in keep))
    return keep


class FileLock:
    """与 enqueue.py 相同的生产者/消费者共享锁。"""
    def __init__(self, path):
        self.path = Path(path); self.fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a+")
        _lock(self.fh)
        return self

    def __exit__(self, *exc):
        try:
            _unlock(self.fh)
            self.fh.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-jobs-per-day", type=int,
                    default=int(os.environ.get("MAX_JOBS_PER_DAY", "3")))
    ap.add_argument("--model", default=os.environ.get("DISTILLER_MODEL"))
    ap.add_argument("--stale-seconds", type=int, default=7200)
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args()
    dry = args.dry_run or os.environ.get("WORKER_DRY_RUN") == "1"

    wl = WorkerLock(LOCK, args.stale_seconds)
    if not wl.acquire():
        log("worker lock held by live process; exit")
        return 0
    try:
        if not JOBS.exists() or JOBS.stat().st_size == 0:
            return 0
        state = load_state()
        jobs = read_jobs()
        if not jobs:
            return 0
        snapshot_keys = {job_key(j) for j in jobs}
        today = time.strftime("%F")
        cnt = read_count()
        remaining = set()
        skipped_done = 0
        for job in jobs:
            key = job_key(job)
            rec = state["jobs"].get(key) or {}
            if rec.get("status") == "done" and cursor_done(job):
                skipped_done += 1
                continue
            if rec.get("status") == "processing" and \
                    time.time() - float(rec.get("updated_at", 0)) < args.stale_seconds:
                remaining.add(key); continue
            if cnt >= args.max_jobs_per_day and not dry:
                remaining.add(key)
                rec.update(status="held", reason="daily-budget", updated_at=time.time())
                state["jobs"][key] = rec
                HOLD.write_text(json.dumps({"date": today, "count": cnt,
                                            "max": args.max_jobs_per_day},
                                           ensure_ascii=False), encoding="utf-8")
                continue
            tp = Path(job["transcript_path"])
            if not tp.is_file():
                log(f"drop {job['session_id'][:8]}: transcript 缺失")
                continue
            if cursor_done(job):
                skipped_done += 1
                continue
            try:
                tools, edits, corr, first_user = analyze(tp)
            except Exception as e:
                log(f"error {job['session_id'][:8]}: 解析失败 {e}")
                remaining.add(key); continue
            if is_meta(first_user):
                log(f"drop {job['session_id'][:8]}: meta-session")
                continue
            if not (tools >= TH_TOOLS or edits >= TH_EDITS or corr >= TH_CORR):
                log(f"drop {job['session_id'][:8]}: 未达标 tools={tools} edits={edits} corr={corr}")
                continue
            if dry:
                log(f"DRY {job['session_id'][:8]}: 达标 tools={tools} edits={edits} corr={corr}")
                continue
            rec.update(status="processing", updated_at=time.time(),
                       attempts=int(rec.get("attempts", 0)) + 1)
            state["jobs"][key] = rec
            save_state(state)
            prompt = PROMPT.format(scripts=SKILL_SCRIPTS, sid=job["session_id"])
            try:
                proc = run_model(prompt, args.timeout, args.model)
            except subprocess.TimeoutExpired:
                err = f"timeout {args.timeout}s"
                log(f"error {job['session_id'][:8]}: {err}")
                rec.update(status="failed", last_error=err, updated_at=time.time())
                state["jobs"][key] = rec
                remaining.add(key)
                continue
            except Exception as e:
                err = f"spawn failed: {e}"
                log(f"error {job['session_id'][:8]}: {err}")
                rec.update(status="failed", last_error=err, updated_at=time.time())
                state["jobs"][key] = rec
                remaining.add(key)
                continue
            if proc.returncode != 0:
                err = (proc.stderr or "").strip()[:500] or f"exit {proc.returncode}"
                log(f"error {job['session_id'][:8]}: model exit={proc.returncode} {err}")
                rec.update(status="failed", last_error=err, updated_at=time.time())
                state["jobs"][key] = rec
                if rec["attempts"] >= 3:
                    dl = QUEUE / "dead-letter.jsonl"
                    with open(dl, "a", encoding="utf-8") as f:
                        f.write(json.dumps({**job, "error": err, "attempts": rec["attempts"]},
                                           ensure_ascii=False) + "\n")
                    log(f"dead-letter {job['session_id'][:8]} after {rec['attempts']} attempts")
                else:
                    remaining.add(key)
                save_state(state)
                continue
            cands, perr = parse_model_output(proc.stdout)
            if perr:
                log(f"error {job['session_id'][:8]}: {perr}")
                rec.update(status="failed", last_error=perr, updated_at=time.time())
                state["jobs"][key] = rec
                remaining.add(key)
                save_state(state)
                continue
            written, invalid, werr = process_candidates(cands, job["session_id"], today)
            if werr:
                log(f"error {job['session_id'][:8]}: {werr}")
                rec.update(status="failed", last_error=werr, updated_at=time.time())
                state["jobs"][key] = rec
                remaining.add(key)
                save_state(state)
                continue
            cnt += 1
            write_count(cnt)
            write_cursor(job, "done", candidates=len(written))
            rec.update(status="done", updated_at=time.time(), candidates=len(written),
                       last_error="")
            state["jobs"][key] = rec
            save_state(state)
            log(f"ok {job['session_id'][:8]}: 候选={len(written)} 无效={invalid} "
                f"（今日 {cnt}/{args.max_jobs_per_day}）")
        if dry:
            log(f"DRY-RUN 完成：队列未修改（done_skip={skipped_done}）")
            return 0
        finalize_jobs(remaining, snapshot_keys)
        if not remaining and HOLD.exists():
            HOLD.unlink(missing_ok=True)
        if skipped_done:
            log(f"已跳过 {skipped_done} 个已完成且未变化的会话")
        return 0
    finally:
        wl.release()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"fatal: {e}")
        sys.exit(1)
