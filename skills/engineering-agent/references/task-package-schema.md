# 任务包 Schema 定义

任务包（Task Package）是工程智能体分发给执行方的标准化契约。执行方只需依据任务包工作，不需要了解全局上下文。

## 完整 Schema

```json
{
  "task_id": "T001",
  "name": "子任务名称",
  "description": "一句话描述子任务的目标",
  "phase": "clarification|planning|execution|verification|writeback",

  "input": {
    "files": [
      "文件路径或 URL（字符串数组；如需标注角色/格式，写在 description 里）"
    ],
    "data": {
      "key": "直接提供的结构化数据"
    },
    "context_summary": "必要的背景说明（最小化，100 字以内）",
    "engineering_agent_plan_ref": "全局计划摘要路径（仅作溯源，不作为执行依据）"
  },

  "dependencies": [
    "T000",
    "external:lark-cli"
  ],

  "output_contract": {
    "primary": {
      "type": "file|text|data|code",
      "format": "markdown|json|python|...",
      "location": "输出位置（文件路径或变量名）",
      "schema": "输出结构定义（JSON Schema / 类型签名 / 模板）"
    },
    "secondary": [
      {
        "type": "artifact|log|metadata",
        "description": "辅助产物说明"
      }
    ],
    "must_not_include": [
      "不应出现在输出中的内容（如全局上下文、其他任务信息）"
    ],
    "required_artifacts": [
      "out/report.md"
    ]
  },

  "acceptance_criteria": [
    {
      "id": "AC-01",
      "description": "验收项描述",
      "expected": "可观察的期望结果（结果侧逐字比对）",
      "evidence_path": "证据落点：文件/日志（不得是目录）",
      "check_method": "auto|manual",
      "check_script": "自动检查脚本路径（check_method=auto 时必填）",
      "independent_review": true,
      "severity": "blocker|major|minor"
    }
  ],

  "failure_handling": {
    "max_retries": 2,
    "retry_strategy": "same_executor|new_executor|escalate|none",
    "fallback_task": "失败后执行的降级任务 ID（可选）",
    "escalation_trigger": "连续失败 N 次或出现特定错误类型时升级",
    "escalation_target": "engineering-agent|human"
  },

  "execution": {
    "type": "sub-agent|script|skill|hook|self",
    "target": "执行方标识（agent 名 / 脚本路径 / skill 名 / hook 事件）",
    "model": "模型选择（sub-agent 类型时）",
    "verifier": "type=self 时必填：另一 sub-agent / 脚本路径 / 人",
    "effort_level": "low|medium|high|xhigh",
    "timeout_seconds": 300,
    "tools_allowed": ["允许的工具列表，空表示不限制"],
    "tools_forbidden": ["禁止的工具列表"]
  },

  "metadata": {
    "created_at": "ISO 8601 时间戳",
    "created_by": "engineering-agent",
    "priority": "high|medium|low",
    "estimated_complexity": "low|medium|high",
    "task_class": "deterministic|judgment",
    "status": "todo|running|done|failed|blocked",
    "tags": ["标签1", "标签2"]
  }
}
```

## 字段说明

### phase（任务阶段）

| 值 | 含义 | 典型任务 |
|----|------|---------|
| `clarification` | 澄清阶段 | 信息收集、背景调研、需求确认 |
| `planning` | 规划阶段 | 方案设计、架构选型、计划制定 |
| `execution` | 执行阶段 | 代码生成、文档写作、数据处理 |
| `verification` | 验证阶段 | 测试、审查、验收检查 |
| `writeback` | 写回阶段 | 资产沉淀、规则更新、记忆写入 |

### dependencies 写法

`dependencies` 是**任务 ID 字符串数组**，只表达顺序：

| 写法 | 含义 | 校验 |
|---|---|---|
| `"T000"` | 内部依赖：必须存在且状态为 `done` 才可派发（校验时需 `--tasks-dir`） | 自依赖、重复、断链、环都会报错 |
| `"external:lark-cli"` | 外部依赖：不查任务目录 | 前缀 `external:` |

对象形式（`{task_id, type: hard\|soft, output_mapping}`）**当前不支持**，见文末「未实现」。

