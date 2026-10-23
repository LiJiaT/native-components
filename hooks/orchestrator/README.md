# Orchestrator Hooks

Orchestrator 的两个上下文注入 hook。它们只负责“让主 agent 知道该用编排流程”，不做审批裁决，因此失败时静默放行，不阻断用户请求或会话启动。

## Hooks

| 脚本 | 事件 | Matcher | 输入 | 输出 | 失败策略 |
|---|---|---|---|---|---|
| `orchestrator-warmup.py` | `SessionStart` | `startup\|resume\|compact\|clear` | 事件 JSON（可含 `model` / `session.model`） | `hookSpecificOutput.additionalContext`，注入编排模式与模型档位提示 | 静默 `exit 0` |
| `orchestrator-classify.py` | `UserPromptSubmit` | 无 | 事件 JSON，读取 `prompt` | 复杂任务时输出 `additionalContext`；简单任务无输出 | 静默 `exit 0` |

两个脚本都从 stdin 读取 JSON，输出 `hookSpecificOutput`，不修改任何文件。

## 安装

```bash
mkdir -p ~/.claude/hooks/orchestrator
cp hooks/orchestrator/*.py ~/.claude/hooks/orchestrator/
```

把 `settings.example.json` 中的 `hooks` 配置合并进 `~/.claude/settings.json`，并按实际安装路径调整。Windows 使用 `win/*.cmd` 包装器：

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "startup|resume|compact|clear",
      "hooks": [{
        "type": "command",
        "command": "C:/Users/<user>/.claude/hooks/orchestrator/win/orchestrator-warmup.cmd",
        "timeout": 10
      }]
    }],
    "UserPromptSubmit": [{
      "hooks": [{
        "type": "command",
        "command": "C:/Users/<user>/.claude/hooks/orchestrator/win/orchestrator-classify.cmd",
        "timeout": 5
      }]
    }]
  }
}
```

`win/*.cmd` 里的 Python 与 Git 路径是按参考机器写的示例，换机器时要改。

## 依赖

- `agents/orchestrator.md`：实际执行编排流程的 agent。
- `skills/orchestrator/`：agent 的 references 与 `task_packager.py`。

只装 hooks 会得到“提示主 agent 去编排”，但不会得到 orchestrator agent 本体。

## 验证

```bash
# 简单任务：应无输出
python hooks/orchestrator/orchestrator-classify.py < hooks/orchestrator/tests/classify-simple.json; echo "exit=$?"

# 复杂任务：应输出包含“Orchestrator 自动激活”的 JSON
python hooks/orchestrator/orchestrator-classify.py < hooks/orchestrator/tests/classify-complex.json

# 会话启动：应输出包含环境标识的 JSON
python hooks/orchestrator/orchestrator-warmup.py < hooks/orchestrator/tests/warmup.json

# 一次跑完
bash hooks/orchestrator/tests/run-tests.sh
```

Windows 下用 `python` 或 `py -3` 替换 `python3`；`run-tests.sh` 支持 `PYTHON=python`。

## 回滚

从 `settings.json` 删除对应 `SessionStart` / `UserPromptSubmit` 条目，再删除 `~/.claude/hooks/orchestrator/`。hook 不写文件，回滚不需要清理数据。

## 边界

- `orchestrator-classify.py` 是启发式分类，不是确定性闸门；误判只影响是否注入提示，不应据此阻断任务。
- 需要“失败即阻断”的审批或校验，按规范 §5.8 另行实现 PreToolUse / Stop hook，不要复用本目录的 fail-open 设计。
