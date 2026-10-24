#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组件安装器：按 registry.json 安装到 Claude Code 有效载入点。

用法：
  python tools/install.py --list
  python tools/install.py --component orchestrator --component grill-me-with-doc
  python tools/install.py --type skill --type agent
  python tools/install.py --all --dry-run
  python tools/install.py --rollback ~/.claude/install-manifest-latest.json

约定：
  - 默认安装到 ~/.claude；可用 --claude-home 覆盖（测试用）。
  - 安装前备份到 <claude-home>/backups/<timestamp>/，安装后写 manifest。
  - 只安装 registry 中 status=active/experimental 的组件；test-only 需 --allow-test-only。
  - 不修改 settings.json；hook 安装后打印 settings 片段供人确认。
  - Memory 组件会写入 MEMORY.md 的受管区块（BEGIN/END），确保启动索引可见。
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "registry.json"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head(repo):
    try:
        return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                       text=True).strip()
    except Exception:
        return "unknown"


def load_registry():
    reg = json.load(open(REGISTRY, encoding="utf-8"))
    return {c["name"]: c for c in reg.get("components", [])}


def iter_files(root):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        yield p


def target_paths(comp, claude_home, project_slug):
    """返回 [(source_rel, target_abs)]；source 是仓库内路径。"""
    name = comp["name"]
    src = REPO / comp["path"]
    h = Path(claude_home)
    typ = comp["type"]
    if typ == "skill":
        base = h / "skills" / name
        return [(p, base / p.relative_to(src)) for p in iter_files(src)]
    if typ == "agent":
        return [(src, h / "agents" / src.name)]
    if typ == "rule":
        sub = comp.get("install_target", "user-global")
        dest = h / "rules" / src.name if sub != "user-domain" else h / "rules" / name / src.name
        return [(src, dest)]
    if typ == "memory":
        if not project_slug:
            raise SystemExit("memory 组件安装需要 --project-slug（项目 memory 作用域）")
        return [(src, h / "projects" / project_slug / "memory" / src.name)]
    if typ == "hook":
        base = h / "hooks" / comp.get("install_dir", name)
        return [(p, base / p.relative_to(src)) for p in iter_files(src)]
    if typ == "flow":
        base = h / "self-evolve"
        pairs = []
        for p in iter_files(src):
            rel = p.relative_to(src)
            if p.name == "DESIGN.md":
                pairs.append((p, base / "DESIGN.md"))
            elif p.name == "CONTEXT.md":
                pairs.append((p, base / "CONTEXT.md"))
            elif "adr" in rel.parts:
                pairs.append((p, base / "adr" / p.name))
            elif rel.name == "README.md":
                pairs.append((p, base / "docs" / "self-evolution-README.md"))
            elif rel.name in ("flow.md", "gates.md"):
                pairs.append((p, base / "docs" / rel.name))
        return pairs
    if typ == "gate":
        base = h / "gates"
        if src.is_file():
            return [(src, base / src.name)]
        return [(p, base / p.relative_to(src)) for p in iter_files(src)]
    if typ == "tool":
        return [(src, h / "gates" / "tools" / src.name)]
    if typ == "schema":
        base = h / "gates" / "schemas"
        return [(p, base / p.name) for p in src.glob("*") if p.is_file()]
    if typ == "doc":
        return [(src, h / "docs" / src.name)]
    return []


def managed_block(name, title, target):
    begin = f"<!-- BEGIN AI-NATIVE-COMPONENT:{name} -->"
    end = f"<!-- END AI-NATIVE-COMPONENT:{name} -->"
    return (f"{begin}\n- [{title}]({target}) — 由 ai-native-basic-component 安装器维护\n{end}\n")


def update_memory_index(claude_home, project_slug, comp, target_rel, title):
    path = Path(claude_home) / "projects" / project_slug / "memory" / "MEMORY.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    block = managed_block(comp["name"], title, target_rel)
    name = comp["name"]
    begin = f"<!-- BEGIN AI-NATIVE-COMPONENT:{name} -->"
    end = f"<!-- END AI-NATIVE-COMPONENT:{name} -->"
    if begin in text and end in text:
        pre = text.split(begin)[0]
        post = text.split(end, 1)[1]
        text = pre + block + post.lstrip("\n")
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += block
    path.write_text(text, encoding="utf-8")
    return path


