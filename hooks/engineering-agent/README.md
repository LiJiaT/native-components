# Engineering Agent Hooks

Engineering Agent 的两个上下文注入 hook。它们只负责“让主 agent 知道该用编排流程”，不做审批裁决，因此失败时静默放行，不阻断用户请求或会话启动。

## Hooks

| 脚本 | 事件 | Matcher | 输入 | 输出 | 失败策略 |
|---|---|---|---|---|---|
| `engineering-agent-warmup.py` | `SessionStart` | `startup\|resume\|compact\|clear` | 事件 JSON（可含 `model` / `session.model`） | `hookSpecificOutput.additionalContext`，注入编排模式与模型档位提示 | 静默 `exit 0` |
| `engineering-agent-classify.py` | `UserPromptSubmit` | 无 | 事件 JSON，读取 `prompt` | 复杂任务时输出 `additionalContext`；简单任务无输出 | 静默 `exit 0` |

两个脚本都从 stdin 读取 JSON，输出 `hookSpecificOutput`，不修改任何文件。

## 安装

```bash
mkdir -p ~/.claude/hooks/engineering-agent
cp hooks/engineering-agent/*.py ~/.claude/hooks/engineering-agent/
```

把 `settings.example.json` 中的 `hooks` 配置合并进 `~/.claude/settings.json`，并按实际安装路径调整。Windows 使用 `win/*.cmd` 包装器：

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "startup|resume|compact|clear",
      "hooks": [{
        "type": "command",
        "command": "C:/Users/<user>/.claude/hooks/engineering-agent/win/engineering-agent-warmup.cmd",
        "timeout": 10
      }]
    }],
    "UserPromptSubmit": [{
      "hooks": [{
        "type": "command",
        "command": "C:/Users/<user>/.claude/hooks/engineering-agent/win/engineering-agent-classify.cmd",
        "timeout": 5
      }]
    }]
  }
}
```

`win/*.cmd` 里的 Python 与 Git 路径是按参考机器写的示例，换机器时要改。

## 依赖

- `agents/engineering-agent.md`：实际执行编排流程的 agent。
- `skills/engineering-agent/`：agent 的 references 与 `task_packager.py`。

只装 hooks 会得到“提示主 agent 去编排”，但不会得到 Engineering Agent 本体。

## 验证

```bash
# 简单任务：应无输出
python hooks/engineering-agent/engineering-agent-classify.py < hooks/engineering-agent/tests/classify-simple.json; echo "exit=$?"

# 复杂任务：应输出包含“Engineering Agent 自动激活”的 JSON
python hooks/engineering-agent/engineering-agent-classify.py < hooks/engineering-agent/tests/classify-complex.json

# 会话启动：应输出包含环境标识的 JSON
python hooks/engineering-agent/engineering-agent-warmup.py < hooks/engineering-agent/tests/warmup.json

# 一次跑完
bash hooks/engineering-agent/tests/run-tests.sh
```

Windows 下用 `python` 或 `py -3` 替换 `python3`；`run-tests.sh` 支持 `PYTHON=python`。

## 回滚

从 `settings.json` 删除对应 `SessionStart` / `UserPromptSubmit` 条目，再删除 `~/.claude/hooks/engineering-agent/`。hook 不写文件，回滚不需要清理数据。

## 边界

- `engineering-agent-classify.py` 是启发式分类，不是确定性闸门；误判只影响是否注入提示，不应据此阻断任务。
- 需要“失败即阻断”的审批或校验，按规范 §5.8 另行实现 PreToolUse / Stop hook，不要复用本目录的 fail-open 设计。
