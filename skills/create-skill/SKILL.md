---
name: create-skill
description: 把一次澄清好的流程做成可复用的 Agent Skill：澄清触发条件与边界 → 按共用模板生成 skills 目录下的技能骨架 → 跑静态校验 → 在 Claude Code 沙箱真实触发一次。当用户说“把这个流程做成技能”“创建 skill”“新建一个技能”“把刚才的步骤固化成技能”“帮我把这套做法沉淀成技能”时使用。不用于创建 hook 或 agent（分别走 create-hook / create-agent），也不用于一次性任务。不用于跨 IDE 安装与多环境同步（走 universal-skill-creator），也不用于技能评测、benchmark 与 .skill 打包（走官方 skill-creator）。
---

# Create Skill（技能工厂）

把"这件事我们做过一遍了"变成"下次会自动照做"的技能包。产出的东西必须能被 `native-components` 的安装器安装、被 registry 门禁校验、并在 Claude Code 里真的被调用起来。

**模板单一来源**：`references/component-template.md`（与 `create-hook`、`create-agent` 共用同一份，改模板改那里）。

## 何时使用

- **使用**：用户要把一套重复性流程固化成技能；用户说"做成 skill / 建个技能 / 把这个流程沉淀下来"；刚在会话里跑通一段多步流程，用户想复用。
- **不要使用**：
  - 要创建的是 hook 或 agent → 分别交 `create-hook` / `create-agent`（三者互不调用，避免套娃）。
  - 任务只做一次、不会有第二次 → 直接做完交付，明确告诉用户"一次性任务不值得做成技能"。
  - 要做的是跨 IDE 安装或跨环境同步 → 那是 `universal-skill-creator` / `universal-env-sync` 的职责，本技能只产出仓库组件。
  - 要做技能评测、benchmark、description 调优或 `.skill` 打包 → 那是官方 `skill-creator` 的职责。

## 输入

| 输入 | 必需 | 缺失时怎么办 |
|---|---|---|
| 技能名（kebab-case） | 是 | 从流程核心动作提炼（如 `probe-file-naming`），向用户确认一次 |
| 触发条件：用户会怎么说 | 是 | 追问 2–3 句真实说法，写不出就不进入生成 |
| 输入 / 输出契约 | 是 | 从本次会话已跑通的步骤里提取；提取不到就追问 |
| 边界：明确不做什么 | 是 | 至少一条，来自任务书或仓库规则，不许自编 |
| 落位目录 | 否 | 默认 `skills/<name>/`；沙箱验证时落沙箱目录 |

## 流程

1. **澄清**：按上表补齐五项；`description` 先写出来——写不出"何时触发"，说明设计没成形，不要往下走。
2. **读模板**：打开 `references/component-template.md` §1、§2，照骨架落文件，不适用的节删掉而不是留占位。
3. **落盘**：`skills/<name>/SKILL.md` 必建；只有长文档才加 `references/`，只有确定性操作才加 `scripts/`，只有输出需要模板文件才加 `assets/`。
4. **写校验**：技能若带脚本，脚本自身要能跑（`py_compile` 通过），并在"验收"节写明命令与期望退出码。
5. **静态校验**：
   ```bash
   python -X utf8 skills/create-skill/scripts/validate_component.py --type skill skills/<name>
   ```
   必须 exit 0；WARN 逐条判断能否解释，解释不了就改。
6. **真实触发（不可省）**：在沙箱工程里按 `references/claude-code-test.md` 跑一次 `claude -p`，确认技能被调用、产物符合契约。只看到文件存在不算通过。
7. **交付**：报三个结果——校验命令与退出码、触发证据路径、已知限制。

## 输出

| 产物 | 路径 | 说明 |
|---|---|---|
| 技能入口 | `skills/<name>/SKILL.md` | 七节齐全，frontmatter 只有 name/description（可选 license、metadata） |
| 技能资源 | `skills/<name>/references|scripts|assets/` | 按需，空目录不建 |
| 校验结果 | 命令输出 | exit 0，附 WARN 说明 |
| 触发证据 | 沙箱 `evidence/<case>/` | `stream.jsonl` + 产物 + `sha256` |

**不产出**：registry 条目（Gate D 统一改）、安装副本（`install.py` 执行）、git 提交（由人执行）。

## 边界

- 不直接写入用户环境（`~/.claude`、`~/.qoder` 等），只在仓库或沙箱里生成文件。
- 不创建 hook / agent，不调用另外两个 create 技能代劳。
- 不修改 Anthropic 官方 `skill-creator` 的任何文件；派生内容按模板 §7 标注来源。
- 不把 `.skill` zip 打包或跨 IDE 安装写进本技能——分发归 `install.py` 与 `universal-env-sync`。
- 不在技能里写密钥、个人路径、内部主机；校验器会拦。

## 验收

```bash
# 1) 结构与内容
python -X utf8 skills/create-skill/scripts/validate_component.py --type skill skills/<name>    # 期望 exit 0

# 2) 校验器自身没被改坏
python -X utf8 skills/create-skill/scripts/validate_component.py --self-test                   # 期望 exit 0

# 3) 真实触发证据存在且非空
ls <sandbox>/evidence/<case>/stream.jsonl
```

逐项判据：
- 校验命令退出码 0，且输出里没有 FAIL 行；
- 沙箱触发证据里有该技能的调用记录（`tool_use` 或技能名），产物文件内容符合"输出"节的契约；
- 证据文件带 sha256，能证明是本次运行产生的。

## 示例

**输入**：用户说"每次交付前我都要检查文件名有没有下划线，这套检查帮我做成技能"。

**输出**：
- `skills/probe-file-naming/SKILL.md`：七节齐全，`description` 含"检查文件名/下划线/交付前"三个触发语；
- `skills/probe-file-naming/scripts/check_names.py`：扫目录并输出违规清单，`py_compile` 通过；
- 校验：`validate_component.py --type skill skills/probe-file-naming` → exit 0；
- 触发：沙箱里 `claude -p "用 probe-file-naming 检查 sandbox/src 的命名"` → stream 里有技能调用，`reports/.../naming.md` 生成。
