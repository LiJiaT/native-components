"""冒烟测试：claude-agent-sdk 经火山方舟网关是否可用。

token 从 ~/.claude/settings.json 的 env 读取（单一真身），不进命令行、不打印。
用法：python smoke_test.py   （依赖 claude_agent_sdk、任意 Python 3.10+）
退出码 0 = 链路正常。
"""
import asyncio
import json
import pathlib
import sys

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    query,
)

_cfg = json.loads((pathlib.Path.home() / ".claude" / "settings.json").read_text())
settings = _cfg["env"]

# 模型单一真身 = settings.json 顶层 model 键（/model 写入处）；env ANTHROPIC_MODEL 已移除，
# 它一旦存在会压过 model 键、使 /model 无法持久化。SDK 侧仍以 env 形式继承该模型名
# （options.model 出过空回复，勿改）。
MODEL = _cfg.get("model") or settings.get("ANTHROPIC_MODEL")

# 关键点：模型放 env ANTHROPIC_MODEL 继承，不用 options.model（后者出过空回复）
OPTS = dict(
    cwd="/tmp",
    env={
        "ANTHROPIC_BASE_URL": settings["ANTHROPIC_BASE_URL"],
        "ANTHROPIC_AUTH_TOKEN": settings["ANTHROPIC_AUTH_TOKEN"],
        "ANTHROPIC_MODEL": MODEL,
        "HTTPS_PROXY": settings.get("HTTPS_PROXY", ""),
        "HTTP_PROXY": settings.get("HTTP_PROXY", ""),
        "NO_PROXY": settings.get("NO_PROXY", ""),
    },
    # 去掉项目级 settings 噪音（用户级 hooks 仍会触发，属正常）
    setting_sources=None,
)


async def main() -> int:
    session_id = None
    text_parts: list[str] = []
    cost = None
    async for msg in query(
        prompt="只回复两个字：正常",
        options=ClaudeAgentOptions(**OPTS),
    ):
        # isinstance 分发 + 未知类型静默忽略（HookEventMessage 等会随版本出现）
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if getattr(block, "type", "") == "text":
                    text_parts.append(block.text)
        elif isinstance(msg, ResultMessage):
            session_id = msg.session_id
            cost = msg.total_cost_usd
    reply = "".join(text_parts).strip()
    print(f"模型回复: {reply!r}")
    print(f"session_id: {session_id}")
    print(f"cost_usd: {cost}")
    return 0 if "正常" in reply else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
