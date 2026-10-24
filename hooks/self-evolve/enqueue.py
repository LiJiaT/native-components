#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SessionEnd hook：把活跃会话安全地排入蒸馏队列。

设计约束：
  - 不 eval 任何输入字段；全部按 JSON 数据处理。
  - 逐行解析 transcript，按 message.content 中的 tool_use 块统计，兼容
    空格、单行多工具、Windows 反斜杠路径与含空格路径。
  - 预过滤与 L0 门槛保持同一上界：tools>=40 OR edits>=3 OR corrections>=2。
  - 任何异常都静默退出 0（旁路 hook 不得阻塞会话），但写入诊断日志。
"""
import json
import os
import re
import sys
import time
import hashlib
from pathlib import Path

HOME = Path.home()
QUEUE = HOME / ".claude" / "self-evolve" / "queue"
INBOX = QUEUE / "inbox"
LOG = QUEUE / "enqueue.log"
TH_TOOLS, TH_EDITS, TH_CORR = 40, 3, 2
CORR_WORDS = ["不对", "不是这样", "错了", "别用", "不要用", "actually", "wrong",
              "no, not that", "instead"]
EDIT_TOOLS = {"Write", "Edit", "NotebookEdit"}


def log(msg):
    try:
        QUEUE.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%F %T')}] {msg}\n")
    except Exception:
        pass


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text")
    return ""


def analyze(path):
    """返回 (tools, edits, corrections, first_user_text, parsed_lines)。"""
    tools = edits = corr = 0
    first_user = ""
    parsed = 0
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            parsed += 1
            msg = event.get("message") or {}
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        tools += 1
                        if block.get("name") in EDIT_TOOLS:
                            edits += 1
            if event.get("type") == "user" and not event.get("isMeta"):
                text = text_of(content)
                if not first_user and text and not text.startswith(
                        ("<local-command", "<command-name", "<system-reminder")):
                    first_user = text
                low = text.lower()
                if text and not text.startswith(("<local-command", "<command-name",
                                                 "<system-reminder")):
                    corr += sum(1 for w in CORR_WORDS if w.lower() in low)
    return tools, edits, corr, first_user, parsed


def is_meta(first_user):
    return ("会话蒸馏" in first_user) or ("extract.sh" in first_user and "--level" in first_user)


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class FileLock:
    """跨进程锁；超时抛 TimeoutError，绝不在未持锁时进入临界区。"""
    def __init__(self, path, timeout=2.0):
        self.path = str(path)
        self.timeout = timeout
        self.fh = None
        self.acquired = False

    def __enter__(self):
        self.fh = open(self.path, "a+")
        deadline = time.time() + self.timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.acquired = True
                return self
            except Exception:
                if time.time() >= deadline:
                    self.fh.close()
                    raise TimeoutError(f"lock timeout: {self.path}")
                time.sleep(0.05)

    def __exit__(self, *exc):
        try:
            if self.acquired:
                if os.name == "nt":
                    import msvcrt
                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            self.fh.close()
        except Exception:
            pass


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception as e:
        log(f"invalid stdin: {e}")
        return 0
    sid = str(data.get("session_id") or "")
    tp = str(data.get("transcript_path") or "")
    if not sid or not tp:
        log("missing session_id/transcript_path")
        return 0
    if not os.path.isfile(tp):
        log(f"skip {sid[:8]}: transcript 不存在: {tp}")
        return 0
    try:
        tools, edits, corr, first_user, parsed = analyze(tp)
    except Exception as e:
        log(f"skip {sid[:8]}: 解析失败 {e} ({tp})")
        return 0
    if parsed == 0:
        log(f"skip {sid[:8]}: 无有效 JSONL 行")
        return 0
    if is_meta(first_user):
        log(f"skip {sid[:8]}: 蒸馏 meta-session")
        return 0
    if not (tools >= TH_TOOLS or edits >= TH_EDITS or corr >= TH_CORR):
        log(f"skip {sid[:8]}: 未达标 tools={tools} edits={edits} corr={corr}")
        return 0

    QUEUE.mkdir(parents=True, exist_ok=True)
    job = {
        "session_id": sid,
        "transcript_path": os.path.abspath(tp),
        "enqueued_at": int(time.time()),
        "stats": {"tools": tools, "edits": edits, "corrections": corr},
        "schema": 2,
    }
    # 唯一 inbox 文件：producer 不需要拿队列锁，避免锁超时丢任务
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", sid)[:40]
    name = f"{safe}-{time.time_ns()}-{os.getpid()}.json"
    atomic_write(INBOX / name, json.dumps(job, ensure_ascii=False) + "\n")
    log(f"enqueued {sid[:8]} tools={tools} edits={edits} corr={corr} inbox={name}")

    # fire-and-forget 拉起 worker；worker 自身有 PID 存活检测的锁
    worker = HOME / ".claude" / "skills" / "session-distiller" / "scripts" / "worker.sh"
    if worker.is_file():
        try:
            import subprocess
            logf = open(QUEUE / "worker.log", "a", encoding="utf-8")
            subprocess.Popen(["bash", str(worker)], stdin=subprocess.DEVNULL,
                             stdout=logf, stderr=subprocess.STDOUT,
                             start_new_session=True, close_fds=True)
        except Exception as e:
            log(f"worker spawn failed: {e}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"fatal: {e}")
        sys.exit(0)
