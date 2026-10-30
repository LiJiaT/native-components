---
name: create-agent
description: 把一次委派角色做成 Claude Code 子代理：澄清职责与边界 → 按共用模板生成 agents 目录下的单文件定义（不写 model）→ 跑静态校验 → 在 Claude Code 沙箱真实派发一次确认 subagent_type 生效。当用户说“创建一个 agent”“做个子智能体”“写个代码审查/规划子代理”“让主 agent 把某类活派给专门的代理”时使用。不做跨平台格式转换（归 universal-agent-creator），也不创建 skill 或 hook。
---

# Create Agent（子代理工厂）

把一个需要**独立上下文 + 独立系统提示**的角色固定下来，让主 agent 知道什么时候该把活派给它。agent 与 skill 的分工：agent 是"可以委派的人"，skill 是"主 agent 自己照做的流程"。

**模板单一来源**：`../create-skill/references/component-template.md` §4（不复制模板；安装时三个 create 技能一起装）。
**验收协议**：`../create-skill/references/claude-code-test.md` C3。

## 何时使用

- **使用**：需要独立角色（代码审查员、规划员、只读调研员）、需要工具白名单隔离、需要长任务并行且不污染主上下文；用户明确说"做成子代理/agent"。
- **不要使用**：
  - 只是主 agent 要按步骤执行的流程 → 用 `create-skill`。
  - 只是要在某个事件上自动跑一段逻辑 → 用 `create-hook`。
  - 需要同时产出 Codex TOML / TRAE `.agent.md` 等跨平台格式 → 那是 `universal-agent-creator` 的职责。
  - 一次性提示词 → 不建组件。

## 输入

| 输入 | 必需 | 缺失时怎么办 |
|---|---|---|
| 角色名（kebab-case） | 是 | 用职责命名（`code-reviewer`、`plan-writer`），不用人名 |
| 职责：做什么、产出什么 | 是 | 追问；只写"帮忙看看"不进入生成 |
| 边界：明确不做什么 | 是 | 至少一条，且要说明为什么不该做 |
| 何时不使用（主 agent 不该委派的情形） | 是 | 至少两条，缺了会抢主 agent 的活 |
| 工具限制 | 否 | 默认省略 `tools`（继承全部）；需要只读就写 `Read, Grep, Glob` |
| 输出契约 | 否 | 默认"标题 + 结论 + 依据"三段 |

## 流程

1. **定角色**：一句话写出"它是谁、被谁在什么时机调用、产出什么"。写不出就不是 agent。
2. **写 frontmatter**：只写 `name`、`description`（可选 `tools`）。**不写 `model`**——该字段在本环境不可解析，工程内已因此回退过一次。
3. **写正文**：照模板 §4.2 骨架，至少包含定位、职责、边界、何时不用、输出。
4. **自查抢活风险**：`description` 太宽会把主 agent 该自己做的事也抢走；在"何时不用"里写清排除项。
5. **静态校验**：
   ```bash
   python -X utf8 skills/create-skill/scripts/validate_component.py --type agent agents/<name>.md
   ```
6. **真实派发（不可省）**：按验收协议 C3 在沙箱 `claude -p` 派发，`stream.jsonl` 里出现该 `subagent_type` 且返回符合契约才算通过。
7. **交付**：报校验退出码、派发证据路径、"未做跨平台格式转换"的说明。

## 输出

| 产物 | 路径 | 说明 |
|---|---|---|
| 代理定义 | `agents/<name>.md` | 单文件，frontmatter 只含 name/description（可选 tools） |
| 校验结果 | 命令输出 | exit 0，WARN 可解释 |
| 派发证据 | 沙箱 `evidence/c3-agent/` | `stream.jsonl` + 返回内容 + `sha256` |

**不产出**：Codex TOML / TRAE `.agent.md`、`model` 字段、registry 条目、git 提交。

## 边界

- 不写 `model` 字段（含 `inherit`）；需要指定模型时由平台侧配置。
- 不做跨平台转换与自动安装；跨环境分发归 `universal-agent-creator` 与 `universal-env-sync`。
- 不创建 skill / hook，也不调用另外两个 create 技能代劳。
- 不把项目私有提示词、密钥、个人路径写进正文；agent 是会被分发出去的文件。
- 不让 agent 绕过审批或沙箱；需要拦截的能力不放进 agent。

## 验收

```bash
# 1) frontmatter、必备节、禁 model
python -X utf8 skills/create-skill/scripts/validate_component.py --type agent agents/<name>.md   # 期望 exit 0

# 2) 沙箱派发证据
ls <sandbox>/evidence/c3-agent/stream.jsonl
```

逐项判据：
- 校验命令 exit 0，且输出无 FAIL；
- `stream.jsonl` 出现该 `subagent_type` 的派发记录，返回内容符合"输出"契约；
- 证据目录带 `sha256`，与本次运行时间一致。

## 示例

**输入**：用户说"我想让一个子代理专门做只读代码审查，不许改文件，只给问题清单"。

**输出**：
- `agents/probe-code-reviewer.md`：`description` 写清"主 agent 在需要只读审查时委派"；`tools: Read, Grep, Glob`；
- 正文含"边界：不写文件、不执行命令、不改配置"与"输出：问题清单（文件:行 + 问题 + 建议）"；
- 校验 exit 0；
- 沙箱 C3：`claude -p "把这次只读审查委派给 probe-code-reviewer"` → stream 出现该 `subagent_type`，返回问题清单。
