#!/usr/bin/env python3
"""
SessionStart hook: Engineering Agent 上下文预热。

在 session 启动时注入轻量级工程智能体标识，
让 Claude 知道当前环境有 engineering-agent 能力可用。

设计原则：任何异常都静默退出（exit 0、无输出），绝不阻断 session 启动。
"""

import json
import os
import sys

# 轻量模型档位词（P1-3：只认结构性档位词，不认品牌词）。
# 品牌词不能代表强弱：DeepSeek-V4-Pro / Kimi-K3 / MiniMax-M3 都是强模型。
# 注意 "mini" 会子串命中品牌 MiniMax——所以匹配前先把品牌 token 剔除，
# 否则 MiniMax-M3 被误判为弱模型。
WEAK_MODEL_MARKERS = ("flash", "lite", "mini", "air", "small")
# 模型名中的品牌 token（剔除后剩余部分才按档位词判断）
BRAND_TOKENS = ("deepseek", "kimi", "minimax", "glm", "doubao", "seed")


def is_weak_model(model: str) -> bool:
    """判断模型是否属于轻量档位。

    先剔除品牌 token（deepseek/kimi/minimax/glm/doubao 等），
    剩余字符串只要含档位词（flash/lite/mini/air/small）即判为弱模型。
    MiniMax-M3 剔除 minimax 后剩 -m3，不含档位词 → 强模型，不警告。
    """
    low = model.lower()
    for token in BRAND_TOKENS:
        low = low.replace(token, "")
    return any(marker in low for marker in WEAK_MODEL_MARKERS)

# settings.json 相对主目录的路径（兜底读顶层 model 字段）
SETTINGS_RELPATH = os.path.expanduser("~/.claude/settings.json")


def _read_settings_model() -> str:
    """从 settings.json 顶层 "model" 字段读取当前模型（多来源兜底之一）。"""
    try:
        with open(SETTINGS_RELPATH, encoding="utf-8") as fh:
            return json.load(fh).get("model") or ""
    except Exception:
        return ""


def main() -> None:
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        data = json.loads(raw)
    except Exception:
        data = {}

    # 注入 engineering-agent 身份标识（极轻量，不干扰正常对话）
    ctx = (
        "[环境标识] 本环境已启用用户级工程智能体 (Engineering Agent)。"
        "当用户提出复杂任务、多步骤项目或需要结构化管理的工作时，"
        "请主动委派给 Engineering Agent 进行全流程管理（澄清→规划→分解→验收→写回）。"
        "简单单步任务直接执行即可，不必触发 engineering-agent。"
    )

    # P1-3：检测当前模型。多来源兜底：hook input model → env ANTHROPIC_MODEL →
    # env CLAUDE_MODEL → settings.json 顶层 "model"。
    # 本环境 settings.json 用顶层 "model" 而非 ANTHROPIC_MODEL env，所以必须读文件。
    current_model = (
        data.get("model")
        or data.get("session", {}).get("model")
        or os.environ.get("ANTHROPIC_MODEL", "")
        or os.environ.get("CLAUDE_MODEL", "")
        or _read_settings_model()
        or ""
    )

    # 无法识别模型时：不当作强模型也不误报，输出一句中性提示（由模型自查）。
    if not current_model:
        ctx += (
            "\n[模型提示] 未能识别当前 session 模型；engineering-agent 建议用强模型编排，"
            "如当前为 flash 级请提示用户切换。"
        )
    elif is_weak_model(current_model):
        ctx += (
            f"\n[模型提示] 当前 session 模型为 {current_model}（轻量级）。"
            "engineering-agent 的澄清/规划/验收属于长程高价值判断，建议使用强模型；"
            "如遇复杂任务，先提示用户切换模型或用 /model 切换后委派。"
        )
    # 其余情况：已识别且非轻量级，不提示（避免误报）。

    try:
        sys.stdout.write(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": ctx,
                    }
                },
                ensure_ascii=False,
            )
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
