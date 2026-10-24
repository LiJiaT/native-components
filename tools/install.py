#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组件安装器：按 registry.json 安装到 Claude Code 有效载入点。

用法：
  python tools/install.py --list
  python tools/install.py --component orchestrator --component grill-me-with-doc
  python tools/install.py --type skill --type agent
  python tools/install.py --all --dry-run
  python tools/install.py --rollback ~/.claude/install-manifest-<txid>.json

约定：
  - 默认安装到 ~/.claude；可用 --claude-home 覆盖（测试用）。
  - 每次安装使用唯一 transaction_id，备份到 <claude-home>/backups/<txid>/。
  - manifest 逐目标记录 created/replaced/unchanged；回滚只删除 created、只恢复
    replaced，unchanged 不动，避免删除安装前已存在的同内容文件。
  - test-only / test-sandbox 组件一律落到 <claude-home>/test-sandbox/，不进入
    rules/memory 等生产载入点。
  - Memory 组件的 MEMORY.md 索引也纳入 targets/backup/rollback。
  - 不修改 settings.json；hook 安装后打印 settings 片段供人确认。
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


def _sandbox(comp):
    return comp.get("install_target") == "test-sandbox" or comp.get("status") == "test-only"


def target_paths(comp, claude_home, project_slug):
    """返回 [(source_abs, target_abs)]；sandbox 组件不落生产载入点。"""
    name = comp["name"]
    src = REPO / comp["path"]
    h = Path(claude_home)
    typ = comp["type"]
    if _sandbox(comp):
        base = h / "test-sandbox"
        if typ == "skill":
            return [(p, base / "skills" / name / p.relative_to(src)) for p in iter_files(src)]
        if typ == "agent":
            return [(src, base / "agents" / src.name)]
        if typ == "rule":
            return [(src, base / "rules" / src.name)]
        if typ == "memory":
            return [(src, base / "memory" / src.name)]
        if typ == "hook":
            return [(p, base / "hooks" / comp.get("install_dir", name) / p.relative_to(src))
                    for p in iter_files(src)]
        if typ == "flow":
            return _flow_pairs(src, base / "self-evolve")
        if typ == "gate":
            pairs = ([(src, base / "gates" / src.name)] if src.is_file()
                     else [(p, base / "gates" / p.relative_to(src)) for p in iter_files(src)])
            return pairs
        if typ == "tool":
            return [(src, base / "tools" / src.name)]
        if typ == "schema":
            return [(p, base / "schemas" / p.name) for p in src.glob("*") if p.is_file()]
        if typ == "doc":
            return [(src, base / "docs" / src.name)]
        return []
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
        return _flow_pairs(src, h / "self-evolve")
    if typ == "gate":
        base = h / "gates"
        pairs = ([(src, base / src.name)] if src.is_file()
                 else [(p, base / p.relative_to(src)) for p in iter_files(src)])
        # 安装后 gate 的默认 repo 是 ~/.claude；快照 registry/schema 让 CLI 可用
        pairs.append((REPO / "registry.json", base / "registry.json"))
        pairs += [(p, base / "schemas" / p.name)
                  for p in (REPO / "schemas").glob("*.json") if p.is_file()]
        return pairs
    if typ == "tool":
        return [(src, h / "gates" / "tools" / src.name)]
    if typ == "schema":
        base = h / "schemas"
        return [(p, base / p.name) for p in src.glob("*") if p.is_file()]
    if typ == "doc":
        return [(src, h / "docs" / src.name)]
    return []


def _flow_pairs(src, base):
    pairs = []
    for p in iter_files(src):
        rel = p.relative_to(src)
        if p.name == "DESIGN.md":
            pairs.append((p, base / "DESIGN.md"))
        elif p.name == "CONTEXT.md":
            pairs.append((p, base / "CONTEXT.md"))
        elif "adr" in rel.parts:
            pairs.append((p, base / "adr" / p.name))
        elif p.name in ("README.md", "flow.md", "gates.md"):
            # 保留目录结构，避免根 README 与 scheduler/README 写同一目标
            pairs.append((p, base / "docs" / rel))
    return pairs


def managed_block(name, title, target):
    begin = f"<!-- BEGIN AI-NATIVE-COMPONENT:{name} -->"
    end = f"<!-- END AI-NATIVE-COMPONENT:{name} -->"
    return (f"{begin}\n- [{title}]({target}) — 由 ai-native-basic-component 安装器维护\n{end}\n")


def render_memory_index(text, comp, target_rel, title):
    block = managed_block(comp["name"], title, target_rel)
    name = comp["name"]
    begin = f"<!-- BEGIN AI-NATIVE-COMPONENT:{name} -->"
    end = f"<!-- END AI-NATIVE-COMPONENT:{name} -->"
    if begin in text and end in text:
        pre = text.split(begin)[0]
        post = text.split(end, 1)[1]
        return pre + block + post.lstrip("\n")
    if text and not text.endswith("\n"):
        text += "\n"
    return text + block


def _backup(dst, backup_root, rel):
    backup = backup_root / rel
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dst, backup)


