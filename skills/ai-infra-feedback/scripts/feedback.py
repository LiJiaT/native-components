#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ai-infra-feedback: 把组件问题结构化为反馈单（Markdown + JSON），
写入 self-evolve outbox，并生成 staging 候选（不自动晋升）。

设计约束：
  - 落盘/预览/发送前统一脱敏（API key / token / 密码 / 手机号 / 邮箱等）。
  - R8：不落原始会议、聊天、调试日志；证据只保留结论 + 指针 + 极短摘录。
  - 默认不发送；--send 默认 dry-run，只有 --send --yes 才真正调用 lark-cli。
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SKILL_NAME = "ai-infra-feedback"
SKILL_VERSION = "0.1.0"
SCHEMA_VERSION = "1.0"
PRIORITIES = ("P0", "P1", "P2", "P3")
DEFAULT_OUTBOX = Path.home() / ".claude" / "self-evolve" / "queue" / "feedback"
DEFAULT_STAGING = Path.home() / ".claude" / "self-evolve" / "staging"

MISSING = "（待补充：需反馈人确认）"


class UsageError(Exception):
    """输入/参数错误，main 统一转成退出码 2。"""


# --------------------------------------------------------------------------
# 脱敏
# --------------------------------------------------------------------------

_SECRET_PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("api_key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{6,}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-+/=]{8,}")),
    ("auth_header", re.compile(r"(?i)\bauthorization\b\s*:\s*[^\r\n]+")),
    ("cookie", re.compile(r"(?i)\bcookie\b\s*:\s*[^\r\n]+")),
    ("url_userinfo", re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@")),
    ("id_card", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("phone_cn", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
]

_SECRET_KV = re.compile(
    r"(?i)\b(api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|auth[_-]?token|token|"
    r"secret|password|passwd|pwd|app[_-]?secret|client[_-]?secret)\b(\s*[:=]\s*)"
    r"(?:(['\"])(.*?)\3|([^\s\"',;&]+))"
)
_SECRET_KEY = re.compile(
    r"(?i)^(?:api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|auth[_-]?token|"
    r"token|secret|password|passwd|pwd|app[_-]?secret|client[_-]?secret|"
    r".*[_-](?:api[_-]?key|token|secret|password))$"
)


def _kv_repl(m: re.Match) -> str:
    quote = m.group(3) or ""
    return f"{m.group(1)}{m.group(2)}{quote}[REDACTED:secret]{quote}"


def redact(text: str, hits: collections.Counter | None = None) -> str:
    """对单个字符串脱敏，命中计数累加到 hits。"""
    if not text:
        return text
    if hits is None:
        hits = collections.Counter()
    for name, pat in _SECRET_PATTERNS:
        text, n = pat.subn(f"[REDACTED:{name}]", text)
        if n:
            hits[name] += n
    text, n = _SECRET_KV.subn(_kv_repl, text)
    if n:
        hits["secret"] += n
    return text


_RAW_PATTERNS = [
    re.compile(r"^\s*\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s+"
               r"(?:DEBUG|TRACE|INFO|WARN(?:ING)?|ERROR|FATAL)\b", re.I),
    re.compile(r"^\s*(?:Speaker\s*[A-Z0-9]+|说话人\s*[A-Z0-9一二三四五六七八九十]+)\s*[:：]", re.I),
]


def looks_like_raw(text: str) -> bool:
    hits = sum(1 for line in str(text).splitlines() if any(p.search(line) for p in _RAW_PATTERNS))
    return hits >= 2


def redact_obj(obj, hits: collections.Counter):
    """递归脱敏 dict/list/str；敏感键名整体遮盖值。"""
    if isinstance(obj, str):
        return redact(obj, hits)
    if isinstance(obj, list):
        return [redact_obj(v, hits) for v in obj]
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and _SECRET_KEY.match(k) and v not in (None, "", [], {}):
                out[k] = "[REDACTED:secret]"
                hits["secret"] += 1
            else:
                out[k] = redact_obj(v, hits)
        return out
    return obj


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------


def now_local() -> datetime:
    return datetime.now().astimezone()


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def truncate(text: str, limit: int, note: str = "…") -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - len(note)] + note


def mask_id(value: str) -> str:
    if not value:
        return ""
    return value[:3] + "..." + value[-4:] if len(value) > 8 else "***"


def clean_missing(value) -> tuple[str, bool]:
    """返回 (文本, 是否缺失)。"""
    if value is None:
        return MISSING, True
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return MISSING, True
        return value, False
    return str(value), False


def norm_priority(value: str | None) -> str:
    p = (value or "P2").strip().upper()
    if p not in PRIORITIES:
        raise UsageError(f"priority 必须是 P0/P1/P2/P3，收到: {value}")
    return p


def split_list(values: list[str] | None, commas: bool = True) -> list[str]:
    out: list[str] = []
    pattern = r"[\n,，;；]+" if commas else r"\n+"
    for raw in values or []:
        for piece in re.split(pattern, str(raw)):
            piece = re.sub(r"^\s*(?:\d+\s*[.)、]|[-*•])\s*", "", piece).strip()
            if piece:
                out.append(piece)
    return out


def _is_shell_script(path: str) -> bool:
    try:
        p = Path(path)
        return p.is_file() and p.read_bytes()[:2] == b"#!"
    except OSError:
        return False


def _exec_argv(cmd: list[str]) -> list[str]:
    """在 Windows 上把 POSIX shell 脚本交给 bash，避免 CreateProcess 无法执行。"""
    exe = cmd[0]
    if not os.path.isabs(exe):
        exe = shutil.which(exe) or exe
    argv = [exe] + cmd[1:]
    if os.name == "nt" and _is_shell_script(exe):
        bash = shutil.which("bash") or shutil.which("sh")
        if bash:
            return [bash, exe] + cmd[1:]
    return argv


def run_capture(cmd: list[str], timeout: int = 4) -> str:
    try:
        p = subprocess.run(_exec_argv(cmd), capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        if p.returncode == 0:
            return (p.stdout or "").strip()
    except Exception:
        pass
    return ""


def _shell_safe_lark(path: str) -> str:
    """Windows 上优先用插件的 POSIX 脚本 + bash，argv 传递比 .cmd 安全。"""
    if os.name != "nt" or not path.lower().endswith(".cmd"):
        return path
    sibling = Path(path).with_suffix("")
    if _is_shell_script(str(sibling)) and (shutil.which("bash") or shutil.which("sh")):
        return str(sibling)
    return path


def discover_lark_cli() -> str:
    env = os.environ.get("LARK_CLI")
    if env and Path(env).exists():
        return env
    found = shutil.which("lark-cli")
    if found:
        return _shell_safe_lark(found)
    # Qoder / Claude 插件缓存里的常见位置，最后兜底
    candidates: list[Path] = []
    for base in (Path.home() / ".qoder-cn" / "plugins" / "cache", Path.home() / ".claude" / "plugins" / "cache"):
        if base.is_dir():
            for name in ("lark-cli.exe", "lark-cli", "lark-cli.cmd"):
                candidates.extend(sorted(base.glob(f"**/bin/{name}"), reverse=True))
    # 优先原生 exe，其次 POSIX 脚本，最后 .cmd
    ordered = ([c for c in candidates if c.suffix.lower() == ".exe"]
               + [c for c in candidates if c.suffix == ""]
               + [c for c in candidates if c.suffix.lower() == ".cmd"])
    seen: set[str] = set()
    for cand in ordered:
        key = str(cand).lower()
        if key in seen or not cand.is_file():
            continue
        seen.add(key)
        return _shell_safe_lark(str(cand))
    return ""


# --------------------------------------------------------------------------
# transcript 提取（L0 级别：只取结论与指针，不复制原文）
# --------------------------------------------------------------------------

COMPLAINT_RE = re.compile(
    r"(不对|不是这样|错了|有问题|报错|失败|无法|不能|卡住|超时|异常|bug|不支持|期望|应该|"
    r"error|failed|broken|doesn't work|does not work|not working|unexpected)",
    re.IGNORECASE,
)
ERROR_RE = re.compile(
    r"(?i)(\berror\b|exception|traceback|npm ERR!|\bfailed\b|\bfailure\b|timed? ?out|permission denied|"
    r"access denied|not found|unable to|cannot |failed to|失败|报错|错误|超时|拒绝|无法|异常)"
)
SKIP_USER_RE = re.compile(r"^(<|system-reminder|Caveat:|This session is being continued)", re.IGNORECASE)


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return ""


def _tool_result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif "content" in block:
                    parts.append(_tool_result_text(block.get("content")))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return ""


def _first_error_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line and ERROR_RE.search(line) and len(line) > 4:
            return truncate(line, 220)
    return ""


def extract_transcript(path: Path) -> dict:
    """扫描 JSONL，返回 session 元信息 + 精简证据。禁止全量回显。"""
    info = {
        "session_id": path.stem,
        "cwd": "",
        "git_branch": "",
        "version": "",
        "started_at": "",
        "last_at": "",
        "lines_scanned": 0,
        "complaints": [],
        "errors": [],
        "failed_commands": [],
        "truncated": False,
    }
    tool_uses: dict[str, tuple[str, int, dict]] = {}
    complaints: collections.deque = collections.deque(maxlen=6)
    errors: list[dict] = []
    seen_errors: set[tuple[str, str]] = set()

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            info["lines_scanned"] = lineno
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue

            if not info["session_id"] or info["session_id"] == path.stem:
                info["session_id"] = obj.get("sessionId") or obj.get("session_id") or path.stem
            info["cwd"] = info["cwd"] or obj.get("cwd", "") or ""
            info["git_branch"] = info["git_branch"] or obj.get("gitBranch", "") or ""
            info["version"] = info["version"] or obj.get("version", "") or ""
            ts = obj.get("timestamp", "") or ""
            if ts:
                info["started_at"] = info["started_at"] or ts
                info["last_at"] = ts

            typ = obj.get("type")
            msg = obj.get("message") or {}
            content = msg.get("content")

            if typ == "user":
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type")
                        if btype == "tool_use":
                            tool_uses[block.get("id", "")] = (
                                block.get("name", "tool"),
                                lineno,
                                block.get("input") or {},
                            )
                        elif btype == "tool_result":
                            is_error = bool(block.get("is_error"))
                            text = _tool_result_text(block.get("content"))
                            err_line = _first_error_line(text)
                            if not is_error and not err_line:
                                continue
                            tool_name, tool_line, tool_input = tool_uses.get(
                                block.get("tool_use_id", ""), ("tool", lineno, {})
                            )
                            cmd = str(tool_input.get("command", "") or "")
                            file_path = str(tool_input.get("file_path", "") or tool_input.get("path", "") or "")
                            if tool_name == "Bash" and cmd:
                                summary = f"命令失败: {truncate(cmd, 160)}"
                                kind = "command"
                            elif file_path:
                                summary = f"工具 {tool_name} 在 {truncate(file_path, 120)} 报错"
                                kind = "file"
                            else:
                                summary = f"工具 {tool_name} 返回错误: {err_line or 'is_error=true'}"
                                kind = "log"
                            pointer = f"{path}#L{lineno}"
                            key = (summary, pointer)
                            if key not in seen_errors and len(errors) < 12:
                                seen_errors.add(key)
                                errors.append({
                                    "kind": kind,
                                    "summary": summary,
                                    "pointer": pointer,
                                    "excerpt": err_line,
                                })
                            if tool_name == "Bash" and cmd:
                                info["failed_commands"].append({
                                    "command": truncate(cmd, 200),
                                    "pointer": f"{path}#L{tool_line or lineno}",
                                })
                elif isinstance(content, str):
                    pass

                text = _content_text(content).strip()
                if text and not SKIP_USER_RE.search(text):
                    if COMPLAINT_RE.search(text):
                        complaints.append({
                            "text": truncate(text, 300),
                            "pointer": f"{path}#L{lineno}",
                            "timestamp": ts,
                        })
            elif typ == "assistant" and isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_uses[block.get("id", "")] = (
                            block.get("name", "tool"),
                            lineno,
                            block.get("input") or {},
                        )

    info["complaints"] = list(complaints)
    info["errors"] = errors
    # 去重失败命令
    dedup: list[dict] = []
    seen_cmd: set[str] = set()
    for item in info["failed_commands"]:
        if item["command"] not in seen_cmd:
            seen_cmd.add(item["command"])
            dedup.append(item)
    info["failed_commands"] = dedup[:5]
    info["truncated"] = len(errors) >= 12 or len(complaints) >= 6
    return info


# --------------------------------------------------------------------------
# 构建反馈单
# --------------------------------------------------------------------------

EVIDENCE_PREFIXES = ("file", "command", "cmd", "log", "pointer")


def parse_evidence(raw: str) -> dict:
    kind = ""
    body = raw.strip()
    if ":" in body:
        head, rest = body.split(":", 1)
        if head.strip().lower() in EVIDENCE_PREFIXES:
            kind = "command" if head.strip().lower() == "cmd" else head.strip().lower()
            body = rest.strip()
    if not kind:
        if re.search(r"\.\w{1,8}:\d+", body):
            kind = "file"
        elif re.search(r"(?i)^(python|bash|sh|git|npm|pnpm|claude|lark-cli)\b", body):
            kind = "command"
        else:
            kind = "pointer"
    summary = truncate(body, 240)
    pointer = ""
    m = re.search(r"((?:[A-Za-z]:[/\\]|/)?[^\s:]+\.\w{1,8}:\d+)", body)
    if m:
        pointer = m.group(1)
    return {"kind": kind, "summary": summary, "pointer": pointer, "excerpt": ""}


def normalize_input_keys(data: dict) -> dict:
    aliases = {
        "问题现象": "problem",
        "影响范围": "impact",
        "期望行为": "expected",
        "复现路径": "repro",
        "涉及组件": "component",
        "优先级": "priority",
        "证据": "evidence",
        "建议动作": "suggested_actions",
        "环境信息": "environment",
        "标题": "title",
    }
    return {aliases.get(k, k): v for k, v in data.items()}


def collect_environment(extra_pairs: list[str], transcript_info: dict | None) -> dict:
    extra: dict[str, str] = {}
    for pair in extra_pairs or []:
        if "=" in pair:
            k, v = pair.split("=", 1)
            extra[k.strip()] = v.strip()
    cwd = (transcript_info or {}).get("cwd") or os.getcwd()
    git_base = ["git", "-C", cwd] if cwd and Path(cwd).is_dir() else ["git"]
    return {
        "os": platform.platform(),
        "python": platform.python_version(),
        "cwd": cwd,
        "git_branch": (transcript_info or {}).get("git_branch", "") or run_capture(
            git_base + ["rev-parse", "--abbrev-ref", "HEAD"]),
        "git_head": run_capture(git_base + ["rev-parse", "--short", "HEAD"]),
        "claude_version": (transcript_info or {}).get("version", "")
        or os.environ.get("CLAUDE_CODE_VERSION", "") or run_capture(["claude", "--version"]),
        "lark_cli_version": run_capture(["lark-cli", "--version"]),
        "extra": extra,
    }


def build_doc(args, input_data: dict) -> dict:
    created = now_local()
    warnings: list[str] = []
    missing: list[str] = []

    transcript_info = None
    if args.session:
        spath = Path(args.session).expanduser().resolve()
        if not spath.is_file():
            raise UsageError(f"--session 文件不存在: {spath}")
        transcript_info = extract_transcript(spath)
        if transcript_info.get("truncated"):
            warnings.append("transcript 提取达到上限，仅保留前 12 条错误摘要/最近 6 条用户陈述")

    problem, miss = clean_missing(args.problem or input_data.get("problem"))
    if miss:
        if transcript_info and transcript_info["complaints"]:
            last = transcript_info["complaints"][-1]
            problem = "（自动摘取）" + last["text"]
            warnings.append(f"问题现象自动摘取自 {last['pointer']}，请人工确认")
        elif transcript_info and transcript_info["errors"]:
            first = transcript_info["errors"][0]
            problem = "（自动摘取）" + first["summary"]
            warnings.append("问题现象自动摘取自 transcript 错误摘要，请人工确认")
        else:
            raise UsageError("缺少 --problem（或在 --session 中可识别的用户问题描述）")

    impact, miss = clean_missing(args.impact or input_data.get("impact"))
    if miss:
        missing.append("影响范围")
    expected, miss = clean_missing(args.expected or input_data.get("expected"))
    if miss:
        missing.append("期望行为")

    repro_raw = args.repro or input_data.get("repro") or []
    if isinstance(repro_raw, str):
        repro_raw = [repro_raw]
    repro_steps = split_list(list(repro_raw), commas=False)
    if not repro_steps and transcript_info and transcript_info["failed_commands"]:
        repro_steps = [
            f"执行 `{item['command']}`（见 {item['pointer']}）"
            for item in transcript_info["failed_commands"][:4]
        ]
        warnings.append("复现路径由失败命令自动推导，请人工确认步骤顺序")
    if not repro_steps:
        repro_steps = [MISSING]
        missing.append("复现路径")

    component_raw = args.component or input_data.get("component") or []
    if isinstance(component_raw, str):
        component_raw = [component_raw]
    components = split_list(list(component_raw))
    if not components:
        if transcript_info and transcript_info.get("cwd"):
            components = ["待确认（session cwd 中涉及的组件）"]
        else:
            components = ["待确认"]
        missing.append("涉及组件")

    priority_input = args.priority or input_data.get("priority")
    if not priority_input:
        warnings.append("未指定优先级，默认按 P2 处理；请与用户确认")
    priority = norm_priority(priority_input)
    priority_rationale = str(args.priority_rationale or input_data.get("priority_rationale") or "").strip()

    evidence: list[dict] = []
    for raw in list(input_data.get("evidence") or []):
        if isinstance(raw, str):
            evidence.append(parse_evidence(raw))
        elif isinstance(raw, dict):
            evidence.append({
                "kind": str(raw.get("kind", "pointer")),
                "summary": str(raw.get("summary", "")),
                "pointer": str(raw.get("pointer", "")),
                "excerpt": str(raw.get("excerpt", "")),
            })
    for raw in args.evidence or []:
        evidence.append(parse_evidence(raw))
    if transcript_info:
        evidence.extend(transcript_info["errors"])
    # 去重 + 截断 + 编号
    dedup_ev: list[dict] = []
    seen_ev: set[tuple[str, str]] = set()
    for item in evidence:
        item["summary"] = truncate(item.get("summary", ""), 260)
        item["excerpt"] = truncate(item.get("excerpt", ""), 240) if item.get("excerpt") else ""
        item["pointer"] = str(item.get("pointer", ""))
        key = (item["summary"], item["pointer"])
        if not item["summary"] or key in seen_ev:
            continue
        seen_ev.add(key)
        dedup_ev.append(item)
        if len(dedup_ev) >= 20:
            break
    evidence = dedup_ev
    for idx, item in enumerate(evidence, 1):
        item["id"] = f"E{idx}"

    actions_raw = args.suggested_action or input_data.get("suggested_actions") or []
    if isinstance(actions_raw, str):
        actions_raw = [actions_raw]
    actions = split_list(list(actions_raw), commas=False)

    title = str(args.title or input_data.get("title") or "").strip()
    if not title:
        first_line = problem.splitlines()[0]
        title = truncate(first_line.replace("（自动摘取）", ""), 64)

    session_path = str(Path(args.session).expanduser().resolve()) if args.session else (
        str(input_data.get("source_session", "")).strip() or ""
    )
    session_id = (transcript_info or {}).get("session_id", "")
    if not session_id and session_path:
        session_id = Path(session_path).stem

    extra_env = input_data.get("environment") or {}
    if isinstance(extra_env, dict):
        env_pairs = [f"{k}={v}" for k, v in extra_env.items()]
    else:
        env_pairs = []
    env = collect_environment(list(args.env or []) + env_pairs, transcript_info)

    user = (args.user or input_data.get("user") or os.environ.get("USERNAME")
            or os.environ.get("USER") or "unknown")

    source_mode = "session" if session_path else "problem"
    if session_path and args.problem:
        source_mode = "problem+session"

    completeness = not missing
    if missing:
        warnings.append("以下字段未提供，已用占位符标注: " + "、".join(dict.fromkeys(missing)))

    doc = {
        "schema_version": SCHEMA_VERSION,
        "feedback_id": f"fb-{created:%Y%m%d}-{created:%H%M%S}-{os.urandom(3).hex()}",
        "created_at": iso(created),
        "timestamp": iso(created),
        "title": title,
        "source": {
            "mode": source_mode,
            "session_id": session_id,
            "transcript_path": session_path,
            "extraction": {
                "lines_scanned": (transcript_info or {}).get("lines_scanned", 0),
                "complaint_messages": len((transcript_info or {}).get("complaints", [])),
                "error_evidence": len((transcript_info or {}).get("errors", [])),
                "note": "仅提取错误摘要、用户陈述与行号指针；未复制原始对话/日志（R8）",
            } if transcript_info else None,
        },
        "reporter": {"user": user, "skill": SKILL_NAME, "skill_version": SKILL_VERSION},
        "issue": {
            "phenomenon": problem,
            "impact": impact,
            "expected": expected,
            "repro_steps": repro_steps,
            "components": components,
            "priority": priority,
            "priority_rationale": priority_rationale,
        },
        "evidence": evidence,
        "environment": env,
        "suggested_actions": actions,
        "source_session": {
            "session_id": session_id,
            "transcript_path": session_path,
            "pointer_note": "原始 transcript 保留在原位，反馈单只引用行号指针",
        },
        "completeness": {
            "complete": completeness,
            "missing_fields": list(dict.fromkeys(missing)),
            "warnings": warnings,
        },
        "redaction": {"applied": True, "hits": {}, "total": 0},
        "delivery": {
            "requested": bool(args.send),
            "mode": "send" if (args.send and args.yes) else ("dry_run" if args.send else "none"),
            "status": "pending",
            "chat_id_masked": "",
            "identity": args.identity or "",
            "command": "",
            "body_preview": "",
            "sent_at": None,
            "error": "",
        },
        "paths": {},
        "r8": {
            "raw_logs_written": False,
            "raw_record_scan": "pass",
            "note": "反馈单只保留结论、证据指针与极短摘录；原始会议/聊天/调试日志未写入。",
        },
    }
    raw_detected = looks_like_raw(json.dumps(
        {"issue": doc["issue"], "evidence": doc["evidence"]}, ensure_ascii=False))
    doc["r8"]["raw_logs_written"] = raw_detected
    doc["r8"]["raw_record_scan"] = "fail" if raw_detected else "pass"
    return doc


# --------------------------------------------------------------------------
# 渲染与落盘
# --------------------------------------------------------------------------


def render_markdown(doc: dict) -> str:
    issue = doc["issue"]
    lines: list[str] = []
    lines.append(f"# [{issue['priority']}] {doc['title']}")
    lines.append("")
    lines.append(f"- 反馈单 ID: `{doc['feedback_id']}`")
    lines.append(f"- 时间: {doc['created_at']}")
    lines.append(f"- 上报人: {doc['reporter']['user']}")
    src = doc["source"]
    if src.get("session_id"):
        lines.append(f"- 来源: {src['mode']} · session `{src['session_id']}`")
    else:
        lines.append("- 来源: 使用者主动描述")
    lines.append("")
    lines.append("## 1. 问题现象")
    lines.append("")
    lines.append(issue["phenomenon"])
    lines.append("")
    lines.append("## 2. 影响范围")
    lines.append("")
    lines.append(issue["impact"])
    lines.append("")
    lines.append("## 3. 期望行为")
    lines.append("")
    lines.append(issue["expected"])
    lines.append("")
    lines.append("## 4. 复现路径")
    lines.append("")
    for i, step in enumerate(issue["repro_steps"], 1):
        lines.append(f"{i}. {step}")
    lines.append("")
    lines.append("## 5. 涉及组件")
    lines.append("")
    for comp in issue["components"]:
        lines.append(f"- {comp}")
    lines.append("")
    lines.append("## 6. 优先级")
    lines.append("")
    pr = issue["priority"]
    lines.append(f"**{pr}**" + (f" — {issue['priority_rationale']}" if issue["priority_rationale"] else ""))
    lines.append("")
    lines.append("## 7. 证据")
    lines.append("")
    if doc["evidence"]:
        lines.append("| ID | 类型 | 摘要 | 指针 |")
        lines.append("|---|---|---|---|")
        for ev in doc["evidence"]:
            summary = ev["summary"].replace("|", "\\|")
            pointer = ev["pointer"].replace("|", "\\|") if ev["pointer"] else "-"
            lines.append(f"| {ev['id']} | {ev['kind']} | {summary} | {pointer} |")
        excerpts = [ev for ev in doc["evidence"] if ev.get("excerpt")]
        if excerpts:
            lines.append("")
            lines.append("极短摘录（已脱敏，完整内容见指针）:")
            for ev in excerpts:
                lines.append(f"- {ev['id']}: `{ev['excerpt']}`")
    else:
        lines.append("（无）")
    lines.append("")
    lines.append("## 8. 环境信息")
    lines.append("")
    env = doc["environment"]
    lines.append(f"- OS: {env['os']}")
    lines.append(f"- Python: {env['python']}")
    lines.append(f"- cwd: `{env['cwd']}`")
    if env.get("git_branch") or env.get("git_head"):
        git_bits = " @ ".join(x for x in (env.get("git_branch"), env.get("git_head")) if x)
        lines.append(f"- git: {git_bits}")
    if env.get("claude_version"):
        lines.append(f"- Claude Code: {env['claude_version']}")
    if env.get("lark_cli_version"):
        lines.append(f"- lark-cli: {env['lark_cli_version']}")
    for k, v in (env.get("extra") or {}).items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## 9. 建议动作")
    lines.append("")
    if doc["suggested_actions"]:
        for action in doc["suggested_actions"]:
            lines.append(f"- {action}")
    else:
        lines.append("（待 AI Infra 团队评估）")
    lines.append("")
    lines.append("## 10. 来源 session")
    lines.append("")
    if src.get("session_id") or src.get("transcript_path"):
        lines.append(f"- session_id: `{src.get('session_id') or '未知'}`")
        if src.get("transcript_path"):
            lines.append(f"- transcript 指针: `{src['transcript_path']}`")
        ext = src.get("extraction")
        if ext:
            lines.append(
                f"- 提取范围: 扫描 {ext['lines_scanned']} 行，"
                f"用户陈述 {ext['complaint_messages']} 条，错误证据 {ext['error_evidence']} 条"
            )
            lines.append(f"- 说明: {ext['note']}")
    else:
        lines.append("- 无（本次为主动描述，未关联 transcript）")
    lines.append("")
    delivery = doc["delivery"]
    if delivery["requested"]:
        lines.append("## 投递")
        lines.append("")
        lines.append(f"- 状态: {delivery['status']}")
        if delivery.get("chat_id_masked"):
            lines.append(f"- 目标群: `{delivery['chat_id_masked']}`")
        if delivery.get("command"):
            lines.append(f"- 命令: `{delivery['command']}`")
        if delivery.get("error"):
            lines.append(f"- 错误: {delivery['error']}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"<!-- 由 {SKILL_NAME} v{SKILL_VERSION} 生成 · "
                 f"R8: 未写入原始日志，仅结论与指针 · 完整 JSON 见同目录同名文件 -->")
    lines.append("")
    return "\n".join(lines)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_feedback_files(doc: dict, outbox: Path) -> tuple[Path, Path]:
    stem = f"{doc['created_at'][:19].replace(':', '').replace('-', '')[:8]}-" \
           f"{doc['created_at'][11:19].replace(':', '')}-{doc['feedback_id'].split('-')[-1]}"
    slug_src = re.sub(r"\[REDACTED:[a-z_]+\]", " ", doc["title"] or "feedback")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", slug_src.lower()).strip("-")[:40] or "feedback"
    md_path = (outbox / f"{stem}-{slug}.md").resolve()
    json_path = (outbox / f"{stem}-{slug}.json").resolve()
    write_text(json_path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    write_text(md_path, render_markdown(doc))
    return md_path, json_path


def one_line(text: str) -> str:
    return " ".join(str(text).split())


def yaml_scalar(value) -> str:
    """JSON 标量/数组是合法 YAML flow 值；统一保证引号与转义。"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(str(value), ensure_ascii=False)


def index_cell(text: str) -> str:
    return one_line(text).replace("|", "\\|").replace("\\|", "\\|")


def write_staging_candidate(doc: dict, staging_dir: Path, index: bool) -> tuple[Path | None, Path | None]:
    issue = doc["issue"]
    cand_id = "cand-" + hashlib.sha1(
        (doc["feedback_id"] + doc["title"]).encode("utf-8")).hexdigest()[:8]
    fm = {
        "id": cand_id,
        "created": doc["created_at"][:10],
        "source_sessions": [doc["source"]["session_id"]] if doc["source"].get("session_id") else [],
        "user": doc["reporter"]["user"],
        "scope": "user",
        "lane": "feedback",
        "status": "staged",
        "supersedes": None,
        "recurrence": 1,
        "feedback_id": doc["feedback_id"],
        "component": issue["components"],
        "priority": issue["priority"],
    }
    body_lines = ["---"]
    body_lines += [f"{k}: {yaml_scalar(v)}" for k, v in fm.items()]
    body_lines += [
        "---",
        f"# [{issue['priority']}] {doc['title']}",
        "",
        f"**问题现象**: {one_line(issue['phenomenon'])}",
        f"**影响范围**: {one_line(issue['impact'])}",
        f"**期望行为**: {one_line(issue['expected'])}",
        "**复现路径**:",
    ]
    for i, step in enumerate(issue["repro_steps"], 1):
        body_lines.append(f"{i}. {step}")
    body_lines.append("**涉及组件**: " + "、".join(issue["components"]))
    if doc["evidence"]:
        body_lines.append("")
        body_lines.append("**证据指针**:")
        for ev in doc["evidence"]:
            ptr = f"（{ev['pointer']}）" if ev["pointer"] else ""
            body_lines.append(f"- {ev['id']} [{ev['kind']}] {ev['summary']}{ptr}")
    if doc["suggested_actions"]:
        body_lines.append("")
        body_lines.append("**建议动作**:")
        for action in doc["suggested_actions"]:
            body_lines.append(f"- {action}")
    body_lines.append("")
    body_lines.append(f"本地反馈单: `{doc['paths'].get('markdown', '')}` / `{doc['paths'].get('json', '')}`")
    body_lines.append(
        f"<!-- 理由: 使用者反馈的组件问题，供 AI Infra 升级评估；来源: session "
        f"{doc['source'].get('session_id') or 'none'}, {doc['created_at'][:10]}, 反馈单 {doc['feedback_id']} -->"
    )
    body_lines.append("")
    cand_path = (staging_dir / f"{cand_id}.md").resolve()
    text = "\n".join(body_lines)
    write_text(cand_path, text)
    # 写后解析校验：frontmatter 必须可被 YAML 解析且 status 未被用户字段劫持
    try:
        import yaml as _yaml
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
        parsed = _yaml.safe_load(m.group(1)) if m else None
        if not isinstance(parsed, dict) or parsed.get("status") != "staged" \
                or parsed.get("id") != cand_id:
            raise UsageError("staging 候选 frontmatter 写后解析失败或 status/id 被覆盖")
    except ImportError:
        pass

    index_path = (staging_dir / "INDEX.md").resolve()
    if index:
        summary = index_cell(truncate(
            f"[{issue['priority']}] {doc['title']}（{', '.join(issue['components'])}）", 80))
        row = f"| {cand_id} | feedback | staged | {summary} |\n"
        existing = index_path.read_text(encoding="utf-8") if index_path.exists() else \
            "# Staging Index\n| id | lane | status | 摘要 |\n|---|---|---|---|\n"
        if cand_id not in existing:
            if not existing.endswith("\n"):
                existing += "\n"
            index_path.write_text(existing + row, encoding="utf-8")
    return cand_path, index_path if index else None


# --------------------------------------------------------------------------
# 发送
# --------------------------------------------------------------------------


def build_send_body(doc: dict, max_chars: int) -> str:
    issue = doc["issue"]
    segs = [
        f"【AI Infra 反馈】[{issue['priority']}] {one_line(doc['title'])}",
        f"反馈单 {doc['feedback_id']}",
        f"组件 {', '.join(one_line(c) for c in issue['components'])}",
        f"现象 {one_line(issue['phenomenon'])}",
        f"影响 {one_line(issue['impact'])}",
        f"期望 {one_line(issue['expected'])}",
        "复现 " + " / ".join(f"{i}) {one_line(s)}" for i, s in enumerate(issue["repro_steps"], 1)),
    ]
    if doc["evidence"]:
        ev_bits = []
        for ev in doc["evidence"][:8]:
            ptr = f" ({ev['pointer']})" if ev["pointer"] else ""
            ev_bits.append(f"{ev['id']} {one_line(ev['summary'])}{ptr}")
        segs.append("证据 " + "; ".join(ev_bits))
    if doc["suggested_actions"]:
        segs.append("建议 " + "; ".join(one_line(a) for a in doc["suggested_actions"]))
    if doc["source"].get("session_id"):
        segs.append(f"来源 session {doc['source']['session_id']} (指针: {doc['source'].get('transcript_path') or '-'})")
    segs.append(f"本地反馈单 {doc['paths'].get('markdown', '')}")
    text = "；".join(segs)
    text = " ".join(text.split())
    if len(text) > max_chars:
        text = text[: max_chars - 30] + "…（已截断，完整内容见本地反馈单）"
    return text


def shell_command(lark_cli: str, chat_id: str, doc: dict, body: str, identity: str) -> str:
    parts = [lark_cli or "lark-cli", "im", "+messages-send", "--chat-id", chat_id,
             "--markdown", body, "--idempotency-key", doc["feedback_id"]]
    if identity:
        parts.extend(["--as", identity])
    parts = _exec_argv(parts)
    return " ".join(shlex.quote(p) for p in parts)


def do_send(doc: dict, args, body: str, chat_id: str, lark_cli: str) -> None:
    delivery = doc["delivery"]
    delivery["chat_id_masked"] = mask_id(chat_id)
    delivery["body_preview"] = body
    delivery["command"] = shell_command(lark_cli or "lark-cli", chat_id, doc, body, args.identity or "")

    if not args.yes:
        delivery["status"] = "dry_run"
        return

    if not lark_cli:
        delivery["status"] = "failed"
        delivery["error"] = "未找到 lark-cli（可用 LARK_CLI 指定路径）"
        raise RuntimeError(delivery["error"])

    cmd = [lark_cli, "im", "+messages-send", "--chat-id", chat_id, "--markdown", body,
           "--idempotency-key", doc["feedback_id"]]
    if args.identity:
        cmd.extend(["--as", args.identity])
    try:
        proc = subprocess.run(_exec_argv(cmd), capture_output=True, text=True, timeout=90,
                              encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        delivery["status"] = "failed"
        delivery["error"] = f"调用 lark-cli 异常: {type(exc).__name__}: {exc}"
        raise RuntimeError(delivery["error"]) from exc

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    ok = False
    try:
        payload = json.loads(out)
        ok = bool(payload.get("ok")) or bool((payload.get("data") or {}).get("message_id"))
    except json.JSONDecodeError:
        ok = proc.returncode == 0 and '"ok": true' in out.replace("\n", "")
    if proc.returncode != 0 or not ok:
        delivery["status"] = "failed"
        delivery["error"] = truncate((err or out or f"exit {proc.returncode}"), 500)
        raise RuntimeError(delivery["error"])
    delivery["status"] = "sent"
    delivery["sent_at"] = iso(now_local())


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="feedback.py",
        description="生成结构化 AI Infra 反馈单（Markdown + JSON + staging 候选）。默认只落盘，不发送。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  feedback.py --problem 'skill 调用报错' --impact '无法生成反馈单' \\\n"
            "      --expected '正常生成' --repro '运行 /ai-infra-feedback' \\\n"
            "      --component ai-infra-feedback --priority P2\n"
            "  feedback.py --session ~/.claude/projects/x/session.jsonl --component lark-cli\n"
            "  feedback.py --problem '...' --send            # dry-run，仅打印\n"
            "  feedback.py --problem '...' --send --yes      # 真正发送（需用户明确确认）\n"
        ),
    )
    p.add_argument("--problem", help="问题现象")
    p.add_argument("--impact", help="影响范围")
    p.add_argument("--expected", help="期望行为")
    p.add_argument("--repro", action="append", help="复现路径（可重复，或换行分隔）")
    p.add_argument("--component", action="append", help="涉及组件（可重复/逗号分隔）")
    p.add_argument("--priority", help="优先级 P0/P1/P2/P3（默认 P2）")
    p.add_argument("--priority-rationale", help="优先级判定理由")
    p.add_argument("--evidence", action="append",
                   help="证据，可重复。支持 'file:path:12 - 摘要'、'cmd:...'、'log:...'、'pointer:...'")
    p.add_argument("--suggested-action", action="append", help="建议动作（可重复）")
    p.add_argument("--env", action="append", help="补充环境信息 KEY=VALUE（可重复）")
    p.add_argument("--session", help="transcript JSONL 路径（提取 session 中的问题与证据）")
    p.add_argument("--title", help="反馈单标题（默认取问题现象首行）")
    p.add_argument("--user", help="上报人（默认取环境变量 USERNAME/USER）")
    p.add_argument("--input", help="结构化输入 JSON 文件（CLI 参数优先）")
    p.add_argument("--outbox", help=f"输出目录（默认 {DEFAULT_OUTBOX}，可用 AI_INFRA_FEEDBACK_OUTBOX）")
    p.add_argument("--staging-dir",
                   help=f"staging 目录（默认 {DEFAULT_STAGING}，可用 AI_INFRA_FEEDBACK_STAGING）")
    p.add_argument("--no-staging", action="store_true", help="不生成 staging 候选")
    p.add_argument("--no-index", action="store_true", help="只写候选文件，不追加 staging/INDEX.md")
    p.add_argument("--send", action="store_true", help="投递到 AI Infra 群；默认 dry-run")
    p.add_argument("--yes", action="store_true", help="与 --send 同用，确认真实发送")
    p.add_argument("--chat-id", help="目标群 chat_id（默认环境变量 AI_INFRA_FEISHU_CHAT_ID）")
    p.add_argument("--identity", choices=["user", "bot"], help="lark-cli 发送身份（默认由 lark-cli 决定）")
    p.add_argument("--max-send-chars", type=int, default=3500, help="发送正文上限（默认 3500）")
    p.add_argument("--json-summary", action="store_true", help="stdout 只输出 JSON 摘要")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(argv or sys.argv[1:])

    input_data: dict = {}
    if args.input:
        ipath = Path(args.input).expanduser()
        if not ipath.is_file():
            print(f"错误: --input 文件不存在: {ipath}", file=sys.stderr)
            return 2
        try:
            input_data = normalize_input_keys(json.loads(ipath.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            print(f"错误: --input JSON 解析失败: {exc}", file=sys.stderr)
            return 2
        except OSError as exc:
            print(f"错误: 读取 --input 失败: {exc}", file=sys.stderr)
            return 2

    if args.yes and not args.send:
        print("错误: --yes 只能与 --send 一起使用；默认不会发送。", file=sys.stderr)
        return 2

    try:
        doc = build_doc(args, input_data)
    except UsageError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2

    outbox = Path(
        args.outbox or input_data.get("outbox")
        or os.environ.get("AI_INFRA_FEEDBACK_OUTBOX") or DEFAULT_OUTBOX
    ).expanduser().resolve()
    staging_dir = Path(
        args.staging_dir or input_data.get("staging_dir")
        or os.environ.get("AI_INFRA_FEEDBACK_STAGING") or DEFAULT_STAGING
    ).expanduser().resolve()

    # 先脱敏，再落盘；路径字段不参与脱敏
    hits: collections.Counter = collections.Counter()
    doc = redact_obj(doc, hits)
    doc["redaction"] = {"applied": True, "hits": dict(hits), "total": sum(hits.values())}
    doc["paths"] = {"outbox": str(outbox), "markdown": "", "json": "",
                    "staging_candidate": "", "staging_index": ""}

    md_path, json_path = write_feedback_files(doc, outbox)
    doc["paths"]["markdown"] = str(md_path)
    doc["paths"]["json"] = str(json_path)

    cand_path = index_path = None
    if not args.no_staging:
        cand_path, index_path = write_staging_candidate(doc, staging_dir, not args.no_index)
        doc["paths"]["staging_candidate"] = str(cand_path) if cand_path else ""
        doc["paths"]["staging_index"] = str(index_path) if index_path else ""

    send_error = ""
    if args.send:
        chat_id = args.chat_id or os.environ.get("AI_INFRA_FEISHU_CHAT_ID", "")
        if not chat_id:
            print("错误: --send 需要 --chat-id 或环境变量 AI_INFRA_FEISHU_CHAT_ID。", file=sys.stderr)
            doc["delivery"].update({"status": "failed", "error": "未配置目标群 chat_id"})
            send_error = "未配置目标群 chat_id"
        else:
            lark_cli = discover_lark_cli()
            body = build_send_body(doc, args.max_send_chars)
            try:
                do_send(doc, args, body, chat_id, lark_cli)
            except RuntimeError as exc:
                send_error = str(exc)
    else:
        doc["delivery"]["status"] = "not_requested"

    # 回写最终 delivery / paths
    write_text(json_path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    write_text(md_path, render_markdown(doc))

    if args.json_summary:
        print(json.dumps({
            "ok": not send_error,
            "feedback_id": doc["feedback_id"],
            "title": doc["title"],
            "priority": doc["issue"]["priority"],
            "components": doc["issue"]["components"],
            "complete": doc["completeness"]["complete"],
            "missing_fields": doc["completeness"]["missing_fields"],
            "redaction_total": doc["redaction"]["total"],
            "delivery": doc["delivery"],
            "paths": doc["paths"],
        }, ensure_ascii=False, indent=2))
    else:
        print(f"反馈单已生成: {doc['feedback_id']}  [{doc['issue']['priority']}] {doc['title']}")
        print(f"  Markdown: {md_path}")
        print(f"  JSON    : {json_path}")
        if cand_path:
            print(f"  staging : {cand_path}（status=staged，未晋升）")
        if index_path:
            print(f"  INDEX   : {index_path}")
        if doc["completeness"]["missing_fields"]:
            print(f"  待补充  : {', '.join(doc['completeness']['missing_fields'])}")
        if doc["redaction"]["total"]:
            print(f"  已脱敏  : {doc['redaction']['total']} 处 {doc['redaction']['hits']}")
        if args.send:
            d = doc["delivery"]
            print(f"  投递    : {d['status']} (chat {d['chat_id_masked'] or '未配置'})")
            if d["status"] == "dry_run":
                print("  --- 将发送的内容（dry-run，未发起任何网络请求）---")
                print(d["body_preview"])
                print("  --- 将执行的命令 ---")
                print(d["command"])
                print("  提示: 确认无误后加 --yes 才会真正发送。")
    if send_error:
        if not args.json_summary:
            print(f"发送失败: {send_error}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
