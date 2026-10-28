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
      {
        "path": "文件路径或 URL",
        "role": "spec|reference|data|template",
        "format": "markdown|json|python|xlsx|..."
      }
    ],
    "data": {
      "key": "直接提供的结构化数据"
    },
    "context_summary": "必要的背景说明（最小化，100 字以内）",
    "engineering_agent_plan_ref": "全局计划摘要路径（仅作溯源，不作为执行依据）"
  },

  "dependencies": [
    {
      "task_id": "T000",
      "type": "hard|soft",
      "output_mapping": {
        "源输出字段": "本任务输入字段"
      }
    }
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
    ]
  },

  "acceptance_criteria": [
    {
      "id": "AC-01",
      "description": "验收项描述",
      "check_method": "auto|manual|semiauto",
      "check_script": "自动检查脚本路径（如适用）",
      "severity": "blocker|major|minor"
    }
  ],

  "failure_handling": {
    "max_retries": 2,
    "retry_strategy": "same_executor|different_executor|escalate",
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

### dependencies.type

| 值 | 含义 |
|----|------|
| `hard` | 硬依赖：必须等前置任务完成且通过验收才能开始 |
| `soft` | 软依赖：可以并行启动，但最终交付前必须满足依赖 |

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
| `auto` | 完全自动化检查 | 文件存在性、格式校验、语法检查、数值比对 |
| `semiauto` | 半自动化 + 人工确认 | 脚本检查 + 人工抽样确认 |
| `manual` | 纯人工检查 | 设计质量、内容准确性、风格一致性 |

## 最小任务包

对于简单子任务，可以只填必要字段：

```json
{
  "task_id": "T001",
  "name": "读取并分析文件 X",
  "description": "读取指定文件并提取关键信息",
  "input": {
    "files": [{"path": "/path/to/file.md", "role": "data"}]
  },
  "output_contract": {
    "primary": {
      "type": "text",
      "format": "markdown",
      "location": "直接在回复中输出"
    }
  },
  "acceptance_criteria": [
    {"id": "AC-01", "description": "提取了所有关键信息点", "check_method": "manual", "severity": "major"}
  ],
  "execution": {
    "type": "sub-agent",
    "model": "DeepSeek-V4-Flash-Official",
    "timeout_seconds": 120
  }
}
```

## 任务包创建原则

1. **单一职责**：每个任务包只做一件事，可以独立验收
2. **最小上下文**：只给执行所需的最少信息，避免上下文污染
3. **可验证**：每条验收标准都能被判断通过/不通过
4. **可失败**：明确失败处理策略，不要假设一定成功
5. **可溯源**：保留 engineering_agent_plan_ref 以便回溯，但不作为执行依据
