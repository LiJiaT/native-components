#!/usr/bin/env python3
"""UserPromptSubmit hook：用户输入命中某场景触发词时，把该场景 STATE.md 注入当轮上下文。

设计原则：任何异常都静默退出（exit 0、无输出），绝不阻断用户 prompt。
数据源：~/.claude/scenarios/<name>/scenario.json（字段 name / triggers / state）。
机制说明：~/.claude/scenarios/README.md
"""

import glob
import json
import os
import sys

SCENARIOS_DIR = os.path.expanduser("~/.claude/scenarios")


def main() -> None:
    try:
        raw = sys.stdin.read()
    except Exception:
        return
    if not raw.strip():
        return
    try:
        prompt = json.loads(raw).get("prompt") or ""
    except Exception:
        return
    if not prompt:
        return

    low = prompt.lower()
    for cfg_path in sorted(glob.glob(os.path.join(SCENARIOS_DIR, "*", "scenario.json"))):
        try:
            with open(cfg_path, encoding="utf-8") as fh:
                cfg = json.load(fh)
        except Exception:
            continue

        triggers = [t for t in (cfg.get("triggers") or []) if t]
        if not any(t.lower() in low for t in triggers):
            continue

        state_path = os.path.join(os.path.dirname(cfg_path), cfg.get("state") or "STATE.md")
        try:
            with open(state_path, encoding="utf-8") as fh:
                state = fh.read()
        except Exception:
            continue

        name = cfg.get("name") or os.path.basename(os.path.dirname(cfg_path))
        ctx = (
            f"[场景上下文] 当前对话涉及长期工作线「{name}」，以下为其当前状态快照"
            f"（源：{state_path}）。按日期的时间线与细节见同目录 HISTORY.md 及文中指针。\n\n"
            f"{state}"
        )
        sys.stdout.write(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": ctx,
                    }
                },
                ensure_ascii=False,
            )
        )
        return


main()
