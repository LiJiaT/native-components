<!-- 派生自 Anthropic skill-creator (Apache-2.0)
     upstream: native-components/env/skills/skill-creator/SKILL.md
     sha256: E030E7685E26283B4A76F5202AA3AE8516FB41DDE799BE5AE8EA6393EC009FE9
     修改摘要: 只保留目录骨架、frontmatter 规则与渐进披露思路；去掉评测流水线、
               .skill 打包与跨 IDE 安装，改为 native-components 的 registry + install.py 契约。 -->

# 组件模板 v1（skill / hook / agent 共用）

本文件是 `create-skill`、`create-hook`、`create-agent` 三个技能的**唯一模板来源**。另外两个技能只写指针，不复制本文件。改模板就改这里，然后跑 §6 的校验。

- 适用仓库：`native-components`
- 校验器：`skills/create-skill/scripts/validate_component.py`
- 校验器自测：`python -X utf8 skills/create-skill/scripts/validate_component.py --self-test`

---

## 0. 使用方式（三步，不许跳）

1. **定形**：先确认产物类型（skill / hook / agent）与名字。名字 = 目录名 = frontmatter `name`，kebab-case。
2. **落骨架**：复制 §2/§3/§4 对应骨架，把每一节写成真实内容；不适用的节删掉，不要留占位文字。
3. **跑校验**：`python -X utf8 skills/create-skill/scripts/validate_component.py --type <skill|hook|agent> <path>`，必须 exit 0（WARN 可接受但要能解释）。

> 文件存在不等于完成。交付前还要按 `create-*` 技能的"实测"要求，在 Claude Code 沙箱里真实触发一次。

---

## 1. 通用约定

| 约定 | 规则 | 依据 |
|---|---|---|
| 目录 | 一个组件一个 kebab-case 目录（agent 是单文件） | `README.md` 目录约定 |
| 入口 | skill 用 `SKILL.md`；hook/agent 用 `README.md` / `<name>.md` | 同上 |
| 名字 | 小写连字符，≤64 字符，目录名与 `name` 必须一致 | 官方 `quick_validate.py` 规则 |
| 描述 | `description` ≤1024 字符、无尖括号、写清"做什么 + 什么时候用 + 什么时候不用" | 同上 + 本仓库 skill 实际触发机制 |
| 私有数据 | 不含密钥、个人路径、内部主机、真实客户数据 | `skills/README.md` 收录标准 |
| 来源 | 派生内容在文件头写 Apache-2.0 与 upstream hash（见 §7） | 许可要求 |
| 版本 | registry 里 `x.y.z`；内容变更就递增，不静默改版本 | `gate.py` 七字段校验 |
| 安装 | 交给 `tools/install.py`，组件内不写安装脚本、不改 `settings.json` | `README.md` 安装节 |
| 上下文 | `SKILL.md` 控制在 500 行内，长内容进 `references/`，确定性操作进 `scripts/` | 渐进披露 |

---

## 2. skill 模板

### 2.1 目录

```text
skills/<name>/
├── SKILL.md            # 必填，七节
├── references/         # 可选：长文档、schema、平台差异
├── scripts/            # 可选：确定性校验/生成脚本
└── assets/             # 可选：输出用模板文件
```

### 2.2 `SKILL.md` 骨架

```markdown
---
name: <kebab-case-name>
description: <做什么 + 何时触发（列具体用户说法）+ 何时不要用；≤1024 字符，不含尖括号>
---

# <中文标题>

<一句话说明这个技能解决什么问题。>

## 何时使用

- 使用：<用户说法/情境 1>、<情境 2>
- 不要使用：<反例 1>、<反例 2>（说明改用哪个技能或直接做）

## 输入

| 输入 | 必需 | 缺失时怎么办 |
|---|---|---|
| <路径/参数> | 是 | <报错退出 / 用默认值 / 追问> |

## 流程

1. <步骤> → 产出 <文件/结论>
2. <步骤> → 产出 <文件/结论>
3. 跑校验：`python -X utf8 "<技能目录>/scripts/<validator>.py" <args>`，非 0 即停。
   脚本路径必须从技能目录解析（`$CLAUDE_SKILL_DIR` 或绝对路径），不要写成裸相对路径——实测在项目根执行会失败。

## 输出

| 产物 | 路径 | 说明 |
|---|---|---|
| <文件> | `<相对路径>` | <字段/格式> |

## 边界

- 不<越界动作 1>（例如：不直接写入用户环境）
- 不<越界动作 2>（例如：不 push、不安装）
- <什么情况下转交给别的技能处理>

## 验收

```bash
python -X utf8 scripts/validate_component.py --type skill <path>   # exit 0
```

- <逐项判据：文件存在 / 字段齐全 / 命令退出码>

## 示例

**输入**：<一句真实用户请求>
**输出**：<落盘路径 + 关键字段 + 校验结果>
```