def install(comps, claude_home, project_slug, dry, force, allow_test_only):
    claude_home = Path(claude_home)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    txid = f"{stamp}-{os.urandom(4).hex()}"
    backup_root = claude_home / "backups" / txid
    manifest = {
        "schema_version": "1",
        "transaction_id": txid,
        "mode": "full" if len(comps) == len(load_registry()) else "partial",
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "target_root": str(claude_home),
        "backup_root": str(backup_root),
        "source_repo": str(REPO),
        "source_commit": git_head(REPO),
        "components": [],
    }
    # 先规划全部目标，检测冲突后再落盘
    planned = []
    owner_by_target = {}
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
                 "status": comp["status"], "source": comp["path"], "targets": [],
                 "hashes": {}, "actions": {}}
        for src, dst in pairs:
            rel = str(dst.relative_to(claude_home)).replace("\\", "/")
            if rel in owner_by_target:
                if owner_by_target[rel] != str(src):
                    raise SystemExit(f"目标冲突: {rel} 同时来自 {owner_by_target[rel]} 与 {src}")
                continue
            owner_by_target[rel] = str(src)
            entry["targets"].append(rel)
            entry["hashes"][rel] = sha256(src)
            planned.append((comp, entry, src, dst, rel))
        manifest["components"].append(entry)

    for comp, entry, src, dst, rel in planned:
        if dry:
            print(f"[dry-run] {src.relative_to(REPO)} -> {dst}")
            continue
        same = dst.is_file() and sha256(dst) == sha256(src)
        if same:
            entry["actions"][rel] = "unchanged"
            continue
        existed = dst.exists()
        if existed:
            if not force:
                _backup(dst, backup_root, rel)
            entry["actions"][rel] = "replaced"
        else:
            entry["actions"][rel] = "created"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if os.name != "nt" and dst.suffix in (".sh", ".py"):
            dst.chmod(dst.stat().st_mode | 0o111)

    # Memory 索引：作为受管目标纳入 targets/hashes/actions/backup
    for comp, entry, src, dst, rel in planned:
        if dry or comp["type"] != "memory" or not entry["targets"]:
            continue
        if _sandbox(comp):
            idx = Path(claude_home) / "test-sandbox" / "memory" / "MEMORY.md"
        elif project_slug:
            idx = Path(claude_home) / "projects" / project_slug / "memory" / "MEMORY.md"
        else:
            continue
        idx_rel = str(idx.relative_to(claude_home)).replace("\\", "/")
        before = idx.read_text(encoding="utf-8") if idx.exists() else None
        new_text = render_memory_index(before or "", comp,
                                       Path(entry["targets"][0]).name, comp["name"])
        if idx_rel not in entry["targets"]:
            entry["targets"].append(idx_rel)
        if before is not None and new_text == before:
            entry["hashes"][idx_rel] = sha256(idx)
            entry["actions"][idx_rel] = "unchanged"
        else:
            if before is not None:
                _backup(idx, backup_root, idx_rel)
            idx.write_text(new_text, encoding="utf-8")
            entry["hashes"][idx_rel] = sha256(idx)
            entry["actions"][idx_rel] = "replaced" if before is not None else "created"

    for entry in manifest["components"]:
        print(("规划" if dry else "安装") + f" {entry['name']} {entry['version']} -> "
              f"{len(entry['targets'])} 个文件")

    if not dry:
        claude_home.mkdir(parents=True, exist_ok=True)
        mp = claude_home / f"install-manifest-{txid}.json"
        body = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        mp.write_text(body, encoding="utf-8")
        (claude_home / "install-manifest-latest.json").write_text(body, encoding="utf-8")
        state_path = claude_home / "install-state.json"
        try:
            state = json.load(open(state_path, encoding="utf-8"))
        except Exception:
            state = {"schema_version": "1", "components": {}}
        state["updated_at"] = manifest["installed_at"]
        state["last_transaction"] = txid
        for entry in manifest["components"]:
            state["components"][entry["name"]] = entry
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        print(f"安装清单: {mp}")
        print("提示：hook 需在 settings.json 中注册，见 hooks/*/settings.example.json；安装器不自动改 settings。")
    else:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))


def rollback(manifest_path, claude_home, force=False):
    m = json.load(open(manifest_path, encoding="utf-8"))
    backup_root = Path(m["backup_root"])
    errors, done = [], 0
    for c in m.get("components", []):
        for rel in c.get("targets", []):
            dst = Path(claude_home) / rel
            action = (c.get("actions") or {}).get(rel)
            expected = (c.get("hashes") or {}).get(rel)
            if action == "unchanged":
                continue
            if action == "created":
                if not dst.exists():
                    continue
                if not force and expected and dst.is_file() and sha256(dst) != expected:
                    errors.append(f"{rel}: 安装后被修改，拒绝删除（ --force 覆盖）")
                    continue
                dst.unlink()
                done += 1
                print(f"删除 {rel}")
            elif action == "replaced":
                bak = backup_root / rel
                if not bak.exists():
                    errors.append(f"{rel}: 缺备份，无法恢复")
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(bak, dst)
                done += 1
                print(f"恢复 {rel}")
            else:
                errors.append(f"{rel}: 缺 action，无法安全回滚（旧 manifest 请人工处理）")
    state_path = Path(claude_home) / "install-state.json"
    try:
        state = json.load(open(state_path, encoding="utf-8"))
        for c in m.get("components", []):
            state.get("components", {}).pop(c.get("name"), None)
        state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    except Exception:
        pass
    print(f"回滚完成（{done} 项）；settings.json 未改动。")
    if errors:
        for e in errors:
            print(f"⚠️  {e}")
        raise SystemExit(1)


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
        rollback(args.rollback, args.claude_home, args.force)
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
