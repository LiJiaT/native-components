#!/usr/bin/env python3
"""Validate and install one portable agent definition across AI IDEs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HOME = Path(os.environ.get("AGENTCTL_HOME") or Path.home()).expanduser()
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME = 64
ALLOWED_FRONTMATTER = {"name", "description", "tools", "model"}


class FrontmatterError(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    id: str
    label: str
    config: Path
    user_dir: Optional[Path]
    project_subdir: str
    fmt: str
    project_only: bool = False


def get_targets() -> list[Target]:
    return [
        Target("claude-code", "Claude Code", HOME / ".claude", HOME / ".claude" / "agents", ".claude/agents", "markdown"),
        Target("qoder-cn", "Qoder CN", HOME / ".qoder-cn", HOME / ".qoder-cn" / "agents", ".qoder/agents", "markdown"),
        Target("qoder", "Qoder IDE", HOME / ".qoder", HOME / ".qoder" / "agents", ".qoder/agents", "markdown"),
        Target("codex", "Codex", HOME / ".codex", HOME / ".codex" / "agents", ".codex/agents", "toml"),
        Target("trae-cn", "TRAE CN", HOME / ".trae-cn", None, ".github/agents", "trae", project_only=True),
        Target("trae", "TRAE", HOME / ".trae", None, ".github/agents", "trae", project_only=True),
    ]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        if value[0] == "'":
            return value[1:-1].replace("''", "'")
        try:
            return json.loads(value)
        except Exception:
            return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise FrontmatterError("agent file must start with a YAML frontmatter block (---)")
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        raise FrontmatterError("frontmatter is missing its closing ---")

    data: dict[str, Any] = {}
    index = 1
    while index < end:
        raw = lines[index]
        if not raw.strip() or raw.lstrip().startswith("#"):
            index += 1
            continue
        if raw[:1].isspace():
            index += 1
            continue
        if ":" not in raw:
            raise FrontmatterError(f"invalid frontmatter line: {raw!r}")
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()

        if value in {"|", ">", "|-", ">-", "|+", ">+"}:
            block: list[str] = []
            index += 1
            while index < end and (not lines[index].strip() or lines[index][:1].isspace()):
                block.append(lines[index].strip())
                index += 1
            joiner = "\n" if value.startswith("|") else " "
            data[key] = joiner.join(block).strip()
            continue

        if value == "":
            items: list[str] = []
            lookahead = index + 1
            while lookahead < end and (not lines[lookahead].strip() or lines[lookahead][:1].isspace()):
                item = lines[lookahead].strip()
                if item.startswith("- "):
                    items.append(unquote(item[2:].strip()))
                lookahead += 1
            if items:
                data[key] = items
                index = lookahead
                continue
            data[key] = ""
            index += 1
            continue

        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            data[key] = [unquote(part.strip()) for part in inner.split(",") if part.strip()] if inner else []
            index += 1
            continue

        data[key] = unquote(value)
        index += 1

    return data, "\n".join(lines[end + 1 :])


def find_unfinished_todo(body: str) -> Optional[str]:
    fence: Optional[str] = None
    for line in body.splitlines():
        match = re.match(r"^[ \t]*(?:[-+*]|\d+[.)])?[ \t]*(`{3,}|~{3,})(.*)$", line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker[0]
            elif marker[0] == fence:
                fence = None
            continue
        if fence is None and "[TODO:" in line:
            return line.strip()
    return None


def normalize_tools(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        raw: list[str] = []
        for item in value:
            raw.extend(str(item).split(","))
    else:
        text = str(value).strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        raw = text.split(",")
    return [unquote(part.strip()) for part in raw if part.strip()]


def agent_stem(path: Path) -> str:
    stem = path.stem
    if stem.endswith(".agent"):
        stem = stem[:-6]
    return stem


def validate_agent(path: Path) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    result: dict[str, Any] = {
        "path": str(path),
        "name": "",
        "description": "",
        "tools": [],
        "model": "",
        "body": "",
        "lines": 0,
        "errors": errors,
        "warnings": warnings,
        "ok": False,
    }

    if path.is_dir():
        candidate = path / "agent.md"
        if candidate.is_file():
            path = candidate
    if not path.is_file():
        errors.append(f"agent file not found: {path}")
        return result
    if path.suffix.lower() != ".md":
        errors.append("agent source must be a Markdown file")
        return result

    try:
        text = read_text(path)
    except OSError as exc:
        errors.append(f"cannot read agent file: {exc}")
        return result

    try:
        frontmatter, body = parse_frontmatter(text)
    except FrontmatterError as exc:
        errors.append(str(exc))
        return result

    name_value = frontmatter.get("name", "")
    description_value = frontmatter.get("description", "")
    if not isinstance(name_value, str):
        errors.append("name must be a string")
        name = ""
    else:
        name = name_value.strip()
    if not isinstance(description_value, str):
        errors.append("description must be a string")
        description = ""
    else:
        description = description_value.strip()

    tools = normalize_tools(frontmatter.get("tools"))
    model_value = frontmatter.get("model", "")
    if not isinstance(model_value, str):
        errors.append("model must be a string")
        model = ""
    else:
        model = model_value.strip()

    result.update(
        name=name,
        description=description,
        tools=tools,
        model=model,
        body=body,
        lines=len(body.splitlines()),
    )

    if not name:
        errors.append("missing required frontmatter field: name")
    elif not NAME_RE.fullmatch(name):
        errors.append(f"name '{name}' must be lowercase hyphen-case (letters, digits, hyphens)")
    elif len(name) > MAX_NAME:
        errors.append(f"name is {len(name)} characters; maximum is {MAX_NAME}")
    elif name != agent_stem(path):
        errors.append(f"name '{name}' must match the agent filename '{agent_stem(path)}'")

    if not description:
        errors.append("missing required frontmatter field: description")
    elif description.startswith("[TODO:"):
        errors.append("description is still a TODO placeholder")
    else:
        if len(description) < 60:
            warnings.append("description is short; the main agent uses it to decide when to delegate")
        if len(description) > 1024:
            warnings.append("description is over 1024 characters; some runtimes may truncate it")

    for key in sorted(set(frontmatter) - ALLOWED_FRONTMATTER):
        warnings.append(f"frontmatter key '{key}' is not portable; omit it or move the detail into the body")
    if "color" in frontmatter:
        warnings.append("'color' is not an official Claude agent field and is ignored elsewhere")

    if "tools" in frontmatter and not tools:
        warnings.append("'tools' is empty; omit it to inherit all tools")
    elif isinstance(frontmatter.get("tools"), list):
        warnings.append("tools is a YAML list; a canonical Claude/Qoder file should use a comma-separated string")

    if not body.strip():
        errors.append("agent body is empty; it is the system prompt")
    if result["lines"] > 800:
        warnings.append(f"agent body is {result['lines']} lines; consider tightening the prompt")

    todo = find_unfinished_todo(body)
    if todo:
        errors.append(f"unfinished TODO in agent body: {todo}")

    for absolute in ("C:\\Users\\", "/Users/", "/home/"):
        if absolute in body:
            warnings.append("body contains an absolute home path; use ~ or paths relative to the project")
            break

    result["ok"] = not errors
    return result


def yaml_quote(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def render_markdown(agent: dict, target: Target) -> str:
    lines = [
        "---",
        f"name: {yaml_quote(agent['name'])}",
        f"description: {yaml_quote(agent['description'])}",
    ]
    if agent["tools"]:
        if target.fmt == "trae":
            lines.append("tools:")
            for tool in agent["tools"]:
                lines.append(f"  - {yaml_quote(tool)}")
        else:
            lines.append(f"tools: {yaml_quote(', '.join(agent['tools']))}")
    if target.fmt == "markdown" and agent["model"]:
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


def render_toml(agent: dict) -> str:
    lines = [
        f"name = {toml_quote(agent['name'])}",
        f"description = {toml_quote(agent['description'])}",
        f"nickname_candidates = [{toml_quote(agent['name'])}]",
        f"developer_instructions = {toml_quote(agent['body'].strip())}",
    ]
    return "\n".join(lines) + "\n"


def render_agent(agent: dict, target: Target) -> str:
    if target.fmt == "toml":
        return render_toml(agent)
    return render_markdown(agent, target)


def agent_filename(target: Target, name: str) -> str:
    if target.fmt == "toml":
        return f"{name}.toml"
    if target.fmt == "trae":
        return f"{name}.agent.md"
    return f"{name}.md"


def count_agents(root: Path, target: Target) -> int:
    if not root.is_dir():
        return 0
    if target.fmt == "toml":
        return sum(1 for item in root.iterdir() if item.is_file() and item.suffix.lower() == ".toml")
    return sum(1 for item in root.iterdir() if item.is_file() and item.suffix.lower() == ".md")


def nearest_existing(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def make_backup(dest: Path, target_id: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = HOME / ".universal-agent-creator" / "backups" / target_id
    base.mkdir(parents=True, exist_ok=True)
    candidate = base / f"{dest.name}-{stamp}"
    counter = 1
    while candidate.exists():
        counter += 1
        candidate = base / f"{dest.name}-{stamp}-{counter}"
    return candidate


def install_file(
    src: Path, dest: Path, content: str, update: bool, dry_run: bool, target_id: str
) -> tuple[str, str, str]:
    if dest.resolve() == src.resolve():
        return "source", "canonical file is already here", ""

    existed = dest.exists()
    if existed and dest.is_file() and read_text(dest) == content:
        return "unchanged", "", ""
    if existed and not update:
        return "conflict", "destination differs; re-run with --update", ""
    if dry_run:
        return ("would-update" if existed else "would-install"), "", ""

    backup_path = ""
    if existed:
        backup_path = str(make_backup(dest, target_id))
        shutil.move(str(dest), backup_path)

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        temporary = dest.parent / f".{dest.name}.tmp-{os.getpid()}"
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary, dest)
    except Exception:
        if existed and backup_path and not dest.exists():
            shutil.move(backup_path, str(dest))
        raise

    return ("updated" if existed else "installed"), "", backup_path


def selected_targets(args: argparse.Namespace) -> list[Target]:
    all_targets = get_targets()
    by_id = {target.id: target for target in all_targets}
    requested: list[str] = []
    for chunk in getattr(args, "ide", None) or []:
        requested.extend(part.strip() for part in chunk.split(",") if part.strip())
    if requested:
        unknown = sorted(set(requested) - set(by_id))
        if unknown:
            raise SystemExit(f"unknown IDE id(s): {', '.join(unknown)}; run detect to list them")
        return [target for target in all_targets if target.id in set(requested)]
    return [
        target
        for target in all_targets
        if target.config.exists() or (target.user_dir is not None and target.user_dir.exists())
    ]


def scope_root(target: Target, args: argparse.Namespace) -> tuple[Optional[Path], Path]:
    if args.scope == "project":
        base = Path(args.project_root or os.getcwd()).expanduser().resolve()
        marker = base / target.project_subdir.split("/", 1)[0]
        return base / target.project_subdir, marker
    if target.user_dir is None:
        return None, target.config
    return target.user_dir, target.config


def cmd_detect(args: argparse.Namespace) -> int:
    rows = []
    for target in get_targets():
        ready = target.config.exists() or (target.user_dir is not None and target.user_dir.exists())
        root = target.user_dir
        probe = root if root is not None and root.exists() else target.config.parent
        rows.append(
            {
                "ide": target.id,
                "label": target.label,
                "ready": ready,
                "scope": "project-only" if target.project_only else "user+project",
                "format": target.fmt,
                "agents": count_agents(root, target) if root is not None else 0,
                "writable": os.access(nearest_existing(probe), os.W_OK),
                "root": str(root) if root is not None else "(project-only)",
            }
        )
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    print(f"{'IDE':<12} {'NAME':<14} {'READY':<6} {'SCOPE':<14} {'FORMAT':<9} {'AGENTS':<7} ROOT")
    for row in rows:
        print(
            f"{row['ide']:<12} {row['label']:<14} {('yes' if row['ready'] else 'no'):<6} "
            f"{row['scope']:<14} {row['format']:<9} {row['agents']:<7} {row['root']}"
        )
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    name = args.name.strip()
    if not NAME_RE.fullmatch(name):
        print(f"ERROR name '{name}' must be lowercase hyphen-case", file=sys.stderr)
        return 1
    if len(name) > MAX_NAME:
        print(f"ERROR name is {len(name)} characters; maximum is {MAX_NAME}", file=sys.stderr)
        return 1

    parent = Path(args.dest).expanduser() if args.dest else HOME / ".claude" / "agents"
    path = parent / f"{name}.md"
    if path.exists():
        print(f"ERROR {path} already exists", file=sys.stderr)
        return 1

    description = args.description or (
        "[TODO: What this agent does and when the main agent should delegate to it. Include concrete user phrases.]"
    )
    tools = normalize_tools(args.tools) if args.tools else []
    model = (args.model or "").strip()
    lines = ["---", f"name: {name}", f"description: {yaml_quote(description)}"]
    if tools:
        lines.append(f"tools: {yaml_quote(', '.join(tools))}")
    if model:
        lines.append(f"model: {yaml_quote(model)}")
    lines.extend(
        [
            "---",
            "",
            f"# {name}",
            "",
            "[TODO: replace this paragraph with the agent's role, scope, workflow, output contract, and boundaries.]",
            "",
            "## Workflow",
            "",
            "1. Add the first concrete step.",
            "2. Add the next step and the expected output.",
            "",
            "## Boundaries",
            "",
            "- Add only constraints that prevent a real failure or scope creep.",
            "",
        ]
    )
    parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
    print(f"Created {path}")
    print("Next: write the body, then run validate and install --all.")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    result = validate_agent(Path(args.path).expanduser())
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1

    for error in result["errors"]:
        print(f"ERROR {error}")
    for warning in result["warnings"]:
        print(f"WARN  {warning}")
    if result["ok"]:
        print(
            f"OK    {result['name']}: valid "
            f"(body {result['lines']} lines, description {len(result['description'])} chars, "
            f"tools {len(result['tools'])}, model {result['model'] or 'default'})"
        )
        return 0
    print(f"FAIL  {result['name'] or result['path']}: {len(result['errors'])} error(s)")
    return 1


def cmd_install(args: argparse.Namespace) -> int:
    src = Path(args.agent_file).expanduser()
    if src.is_dir():
        candidates = [p for p in src.glob("*.md") if p.is_file()]
        if len(candidates) != 1:
            print(f"ERROR {src} must contain exactly one .md agent file", file=sys.stderr)
            return 2
        src = candidates[0]
    src = src.resolve()

    validation = validate_agent(src)
    if not validation["ok"]:
        for error in validation["errors"]:
            print(f"ERROR {error}", file=sys.stderr)
        for warning in validation["warnings"]:
            print(f"WARN  {warning}", file=sys.stderr)
        print(f"Refusing to install invalid agent: {src}", file=sys.stderr)
        return 2
    for warning in validation["warnings"]:
        print(f"WARN  {warning}")

    agent = {
        "name": validation["name"],
        "description": validation["description"],
        "tools": validation["tools"],
        "model": validation["model"],
        "body": validation["body"],
    }

    targets = selected_targets(args)
    if not targets:
        print("No IDE targets detected. Use --ide <id> to choose one explicitly.", file=sys.stderr)
        return 2

    rows = []
    seen: dict[Path, str] = {}
    exit_code = 0
    trae_note = False
    codex_note = False
    for target in targets:
        root, marker = scope_root(target, args)
        if args.scope == "user" and root is None:
            rows.append(
                {
                    "ide": target.id,
                    "label": target.label,
                    "status": "skipped",
                    "dest": "-",
                    "backup": "",
                    "detail": "TRAE custom agents are project-scoped; use --scope project",
                }
            )
            continue
        if args.scope == "project" and not marker.exists() and not args.create_missing:
            rows.append(
                {
                    "ide": target.id,
                    "label": target.label,
                    "status": "skipped",
                    "dest": str((root or target.config) / agent_filename(target, agent["name"])),
                    "backup": "",
                    "detail": "project has no IDE config; use --create-missing",
                }
            )
            continue

        assert root is not None
        dest = root / agent_filename(target, agent["name"])
        resolved = dest.resolve()
        if resolved in seen:
            rows.append(
                {
                    "ide": target.id,
                    "label": target.label,
                    "status": "duplicate",
                    "dest": str(dest),
                    "backup": "",
                    "detail": f"same destination as {seen[resolved]}",
                }
            )
            continue
        seen[resolved] = target.id

        content = render_agent(agent, target)
        status, detail, backup = install_file(src, dest, content, args.update, args.dry_run, target.id)
        if status == "conflict":
            exit_code = 1
        if target.fmt == "trae" and status in {"installed", "updated", "unchanged", "would-install", "would-update"}:
            trae_note = True
        if target.fmt == "toml" and status in {"installed", "updated", "unchanged", "would-install", "would-update"}:
            codex_note = True
        rows.append(
            {
                "ide": target.id,
                "label": target.label,
                "status": status,
                "dest": str(dest),
                "backup": backup,
                "detail": detail,
            }
        )

    if args.json:
        print(
            json.dumps(
                {
                    "source": str(src),
                    "dry_run": args.dry_run,
                    "results": rows,
                    "notes": {
                        "trae_model_omitted": trae_note and bool(agent["model"]) and agent["model"] != "inherit",
                        "codex_tools_omitted": codex_note and bool(agent["tools"]),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"{'IDE':<12} {'STATUS':<15} DESTINATION")
        for row in rows:
            print(f"{row['ide']:<12} {row['status']:<15} {row['dest']}")
            if row["detail"]:
                print(f"{'':<12} {'':<15} {row['detail']}")
            if row["backup"]:
                print(f"{'':<12} {'':<15} backup: {row['backup']}")

        counts: dict[str, int] = {}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        print()
        print(", ".join(f"{key}: {value}" for key, value in sorted(counts.items())))
        if trae_note and agent["model"] and agent["model"] != "inherit":
            print("TRAE copy omits model; choose the model in the TRAE agent UI.")
        if codex_note and agent["tools"]:
            print("Codex TOML does not carry tools; Codex applies its own tool policy.")
        if counts.get("conflict"):
            print("Conflicts were not changed. Re-run with --update to replace them after backup.")
        if args.dry_run:
            print("Dry run only; nothing was written.")

    return exit_code


def cmd_list(args: argparse.Namespace) -> int:
    name = args.name
    source = None
    if args.from_agent:
        if not name:
            print("ERROR --from requires --name", file=sys.stderr)
            return 2
        validation = validate_agent(Path(args.from_agent).expanduser())
        if not validation["ok"]:
            for error in validation["errors"]:
                print(f"ERROR {error}", file=sys.stderr)
            return 2
        source = {
            "name": validation["name"],
            "description": validation["description"],
            "tools": validation["tools"],
            "model": validation["model"],
            "body": validation["body"],
        }

    rows = []
    for target in selected_targets(args):
        root, _marker = scope_root(target, args)
        row = {
            "ide": target.id,
            "label": target.label,
            "root": str(root) if root is not None else "-",
            "exists": root.is_dir() if root is not None else False,
            "agents": count_agents(root, target) if root is not None else 0,
            "status": "project-only" if root is None else ("no-root" if not root.is_dir() else "ok"),
            "hash": "",
        }
        if name:
            if root is None:
                row["status"] = "project-only"
            else:
                dest = root / agent_filename(target, name)
                if dest.is_file():
                    actual = read_text(dest)
                    row["hash"] = hashlib.sha256(actual.encode("utf-8")).hexdigest()[:12]
                    if source is not None:
                        row["status"] = "current" if actual == render_agent(source, target) else "stale"
                    else:
                        row["status"] = "present"
                elif root.is_dir():
                    row["status"] = "missing"
        rows.append(row)

    if args.json:
        print(json.dumps({"name": name, "from": args.from_agent, "results": rows}, ensure_ascii=False, indent=2))
        return 0

    print(f"{'IDE':<12} {'AGENTS':<7} {'STATUS':<12} {'HASH':<13} ROOT")
    for row in rows:
        print(
            f"{row['ide']:<12} {row['agents']:<7} {row['status']:<12} "
            f"{row['hash']:<13} {row['root']}"
        )
    if source is not None and any(row["status"] == "stale" for row in rows):
        print()
        print("Some copies are stale. Re-run install from the canonical agent file with --update.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentctl",
        description="Validate and install portable agent definitions across AI IDEs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect = subparsers.add_parser("detect", help="show detected IDEs and agent roots")
    detect.add_argument("--json", action="store_true")
    detect.set_defaults(func=cmd_detect)

    init = subparsers.add_parser("init", help="scaffold a canonical Markdown agent")
    init.add_argument("name")
    init.add_argument("--dest", help="parent directory (default: ~/.claude/agents)")
    init.add_argument("--description")
    init.add_argument("--tools", help="comma-separated tool names")
    init.add_argument("--model", default="inherit", help="model alias; default: inherit")
    init.set_defaults(func=cmd_init)

    validate = subparsers.add_parser("validate", help="validate one canonical agent file")
    validate.add_argument("path")
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(func=cmd_validate)

    install = subparsers.add_parser("install", help="convert and install one agent")
    install.add_argument("agent_file")
    install.add_argument("--all", action="store_true", help="install to every detected IDE")
    install.add_argument("--ide", action="append", metavar="ID", help="limit to IDE id(s); repeat or comma-separate")
    install.add_argument("--scope", choices=("user", "project"), default="user")
    install.add_argument("--project-root", help="project directory for --scope project")
    install.add_argument("--create-missing", action="store_true", help="create project IDE dirs if absent")
    install.add_argument("--update", action="store_true", help="replace differing copies after backup")
    install.add_argument("--dry-run", action="store_true", help="show actions without writing")
    install.add_argument("--json", action="store_true")
    install.set_defaults(func=cmd_install)

    listing = subparsers.add_parser("list", help="show installed agents and copy freshness")
    listing.add_argument("--name")
    listing.add_argument("--from", dest="from_agent", help="canonical agent file for freshness checks")
    listing.add_argument("--ide", action="append", metavar="ID")
    listing.add_argument("--scope", choices=("user", "project"), default="user")
    listing.add_argument("--project-root", help="project directory for --scope project")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_list)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
