#!/usr/bin/env python3
"""Validate and install portable Agent Skills across every AI IDE on the machine."""

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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HOME = Path(os.environ.get("SKILLCTL_HOME") or Path.home()).expanduser()
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
IGNORED_DIRS = {".git", "__pycache__", ".skill-backups"}
IGNORED_FILES = {".DS_Store", "Thumbs.db"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", "*.pyc", "*.pyo", ".DS_Store", "Thumbs.db", ".skill-backups"
)
ALLOWED_FRONTMATTER = {
    "name",
    "description",
    "license",
    "allowed-tools",
    "metadata",
    "compatibility",
}


class FrontmatterError(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    id: str
    label: str
    config: Path
    user_root: Path
    project_root: str


def get_targets() -> list[Target]:
    return [
        Target("claude-code", "Claude Code", HOME / ".claude", HOME / ".claude" / "skills", ".claude/skills"),
        Target("qoder-cn", "Qoder CN", HOME / ".qoder-cn", HOME / ".qoder-cn" / "skills", ".qoder/skills"),
        Target("qoder", "Qoder IDE", HOME / ".qoder", HOME / ".qoder" / "skills", ".qoder/skills"),
        Target("trae-cn", "TRAE CN", HOME / ".trae-cn", HOME / ".trae-cn" / "skills", ".trae/skills"),
        Target("trae", "TRAE", HOME / ".trae", HOME / ".trae" / "skills", ".trae/skills"),
        Target("codex", "Codex", HOME / ".codex", HOME / ".codex" / "skills", ".codex/skills"),
        Target("agents", "Agent Skills (shared)", HOME / ".agents", HOME / ".agents" / "skills", ".agents/skills"),
    ]


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise FrontmatterError("SKILL.md must start with a YAML frontmatter block (---)")
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        raise FrontmatterError("frontmatter is missing its closing ---")

    data: dict[str, str] = {}
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
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            quote = value[0]
            inner = value[1:-1]
            if quote == "'":
                inner = inner.replace("''", "'")
            else:
                inner = inner.replace('\\"', '"').replace("\\\\", "\\")
            value = inner
        data[key] = value
        index += 1

    return data, "\n".join(lines[end + 1 :])


def find_unfinished_todo(body: str) -> str | None:
    fence: str | None = None
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


def validate_skill(path: Path) -> dict:
    if path.is_file() and path.name == "SKILL.md":
        path = path.parent
    errors: list[str] = []
    warnings: list[str] = []
    result = {
        "path": str(path),
        "name": "",
        "description": "",
        "lines": 0,
        "files": 0,
        "errors": errors,
        "warnings": warnings,
        "ok": False,
    }
    if not path.is_dir():
        errors.append(f"skill directory not found: {path}")
        return result

    skill_md = path / "SKILL.md"
    if not skill_md.is_file():
        errors.append("SKILL.md not found")
        return result

    try:
        text = skill_md.read_text(encoding="utf-8-sig")
    except OSError as exc:
        errors.append(f"cannot read SKILL.md: {exc}")
        return result

    try:
        frontmatter, body = parse_frontmatter(text)
    except FrontmatterError as exc:
        errors.append(str(exc))
        return result

    name = str(frontmatter.get("name", "")).strip()
    description = str(frontmatter.get("description", "")).strip()
    result["name"] = name
    result["description"] = description
    result["lines"] = len(body.splitlines())
    result["files"] = sum(
        1 for item in path.rglob("*") if item.is_file() and not is_ignored(item, path)
    )

    if not name:
        errors.append("missing required frontmatter field: name")
    elif not NAME_RE.fullmatch(name):
        errors.append(f"name '{name}' must be lowercase hyphen-case (letters, digits, hyphens)")
    elif len(name) > MAX_NAME:
        errors.append(f"name is {len(name)} characters; maximum is {MAX_NAME}")
    elif name != path.name:
        errors.append(f"name '{name}' must match the skill directory name '{path.name}'")

    if not description:
        errors.append("missing required frontmatter field: description")
    elif len(description) > MAX_DESCRIPTION:
        errors.append(f"description is {len(description)} characters; maximum is {MAX_DESCRIPTION}")
    elif "<" in description or ">" in description:
        errors.append("description cannot contain angle brackets (< or >)")
    elif description.startswith("[TODO:"):
        errors.append("description is still a TODO placeholder")
    elif len(description) < 60:
        warnings.append("description is short; it is the only auto-trigger, so include when to use it")

    for key in sorted(set(frontmatter) - ALLOWED_FRONTMATTER):
        warnings.append(f"frontmatter key '{key}' is not portable; some IDEs will ignore it")
    if "allowed-tools" in frontmatter:
        warnings.append("'allowed-tools' only affects Claude-style runtimes; other IDEs ignore it")

    if not body.strip():
        errors.append("SKILL.md body is empty")
    if result["lines"] > 500:
        warnings.append(f"SKILL.md body is {result['lines']} lines; move detail into references/")

    todo = find_unfinished_todo(body)
    if todo:
        errors.append(f"unfinished TODO in SKILL.md body: {todo}")

    for absolute in ("C:\\Users\\", "/Users/", "/home/"):
        if absolute in body:
            warnings.append("body contains an absolute home path; use ~ or paths relative to the skill")
            break

    result["ok"] = not errors
    return result


def is_ignored(item: Path, root: Path) -> bool:
    parts = item.relative_to(root).parts
    if any(part in IGNORED_DIRS for part in parts):
        return True
    return item.name in IGNORED_FILES or item.suffix in IGNORED_SUFFIXES


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if not item.is_file() or is_ignored(item, path):
            continue
        relative = item.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def same_tree(left: Path, right: Path) -> bool:
    if not right.is_dir():
        return False
    return tree_hash(left) == tree_hash(right)


def nearest_existing(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def make_backup(dest: Path, target_id: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = HOME / ".universal-skill-creator" / "backups" / target_id
    base.mkdir(parents=True, exist_ok=True)
    candidate = base / f"{dest.name}-{stamp}"
    counter = 1
    while candidate.exists():
        counter += 1
        candidate = base / f"{dest.name}-{stamp}-{counter}"
    return candidate


def install_one(
    src: Path, dest: Path, update: bool, dry_run: bool, target_id: str
) -> tuple[str, str, str]:
    if dest.resolve() == src.resolve():
        return "source", "already the installed copy", ""

    existed = dest.exists()
    if existed and same_tree(src, dest):
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
        if temporary.exists():
            shutil.rmtree(temporary)
        shutil.copytree(src, temporary, ignore=IGNORE)
        temporary.rename(dest)
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
    include_missing = getattr(args, "include_missing", False)
    return [
        target
        for target in all_targets
        if include_missing or target.config.exists() or target.user_root.exists()
    ]


def scope_root(target: Target, args: argparse.Namespace) -> tuple[Path, Path]:
    if args.scope == "project":
        base = Path(args.project_root or os.getcwd()).expanduser().resolve()
        marker = base / target.project_root.split("/", 1)[0]
        return base / target.project_root, marker
    return target.user_root, target.config


def count_skills(root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(1 for item in root.iterdir() if item.is_dir() and (item / "SKILL.md").is_file())


def cmd_detect(args: argparse.Namespace) -> int:
    rows = []
    for target in get_targets():
        installed = target.config.exists() or target.user_root.exists()
        probe = target.user_root if target.user_root.exists() else target.config.parent
        rows.append(
            {
                "ide": target.id,
                "label": target.label,
                "installed": installed,
                "user_root": str(target.user_root),
                "project_root": target.project_root,
                "skills": count_skills(target.user_root),
                "writable": os.access(nearest_existing(probe), os.W_OK),
            }
        )
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    print(f"{'IDE':<12} {'NAME':<24} {'READY':<6} {'SKILLS':<7} {'WRITE':<6} ROOT")
    for row in rows:
        print(
            f"{row['ide']:<12} {row['label']:<24} "
            f"{('yes' if row['installed'] else 'no'):<6} {row['skills']:<7} "
            f"{('yes' if row['writable'] else 'no'):<6} {row['user_root']}"
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

    parent = Path(args.dest).expanduser() if args.dest else HOME / ".claude" / "skills"
    skill_dir = parent / name
    if skill_dir.exists():
        print(f"ERROR {skill_dir} already exists", file=sys.stderr)
        return 1

    description = args.description or (
        "[TODO: What this skill does and when it should trigger. Include concrete user phrases and contexts.]"
    )
    title = " ".join(word.capitalize() for word in name.split("-"))
    template = f"""---
name: {name}
description: {json.dumps(description, ensure_ascii=False)}
---

# {title}

[TODO: replace this paragraph with the skill's purpose, workflow, and output contract.]

## Workflow

1. Add the first concrete step.
2. Add the next step and the expected output.

## Rules

- Add only constraints that prevent a real failure or ambiguity.
"""
    skill_dir.mkdir(parents=True)
    with (skill_dir / "SKILL.md").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(template)
    print(f"Created {skill_dir}")
    print("Next: write the body, then run validate and install --all.")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    result = validate_skill(Path(args.path).expanduser())
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
            f"({result['files']} files, body {result['lines']} lines, "
            f"description {len(result['description'])} chars)"
        )
        return 0
    print(f"FAIL  {result['name'] or result['path']}: {len(result['errors'])} error(s)")
    return 1


def cmd_install(args: argparse.Namespace) -> int:
    src = Path(args.skill_dir).expanduser()
    if src.is_file() and src.name == "SKILL.md":
        src = src.parent
    src = src.resolve()

    validation = validate_skill(src)
    if not validation["ok"]:
        for error in validation["errors"]:
            print(f"ERROR {error}", file=sys.stderr)
        for warning in validation["warnings"]:
            print(f"WARN  {warning}", file=sys.stderr)
        print(f"Refusing to install invalid skill: {src}", file=sys.stderr)
        return 2
    for warning in validation["warnings"]:
        print(f"WARN  {warning}")

    targets = selected_targets(args)
    if not targets:
        print("No IDE targets detected. Use --ide <id> to choose one explicitly.", file=sys.stderr)
        return 2

    rows = []
    exit_code = 0
    for target in targets:
        dest_root, marker = scope_root(target, args)
        if args.scope == "project" and not marker.exists() and not args.create_missing:
            rows.append(
                {
                    "ide": target.id,
                    "label": target.label,
                    "status": "skipped",
                    "dest": str(dest_root / src.name),
                    "backup": "",
                    "detail": "project has no IDE config; use --create-missing",
                }
            )
            continue
        dest = dest_root / src.name
        status, detail, backup = install_one(src, dest, args.update, args.dry_run, target.id)
        if status == "conflict":
            exit_code = 1
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
                {"source": str(src), "dry_run": args.dry_run, "results": rows},
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
        summary = ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))
        print()
        print(summary)
        if counts.get("conflict"):
            print("Conflicts were not changed. Re-run with --update to replace them after backup.")
        if args.dry_run:
            print("Dry run only; nothing was written.")

    return exit_code


def cmd_list(args: argparse.Namespace) -> int:
    name = args.name
    rows = []
    hashes: dict[str, list[str]] = {}
    for target in selected_targets(args):
        root, _marker = scope_root(target, args)
        row = {
            "ide": target.id,
            "label": target.label,
            "root": str(root),
            "exists": root.is_dir(),
            "skills": count_skills(root),
            "status": "no-root" if not root.is_dir() else "ok",
            "hash": "",
        }
        if name:
            skill_dir = root / name
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
                digest = tree_hash(skill_dir)
                row["status"] = "present"
                row["hash"] = digest[:12]
                hashes.setdefault(digest, []).append(target.id)
            elif root.is_dir():
                row["status"] = "missing"
        rows.append(row)

    drift = len(hashes) > 1
    if args.json:
        print(json.dumps({"name": name, "drift": drift, "results": rows}, ensure_ascii=False, indent=2))
        return 0

    print(f"{'IDE':<12} {'SKILLS':<7} {'STATUS':<9} {'HASH':<13} ROOT")
    for row in rows:
        print(
            f"{row['ide']:<12} {row['skills']:<7} {row['status']:<9} "
            f"{row['hash']:<13} {row['root']}"
        )
    if drift:
        print()
        print(f"DRIFT: copies of '{name}' differ across IDEs:")
        for digest, ide_ids in hashes.items():
            print(f"  {digest[:12]}  {', '.join(ide_ids)}")
        print("Run install --all --update from the canonical copy to align them.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skillctl",
        description="Validate and install portable Agent Skills across AI IDEs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect = subparsers.add_parser("detect", help="show detected IDEs and skill roots")
    detect.add_argument("--json", action="store_true")
    detect.set_defaults(func=cmd_detect)

    init = subparsers.add_parser("init", help="scaffold a new skill")
    init.add_argument("name")
    init.add_argument("--dest", help="parent directory (default: ~/.claude/skills)")
    init.add_argument("--description", help="initial description")
    init.set_defaults(func=cmd_init)

    validate = subparsers.add_parser("validate", help="validate one skill folder")
    validate.add_argument("path")
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(func=cmd_validate)

    install = subparsers.add_parser("install", help="copy one skill into IDE skill roots")
    install.add_argument("skill_dir")
    install.add_argument("--all", action="store_true", help="install to every detected IDE")
    install.add_argument("--ide", action="append", metavar="ID", help="limit to IDE id(s); repeat or comma-separate")
    install.add_argument("--scope", choices=("user", "project"), default="user")
    install.add_argument("--project-root", help="project directory for --scope project")
    install.add_argument("--create-missing", action="store_true", help="create project IDE dirs if absent")
    install.add_argument("--include-missing", action="store_true", help="also install to undetected user roots")
    install.add_argument("--update", action="store_true", help="replace differing copies after backup")
    install.add_argument("--dry-run", action="store_true", help="show actions without writing")
    install.add_argument("--json", action="store_true")
    install.set_defaults(func=cmd_install)

    listing = subparsers.add_parser("list", help="show installed skills and copy drift")
    listing.add_argument("--name", help="check one skill across IDEs")
    listing.add_argument("--ide", action="append", metavar="ID")
    listing.add_argument("--scope", choices=("user", "project"), default="user")
    listing.add_argument("--project-root", help="project directory for --scope project")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