### execution.type 选择优先级

遵循**确定性优先原则**，选择优先级从高到低：

1. **script** — 有现成脚本可以完成的，用脚本
2. **skill** — 有成熟 skill 覆盖的，用 skill
3. **sub-agent** — 需要理解推理的，派 sub-agent
4. **hook** — 事件触发型的，注册为 hook

**`self` 是异常路径，仅在内部推理、不交付时使用；必须指定独立 `verifier`**（§6.6 验证必须独立于执行）。`type=self` 而无 `verifier` 的任务包无法通过 `validate --strict`。

### acceptance_criteria.check_method

| 值 | 含义 | 适用场景 |
|----|------|---------|
| `auto` | 完全自动化检查（必须提供 `check_script`） | 文件存在性、格式校验、语法检查、数值比对 |
| `manual` | 纯人工检查 | 设计质量、内容准确性、风格一致性 |

需要“先跑脚本再人工确认”的，拆成两条 AC：一条 `auto` + 一条 `manual`（`semiauto` 当前不支持，见文末「未实现」）。

## 最小任务包（能通过 --strict）

下面这份是**真能过 `validate --strict`** 的最小集合；少一个 `expected` / `evidence_path` / `independent_review` / `metadata.task_class` 都会被拒。

```json
{
  "task_id": "T001",
  "name": "读取并分析文件 X",
  "description": "读取指定文件并提取关键信息",
  "phase": "execution",
  "input": {
    "files": ["/path/to/file.md"],
    "data": {},
    "context_summary": "为什么要读这个文件，以及不能违反的约束"
  },
  "dependencies": [],
  "output_contract": {
    "primary": {
      "type": "text",
      "format": "markdown",
      "location": "直接在回复中输出"
    },
    "must_not_include": []
  },
  "acceptance_criteria": [
    {
      "id": "AC-01",
      "description": "提取了所有关键信息点",
      "expected": "每个章节的关键结论都有一行摘要",
      "evidence_path": "out/ac-01.md",
      "check_method": "manual",
      "independent_review": true,
      "severity": "major"
    }
  ],
  "failure_handling": {
    "max_retries": 2,
    "retry_strategy": "same_executor",
    "escalation_target": "engineering-agent"
  },
  "execution": {
    "type": "sub-agent",
    "target": "engineering-agent",
    "model": "DeepSeek-V4-Flash-Official",
    "timeout_seconds": 120
  },
  "metadata": {
    "created_at": "2026-10-30T00:00:00Z",
    "created_by": "engineering-agent",
    "priority": "medium",
    "estimated_complexity": "low",
    "task_class": "judgment",
    "status": "todo",
    "tags": []
  }
}
```

注意：`required_artifacts` **要么不写，要么写非空字符串列表**；写 `[]` 会被拒。

## 未实现（不要照抄）

下列写法曾在历史文档里出现，**当前 `validate` 不支持**，照抄会被拒；本轮不实现，留待后续批次（见 `reports/06-dispatch/recommendation.md`）。

| 写法 | 当前行为 | 该怎么写 |
|---|---|---|
| `input.files` 为对象数组 `{path, role, format}` | 报 `input.files 必须是字符串列表` | 直接写路径字符串数组；角色/格式写进 `description` |
| `dependencies` 为对象数组 `{task_id, type, output_mapping}` | 报 `dependencies 必须是字符串列表，且每项非空（当前不支持对象形式…）` | 写任务 ID 字符串数组；外部依赖用 `external:` 前缀 |
| `check_method: semiauto` | 报 `check_method 非法` | 拆成两条 AC：一条 `auto` + 一条 `manual` |
| `retry_strategy: different_executor` | 报 `retry_strategy 非法` | 用 `new_executor` |

## 任务包创建原则

1. **单一职责**：每个任务包只做一件事，可以独立验收
2. **最小上下文**：只给执行所需的最少信息，避免上下文污染
3. **可验证**：每条验收标准都能被判断通过/不通过
4. **可失败**：明确失败处理策略，不要假设一定成功
5. **可溯源**：保留 engineering_agent_plan_ref 以便回溯，但不作为执行依据
