#!/usr/bin/env python3
"""Universal AI IDE environment sync.

Claude Code (~/.claude) is the single master. Other AI IDEs are generated copies.
First sync only reports and records a baseline; later syncs update copies that have
not drifted and report every local divergence.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

VERSION = 1

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOME = Path(os.environ.get("AI_ENV_SYNC_HOME") or Path.home()).expanduser()
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (HOME / ".claude")).expanduser()
STATE_DIR_DEFAULT = Path(os.environ.get("AI_ENV_SYNC_STATE_DIR") or (HOME / ".ai-env-sync")).expanduser()
PROJECT_DEFAULT = Path(os.environ.get("AI_ENV_SYNC_PROJECT") or Path.cwd()).resolve()
if os.environ.get("AI_ENV_SYNC_APPDATA"):
    APPDATA = Path(os.environ["AI_ENV_SYNC_APPDATA"]).expanduser()
elif os.environ.get("AI_ENV_SYNC_HOME"):
    APPDATA = HOME / "AppData" / "Roaming"
else:
    APPDATA = Path(os.environ.get("APPDATA") or (HOME / "AppData" / "Roaming"))
CLAUDE_JSON = CLAUDE_DIR.parent / ".claude.json"
SKILL_NAME = "universal-env-sync"

IGNORED_DIRS = {".git", "__pycache__", ".skill-backups", ".ai-env-sync"}
IGNORED_FILES = {".DS_Store", "Thumbs.db"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}

SECRET_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|password|passwd|"
    r"authorization|credential|private[_-]?key)"
)
SECRET_PREFIXES = (
    "sk-", "ark-", "ghp_", "github_pat_", "xoxb-", "xoxp-", "xoxa-", "xoxr-",
    "AKIA", "ASIA", "glpat-", "hf_", "sk_live_", "sk_test_",
)
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

DEFAULT_CONFIG: dict[str, Any] = {
    "version": VERSION,
    "exclude_skills": [
        "apple-notes",
        "apple-reminders",
        "cc-connect-bridge",
        "colima-rosetta-x86-docker",
        "launchd-watchdog",
        "skill-creator",
        "lark-*",
    ],
    "exclude_agents": [],
    "sync_global_memory": True,
    "sync_project_memory": True,
    "include_shared_skills": True,
    "hook_events": {
        "qoder-cn": ["SessionStart", "UserPromptSubmit"],
        "codex": ["SessionStart", "UserPromptSubmit", "SessionEnd"],
    },
}


# ---------------------------------------------------------------------------
# small utilities
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def run_id() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_json_atomic(path: Path, data: Any) -> None:
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(read_text(path))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"无法解析 JSON: {path}: {exc}") from exc


def encode_path(path: Path) -> str:
    return re.sub(r"[\\/:]", "-", str(path))


def tree_files(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        return
    for item in sorted(root.rglob("*")):
        if item.is_dir():
            continue
        rel = item.relative_to(root)
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        if item.name in IGNORED_FILES or item.suffix in IGNORED_SUFFIXES:
            continue
        yield item


def tree_hash(root: Path) -> str | None:
    if not root.is_dir():
        return None
    digest = hashlib.sha256()
    found = False
    for item in tree_files(root):
        found = True
        rel = item.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest() if found else sha_text("")


def copy_tree(src: Path, dst: Path) -> None:
    ignore = shutil.ignore_patterns(*IGNORED_DIRS, *IGNORED_FILES, "*.pyc", "*.pyo")
    shutil.copytree(src, dst, ignore=ignore)


def replace_tree(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + f".envsync-{os.getpid()}")
    if tmp.exists():
        shutil.rmtree(tmp)
    copy_tree(src, tmp)
    if dst.is_dir():
        shutil.rmtree(dst)
    elif dst.exists():
        dst.unlink()
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            os.replace(tmp, dst)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.15 * (attempt + 1))
    # Windows 上目录句柄（杀毒、索引、IDE 监听）可能短暂占用目标路径，
    # 重命名失败时退化为逐文件复制，保证安装最终成功。
    try:
        copy_tree(tmp, dst)
    except Exception:
        raise last_error or RuntimeError(f"无法替换目录: {dst}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def file_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    return sha_text(read_text(path))


def mask_value(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "…" + value[-2:]


def excluded(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


# ---------------------------------------------------------------------------
# config / state / context
# ---------------------------------------------------------------------------

@dataclass
class Target:
    id: str
    label: str
    root: Path
    skills: Path | None = None
    agents: Path | None = None
    rules: Path | None = None
    memory: Path | None = None
    mcp_path: Path | None = None
    mcp_key: str = "mcpServers"
    mcp_format: str = "json"
    hooks_path: Path | None = None
    hooks_kind: str = "claude"
    hook_events: list[str] = field(default_factory=list)
    agent_fmt: str = "markdown"
    project_only: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class Asset:
    kind: str
    name: str
    target: str
    key: str
    master_path: Path | None = None
    target_path: Path | None = None
    expected_hash: str | None = None
    target_hash: str | None = None
    expected_text: str | None = None
    expected_obj: Any = None
    current_obj: Any = None
    is_dir: bool = False
    status: str = "unknown"
    action: str = "none"
    note: str = ""
    marker: str | None = None
    block_text: str | None = None
    current_block: str | None = None
    hook_event: str | None = None
    hook_basename: str | None = None
    matcher: str | None = None
    external: bool = False
    target_only: bool = False
    master_missing: bool = False
    blocked: bool = False
    findings: list[str] = field(default_factory=list)
    fmt: str | None = None
    preserve_frontmatter: bool = False


class Ctx:
    def __init__(self, state_dir: Path, project: Path):
        self.state_dir = state_dir
        self.project = project
        self.reports_dir = state_dir / "reports"
        self.backups_root = state_dir / "backups"
        self.state_file = state_dir / "state.json"
        self.config_file = state_dir / "config.json"
        self.run_id = run_id()
        self.json_cache: dict[Path, Any] = {}
        self.backed_up: set[Path] = set()
        self.config = self._load_config()
        self.targets = detect_targets(self.config, self.project)
        self.unsupported: list[dict[str, str]] = []

    def _load_config(self) -> dict[str, Any]:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        if self.config_file.exists():
            try:
                user = load_json(self.config_file, {})
            except SystemExit:
                user = {}
            if isinstance(user, dict):
                for key, value in user.items():
                    if isinstance(value, dict) and isinstance(config.get(key), dict):
                        config[key].update(value)
                    else:
                        config[key] = value
        return config

    def ensure_dirs(self) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.backups_root.mkdir(parents=True, exist_ok=True)

    def save_config(self) -> None:
        self.ensure_dirs()
        if not self.config_file.exists():
            write_json_atomic(self.config_file, self.config)

    def load_state(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {"version": VERSION, "initialized": False, "assets": {}}
        try:
            state = load_json(self.state_file, {})
        except SystemExit:
            return {"version": VERSION, "initialized": False, "assets": {}}
        state.setdefault("assets", {})
        return state

    def save_state(self, state: dict[str, Any]) -> None:
        self.ensure_dirs()
        state["version"] = VERSION
        state["master"] = str(CLAUDE_DIR)
        state["updated_at"] = now_iso()
        write_json_atomic(self.state_file, state)

    def backup(self, path: Path) -> None:
        if path in self.backed_up or not path.exists():
            self.backed_up.add(path)
            return
        try:
            rel = path.resolve().relative_to(HOME.resolve())
        except ValueError:
            rel = Path(re.sub(r"[\\/:]", "_", str(path.resolve())))
        dst = self.backups_root / self.run_id / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            copy_tree(path, dst)
        else:
            shutil.copy2(path, dst)
        self.backed_up.add(path)

    def read_json(self, path: Path, default: Any) -> Any:
        if path in self.json_cache:
            return self.json_cache[path]
        data = load_json(path, json.loads(json.dumps(default)))
        self.json_cache[path] = data
        return data

    def write_json(self, path: Path, data: Any) -> None:
        self.backup(path)
        write_json_atomic(path, data)
        self.json_cache[path] = data

    def note_unsupported(self, target: str, area: str, message: str) -> None:
        self.unsupported.append({"target": target, "area": area, "message": message})


def detect_targets(config: dict[str, Any], project: Path) -> list[Target]:
    targets: list[Target] = []

    qcn = HOME / ".qoder-cn"
    if qcn.is_dir():
        targets.append(Target(
            "qoder-cn", "Qoder CN", qcn,
            skills=qcn / "skills", agents=qcn / "agents", memory=qcn / "memory",
            mcp_path=qcn / "settings.json", mcp_key="mcpServers", mcp_format="json",
            hooks_path=qcn / "settings.json", hooks_kind="claude",
            hook_events=list(config.get("hook_events", {}).get("qoder-cn", ["SessionStart", "UserPromptSubmit"])),
            agent_fmt="markdown",
        ))

    qide = HOME / ".qoder"
    if qide.is_dir():
        targets.append(Target(
            "qoder", "Qoder IDE", qide,
            skills=qide / "skills", agents=qide / "agents",
            mcp_path=qide / "mcp.json", mcp_key="mcpServers", mcp_format="json",
            agent_fmt="markdown",
        ))
        targets.append(Target(
            "qoder-rules", "Qoder 规则（CN/IDE 共享）", qide,
            rules=qide / "rules",
        ))

    tcn = HOME / ".trae-cn"
    if tcn.is_dir():
        targets.append(Target(
            "trae-cn", "TRAE CN", tcn,
            skills=tcn / "skills", rules=tcn / "user_rules", memory=tcn / "memory",
            mcp_path=APPDATA / "Trae CN" / "User" / "mcp.json", mcp_key="mcpServers",
            agent_fmt="trae",
        ))

    trae = HOME / ".trae"
    if trae.is_dir():
        targets.append(Target(
            "trae", "TRAE", trae,
            skills=trae / "skills", rules=trae / "user_rules", memory=trae / "memory",
            mcp_path=APPDATA / "Trae" / "User" / "mcp.json", mcp_key="mcpServers",
            agent_fmt="trae",
        ))

    if tcn.is_dir() or trae.is_dir():
        targets.append(Target(
            "trae-project", "TRAE 当前项目", project,
            agents=project / ".github" / "agents",
            mcp_path=project / ".trae" / "mcp.json", mcp_key="mcpServers",
            agent_fmt="trae", project_only=True,
        ))

    codex = HOME / ".codex"
    if codex.is_dir():
        targets.append(Target(
            "codex", "Codex", codex,
            skills=codex / "skills", agents=codex / "agents",
            mcp_path=codex / "config.toml", mcp_key="mcp_servers", mcp_format="toml",
            hooks_path=codex / "hooks.json", hooks_kind="codex",
            hook_events=list(config.get("hook_events", {}).get("codex", ["SessionStart", "UserPromptSubmit", "SessionEnd"])),
            agent_fmt="toml",
        ))

    if config.get("include_shared_skills", True):
        shared = HOME / ".agents"
        if shared.is_dir():
            targets.append(Target(
                "agents-shared", "共享 skills (~/.agents)", shared,
                skills=shared / "skills",
            ))

    return targets


# ---------------------------------------------------------------------------
# frontmatter / agent rendering
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, text

    data: dict[str, Any] = {}
    index = 1
    while index < end:
        raw = lines[index]
        if not raw.strip() or raw.lstrip().startswith("#") or raw[:1].isspace():
            index += 1
            continue
        if ":" not in raw:
            index += 1
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            items: list[str] = []
            index += 1
            while index < end and (not lines[index].strip() or lines[index][:1].isspace()):
                item = lines[index].strip()
                if item.startswith("- "):
                    items.append(item[2:].strip().strip("\"'"))
                index += 1
            data[key] = items
            continue
        if value.startswith("[") and value.endswith("]"):
            try:
                data[key] = [str(item).strip().strip("\"'") for item in value[1:-1].split(",") if item.strip()]
            except Exception:
                data[key] = value
        else:
            data[key] = value.strip("\"'")
        index += 1
    body = "\n".join(lines[end + 1:]).strip() + "\n"
    return data, body


def split_frontmatter(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            frontmatter = "\n".join(lines[: index + 1]).strip() + "\n"
            body = "\n".join(lines[index + 1:]).strip() + "\n"
            return frontmatter, body
    return "", text


def agent_record(path: Path) -> dict[str, Any]:
    text = read_text(path)
    meta, body = parse_frontmatter(text)
    name = str(meta.get("name") or path.stem)
    tools = meta.get("tools") or []
    if isinstance(tools, str):
        tools = [item.strip() for item in tools.split(",") if item.strip()]
    return {
        "name": re.sub(r"[^A-Za-z0-9_-]", "-", name).strip("-") or path.stem,
        "description": str(meta.get("description") or ""),
        "tools": tools,
        "model": str(meta.get("model") or ""),
        "body": body,
        "raw": text,
    }


def yaml_quote(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def render_claude_agent(agent: dict[str, Any]) -> str:
    lines = ["---", f"name: {yaml_quote(agent['name'])}", f"description: {yaml_quote(agent['description'])}"]
    if agent.get("tools"):
        lines.append(f"tools: {yaml_quote(', '.join(agent['tools']))}")
    if agent.get("model"):
        lines.append(f"model: {yaml_quote(agent['model'])}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + agent["body"].strip() + "\n"


def toml_quote(value: str) -> str:
    out = ['"']
    for char in str(value):
        if char == "\\":
            out.append("\\\\")
        elif char == '"':
            out.append('\\"')
        elif char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif char == "\t":
            out.append("\\t")
        elif ord(char) < 0x20:
            out.append(f"\\u{ord(char):04X}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def render_codex_agent(agent: dict[str, Any]) -> str:
    lines = [
        f"name = {toml_quote(agent['name'])}",
        f"description = {toml_quote(agent['description'])}",
        f"nickname_candidates = [{toml_quote(agent['name'])}]",
        f"developer_instructions = {toml_quote(agent['body'].strip())}",
    ]
    return "\n".join(lines) + "\n"


def render_trae_agent(agent: dict[str, Any]) -> str:
    lines = ["---", f"name: {yaml_quote(agent['name'])}", f"description: {yaml_quote(agent['description'])}"]
    if agent.get("tools"):
        lines.append("tools:")
        for tool in agent["tools"]:
            lines.append(f"  - {yaml_quote(tool)}")
    if agent.get("model"):
        lines.append(f"model: {yaml_quote(agent['model'])}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + agent["body"].strip() + "\n"


def agent_expected(target: Target, agent: dict[str, Any]) -> tuple[str, str]:
    if target.agent_fmt == "toml":
        return render_codex_agent(agent), ".toml"
    if target.agent_fmt == "trae":
        return render_trae_agent(agent), ".agent.md"
    return agent["raw"].replace("\r\n", "\n").replace("\r", "\n"), ".md"


def normalize_tools(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def agent_semantic_hash(agent: dict[str, Any], fmt: str = "toml") -> str:
    payload = {
        "name": agent.get("name", ""),
        "description": agent.get("description", ""),
        "body": (agent.get("body") or "").strip(),
    }
    if fmt == "trae":
        payload["tools"] = normalize_tools(agent.get("tools"))
        payload["model"] = str(agent.get("model") or "")
    return sha_text(canonical(payload))


def agent_from_target(path: Path, fmt: str) -> dict[str, Any] | None:
    if fmt == "toml":
        try:
            data = tomllib.loads(read_text(path))
        except Exception:
            return None
        return {
            "name": str(data.get("name") or path.stem),
            "description": str(data.get("description") or ""),
            "body": (str(data.get("developer_instructions") or "")).strip() + "\n",
        }
    try:
        meta, body = parse_frontmatter(read_text(path))
    except Exception:
        return None
    return {
        "name": str(meta.get("name") or path.stem),
        "description": str(meta.get("description") or ""),
        "tools": meta.get("tools") or [],
        "model": str(meta.get("model") or ""),
        "body": body,
    }


# ---------------------------------------------------------------------------
# collectors
# ---------------------------------------------------------------------------

def new_asset(kind: str, name: str, target: str, **kwargs: Any) -> Asset:
    return Asset(kind=kind, name=name, target=target, key=f"{kind}:{name}@{target}", **kwargs)


def collect_skills(ctx: Ctx) -> list[Asset]:
    assets: list[Asset] = []
    master = CLAUDE_DIR / "skills"
    if not master.is_dir():
        return assets
    patterns = list(ctx.config.get("exclude_skills", []))
    all_master = sorted(d.name for d in master.iterdir() if d.is_dir() and (d / "SKILL.md").exists())
    included = [name for name in all_master if not excluded(name, patterns)]

    for target in ctx.targets:
        if not target.skills:
            continue
        for name in included:
            src = master / name
            dst = target.skills / name
            assets.append(new_asset(
                "skill", name, target.id,
                master_path=src, target_path=dst, is_dir=True,
                expected_hash=tree_hash(src),
                target_hash=tree_hash(dst) if dst.is_dir() else None,
            ))
        if target.skills.is_dir():
            for item in sorted(target.skills.iterdir()):
                if not item.is_dir() or item.name == ".system":
                    continue
                if item.name in all_master or excluded(item.name, patterns):
                    continue
                if (item / "SKILL.md").exists():
                    assets.append(new_asset(
                        "skill", item.name, target.id,
                        target_path=item, is_dir=True, target_only=True,
                        target_hash=tree_hash(item),
                    ))
    return assets


def collect_agents(ctx: Ctx) -> list[Asset]:
    assets: list[Asset] = []
    master = CLAUDE_DIR / "agents"
    if not master.is_dir():
        return assets
    patterns = list(ctx.config.get("exclude_agents", []))
    master_agents: dict[str, dict[str, Any]] = {}
    for path in sorted(master.glob("*.md")):
        if path.is_file():
            agent = agent_record(path)
            master_agents[agent["name"]] = agent

    for target in ctx.targets:
        if not target.agents:
            continue
        for name, agent in master_agents.items():
            if excluded(name, patterns):
                continue
            text, suffix = agent_expected(target, agent)
            dst = target.agents / f"{name}{suffix}"
            if target.agent_fmt in ("toml", "trae"):
                expected_hash = agent_semantic_hash(agent, target.agent_fmt)
                existing = agent_from_target(dst, target.agent_fmt) if dst.is_file() else None
                target_hash = agent_semantic_hash(existing, target.agent_fmt) if existing else file_hash(dst)
            else:
                expected_hash = sha_text(text)
                target_hash = file_hash(dst)
            assets.append(new_asset(
                "agent", name, target.id,
                master_path=master / f"{name}.md", target_path=dst,
                expected_text=text, expected_hash=expected_hash,
                target_hash=target_hash, fmt=target.agent_fmt,
            ))
        if target.agents.is_dir():
            for path in sorted(target.agents.iterdir()):
                if not path.is_file() or path.suffix.lower() not in (".md", ".toml"):
                    continue
                name = path.stem
                if path.suffix.lower() == ".toml":
                    try:
                        data = tomllib.loads(read_text(path))
                        name = str(data.get("name") or path.stem)
                    except Exception:
                        name = path.stem
                elif path.name.endswith(".agent.md"):
                    fallback = path.name[: -len(".agent.md")]
                    try:
                        name = str(parse_frontmatter(read_text(path))[0].get("name") or fallback)
                    except Exception:
                        name = fallback
                if name in master_agents or excluded(name, patterns):
                    continue
                assets.append(new_asset(
                    "agent", name, target.id,
                    target_path=path, target_only=True, fmt=target.agent_fmt,
                    target_hash=file_hash(path),
                ))
    return assets


def collect_rules(ctx: Ctx) -> list[Asset]:
    assets: list[Asset] = []
    rules_dir = CLAUDE_DIR / "rules"
    targets = [t for t in ctx.targets if t.rules]
    sources: list[tuple[str, Path]] = []
    if rules_dir.is_dir():
        sources.extend((path.stem, path) for path in sorted(rules_dir.glob("*.md")) if path.is_file())
    agents_md = CLAUDE_DIR / "AGENTS.md"
    if agents_md.is_file():
        sources.append(("_global_agents", agents_md))

    for target in targets:
        for name, src in sources:
            text = read_text(src)
            _, source_body = split_frontmatter(text)
            dst = target.rules / f"{name}.md"
            preserve = False
            expected_text = text
            target_hash = file_hash(dst)
            if dst.is_file():
                existing_text = read_text(dst)
                existing_fm, existing_body = split_frontmatter(existing_text)
                if existing_fm:
                    preserve = True
                    expected_text = source_body
                    target_hash = sha_text(existing_body)
            assets.append(new_asset(
                "rule", name, target.id,
                master_path=src, target_path=dst,
                expected_text=expected_text, expected_hash=sha_text(expected_text),
                target_hash=target_hash, preserve_frontmatter=preserve,
            ))
    return assets


def block_markers(kind: str) -> tuple[str, str]:
    return (
        f"<!-- >>> ai-env-sync:{kind} >>> -->",
        f"<!-- <<< ai-env-sync:{kind} <<< -->",
    )


def extract_block(text: str, kind: str) -> str | None:
    start, end = block_markers(kind)
    match = re.search(re.escape(start) + r"\s*(.*?)\s*" + re.escape(end), text, re.S)
    return match.group(1).strip() + "\n" if match else None


def render_block(kind: str, content: str) -> str:
    start, end = block_markers(kind)
    return f"{start}\n{content.rstrip()}\n{end}\n"


def block_asset(
    kind: str,
    name: str,
    target: Target,
    target_path: Path,
    content: str,
    master_path: Path | None = None,
) -> Asset:
    content = content.strip() + "\n"
    current = None
    if target_path.is_file():
        current = extract_block(read_text(target_path), kind)
    return new_asset(
        kind, name, target.id,
        master_path=master_path, target_path=target_path,
        expected_text=content, expected_hash=sha_text(content),
        target_hash=sha_text(current) if current is not None else None,
        block_text=content, current_block=current, marker=kind,
    )


def collect_prompts(ctx: Ctx) -> list[Asset]:
    assets: list[Asset] = []
    claude_md = CLAUDE_DIR / "CLAUDE.md"
    agents_md = CLAUDE_DIR / "AGENTS.md"
    if not claude_md.is_file():
        return assets
    prompt = read_text(claude_md)
    codex_prompt = prompt
    if agents_md.is_file():
        codex_prompt += "\n\n---\n\n" + read_text(agents_md)
    rules_dir = CLAUDE_DIR / "rules"
    if rules_dir.is_dir():
        rule_parts = []
        for path in sorted(rules_dir.glob("*.md")):
            rule_parts.append(f"## {path.stem}\n\n{read_text(path).strip()}")
        if rule_parts:
            codex_prompt += "\n\n---\n\n" + "\n\n".join(rule_parts)

    for target in ctx.targets:
        if target.rules:
            assets.append(block_asset(
                "prompt", "CLAUDE", target, target.rules / "_global_claude.md",
                prompt, master_path=claude_md,
            ))
        if target.id == "codex":
            assets.append(block_asset(
                "prompt", "AGENTS", target, target.root / "AGENTS.md",
                codex_prompt, master_path=claude_md,
            ))
    return assets


def detect_global_memory() -> Path | None:
    candidates = [CLAUDE_DIR / "memory", CLAUDE_DIR / "projects" / encode_path(HOME) / "memory"]
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.glob("*.md")):
            return candidate
    best: tuple[int, Path] | None = None
    projects = CLAUDE_DIR / "projects"
    if projects.is_dir():
        for candidate in projects.glob("*/memory"):
            if candidate.is_dir() and (candidate / "MEMORY.md").exists():
                count = len(list(candidate.glob("*.md")))
                if best is None or count > best[0]:
                    best = (count, candidate)
    return best[1] if best else None


def project_memory_dir(root: Path, project: Path) -> Path:
    return root / "projects" / encode_path(project) / "memory"


def memory_files(root: Path | None) -> list[Path]:
    if not root or not root.is_dir():
        return []
    return [path for path in sorted(root.glob("*.md")) if path.is_file()]


def collect_memory(ctx: Ctx) -> list[Asset]:
    assets: list[Asset] = []
    global_src = detect_global_memory()
    global_files = memory_files(global_src) if ctx.config.get("sync_global_memory", True) else []
    project_src = project_memory_dir(CLAUDE_DIR, ctx.project)
    project_files = memory_files(project_src) if ctx.config.get("sync_project_memory", True) else []

    for target in ctx.targets:
        if target.id == "qoder-cn":
            for path in global_files:
                dst = target.memory / path.name if target.memory else None
                if not dst:
                    continue
                assets.append(new_asset(
                    "memory", path.stem, target.id,
                    master_path=path, target_path=dst,
                    expected_text=read_text(path), expected_hash=file_hash(path),
                    target_hash=file_hash(dst),
                ))
            if target.memory and target.memory.is_dir():
                master_names = {path.name for path in global_files}
                for path in sorted(target.memory.glob("*.md")):
                    if path.name not in master_names:
                        assets.append(new_asset(
                            "memory", path.stem, target.id,
                            target_path=path, target_only=True, target_hash=file_hash(path),
                        ))
            project_target = project_memory_dir(target.root, ctx.project)
            for path in project_files:
                dst = project_target / path.name
                assets.append(new_asset(
                    "memory", f"project:{path.stem}", target.id,
                    master_path=path, target_path=dst,
                    expected_text=read_text(path), expected_hash=file_hash(path),
                    target_hash=file_hash(dst),
                ))
            if project_target.is_dir():
                master_names = {path.name for path in project_files}
                for path in sorted(project_target.glob("*.md")):
                    if path.name not in master_names:
                        assets.append(new_asset(
                            "memory", f"project:{path.stem}", target.id,
                            target_path=path, target_only=True, target_hash=file_hash(path),
                        ))

        elif target.id in ("trae-cn", "trae"):
            parts = ["## Claude 记忆（ai-env-sync 管理）", ""]
            for path in global_files:
                parts.append(f"### {path.stem}")
                parts.append("")
                parts.append(read_text(path).strip())
                parts.append("")
            if not global_files:
                continue
            content = "\n".join(parts).strip() + "\n"
            target_path = (target.memory or (target.root / "memory")) / "user_profile.md"
            assets.append(block_asset(
                "memory", "user_profile", target, target_path, content,
                master_path=global_src,
            ))
    return assets


def load_claude_mcp() -> dict[str, Any]:
    data = load_json(CLAUDE_JSON, {}) if CLAUDE_JSON.exists() else {}
    servers = data.get("mcpServers") or {}
    return servers if isinstance(servers, dict) else {}


def load_project_mcp(project: Path) -> dict[str, Any]:
    path = project / ".mcp.json"
    if not path.exists():
        return {}
    data = load_json(path, {})
    servers = data.get("mcpServers") or {}
    return servers if isinstance(servers, dict) else {}


def is_secret_value(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if value.startswith("${") or value.startswith("$"):
        return False
    if value.startswith(SECRET_PREFIXES):
        return True
    if any(token in value for token in ("api_key=", "apikey=", "token=", "secret=", "password=")):
        return True
    if re.fullmatch(r"[A-Z0-9_]+", value):
        return False
    if re.fullmatch(r"[0-9a-fA-F-]{36}", value):
        return False
    if len(value) >= 24 and "/" not in value and "\\" not in value and " " not in value:
        return bool(re.fullmatch(r"[A-Za-z0-9_\-\.]{24,}", value))
    return False


def sanitize_server(
    name: str,
    config: dict[str, Any],
    target: Target | None = None,
) -> tuple[dict[str, Any], list[str], bool]:
    data = json.loads(json.dumps(config))
    findings: list[str] = []
    blocked = False
    env_refs = target is None or target.id in ("qoder-cn", "qoder")

    env = data.get("env")
    if isinstance(env, dict):
        for key, value in list(env.items()):
            if not isinstance(value, str):
                continue
            is_ref = value.startswith("${") or value.startswith("$")
            if is_ref and not env_refs:
                del env[key]
                findings.append(f"env.{key} 的变量引用在目标不支持，已移除，依赖系统环境变量 {key}")
                continue
            if is_secret_value(value):
                if ENV_NAME_RE.match(str(key)):
                    if env_refs:
                        env[key] = f"${{{key}}}"
                        findings.append(f"env.{key} 已转为 ${{{key}}} 引用")
                    else:
                        del env[key]
                        findings.append(f"env.{key} 已移除明文，依赖系统环境变量 {key}")
                else:
                    env[key] = mask_value(value)
                    blocked = True
                    findings.append(f"env.{key} 含明文凭证，已拦截")
    headers = data.get("headers")
    if isinstance(headers, dict):
        for key, value in list(headers.items()):
            if str(key).lower() in ("authorization", "proxy-authorization") or (
                isinstance(value, str) and is_secret_value(value)
            ):
                blocked = True
                findings.append(f"headers.{key} 含明文凭证，已拦截")

    def walk(node: Any, path: str) -> None:
        nonlocal blocked
        if isinstance(node, dict):
            for key, value in node.items():
                if path.count(".") == 0 and key in ("env", "headers"):
                    continue
                if SECRET_KEY_RE.search(str(key)) and isinstance(value, str) and not value.startswith("${"):
                    blocked = True
                    findings.append(f"{path}.{key} 含明文凭证，已拦截")
                else:
                    walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            if path.endswith(".env_vars"):
                return
            for index, value in enumerate(node):
                if isinstance(value, str) and is_secret_value(value):
                    blocked = True
                    findings.append(f"{path}[{index}] 疑似凭证，已拦截")
                else:
                    walk(value, f"{path}[{index}]")

    for key, value in data.items():
        if key not in ("env", "headers"):
            walk(value, name)

    url = data.get("url")
    if isinstance(url, str) and "://" in url and "@" in url.split("://", 1)[1].split("/", 1)[0]:
        blocked = True
        findings.append("url 含内嵌凭证，已拦截")
    return data, findings, blocked


def convert_mcp_server(target: Target, server: dict[str, Any]) -> dict[str, Any]:
    data = json.loads(json.dumps(server))
    if target.id.startswith("trae"):
        data.pop("type", None)
        if "command" in data:
            allowed = {"command", "args", "env", "cwd", "disabled", "fromGalleryId"}
        else:
            allowed = {"url", "headers", "oauth", "fromGalleryId", "disabled"}
        data = {key: value for key, value in data.items() if key in allowed}
        if data.get("env") == {}:
            data.pop("env", None)
    elif target.id in ("qoder-cn", "qoder"):
        for key in ("env_vars", "startup_timeout_sec", "tool_timeout_sec", "enabled"):
            data.pop(key, None)
    if target.mcp_format == "toml":
        codex: dict[str, Any] = {}
        for key in ("command", "args", "env", "url", "env_vars", "startup_timeout_sec", "tool_timeout_sec", "enabled"):
            if key in data:
                if key == "env" and data[key] == {}:
                    continue
                codex[key] = data[key]
        if "headers" in data:
            codex["http_headers"] = data["headers"]
        return codex
    return data


CODEX_TARGET_ONLY_MCP_KEYS = ("env_vars", "startup_timeout_sec", "tool_timeout_sec", "enabled")


def mcp_compare_obj(target: Target, server: dict[str, Any] | None) -> dict[str, Any] | None:
    if server is None:
        return None
    data = json.loads(json.dumps(server))
    if target.mcp_format == "toml":
        for key in CODEX_TARGET_ONLY_MCP_KEYS:
            data.pop(key, None)
    return data


def read_target_servers(target: Target) -> dict[str, Any]:
    if not target.mcp_path or not target.mcp_path.exists():
        return {}
    if target.mcp_format == "toml":
        try:
            data = tomllib.loads(read_text(target.mcp_path))
        except Exception:
            return {}
        servers = data.get("mcp_servers") or {}
        return servers if isinstance(servers, dict) else {}
    try:
        data = load_json(target.mcp_path, {})
    except SystemExit:
        return {}
    servers = data.get(target.mcp_key) or {}
    return servers if isinstance(servers, dict) else {}


def collect_mcp(ctx: Ctx) -> list[Asset]:
    assets: list[Asset] = []
    user_servers = load_claude_mcp()
    project_servers = load_project_mcp(ctx.project)

    for target in ctx.targets:
        if not target.mcp_path:
            continue
        source = project_servers if target.project_only else user_servers
        current_all = read_target_servers(target)
        for name, server in source.items():
            sanitized, findings, blocked = sanitize_server(name, server, target)
            expected = convert_mcp_server(target, sanitized)
            current = current_all.get(name)
            assets.append(new_asset(
                "mcp", name, target.id,
                master_path=(ctx.project / ".mcp.json") if target.project_only else CLAUDE_JSON,
                target_path=target.mcp_path,
                expected_obj=expected, current_obj=current,
                expected_hash=sha_text(canonical(expected)),
                target_hash=sha_text(canonical(mcp_compare_obj(target, current))) if current is not None else None,
                blocked=blocked, findings=findings,
            ))
        for name, current in current_all.items():
            if name in source:
                continue
            assets.append(new_asset(
                "mcp", name, target.id,
                target_path=target.mcp_path, current_obj=current,
                target_only=True, target_hash=sha_text(canonical(current)),
            ))

    if (HOME / ".qoder-cn").is_dir() and (ctx.project / ".mcp.json").exists():
        ctx.note_unsupported("qoder-cn", "project-mcp", "Qoder CN 直接读取项目 .mcp.json，无需复制")
    if (HOME / ".qoder").is_dir() and (ctx.project / ".mcp.json").exists():
        ctx.note_unsupported("qoder", "project-mcp", "Qoder IDE 项目级 MCP 落点未验证，未写入")
    if (HOME / ".codex").is_dir() and (ctx.project / ".mcp.json").exists():
        ctx.note_unsupported("codex", "project-mcp", "Codex 未验证项目级 MCP，未写入")
    return assets


# ---------------------------------------------------------------------------
# hooks
# ---------------------------------------------------------------------------

def hook_managed_dir(target: Target) -> Path:
    return target.root / ".ai-env-sync" / "hooks"


def is_managed_command(command: str) -> bool:
    return ".ai-env-sync" in command.replace("\\", "/")


def hook_tree_hash(root: Path) -> str:
    if not root.is_dir():
        return ""
    tokens = {
        str(root),
        str(root).replace("\\", "/"),
        str(CLAUDE_DIR / "hooks"),
        str(CLAUDE_DIR / "hooks").replace("\\", "/"),
        "~/.claude/hooks",
    }
    digest = hashlib.sha256()
    found = False
    for item in tree_files(root):
        found = True
        rel = item.relative_to(root).as_posix()
        data = item.read_bytes()
        if item.suffix.lower() == ".cmd":
            text = data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
            for token in sorted(tokens, key=len, reverse=True):
                if token:
                    text = text.replace(token, "{{HOOKS}}")
            data = text.encode("utf-8")
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest() if found else ""


def load_hook_config(ctx: Ctx, target: Target) -> dict[str, Any]:
    default = {"hooks": {}}
    if not target.hooks_path:
        return default
    return ctx.read_json(target.hooks_path, default)


def find_hook(entries: dict[str, Any], event: str, basename: str) -> tuple[int, int, dict[str, Any]] | None:
    for group_index, group in enumerate(entries.get(event, [])):
        for hook_index, hook in enumerate(group.get("hooks", [])):
            command = str(hook.get("command") or hook.get("commandWindows") or "")
            if Path(command.replace("\\", "/")).name.lower() == basename.lower():
                return group_index, hook_index, hook
    return None


def collect_hooks(ctx: Ctx) -> list[Asset]:
    assets: list[Asset] = []
    settings_path = CLAUDE_DIR / "settings.json"
    if not settings_path.is_file():
        return assets
    try:
        master = load_json(settings_path, {})
    except SystemExit:
        return assets
    master_hooks = master.get("hooks") or {}
    if not isinstance(master_hooks, dict):
        return assets
    master_tree = hook_tree_hash(CLAUDE_DIR / "hooks")

    for target in ctx.targets:
        if not target.hooks_path or not target.hook_events:
            if target.id in ("qoder", "trae-cn", "trae"):
                ctx.note_unsupported(target.id, "hooks", "该目标没有已验证的用户级 hook 机制，未写入")
            continue
        config = load_hook_config(ctx, target)
        entries = config.get("hooks") or {}
        if not isinstance(entries, dict):
            entries = {}
        for event in target.hook_events:
            for group in master_hooks.get(event, []):
                matcher = group.get("matcher")
                for hook in group.get("hooks", []):
                    command = str(hook.get("command") or "")
                    if not command:
                        continue
                    basename = Path(command.replace("\\", "/")).name
                    current = find_hook(entries, event, basename)
                    expected_command = str(hook_managed_dir(target) / "win" / basename)
                    expected: dict[str, Any] = {
                        "type": "command",
                        "command": expected_command,
                        "timeout": int(hook.get("timeout") or 10),
                    }
                    if target.hooks_kind == "codex":
                        expected["commandWindows"] = expected_command
                    asset = new_asset(
                        "hook", f"{event}:{basename}", target.id,
                        master_path=settings_path, target_path=target.hooks_path,
                        expected_obj=expected,
                        expected_hash=sha_text(canonical(expected) + master_tree),
                        hook_event=event, hook_basename=basename, matcher=matcher,
                    )
                    if current:
                        _, _, found = current
                        command_now = str(found.get("command") or found.get("commandWindows") or "")
                        asset.current_obj = found
                        asset.target_hash = sha_text(canonical(found) + hook_tree_hash(hook_managed_dir(target)))
                        if is_managed_command(command_now):
                            pass
                        else:
                            asset.external = True
                            asset.note = "目标已有同名 hook，保留目标版本"
                    assets.append(asset)

        managed_pairs: set[tuple[str, str]] = set()
        for event, groups in entries.items():
            if not isinstance(groups, list):
                continue
            for group in groups:
                if not isinstance(group, dict):
                    continue
                for hook in group.get("hooks", []):
                    command = str(hook.get("command") or hook.get("commandWindows") or "")
                    if is_managed_command(command):
                        managed_pairs.add((str(event), Path(command.replace("\\", "/")).name))
        master_pairs = {
            (event, Path(str(hook.get("command") or "")).name)
            for event in target.hook_events
            for group in master_hooks.get(event, [])
            for hook in group.get("hooks", [])
        }
        for event, basename in sorted(managed_pairs - master_pairs):
            asset = new_asset(
                "hook", f"{event}:{basename}", target.id,
                target_path=target.hooks_path, target_only=True,
                note="受管 hook 已不在主源，可用 --prune 移除",
            )
            asset.hook_event = event
            asset.hook_basename = basename
            assets.append(asset)
    return assets


def copy_hook_tree(ctx: Ctx, target: Target) -> None:
    src = CLAUDE_DIR / "hooks"
    if not src.is_dir():
        return
    dst = hook_managed_dir(target)
    ctx.backup(dst)
    replace_tree(src, dst)
    old_forward = str(CLAUDE_DIR / "hooks").replace("\\", "/")
    new_forward = str(dst).replace("\\", "/")
    old_back = str(CLAUDE_DIR / "hooks")
    new_back = str(dst)
    for path in dst.rglob("*.cmd"):
        text = read_text(path)
        text = text.replace("~/.claude/hooks/", new_forward + "/")
        text = text.replace(old_forward + "/", new_forward + "/")
        text = text.replace(old_back + "\\", new_back + "\\")
        write_text_atomic(path, text)


def upsert_hook(config: dict[str, Any], asset: Asset) -> bool:
    entries = config.setdefault("hooks", {})
    event = asset.hook_event or ""
    groups = entries.setdefault(event, [])
    expected = asset.expected_obj
    basename = asset.hook_basename or ""
    for group in groups:
        for hook in group.get("hooks", []):
            command = str(hook.get("command") or hook.get("commandWindows") or "")
            if is_managed_command(command) and Path(command.replace("\\", "/")).name.lower() == basename.lower():
                hook.clear()
                hook.update(expected)
                return True
    matcher = asset.matcher
    for group in groups:
        if group.get("matcher") == matcher:
            group.setdefault("hooks", []).append(json.loads(json.dumps(expected)))
            return True
    new_group: dict[str, Any] = {"hooks": [json.loads(json.dumps(expected))]}
    if matcher:
        new_group["matcher"] = matcher
    groups.append(new_group)
    return True


def remove_managed_hook(config: dict[str, Any], event: str, basename: str) -> bool:
    entries = config.get("hooks") or {}
    groups = entries.get(event, [])
    for group in list(groups):
        hooks = group.get("hooks", [])
        for hook in list(hooks):
            command = str(hook.get("command") or hook.get("commandWindows") or "")
            if is_managed_command(command) and Path(command.replace("\\", "/")).name.lower() == basename.lower():
                hooks.remove(hook)
                if not hooks and group in groups:
                    groups.remove(group)
                if not groups:
                    entries.pop(event, None)
                return True
    return False


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------

STATUS_LABELS = {
    "clean": "一致",
    "missing": "待创建",
    "missing-block": "待写入受管区块",
    "update": "待更新",
    "drift": "冲突/漂移",
    "target-only": "目标独有",
    "master-deleted": "主源已删除",
    "blocked-secret": "密钥拦截",
    "external": "目标已有同类项",
    "unsupported": "不支持",
    "new": "主源新增",
}


def evaluate(assets: list[Asset], state: dict[str, Any], first: bool) -> None:
    entries = state.get("assets", {})
    for asset in assets:
        if asset.target_only:
            asset.status = "target-only"
            asset.action = "report"
            continue
        if asset.external:
            asset.status = "external"
            asset.action = "none"
            continue
        if asset.master_missing:
            baseline = entries.get(asset.key) or {}
            target_changed = asset.target_hash != baseline.get("target_hash")
            asset.status = "master-deleted"
            asset.action = "prune" if (asset.target_hash is None or not target_changed) else "report"
            if asset.target_hash is None:
                asset.action = "prune"
            continue
        if asset.blocked:
            asset.status = "blocked-secret"
            asset.action = "report"
            continue
        if not asset.expected_hash:
            asset.status = "unsupported"
            asset.action = "report"
            continue

        baseline = entries.get(asset.key)
        target_hash = asset.target_hash
        expected_hash = asset.expected_hash

        if asset.marker:
            _evaluate_block(asset, baseline, first)
            continue

        if baseline is None:
            if target_hash is None:
                asset.status = "missing"
                asset.action = "report-first-run" if first else "create"
            elif target_hash == expected_hash:
                asset.status = "clean"
            else:
                asset.status = "drift"
                asset.action = "report"
                asset.note = "首跑发现差异" if first else "目标内容与主源不同"
            continue

        relation = baseline.get("relation", "clean")
        master_changed = expected_hash != baseline.get("master_hash")
        target_changed = target_hash != baseline.get("target_hash")

        if relation == "blocked":
            if master_changed:
                relation = "clean"
            else:
                asset.status = "blocked-secret"
                asset.action = "report"
                continue
        if relation == "external":
            asset.status = "external"
            asset.action = "none"
            continue
        if relation == "master-deleted":
            if expected_hash is None:
                asset.status = "master-deleted"
                asset.action = "prune" if (not target_changed) else "report"
                continue

        if relation == "drift":
            if target_hash is None:
                asset.status = "missing"
                asset.action = "report-first-run" if first else "create"
                asset.note = "目标副本已删除，可重新创建"
            elif target_hash == expected_hash:
                asset.status = "clean"
                asset.note = "已与主源对齐"
            else:
                asset.status = "drift"
                asset.action = "report"
                asset.note = "已有冲突，未自动覆盖"
            continue

        if target_hash is None:
            asset.status = "missing"
            asset.action = "report-first-run" if first else "create"
        elif expected_hash is None:
            asset.status = "master-deleted"
            asset.action = "prune" if (not target_changed) else "report"
        elif target_hash == expected_hash:
            asset.status = "clean"
        elif not target_changed and master_changed:
            asset.status = "update"
            asset.action = "report-first-run" if first else "update"
        else:
            asset.status = "drift"
            asset.action = "report"
            asset.note = "目标被本地修改" if target_changed else "主源与目标不一致"


def _evaluate_block(asset: Asset, baseline: dict[str, Any] | None, first: bool) -> None:
    target_hash = asset.target_hash
    expected_hash = asset.expected_hash
    if asset.target_path and asset.target_path.is_file() and asset.current_block is None:
        asset.status = "missing-block"
        asset.action = "report-first-run" if first else "append-block"
        asset.note = "文件存在但缺少受管区块，将在保留原文的前提下追加"
        return
    if baseline is None:
        if target_hash is None:
            asset.status = "missing"
            asset.action = "report-first-run" if first else "create"
        elif target_hash == expected_hash:
            asset.status = "clean"
        else:
            asset.status = "drift"
            asset.action = "report"
            asset.note = "首跑发现差异" if first else "受管区块与主源不同"
        return
    relation = baseline.get("relation", "clean")
    master_changed = expected_hash != baseline.get("master_hash")
    target_changed = target_hash != baseline.get("target_hash")
    if relation == "drift":
        if target_hash == expected_hash:
            asset.status = "clean"
            asset.note = "已与主源对齐"
        else:
            asset.status = "drift"
            asset.action = "report"
            asset.note = "已有冲突，未自动覆盖"
        return
    if target_hash is None:
        if asset.target_path and not asset.target_path.exists():
            asset.status = "missing"
            asset.action = "report-first-run" if first else "create"
        else:
            asset.status = "missing-block"
            asset.action = "report-first-run" if first else "append-block"
    elif target_hash == expected_hash:
        asset.status = "clean"
    elif not target_changed and master_changed:
        asset.status = "update"
        asset.action = "report-first-run" if first else "update"
    else:
        asset.status = "drift"
        asset.action = "report"
        asset.note = "受管区块被本地修改"


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

def write_block(path: Path, kind: str, content: str, ctx: Ctx) -> None:
    ctx.backup(path)
    start, end = block_markers(kind)
    block = render_block(kind, content)
    if path.exists():
        text = read_text(path)
        pattern = re.compile(re.escape(start) + r".*?" + re.escape(end) + r"\s*", re.S)
        if pattern.search(text):
            text = pattern.sub(block, text, count=1)
        else:
            text = text.rstrip() + "\n\n" + block
    else:
        text = block
    write_text_atomic(path, text)


def apply_asset(ctx: Ctx, asset: Asset) -> bool:
    if asset.action in ("none", "report", "report-first-run"):
        return False
    if asset.kind in ("skill",) and asset.master_path and asset.target_path:
        ctx.backup(asset.target_path)
        replace_tree(asset.master_path, asset.target_path)
        asset.target_hash = tree_hash(asset.target_path)
        return True
    if asset.kind == "agent" and asset.expected_text is not None and asset.target_path:
        ctx.backup(asset.target_path)
        write_text_atomic(asset.target_path, asset.expected_text)
        asset.target_hash = asset.expected_hash if asset.fmt in ("toml", "trae") else sha_text(asset.expected_text)
        return True
    if asset.kind == "rule" and asset.expected_text is not None and asset.target_path:
        ctx.backup(asset.target_path)
        if asset.preserve_frontmatter and asset.target_path.is_file():
            existing_fm, _ = split_frontmatter(read_text(asset.target_path))
            text = existing_fm + "\n" + asset.expected_text if existing_fm else asset.expected_text
        else:
            text = asset.expected_text
        write_text_atomic(asset.target_path, text)
        asset.target_hash = asset.expected_hash
        return True
    if asset.kind == "memory" and asset.expected_text is not None and asset.target_path and not asset.marker:
        ctx.backup(asset.target_path)
        write_text_atomic(asset.target_path, asset.expected_text)
        asset.target_hash = sha_text(asset.expected_text)
        return True
    if asset.kind in ("prompt", "memory") and asset.marker and asset.block_text is not None and asset.target_path:
        write_block(asset.target_path, asset.marker, asset.block_text, ctx)
        asset.current_block = extract_block(read_text(asset.target_path), asset.marker) if asset.target_path.exists() else None
        asset.target_hash = sha_text(asset.current_block) if asset.current_block is not None else None
        return True
    return False


def apply_mcp(ctx: Ctx, assets: list[Asset], prune: bool) -> None:
    by_target: dict[str, list[Asset]] = {}
    for asset in assets:
        if asset.kind == "mcp" and not asset.target_only:
            by_target.setdefault(asset.target, []).append(asset)
    target_map = {target.id: target for target in ctx.targets}

    for target_id, group in by_target.items():
        target = target_map.get(target_id)
        if not target or not target.mcp_path:
            continue
        if not any(asset.action in ("create", "update", "prune") for asset in group):
            continue
        if target.mcp_format == "toml":
            apply_codex_mcp(ctx, target, group, prune)
            continue

        data = ctx.read_json(target.mcp_path, {})
        servers = data.get(target.mcp_key)
        if not isinstance(servers, dict):
            servers = {}
            data[target.mcp_key] = servers
        changed = False
        for asset in group:
            if asset.action in ("create", "update"):
                servers[asset.name] = json.loads(json.dumps(asset.expected_obj))
                asset.target_hash = asset.expected_hash
                asset.status = "clean"
                asset.action = "none"
                changed = True
            elif asset.action == "prune" and prune:
                if servers.pop(asset.name, None) is not None:
                    changed = True
        if changed:
            ctx.write_json(target.mcp_path, data)


def toml_key(key: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", key):
        return key
    return toml_quote(key)


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return toml_quote(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{toml_key(str(k))} = {toml_value(v)}" for k, v in value.items()) + " }"
    return toml_quote(str(value))


CODEX_START = "# >>> ai-env-sync:mcp >>>"
CODEX_END = "# <<< ai-env-sync:mcp <<<"


def render_codex_mcp(servers: dict[str, Any]) -> str:
    lines = [CODEX_START]
    for name, server in servers.items():
        lines.append(f"[mcp_servers.{toml_key(name)}]")
        for key, value in server.items():
            if isinstance(value, dict):
                continue
            lines.append(f"{toml_key(key)} = {toml_value(value)}")
        for key, value in server.items():
            if not isinstance(value, dict):
                continue
            lines.append("")
            lines.append(f"[mcp_servers.{toml_key(name)}.{toml_key(key)}]")
            for sub_key, sub_value in value.items():
                lines.append(f"{toml_key(str(sub_key))} = {toml_value(sub_value)}")
        lines.append("")
    lines.append(CODEX_END)
    return "\n".join(lines) + "\n"


def apply_codex_mcp(ctx: Ctx, target: Target, assets: list[Asset], prune: bool) -> None:
    path = target.mcp_path
    assert path is not None
    text = read_text(path) if path.exists() else ""
    pattern = re.compile(re.escape(CODEX_START) + r".*?" + re.escape(CODEX_END) + r"\s*", re.S)
    existing_block = pattern.search(text)
    block_text = existing_block.group(0) if existing_block else ""
    text_without = pattern.sub("", text).rstrip() + "\n" if existing_block else text

    try:
        parsed = tomllib.loads(text_without) if text_without.strip() else {}
    except Exception:
        parsed = {}
    external = parsed.get("mcp_servers") or {}

    block_servers: dict[str, Any] = {}
    if existing_block:
        try:
            parsed_block = tomllib.loads(block_text)
            block_servers = parsed_block.get("mcp_servers") or {}
        except Exception:
            block_servers = {}

    result: dict[str, Any] = {}
    for name, server in block_servers.items():
        result[name] = server
    for asset in assets:
        if asset.blocked:
            result.pop(asset.name, None)
            continue
        if asset.external:
            continue
        if asset.name in external:
            if asset.action in ("create", "update"):
                asset.note = "Codex 已存在非受管同名服务器，未覆盖"
            continue
        if asset.action in ("create", "update"):
            merged = json.loads(json.dumps(asset.expected_obj))
            previous = block_servers.get(asset.name) or {}
            for key in CODEX_TARGET_ONLY_MCP_KEYS:
                if key not in merged and key in previous:
                    merged[key] = previous[key]
            result[asset.name] = merged
            asset.target_hash = asset.expected_hash
            asset.status = "clean"
            asset.action = "none"
        elif asset.action == "prune" and prune:
            result.pop(asset.name, None)
    content = render_codex_mcp(result) if result else ""
    new_text = text_without.rstrip()
    if new_text:
        new_text += "\n\n"
    new_text += content
    ctx.backup(path)
    write_text_atomic(path, new_text)


def apply_hooks(ctx: Ctx, assets: list[Asset], prune: bool) -> None:
    by_target: dict[str, list[Asset]] = {}
    for asset in assets:
        if asset.kind == "hook" and not asset.target_only:
            by_target.setdefault(asset.target, []).append(asset)
    target_map = {target.id: target for target in ctx.targets}

    for target_id, group in by_target.items():
        target = target_map.get(target_id)
        if not target or not target.hooks_path:
            continue
        if not any(asset.action in ("create", "update", "prune") for asset in group):
            continue
        copy_hook_tree(ctx, target)
        config = load_hook_config(ctx, target)
        for asset in group:
            if asset.action in ("create", "update"):
                upsert_hook(config, asset)
                asset.target_hash = asset.expected_hash
                asset.status = "clean"
                asset.action = "none"
            elif asset.action == "prune" and prune and asset.hook_event and asset.hook_basename:
                remove_managed_hook(config, asset.hook_event, asset.hook_basename)
        ctx.write_json(target.hooks_path, config)


def apply_prune_files(ctx: Ctx, assets: list[Asset]) -> None:
    for asset in assets:
        if asset.kind not in ("skill", "agent", "rule", "memory") or asset.marker:
            continue
        if asset.action != "prune" or not asset.target_path:
            continue
        ctx.backup(asset.target_path)
        if asset.target_path.is_dir():
            shutil.rmtree(asset.target_path)
        elif asset.target_path.exists():
            asset.target_path.unlink()


# ---------------------------------------------------------------------------
# state maintenance
# ---------------------------------------------------------------------------

def relation_for(asset: Asset) -> str:
    if asset.status in ("clean",):
        return "clean"
    if asset.status == "drift":
        return "drift"
    if asset.status == "blocked-secret":
        return "blocked"
    if asset.status == "external":
        return "external"
    if asset.status == "master-deleted":
        return "master-deleted"
    if asset.status in ("missing", "missing-block", "new"):
        return "missing"
    return "clean"


def update_state(state: dict[str, Any], assets: list[Asset], applied: set[str]) -> None:
    entries = state.setdefault("assets", {})
    for asset in assets:
        if asset.target_only or asset.status == "unsupported":
            continue
        if asset.status == "master-deleted" and asset.action == "report":
            continue
        if asset.action in ("prune", "pruned") and asset.key in applied:
            entries.pop(asset.key, None)
            continue
        if asset.action in ("report", "report-first-run") and asset.status in ("drift", "blocked-secret", "external", "master-deleted"):
            entries[asset.key] = {
                "relation": relation_for(asset),
                "kind": asset.kind,
                "name": asset.name,
                "target": asset.target,
                "master_hash": asset.expected_hash,
                "target_hash": asset.target_hash,
                "master_path": str(asset.master_path) if asset.master_path else None,
                "target_path": str(asset.target_path) if asset.target_path else None,
                "updated_at": now_iso(),
            }
            continue
        entries[asset.key] = {
            "relation": relation_for(asset),
            "kind": asset.kind,
            "name": asset.name,
            "target": asset.target,
            "master_hash": asset.expected_hash,
            "target_hash": asset.target_hash,
            "master_path": str(asset.master_path) if asset.master_path else None,
            "target_path": str(asset.target_path) if asset.target_path else None,
            "updated_at": now_iso(),
        }


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------

def summarize(assets: list[Asset]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for asset in assets:
        counts[asset.status] = counts.get(asset.status, 0) + 1
    return counts


def report_payload(ctx: Ctx, assets: list[Asset], first: bool, mode: str) -> dict[str, Any]:
    items = []
    for asset in assets:
        items.append({
            "key": asset.key,
            "kind": asset.kind,
            "name": asset.name,
            "target": asset.target,
            "status": asset.status,
            "status_label": STATUS_LABELS.get(asset.status, asset.status),
            "action": asset.action,
            "note": asset.note,
            "master_path": str(asset.master_path) if asset.master_path else None,
            "target_path": str(asset.target_path) if asset.target_path else None,
            "findings": asset.findings,
            "blocked": asset.blocked,
        })
    return {
        "version": VERSION,
        "generated_at": now_iso(),
        "mode": mode,
        "first_run": first,
        "master": str(CLAUDE_DIR),
        "project": str(ctx.project),
        "targets": [{"id": t.id, "label": t.label, "root": str(t.root)} for t in ctx.targets],
        "summary": summarize(assets),
        "assets": items,
        "unsupported": ctx.unsupported,
    }


def write_report(ctx: Ctx, payload: dict[str, Any]) -> tuple[Path, Path]:
    ctx.ensure_dirs()
    latest_json = ctx.reports_dir / "latest.json"
    latest_md = ctx.reports_dir / "latest.md"
    stamped = ctx.reports_dir / f"{ctx.run_id}.json"
    write_json_atomic(latest_json, payload)
    write_json_atomic(stamped, payload)

    lines = [
        "# AI IDE 环境同步报告",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 模式：{payload['mode']}",
        f"- 主源：`{payload['master']}`",
        f"- 当前项目：`{payload['project']}`",
        f"- 首跑：{'是（仅报告，未修改 IDE）' if payload['first_run'] else '否'}",
        "",
        "## 汇总",
        "",
    ]
    for key, label in STATUS_LABELS.items():
        if payload["summary"].get(key):
            lines.append(f"- {label}（{key}）：{payload['summary'][key]}")
    if not payload["summary"]:
        lines.append("- 无资产")

    groups = [
        ("冲突 / 漂移", {"drift", "blocked-secret", "master-deleted"}),
        ("目标独有", {"target-only"}),
        ("将创建 / 更新", {"missing", "missing-block", "update", "new"}),
        ("目标已有同类项", {"external"}),
    ]
    for title, statuses in groups:
        rows = [item for item in payload["assets"] if item["status"] in statuses]
        if not rows:
            continue
        lines.extend(["", f"## {title}", "", "| Key | 资产 | 目标 | 状态 | 说明 |", "|---|---|---|---|---|"])
        for item in rows[:200]:
            note = (item["note"] or "").replace("|", "\\|")
            if item["findings"]:
                note = (note + "；" if note else "") + "；".join(item["findings"])
            lines.append(f"| `{item['key']}` | {item['kind']}:{item['name']} | {item['target']} | {item['status_label']} | {note} |")
        if len(rows) > 200:
            lines.append(f"| … | 其余 {len(rows) - 200} 项 | | | |")

    if payload["unsupported"]:
        lines.extend(["", "## 不支持 / 需人工", "", "| 目标 | 领域 | 说明 |", "|---|---|---|"])
        for item in payload["unsupported"]:
            lines.append(f"| {item['target']} | {item['area']} | {item['message']} |")

    lines.extend([
        "",
        "## 下一步",
        "",
        "- 审阅冲突后，用 `adopt <key>` 把确认保留的本地修改采纳回 Claude；否则手工修复该副本。",
        "- 首跑报告不会改 IDE；再次执行 `sync` 才会创建缺失副本、更新无漂移副本。",
        "- 主源删除资产默认只报告；确认后执行 `sync --prune`。",
        "- 若 Claude 用户级 MCP 为空，先执行 `adopt-mcp --from codex`。",
        "",
        f"- 机器可读报告：`{latest_json}`",
    ])
    write_text_atomic(latest_md, "\n".join(lines) + "\n")
    return latest_md, latest_json


def print_summary(ctx: Ctx, assets: list[Asset], first: bool, report_md: Path) -> None:
    counts = summarize(assets)
    print(f"主源: {CLAUDE_DIR}")
    print(f"项目: {ctx.project}")
    print(f"目标: {', '.join(t.id for t in ctx.targets) or '无'}")
    print("汇总: " + " | ".join(
        f"{STATUS_LABELS.get(key, key)} {counts[key]}" for key in STATUS_LABELS if counts.get(key)
    ))
    if first:
        print("首跑：仅建立基线并输出报告，未修改任何 IDE 文件。再次运行 sync 才会应用安全变更。")
    conflicts = [a for a in assets if a.status in ("drift", "blocked-secret", "master-deleted", "target-only")]
    if conflicts:
        print(f"冲突/需关注 {len(conflicts)} 项（前 20）:")
        for asset in conflicts[:20]:
            note = asset.note or "；".join(asset.findings)
            print(f"  {asset.key}  [{STATUS_LABELS.get(asset.status)}] {note}")
        if len(conflicts) > 20:
            print(f"  ... 其余 {len(conflicts) - 20} 项见报告")
    if ctx.unsupported:
        print(f"不支持/需人工 {len(ctx.unsupported)} 项，见报告。")
    print(f"报告: {report_md}")


# ---------------------------------------------------------------------------
# adoption
# ---------------------------------------------------------------------------

def asset_by_key(ctx: Ctx, key: str) -> Asset | None:
    state = ctx.load_state()
    assets = build_assets(ctx, state)
    evaluate(assets, state, first=False)
    for asset in assets:
        if asset.key == key:
            return asset
    return None


def adopt_asset(ctx: Ctx, key: str) -> int:
    asset = asset_by_key(ctx, key)
    if not asset:
        print(f"找不到资产: {key}")
        return 2
    if asset.status not in ("drift", "target-only", "blocked-secret"):
        print(f"资产 {key} 当前状态为 {STATUS_LABELS.get(asset.status)}，无需采纳。")
        return 1
    if not asset.target_path or not asset.target_path.exists():
        print(f"目标副本不存在: {key}")
        return 2
    if asset.kind == "hook":
        print("hook 采纳暂不支持；请手工把目标 hook 合并回 ~/.claude/settings.json。")
        return 2
    if asset.kind == "mcp":
        print("MCP 采纳请使用 `adopt-mcp --from <target>`；单项 MCP 采纳暂不支持。")
        return 2

    if asset.kind == "skill":
        src = asset.target_path
        dst = CLAUDE_DIR / "skills" / asset.name
        ctx.backup(dst)
        replace_tree(src, dst)
        print(f"已采纳 skill: {src} -> {dst}")
    elif asset.kind == "agent":
        dst = CLAUDE_DIR / "agents" / f"{asset.name}.md"
        if asset.target_path.suffix.lower() == ".toml":
            data = tomllib.loads(read_text(asset.target_path))
            agent = {
                "name": str(data.get("name") or asset.name),
                "description": str(data.get("description") or ""),
                "tools": [],
                "model": "",
                "body": str(data.get("developer_instructions") or "") + "\n",
            }
        else:
            record = agent_record(asset.target_path)
            agent = record
        text = render_claude_agent(agent)
        ctx.backup(dst)
        write_text_atomic(dst, text)
        print(f"已采纳 agent: {asset.target_path} -> {dst}")
    elif asset.kind in ("rule", "memory"):
        dst = None
        if asset.kind == "rule":
            if asset.name == "_global_agents":
                dst = CLAUDE_DIR / "AGENTS.md"
            else:
                dst = CLAUDE_DIR / "rules" / f"{asset.name}.md"
        else:
            global_mem = detect_global_memory() or (CLAUDE_DIR / "projects" / encode_path(HOME) / "memory")
            if asset.name.startswith("project:"):
                dst = project_memory_dir(CLAUDE_DIR, ctx.project) / f"{asset.name.split(':', 1)[1]}.md"
            else:
                dst = global_mem / f"{asset.name}.md"
        ctx.backup(dst)
        write_text_atomic(dst, read_text(asset.target_path))
        print(f"已采纳 {asset.kind}: {asset.target_path} -> {dst}")
    else:
        print(f"暂不支持采纳类型: {asset.kind}")
        return 2

    state = ctx.load_state()
    state.get("assets", {}).pop(key, None)
    ctx.save_state(state)
    print("已更新基线；请运行 `sync` 把主源变更传播到其他 IDE，并自行 review / commit Claude 变更。")
    return 0


def codex_server_to_claude(server: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("command", "args", "env", "url"):
        if key in server:
            result[key] = server[key]
    if "http_headers" in server:
        result["headers"] = server["http_headers"]
    return result


def adopt_mcp(ctx: Ctx, source: str) -> int:
    if source != "codex":
        print(f"当前只支持从 codex 采纳 MCP，收到: {source}")
        return 2
    codex_config = HOME / ".codex" / "config.toml"
    if not codex_config.is_file():
        print(f"找不到 Codex 配置: {codex_config}")
        return 2
    try:
        data = tomllib.loads(read_text(codex_config))
    except Exception as exc:
        print(f"无法解析 Codex config.toml: {exc}")
        return 2
    servers = data.get("mcp_servers") or {}
    if not isinstance(servers, dict) or not servers:
        print("Codex 没有 mcp_servers。")
        return 1

    claude_data = load_json(CLAUDE_JSON, {}) if CLAUDE_JSON.exists() else {}
    existing = claude_data.get("mcpServers")
    if not isinstance(existing, dict):
        existing = {}
        claude_data["mcpServers"] = existing

    adopted: list[str] = []
    skipped: list[str] = []
    for name, server in servers.items():
        converted = codex_server_to_claude(server)
        sanitized, findings, blocked = sanitize_server(name, converted, None)
        if blocked:
            skipped.append(f"{name}（密钥拦截：{'；'.join(findings)}）")
            continue
        if name in existing and canonical(existing[name]) != canonical(sanitized):
            skipped.append(f"{name}（Claude 已有同名且内容不同）")
            continue
        if name not in existing:
            existing[name] = sanitized
            adopted.append(name)

    if not adopted:
        print("没有可采纳的 MCP 服务器。")
        for item in skipped:
            print(f"  跳过 {item}")
        return 1
    ctx.backup(CLAUDE_JSON)
    write_json_atomic(CLAUDE_JSON, claude_data)
    print(f"已采纳 {len(adopted)} 个 Codex MCP 到 {CLAUDE_JSON}: {', '.join(adopted)}")
    for item in skipped:
        print(f"  跳过 {item}")
    print("未自动 git commit；请 review ~/.claude 变更后运行 `sync`。")
    return 0


# ---------------------------------------------------------------------------
# install self
# ---------------------------------------------------------------------------

def install_self(ctx: Ctx) -> int:
    canonical = CLAUDE_DIR / "skills" / SKILL_NAME
    src = canonical if (canonical / "SKILL.md").is_file() else Path(__file__).resolve().parent.parent
    skill_file = src / "SKILL.md"
    if not skill_file.is_file():
        print(f"找不到源技能: {skill_file}")
        return 2
    meta, _ = parse_frontmatter(read_text(skill_file))
    if meta.get("name") != SKILL_NAME or not meta.get("description"):
        print("源技能 frontmatter 校验失败。")
        return 2
    results = []
    for target in ctx.targets:
        if not target.skills:
            continue
        dst = target.skills / SKILL_NAME
        if tree_hash(src) == tree_hash(dst):
            results.append((target.id, str(dst), "已一致"))
            continue
        ctx.backup(dst)
        replace_tree(src, dst)
        results.append((target.id, str(dst), "已安装/更新"))
    print(f"源: {src}")
    for target_id, dst, status in results:
        print(f"  {target_id:14s} {status:8s} {dst}")
    if not results:
        print("没有可用的 skills 目标。")
    return 0


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def collect_all(ctx: Ctx) -> list[Asset]:
    assets: list[Asset] = []
    assets.extend(collect_skills(ctx))
    assets.extend(collect_agents(ctx))
    assets.extend(collect_rules(ctx))
    assets.extend(collect_prompts(ctx))
    assets.extend(collect_memory(ctx))
    assets.extend(collect_mcp(ctx))
    assets.extend(collect_hooks(ctx))
    return assets


def reconcile_deletions(ctx: Ctx, assets: list[Asset], state: dict[str, Any]) -> None:
    by_key = {asset.key: asset for asset in assets}
    target_map = {target.id: target for target in ctx.targets}
    for key, baseline in state.get("assets", {}).items():
        kind = baseline.get("kind") or key.split(":", 1)[0]
        target_id = baseline.get("target") or (key.rsplit("@", 1)[1] if "@" in key else "")
        name = baseline.get("name") or key.split(":", 1)[1].split("@", 1)[0]
        master_path = Path(baseline["master_path"]) if baseline.get("master_path") else None
        target_path = Path(baseline["target_path"]) if baseline.get("target_path") else None

        current = by_key.get(key)
        if current is not None:
            if current.target_only:
                master_gone = kind in ("mcp", "hook") or (
                    baseline.get("master_path") and not Path(baseline["master_path"]).exists()
                )
                if master_gone:
                    current.target_only = False
                    current.master_missing = True
                    current.expected_hash = None
            continue

        if kind not in ("skill", "agent", "rule", "memory", "mcp", "hook"):
            continue
        master_gone = kind in ("mcp", "hook") or (master_path is not None and not master_path.exists())
        if not master_gone:
            continue
        target = target_map.get(target_id)
        target_hash = None
        if kind == "mcp" and target:
            server = read_target_servers(target).get(name)
            target_hash = sha_text(canonical(server)) if server is not None else None
        elif kind == "hook" and target:
            body = key.split(":", 1)[1].rsplit("@", 1)[0]
            event, _, basename = body.partition(":")
            config = load_hook_config(ctx, target)
            found = find_hook(config.get("hooks") or {}, event, basename)
            if found:
                target_hash = sha_text(canonical(found[2]) + hook_tree_hash(hook_managed_dir(target)))
        elif target_path and target_path.exists():
            target_hash = tree_hash(target_path) if target_path.is_dir() else file_hash(target_path)

        asset = new_asset(
            kind, name, target_id,
            master_path=master_path, target_path=target_path,
            target_hash=target_hash, expected_hash=None, master_missing=True,
        )
        if kind == "hook":
            body = key.split(":", 1)[1].rsplit("@", 1)[0]
            event, _, basename = body.partition(":")
            asset.hook_event = event
            asset.hook_basename = basename
        assets.append(asset)


def build_assets(ctx: Ctx, state: dict[str, Any]) -> list[Asset]:
    assets = collect_all(ctx)
    reconcile_deletions(ctx, assets, state)
    return assets


def filter_assets(assets: list[Asset], patterns: list[str]) -> list[Asset]:
    if not patterns:
        return assets
    return [asset for asset in assets if any(pattern in asset.key or pattern in asset.name or pattern in asset.target for pattern in patterns)]


def cmd_detect(ctx: Ctx) -> int:
    print(f" Claude 主源: {CLAUDE_DIR}")
    print(f" 状态目录:   {ctx.state_dir}")
    print(f" 当前项目:   {ctx.project}")
    print("")
    print(f"{'目标':14s} {'技能':>4s} {'代理':>4s} {'规则':>4s} {'记忆':>4s} {'MCP':>4s} {'Hooks':>6s}  根目录")
    for target in ctx.targets:
        skills = len([d for d in target.skills.iterdir() if d.is_dir() and (d / "SKILL.md").exists()]) if target.skills and target.skills.is_dir() else 0
        agents = len([p for p in target.agents.iterdir() if p.is_file()]) if target.agents and target.agents.is_dir() else 0
        rules = len([p for p in target.rules.glob("*.md")]) if target.rules and target.rules.is_dir() else 0
        memory = len([p for p in target.memory.glob("*.md")]) if target.memory and target.memory.is_dir() else 0
        mcp = len(read_target_servers(target)) if target.mcp_path else 0
        hooks = len(target.hook_events) if target.hooks_path else 0
        print(f"{target.id:14s} {skills:4d} {agents:4d} {rules:4d} {memory:4d} {mcp:4d} {hooks:6d}  {target.root}")
    print("")
    print("主源统计:")
    for label, path in [
        ("skills", CLAUDE_DIR / "skills"),
        ("agents", CLAUDE_DIR / "agents"),
        ("rules", CLAUDE_DIR / "rules"),
        ("hooks", CLAUDE_DIR / "hooks"),
    ]:
        if path.is_dir():
            if label in ("skills",):
                count = len([d for d in path.iterdir() if d.is_dir() and (d / "SKILL.md").exists()])
            else:
                count = len([p for p in path.iterdir() if p.is_file()])
            print(f"  {label:8s} {count}")
    global_mem = detect_global_memory()
    if global_mem:
        print(f"  memory   {len(memory_files(global_mem))}  ({global_mem})")
    print(f"  MCP      {len(load_claude_mcp())} 用户级 + {len(load_project_mcp(ctx.project))} 项目级")
    if ctx.unsupported:
        print("")
        print("不支持/需人工:")
        for item in ctx.unsupported:
            print(f"  {item['target']}/{item['area']}: {item['message']}")
    return 0


def cmd_status(ctx: Ctx, json_output: bool) -> int:
    state = ctx.load_state()
    assets = build_assets(ctx, state)
    first = not state.get("initialized", False)
    evaluate(assets, state, first)
    payload = report_payload(ctx, assets, first, "status")
    report_md, _ = write_report(ctx, payload)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_summary(ctx, assets, first, report_md)
    return 0


def cmd_sync(ctx: Ctx, dry_run: bool, prune: bool, only: list[str], force: bool, json_output: bool) -> int:
    state = ctx.load_state()
    all_assets = build_assets(ctx, state)
    first = not state.get("initialized", False)
    if first and only:
        print("首跑需要完整基线，本次忽略 --only。")
        only = []
    assets = filter_assets(all_assets, only)
    evaluate(assets, state, first)
    if force and first:
        print("首跑只建立基线，不能使用 --force；先完成首跑再执行。")
        return 2
    if force and not only:
        print("--force 必须配合 --only 使用，避免全量覆盖漂移副本。")
        return 2
    if force:
        forced = 0
        for asset in assets:
            if asset.status == "drift" and asset.action == "report":
                asset.status = "update"
                asset.action = "update"
                asset.note = "按 --force 以主源覆盖（已备份）"
                forced += 1
        print(f"--force：将覆盖 {forced} 个漂移副本。")
    mode = "dry-run" if dry_run else ("first-run" if first else "sync")

    if dry_run:
        payload = report_payload(ctx, assets, first, mode)
        report_md, _ = write_report(ctx, payload)
        print_summary(ctx, assets, first, report_md)
        return 0

    if first:
        payload = report_payload(ctx, assets, True, mode)
        ctx.save_config()
        update_state(state, assets, set())
        state["initialized"] = True
        state["first_run_at"] = now_iso()
        ctx.save_state(state)
        report_md, _ = write_report(ctx, payload)
        print_summary(ctx, assets, True, report_md)
        return 0

    applied: set[str] = set()
    for asset in assets:
        if asset.action in ("create", "update", "append-block"):
            if apply_asset(ctx, asset):
                applied.add(asset.key)
                asset.status = "clean"
                asset.action = "none"
    apply_mcp(ctx, assets, prune)
    apply_hooks(ctx, assets, prune)
    if prune:
        apply_prune_files(ctx, assets)
    for asset in assets:
        if asset.kind in ("mcp", "hook") and asset.action in ("create", "update") and asset.target_hash == asset.expected_hash:
            asset.status = "clean"
            asset.action = "none"
        if asset.action == "prune" and prune:
            applied.add(asset.key)
            asset.status = "clean"
            asset.action = "pruned"
            asset.target_hash = None

    payload = report_payload(ctx, assets, False, mode)
    update_state(state, assets, applied)
    state["initialized"] = True
    state["last_sync_at"] = now_iso()
    ctx.save_state(state)
    report_md, _ = write_report(ctx, payload)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_summary(ctx, assets, False, report_md)
    return 0


def cmd_adopt(ctx: Ctx, key: str) -> int:
    return adopt_asset(ctx, key)


def cmd_adopt_mcp(ctx: Ctx, source: str) -> int:
    return adopt_mcp(ctx, source)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="在 Claude 主源与所有 AI IDE 之间同步环境")
    parser.add_argument("--state-dir", default=str(STATE_DIR_DEFAULT), help="状态与报告目录")
    parser.add_argument("--project", default=str(PROJECT_DEFAULT), help="当前项目目录")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("detect", help="列出目标与资产落点")
    p_status = sub.add_parser("status", help="只对比并输出报告")
    p_status.add_argument("--json", action="store_true", dest="json_output")

    p_sync = sub.add_parser("sync", help="同步（首跑只报告）")
    p_sync.add_argument("--dry-run", action="store_true")
    p_sync.add_argument("--prune", action="store_true")
    p_sync.add_argument("--only", action="append", default=[], help="只处理匹配子串的资产")
    p_sync.add_argument("--force", action="store_true", help="配合 --only 以主源覆盖漂移副本")
    p_sync.add_argument("--json", action="store_true", dest="json_output")

    p_adopt = sub.add_parser("adopt", help="把目标副本采纳回 Claude 主源")
    p_adopt.add_argument("key")

    p_mcp = sub.add_parser("adopt-mcp", help="把 Codex MCP 采纳进 Claude")
    p_mcp.add_argument("--from", dest="source", default="codex")

    sub.add_parser("install-self", help="把本技能安装到所有 IDE 的 skills 目录")

    args = parser.parse_args(argv)
    ctx = Ctx(Path(args.state_dir).expanduser(), Path(args.project).resolve())

    if args.command == "detect":
        return cmd_detect(ctx)
    if args.command == "status":
        return cmd_status(ctx, args.json_output)
    if args.command == "sync":
        return cmd_sync(ctx, args.dry_run, args.prune, args.only, args.force, args.json_output)
    if args.command == "adopt":
        return cmd_adopt(ctx, args.key)
    if args.command == "adopt-mcp":
        return cmd_adopt_mcp(ctx, args.source)
    if args.command == "install-self":
        return install_self(ctx)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