def install(comps, claude_home, project_slug, dry, force, allow_test_only):
    claude_home = Path(claude_home)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_root = claude_home / "backups" / stamp
    manifest = {
        "schema_version": "1",
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "target_root": str(claude_home),
        "backup_root": str(backup_root),
        "source_repo": str(REPO),
        "source_commit": git_head(REPO),
        "components": [],
    }
    for comp in comps:
        if comp.get("install_target") == "source-only":
            print(f"跳过 source-only 组件: {comp['name']}")
            continue
        if comp["status"] == "test-only" and not allow_test_only:
            print(f"跳过 test-only 组件: {comp['name']}（需 --allow-test-only）")
            continue
        if comp["status"] not in ("active", "experimental", "test-only"):
            print(f"跳过非安装状态组件: {comp['name']} status={comp['status']}")
            continue
        try:
            pairs = target_paths(comp, claude_home, project_slug)
        except SystemExit as e:
            print(f"跳过 {comp['name']}: {e}")
            continue
        entry = {"name": comp["name"], "version": comp["version"], "type": comp["type"],
                 "source": comp["path"], "targets": [], "hashes": {}}
        for src, dst in pairs:
            rel = str(dst.relative_to(claude_home)).replace("\\", "/")
            entry["targets"].append(rel)
            entry["hashes"][rel] = sha256(src)
            if dry:
                print(f"[dry-run] {src.relative_to(REPO)} -> {dst}")
                continue
            if dst.exists() and dst.is_file() and sha256(dst) == sha256(src):
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists() and not force:
                backup = backup_root / rel
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, backup)
            shutil.copy2(src, dst)
            if os.name != "nt" and dst.suffix in (".sh", ".py"):
                dst.chmod(dst.stat().st_mode | 0o111)
        if comp["type"] == "memory" and not dry:
            dst = Path(entry["targets"][0])
            update_memory_index(claude_home, project_slug, comp, dst.name, comp["name"])
        manifest["components"].append(entry)
        print(("规划" if dry else "安装") + f" {comp['name']} {comp['version']} -> {len(entry['targets'])} 个文件")
    if not dry:
        claude_home.mkdir(parents=True, exist_ok=True)
        mp = claude_home / f"install-manifest-{stamp}.json"
        mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (claude_home / "install-manifest-latest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"安装清单: {mp}")
        print("提示：hook 需在 settings.json 中注册，见 hooks/*/settings.example.json；安装器不自动改 settings。")
    else:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))


def rollback(manifest_path, claude_home):
    m = json.load(open(manifest_path, encoding="utf-8"))
    backup_root = Path(m["backup_root"])
    for c in m.get("components", []):
        for rel in c.get("targets", []):
            dst = Path(claude_home) / rel
            bak = backup_root / rel
            if bak.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(bak, dst)
                print(f"恢复 {rel}")
            elif dst.exists():
                dst.unlink()
                print(f"删除 {rel}")
    print("回滚完成；settings.json 未改动。")


def main():
    ap = argparse.ArgumentParser(description="ai-native-basic-component 安装器")
    ap.add_argument("--claude-home", default=str(Path.home() / ".claude"))
    ap.add_argument("--project-slug", help="memory 组件的项目 slug（~/.claude/projects/<slug>）")
    ap.add_argument("--component", action="append", default=[])
    ap.add_argument("--type", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--allow-test-only", action="store_true")
    ap.add_argument("--rollback", help="按 install manifest 回滚")
    args = ap.parse_args()
    reg = load_registry()
    if args.list:
        for c in reg.values():
            print(f"{c['name']:38s} {c['type']:7s} {c['version']:7s} {c['status']:11s} {c['path']}")
        return
    if args.rollback:
        rollback(args.rollback, args.claude_home)
        return
    selected = []
    if args.all:
        selected = list(reg.values())
    for name in args.component:
        if name not in reg:
            raise SystemExit(f"未知组件: {name}")
        selected.append(reg[name])
    for typ in args.type:
        selected += [c for c in reg.values() if c["type"] == typ]
    if not selected:
        ap.error("指定 --list / --component / --type / --all / --rollback")
    seen, comps = set(), []
    for c in selected:
        if c["name"] not in seen:
            comps.append(c); seen.add(c["name"])
    install(comps, args.claude_home, args.project_slug, args.dry_run, args.force,
            args.allow_test_only)


if __name__ == "__main__":
    main()