### 2.3 七节各写什么

| 节 | 判据 |
|---|---|
| 何时使用 | 至少一条"不要使用"，且指向替代方案 |
| 输入 | 每项标必需/可选，缺必需项要有确定动作 |
| 流程 | 有序、每步有产出；含校验命令 |
| 输出 | 精确到路径与文件名 |
| 边界 | ≥1 条"不做什么"，来自任务书或仓库规则 |
| 验收 | 至少一条可执行命令，退出码即结论 |
| 示例 | 具体输入→具体产出，不是抽象描述 |

---

## 3. hook 模板

### 3.1 目录

```text
hooks/<name>/
├── <name>.py                 # 主脚本：读 stdin JSON → 输出 hookSpecificOutput → exit 0
├── <name2>.py                # 可选，多事件各一脚本
├── settings.example.json     # 必填，示例配置（不自动应用）
├── win/<name>.cmd            # 必填，Windows 包装器（每个 .py 一个）
├── tests/<event>.json        # 必填，最小事件输入
└── README.md                 # 必填，五要素
```

### 3.2 脚本骨架

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""<事件> hook：<一句话职责>。fail-open：任何异常都静默 exit 0。"""
import json
import sys


def main() -> int:
    try:
        # 未使用 stdin 时也要读完，避免上游写管道被阻塞
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    try:
        context = build_context(event)   # 只做轻量判断，不做重活
    except Exception:
        return 0

    if context:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "<SessionStart|UserPromptSubmit|...>",
                "additionalContext": context,
            }
        }, ensure_ascii=False))
    return 0


def build_context(event: dict) -> str:
    return ""


if __name__ == "__main__":
    sys.exit(main())
```

要点：
- 只做上下文注入或旁路提示，**不做审批裁决**；需要 fail-closed 的门禁放 `gates/`。
- 不写业务数据、不改用户配置、不发网络请求；只允许写「自身状态/标记」类小文件（如 marker），且路径由 `command` 参数传入，不硬编码。
- 单次执行控制在 5 秒内（`timeout` 在 settings 里显式给）。

### 3.3 `settings.example.json`

```json
{
  "hooks": {
    "<EventName>": [
      {
        "matcher": "<正则或省略>",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/<name>/win/<name>.cmd",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

- POSIX 用 `~/.claude/hooks/<name>/<name>.py`，Windows 用 `win/*.cmd`。
- 只给示例，**不合并进用户 `settings.json`**；合并是安装步骤，由人执行或 Gate D 明确批准。

### 3.4 `win/<name>.cmd`

```bat
@echo off
rem <EventName> hook wrapper (Windows). <一句话职责>
"%LOCALAPPDATA%\Programs\Python\Python314\python.exe" "%~dp0..\<name>.py"
exit /b 0
```

Python 路径优先写 `python`（PATH 可控时）；只有目标机器 PATH 不可控时才写绝对路径，并注明换机器要改。`exit /b 0` 保证 hook 失败不阻断会话。

### 3.5 `tests/<event>.json`

最小真实事件形状，例如 SessionStart：

```json
{"session_id": "test-session", "hook_event_name": "SessionStart", "source": "startup"}
```

### 3.6 `README.md` 骨架（五要素必须出现）

```markdown
# <Name> Hook

<一句话职责，以及为什么是 fail-open。>

## Hooks

| 脚本 | 触发事件 | matcher | 输入 | 输出 | 失败策略 |
|---|---|---|---|---|---|
| `<name>.py` | `<EventName>` | `<matcher>` | stdin 事件 JSON | `additionalContext` | 静默 exit 0 |

## 安装

1. `python -X utf8 tools/install.py --component <name>`
2. 把 `settings.example.json` 的 `hooks` 合并进 `~/.claude/settings.json`（Windows 用 `win/*.cmd` 绝对路径）

## 验证

```bash
python -X utf8 hooks/<name>/<name>.py < hooks/<name>/tests/<event>.json
```

## 回滚

从 `settings.json` 删除对应事件条目，再删除 `~/.claude/hooks/<name>/`；hook 最多只追加过 marker 类文件，删除该文件即清理完毕。

## 边界

- <不做什么：例如不阻断、不改文件、不做审批>
```

---

## 4. agent 模板

### 4.1 frontmatter

```yaml
---
name: <kebab-case-name>
description: <角色做什么 + 主 agent 何时该委派 + 用户会说的话；≤1024 字符>
tools: <可选：逗号分隔，如 Read, Grep, Glob；省略 = 继承全部工具>
---
```

**不写 `model`**：该字段可选，`inherit` 在本环境不可解析，`engineering-agent` 2.1.2 已因此回退为缺省。需要指定模型时在平台侧配置，不写进组件。

### 4.2 正文骨架

```markdown
你是<角色>。用中文回复。

## 定位

<一段话说清：负责什么、在什么环节被调用、与主 agent 的分工。>

## 职责

- <职责 1>，产出 <物>
- <职责 2>，产出 <物>

## 边界

- 不<越界动作>（说明为什么）
- 不做 <另一角色的事>，那种情况交回主 agent / 别的 agent

## 何时不用

<主 agent 不该委派的情形，2 条以上>

## 输出

<固定报告结构：标题 + 必填小节；或一句话产物契约。>
```

### 4.3 与 skill 的分工

| 用 agent | 用 skill |
|---|---|
| 需要独立上下文、独立系统提示的角色 | 主 agent 直接加载的流程 |
| 长时间、可并行、可隔离的执行体 | 一次性的步骤指引 |
| 需要工具白名单隔离 | 需要与现有审查/文档流程共用规则 |

---

## 5. registry 条目

Gate D 通过后才写入 `registry.json`（Gate B 阶段只准备草稿）：

```json
{
  "name": "<组件名>",
  "type": "<skill|hook|agent>",
  "owner": "AI 平台团队",
  "interface": "<输入什么，产出什么，校验命令是什么>",
  "dependencies": ["external:python3", "external:claude-code"],
  "version": "1.0.0",
  "status": "active",
  "path": "<skills/... | hooks/... | agents/....md>",
  "install_target": "user-global"
}
```

- 八字段齐全；`version` 严格 `x.y.z`；`path` 必须真实存在。
- 依赖只能是库内组件名或 `external:*`，且不能成环。
- 新增的 `skills/*/SKILL.md` 必须登记，否则 `gate.py component-registry` 失败。

---

## 6. 校验清单

```bash
# 组件结构 + 内容
python -X utf8 skills/create-skill/scripts/validate_component.py --type skill <path>
python -X utf8 skills/create-skill/scripts/validate_component.py --type hook  <path>
python -X utf8 skills/create-skill/scripts/validate_component.py --type agent <path>

# 校验器自身（防止永远返回 OK 的假绿）
python -X utf8 skills/create-skill/scripts/validate_component.py --self-test

# registry（Gate D）
python -X utf8 gates/gate.py component-registry --repo .
```

| 检查组 | 内容 |
|---|---|
| 结构 | 路径前缀、入口文件、目录名 == name |
| frontmatter | 字段白名单、kebab-case、长度、尖括号、禁 `model` |
| 正文 | 七节（skill）/ 四节（agent）、非空、无占位残留 |
| 代码 | `.py` 可编译；hook 有 `win/*.cmd`、`tests/*.json`、合法 `settings.example.json` |
| 安全 | 密钥模式、个人路径、`settings.json` 直写 |
| 规模 | 文件数 >50、单文件 >200 KB 给出警告 |

---

## 7. 来源标注

派生自官方或其他上游的内容，在文件头加：

```html
<!-- 派生自 <来源与许可>
     upstream: <仓库内路径或 URL>
     sha256: <上游文件 hash>
     修改摘要: <一句话> -->
```

不要大段复制上游正文；只复用结构与规则，并保留许可声明。上游更新时先比对 hash，再决定是否同步。

---

## 8. 反例（见到就退回重做）

| 反例 | 为什么不行 |
|---|---|
| `description: 一个有用的技能` | 没有触发条件，永远不会被自动调用 |
| 正文只有"按需处理"四个字 | 模型无法据此行动，等价于没有技能 |
| hook 里 `exit 1` 阻断会话 | 旁路通知不该有否决权；门禁要放 `gates/` |
| hook 直接改 `settings.json` | 覆盖用户配置，且安装不可回滚 |
| agent 写 `model: inherit` | 本环境不可解析，已发生过的回退 |
| 组件里写死本机用户主目录的绝对路径 | 换机器即坏；路径由安装器决定 |
| 三个技能各自复制一份本模板 | 模板漂移，改一处漏两处 |
