#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安装器回归：hook 目录名与缓存文件过滤。"""
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import install  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  OK {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL {name} {detail}")


def main():
    reg = install.load_registry()
    check("installer 为 source-only",
          reg["installer"].get("install_target") == "source-only")
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        for name, expected in (("orchestrator-hooks", "hooks/orchestrator"),
                               ("self-evolve-hooks", "hooks/self-evolve")):
            comp = reg[name]
            pairs = install.target_paths(comp, home, None)
            rels = [str(dst.relative_to(home)).replace("\\", "/") for _, dst in pairs]
            check(f"{name} 安装目录", all(r.startswith(expected + "/") for r in rels),
                  f"targets={rels[:3]}")
            check(f"{name} 无缓存文件",
                  not any("__pycache__" in r or r.endswith(".pyc") for r in rels))
        comp = reg["assetize"]
        rels = [str(dst.relative_to(home)).replace("\\", "/")
                for _, dst in install.target_paths(comp, home, None)]
        check("skill 无缓存文件",
              not any("__pycache__" in r or r.endswith(".pyc") for r in rels))
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        return 1
    print("PASS: installer paths and cache filter")
    return 0


if __name__ == "__main__":
    sys.exit(main())
