---
name: create-hook
description: 把一次确定性的事件回调做成 Claude Code hook 组：脚本读 stdin 事件 JSON、只做上下文注入或旁路提示 → 生成 settings.example.json、Windows 包装器、最小测试与 README 五要素 → 跑静态校验 → 在 Claude Code 沙箱真实触发一次。当用户说“建个 hook”“创建钩子”“每次会话启动/提交 prompt 时自动做某件事”“把这段检查挂到某个事件上”时使用。不做审批门禁（fail-closed 的拦截放 gates/），也不创建 skill 或 agent。
---

# Create Hook（钩子工厂）

把"每次都要人记得做的一步"挂到确定的会话事件上。hook 的价值是**稳定触发**，不是获得否决权：本技能产出的 hook 一律 fail-open，异常静默退出，不阻断用户。

**模板单一来源**：`../create-skill/references/component-template.md` §3（不复制模板；安装时三个 create 技能一起装）。
**验收协议**：`../create-skill/references/claude-code-test.md` C2。

## 何时使用

- **使用**：用户要在会话启动、用户提交 prompt、会话结束等事件上自动做一次轻量动作（注入环境提示、记录一行标记、提醒待确认项）；用户说"挂个钩子""每次开新会话就…"。
- **不要使用**：
  - 需要**阻断**危险操作或做审批裁决 → 那是 `gates/` 的门禁，本技能只产旁路 hook。
  - 需要主 agent 按步骤执行一段流程 → 用 `create-skill`。
  - 需要独立角色与工具边界 → 用 `create-agent`。

## 输入

| 输入 | 必需 | 缺失时怎么办 |
|---|---|---|
| 事件名（SessionStart / UserPromptSubmit / SessionEnd / PreToolUse 等） | 是 | 按"动作发生在什么时候"选，向用户确认一次 |
| matcher | 否 | SessionStart 默认 `startup|resume|compact|clear`，其他可省略 |
| 触发后要做什么（一句话，且必须是轻量动作） | 是 | 追问；若动作需要读写大量文件或调网络，劝退并说明原因 |
| 失败策略 | 是 | 默认 fail-open（静默 exit 0）；用户要求阻断则转 `gates/` |
| 输出形态 | 否 | 默认 `hookSpecificOutput.additionalContext` |

## 流程

1. **定事件与 matcher**：动作发生在哪个钩子点、对哪类输入生效。
2. **写脚本**：照模板 §3.2 骨架，从 stdin 读完事件 JSON，只做轻量判断，输出 `hookSpecificOutput`，任何异常 `return 0`。
3. **配示例**：`settings.example.json` 写清事件、matcher、command、timeout；**不合并进用户 `settings.json`**。
4. **补包装器**：每个 `.py` 一个 `win/<name>.cmd`，末行 `exit /b 0`。
5. **写测试与 README**：`tests/<event>.json` 给最小事件；README 五要素齐全（触发事件、matcher、输入输出、失败策略、回滚）。
6. **静态校验**：
   ```bash
   python -X utf8 skills/create-skill/scripts/validate_component.py --type hook hooks/<name>
   ```
7. **真实触发（不可省）**：按验收协议 C2 在沙箱注册并跑 `claude -p`，marker 真的出现才算通过。
8. **交付**：报校验退出码、触发证据路径、以及"只给示例配置、需人工合并"的说明。

## 输出

| 产物 | 路径 | 说明 |
|---|---|---|
| 主脚本 | `hooks/<name>/<name>.py` | 读 stdin、fail-open、不写文件 |
| 示例配置 | `hooks/<name>/settings.example.json` | 含事件/matcher/command/timeout |
| Windows 包装器 | `hooks/<name>/win/<name>.cmd` | 末行 `exit /b 0` |
| 测试样例 | `hooks/<name>/tests/<event>.json` | 最小事件输入 |
| 说明 | `hooks/<name>/README.md` | 五要素 + 安装 + 验证 + 回滚 + 边界 |

**不产出**：用户 `settings.json` 的修改、门禁规则、registry 条目、git 提交。

## 边界

- 不把 hook 写成 fail-closed 闸门；拦截逻辑属于 `gates/`，混进来会让会话因一次脚本异常而不可用。
- 不改用户 `settings.json`，不写 `~/.claude/hooks` 之外的路径；安装归 `install.py`，配置合并由人执行。
- 不在 hook 里发网络请求、写业务数据、调用模型；超时时间显式给（≤10 秒）。
- 不在脚本里硬编码 Python 安装路径之外的个人目录；`win/*.cmd` 的 Python 路径换机器必须可改。
- 不创建 skill / agent，也不调用另外两个 create 技能代劳。

## 验收

```bash
# 1) 结构、示例配置、包装器、测试、README 五要素
python -X utf8 skills/create-skill/scripts/validate_component.py --type hook hooks/<name>   # 期望 exit 0

# 2) 本地最小事件能跑通
python -X utf8 hooks/<name>/<name>.py < hooks/<name>/tests/<event>.json                     # 期望 exit 0

# 3) 沙箱真实触发证据
ls <sandbox>/evidence/c2-hook/marker.txt
```

逐项判据：
- 校验命令 exit 0；
- 最小事件跑通且输出是合法 JSON（或按设计无输出）；
- 沙箱 `marker.txt` 出现预期行，**且** `stream.jsonl` 里有本 hook 的 `hook_response`、其输出含本 hook 的特征串，**且**该事件的 `session_id` 与 marker 一致。只看到 `hook_started`/`hook_response` 不够：用户级 hooks（如 engineering-agent）同样会产出 `SessionStart` 事件和同一个 session_id，必须用 hook 自身输出特征区分。

## 示例

**输入**：用户说"每次新会话开始，往 `/tmp/session-mark.log` 记一行时间戳，方便我看今天开了几次"。

**输出**：
- `hooks/probe-session-mark/probe-session-mark.py`：读 SessionStart 事件，向 marker 文件追加时间戳，异常静默退出；
- `settings.example.json`：`SessionStart` + `matcher=startup|resume|compact|clear` + `timeout=5`；
- `win/probe-session-mark.cmd`：包装器，末行 `exit /b 0`；
- `tests/session-start.json`：最小事件样例；
- 校验 exit 0；沙箱 C2 跑完 `marker.txt` 多出一行，`stream.jsonl` 记录同一次 `session_id`。
