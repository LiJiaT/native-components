#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安装器回归：目标映射、事务回滚、MEMORY 索引、test-sandbox、install gate。"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable
FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  OK {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL {name} {detail}")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(args):
    return subprocess.run([PY, "-X", "utf8"] + [str(x) for x in args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def latest(home):
    return home / "install-manifest-latest.json"


def main():
    sys.path.insert(0, str(REPO / "tools"))
    import install as inst
    reg = inst.load_registry()
    check("installer 为 source-only", reg["installer"].get("install_target") == "source-only")
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        for name, expected in (("orchestrator-hooks", "hooks/orchestrator"),
                               ("self-evolve-hooks", "hooks/self-evolve")):
            rels = [str(dst.relative_to(home)).replace("\\", "/")
                    for _, dst in inst.target_paths(reg[name], home, None)]
            check(f"{name} 安装目录", all(r.startswith(expected + "/") for r in rels),
                  rels[:3])
            check(f"{name} 无缓存文件",
                  not any("__pycache__" in r or r.endswith(".pyc") for r in rels))
        skill_rels = [str(dst.relative_to(home)).replace("\\", "/")
                      for _, dst in inst.target_paths(reg["assetize"], home, None)]
        check("skill 无缓存文件",
              not any("__pycache__" in r or r.endswith(".pyc") for r in skill_rels))
        flow_rels = [str(dst.relative_to(home)).replace("\\", "/")
                     for _, dst in inst.target_paths(reg["self-evolution"], home, None)]
        check("flow README 不再撞同一目标", len(flow_rels) == len(set(flow_rels)), flow_rels)
        gate_rels = [str(dst.relative_to(home)).replace("\\", "/")
                     for _, dst in inst.target_paths(reg["gate-core"], home, None)]
        check("gate 安装含 registry 快照", "gates/registry.json" in gate_rels, gate_rels)

        full = run([REPO / "tools/install.py", "--claude-home", home,
                    "--project-slug", "synthetic-project", "--all"])
        check("全量安装成功", full.returncode == 0, full.stderr[-300:])
        gate = run([REPO / "gates/gate.py", "install",
                    "--manifest", latest(home), "--repo", REPO])
        check("install gate 通过", gate.returncode == 0, gate.stdout[-300:])
        m = json.load(open(latest(home), encoding="utf-8"))
        check("transaction_id 唯一格式", len(m["transaction_id"]) > 20)
        check("MEMORY.md 纳入 targets",
              any("MEMORY.md" in t for c in m["components"] for t in c["targets"]))
        check("目标全局唯一",
              len({t for c in m["components"] for t in c["targets"]}) ==
              sum(len(c["targets"]) for c in m["components"]))
        installed_gate = run([home / "gates/gate.py", "component-registry"])
        check("安装后 gate registry 可用", installed_gate.returncode == 0,
              installed_gate.stdout[-300:])

        rule = home / "rules/no-auto-external-actions.md"
        rule.write_text(rule.read_text(encoding="utf-8") + "\nTAMPER\n", encoding="utf-8")
        bad = run([REPO / "gates/gate.py", "install",
                   "--manifest", latest(home), "--repo", REPO])
        check("install gate 检出篡改", bad.returncode != 0, bad.stdout[-200:])
        shutil.copy2(REPO / reg["rule-no-auto-external-actions"]["path"], rule)
        check("恢复后 gate 通过",
              run([REPO / "gates/gate.py", "install", "--manifest", latest(home),
                   "--repo", REPO]).returncode == 0)

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        rule = home / "rules/no-auto-external-actions.md"
        rule.parent.mkdir(parents=True)
        shutil.copy2(REPO / reg["rule-no-auto-external-actions"]["path"], rule)
        r = run([REPO / "tools/install.py", "--claude-home", home,
                 "--component", "rule-no-auto-external-actions"])
        check("同内容预存安装成功", r.returncode == 0, r.stderr[-200:])
        m = json.load(open(latest(home), encoding="utf-8"))
        comp = next(c for c in m["components"] if c["name"] == "rule-no-auto-external-actions")
        action = comp["actions"]["rules/no-auto-external-actions.md"]
        check("同内容标记 unchanged", action == "unchanged", action)
        r = run([REPO / "tools/install.py", "--claude-home", home,
                 "--rollback", latest(home)])
        check("回滚不删除预存文件", rule.is_file(), r.stdout[-200:])

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        idx = home / "projects/p/memory/MEMORY.md"
        idx.parent.mkdir(parents=True)
        idx.write_text("# User\n\n- keep\n", encoding="utf-8")
        r = run([REPO / "tools/install.py", "--claude-home", home,
                 "--project-slug", "p", "--component", "memory-asset-taxonomy"])
        check("memory 安装成功", r.returncode == 0, r.stderr[-200:])
        check("索引写入受管块", "AI-NATIVE-COMPONENT" in idx.read_text(encoding="utf-8"))
        r = run([REPO / "tools/install.py", "--claude-home", home,
                 "--rollback", latest(home)])
        text = idx.read_text(encoding="utf-8")
        check("索引回滚保留用户正文", "# User" in text and "AI-NATIVE-COMPONENT" not in text,
              text)
        check("topic 回滚删除",
              not (home / "projects/p/memory/asset-taxonomy.md").exists())

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        r = run([REPO / "tools/install.py", "--claude-home", home,
                 "--component", "sample-rule-bist-scan-same-cycle", "--allow-test-only"])
        check("test-only 安装成功", r.returncode == 0, r.stderr[-200:])
        files = [str(p.relative_to(home)).replace("\\", "/")
                 for p in home.rglob("*") if p.is_file()]
        check("test-only 只落 test-sandbox",
              all(f.startswith("test-sandbox/") or f.startswith("install-")
                  for f in files), files)
        check("test-only 不写生产 rules",
              not (home / "rules/bist-scan-same-cycle-exclusion.md").exists())

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        r = run([REPO / "tools/install.py", "--claude-home", home,
                 "--component", "orchestrator", "--project-slug", "p"])
        check("依赖闭包安装成功", r.returncode == 0, r.stderr[-200:])
        m = json.load(open(latest(home), encoding="utf-8"))
        names = {c["name"] for c in m["components"]}
        check("依赖闭包含 grill-me-with-doc", "grill-me-with-doc" in names, names)
        check("依赖闭包含 task-packager", "task-packager" in names, names)

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        r = run([REPO / "tools/install.py", "--claude-home", home,
                 "--component", "orchestrator", "--project-slug", "p", "--no-deps"])
        check("--no-deps 安装成功", r.returncode == 0, r.stderr[-200:])
        m = json.load(open(latest(home), encoding="utf-8"))
        names = {c["name"] for c in m["components"]}
        check("--no-deps 不装依赖", names == {"orchestrator"}, names)

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        r = run([REPO / "tools/install.py", "--claude-home", home,
                 "--component", "memory-asset-taxonomy"])
        check("显式 Memory 缺 slug 失败", r.returncode != 0, r.stdout[-200:])
        check("失败不写空 latest", not (home / "install-manifest-latest.json").exists())

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        rule = home / "rules/no-auto-external-actions.md"
        rule.parent.mkdir(parents=True)
        rule.write_text("OLD LOCAL CONTENT\n", encoding="utf-8")
        r = run([REPO / "tools/install.py", "--claude-home", home,
                 "--component", "rule-no-auto-external-actions"])
        check("replaced 安装成功", r.returncode == 0, r.stderr[-200:])
        rule.write_text("USER EDIT AFTER INSTALL\n", encoding="utf-8")
        r = run([REPO / "tools/install.py", "--claude-home", home,
                 "--rollback", latest(home)])
        check("replaced 回滚保护用户修改", r.returncode != 0 and
              "USER EDIT AFTER INSTALL" in rule.read_text(encoding="utf-8"), r.stdout[-300:])
        r = run([REPO / "tools/install.py", "--claude-home", home,
                 "--rollback", latest(home), "--force"])
        check("--force 恢复旧文件", r.returncode == 0 and
              "OLD LOCAL CONTENT" in rule.read_text(encoding="utf-8"), r.stdout[-300:])

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        for _ in range(2):
            r = run([REPO / "tools/install.py", "--claude-home", home,
                     "--component", "rule-no-auto-external-actions"])
            check("重复安装成功", r.returncode == 0, r.stderr[-200:])
        r = run([REPO / "tools/install.py", "--claude-home", home,
                 "--rollback", latest(home)])
        state = json.load(open(home / "install-state.json", encoding="utf-8"))
        check("unchanged 回滚恢复前序安装状态",
              "rule-no-auto-external-actions" in state.get("components", {}), state)

    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        return 1
    print("PASS: installer transactions / rollback / sandbox / install gate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
