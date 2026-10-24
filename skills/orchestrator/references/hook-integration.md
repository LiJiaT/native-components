# Hook 集成：哪些环节可以实现为 Hook

## 核心结论

编排智能体的**主体是 orchestrator agent**（需要交互式决策、多轮对话、用户确认），但有 **5 个环节可以借助 hook** 增强自动化。⚠️ 其中 3 项已实现，PreToolUse / PostToolBatch 为 v2 待办，SessionEnd 的 orchestrator 任务标签尚未接入（见下）——本文档标注的 ✅ 与实现需逐一核对，避免文档超前于实现。

---

## 可 Hook 化的环节

### ✅ Hook 1：SessionStart — 上下文预热

**Hook 事件**：`SessionStart`

**做什么**：
- 检查当前项目目录，加载项目级上下文（CLAUDE.md、.claude/ 目录）
- 加载相关场景上下文（scenario 触发词匹配）
- 检查 staging 区待处理事项（蒸馏候选、待确认规则）
- 注入 orchestrator 的轻量提示（"你是编排智能体，负责..."）

**为什么适合 Hook**：
- 固定动作，不需要决策
- 在用户输入前完成，零感知成本
- 已有先例（scenario-inject、distill-notify）

**实现复杂度**：低
**优先级**：高

---

### ✅ Hook 2：UserPromptSubmit — 复杂度预分类

**Hook 事件**：`UserPromptSubmit`

**做什么**：
- 快速分析用户输入的复杂度（关键词匹配 + 启发式规则）
- 判定为复杂任务时，注入 orchestrator 的工作流提示
- 判定为简单任务时，不注入（不干扰正常使用）
- 可附加：自动附加相关场景的状态快照

**分类启发式规则**：
```python
def is_complex(prompt):
    # 复杂信号
    complex_signals = [
        len(prompt) > 300,          # 长输入
        any(k in prompt for k in [  # 多步骤关键词
            '计划', '规划', '分解', '分步骤', '分阶段',
            '项目', '系统', '架构', '设计', '调研',
            'orchestrator', 'workflow', 'pipeline'
        ]),
        prompt.count('\n') > 3,     # 多行结构化输入
        '帮我做一个' in prompt and not '简单' in prompt,
    ]
    return sum(complex_signals) >= 2  # 命中 2+ 个信号
```

**为什么适合 Hook**：
- 前置判断，不需要用户主动触发 orchestrator
- 启发式规则即可，不需要 LLM 参与
- 误判代价低（复杂任务漏判=用户手动触发，简单任务误判=多一点系统提示）

**实现复杂度**：低-中
**优先级**：高

---

### ⚠️ Hook 3：PreToolUse — 上下文审计（v2 待实现）

**Hook 事件**：`PreToolUse`

**做什么**：
- 检测当前上下文长度是否超过阈值（如 80K tokens）
- 超过阈值时注入提醒："上下文较长，考虑使用 sub-agent 或 compact"
- 检测是否在做"边读边改"的碎片化操作，建议先收集完整信息再动手
- 防止违反 5.1 上下文工程原则

**为什么适合 Hook**：
- 自动监控，持续生效
- 不需要用户主动想起
- 轻量操作（读 token 计数 + 简单判断）

**实现复杂度**：中
**优先级**：中

**注意**：这个 hook 需要能访问 token 计数，可能需要依赖 harness 的能力。如果不可行，退化为 PostToolBatch 周期性检查。

---

### ⚠️ Hook 4：PostToolBatch — 进度自检（v2 待实现）

**Hook 事件**：`PostToolBatch`

**做什么**：
- 周期性检查任务进度（每 N 个工具调用后）
- 检测是否偏离计划（如工具调用模式异常、反复重试同一操作）
- 检测是否陷入"局部最优"（在次要问题上花太多时间）
- 注入自我批判提醒："当前进度如何？是否需要调整策略？"

**为什么适合 Hook**：
- 防止 Agent 在错误方向上走太远
- 周期性纠偏，降低长任务的累积偏差
- 对应 5.5 交付前自我批判的"过程中自我批判"扩展

**实现复杂度**：中-高
**优先级**：低（v2 再做）

---

### ✅ Hook 5：SessionEnd — 自动蒸馏入队

**Hook 事件**：`SessionEnd`

**做什么**：
- 检查当前 session 是否满足蒸馏入选条件（工具调用数、编辑数、纠错信号数）
- 满足条件则加入蒸馏队列（调用 session-distiller 的入队逻辑）
- 对应 orchestrator 闭环的 Step 5 写回的自动化部分

**为什么适合 Hook**：
- 已有现成实现（distill-enqueue）
- SessionEnd 触发，零感知成本
- 对应 7.3 反馈与自进化机制

**实现复杂度**：低（复用现有 distill-enqueue）
**优先级**：高（已有基础设施，几乎零成本）
**当前状态**：✅ 已完成——复用现有 `distill-enqueue`：本环境中 orchestrator 无需额外改动即接入蒸馏入队；但「orchestrator 任务 vs 普通任务」的**任务标签记录尚未实现**，属 v2 增量，暂不开发。

---

## 不适合 Hook 化的环节

### ❌ 澄清阶段

**原因**：
- 需要交互式多轮对话
- 需要理解用户意图并生成追问
- 需要用户确认才能进入下一步

**正确形态**：skill 内的工作流（grill-me-with-doc）

---

### ❌ 规划阶段

**原因**：
- 需要深度理解需求并设计方案
- 需要用户确认计划
- 每个任务的规划都不同，无法标准化为固定动作

**正确形态**：skill 内的 LLM 推理步骤

---

### ❌ 任务分发

**原因**：
- 需要动态决策执行方选择
- 需要生成任务包
- 需要管理依赖关系和执行顺序

**正确形态**：skill 内的编排逻辑 + sub-agent 调用

---

### ⚠️ 验收阶段（确定性证据 + 独立判断）

**原因**：
- 验收清单的逐项证据可由工具聚合（`gates/gate.py acceptance`：ID 对账、verdict 重算、reviewer/executor 独立性）
- 语义是否正确、结论是否成立仍需独立 reviewer 判断

**正确形态**：先用确定性工具聚合证据并拒绝缺项/非独立复核，再由 LLM/人做语义判断；不能只用 LLM 口头结论替代证据文件。

---

## Hook 架构总览

```
                    ┌─────────────────────────────┐
                    │      Orchestrator agent      │
                    │  (主体：澄清/规划/分发/验收)  │
                    └──────────────┬──────────────┘
                                   │
       ┌───────────┬───────────────┼───────────────┬───────────┐
       ▼           ▼               ▼               ▼           ▼
  SessionStart  UserPromptSubmit  PreToolUse   PostToolBatch  SessionEnd
  (上下文预热)   (复杂度预分类)    (上下文审计)   (进度自检)    (自动蒸馏)
      ✅ v1         ✅ v1           ⚠️ v2         ⚠️ v2      ✅ v1(标签部分v2)
```

## 实施建议

### v1（当前版本，已落地）
1. ✅ **SessionStart 上下文预热** — 复用 scenario-inject 模式，注入 orchestrator 标识
2. ✅ **UserPromptSubmit 复杂度预分类** — 启发式规则，复杂任务注入提示
3. ✅ **SessionEnd 自动蒸馏** — 复用现有 distill-enqueue（orchestrator 任务**标签**未接入，v2 增量）

### v2（后续迭代，未开发）
4. ⚠️ **PreToolUse 上下文审计** — 监控上下文长度，提醒 compact / 用 sub-agent
5. ⚠️ **PostToolBatch 进度自检** — 周期性纠偏，防止偏离计划
6. ⚠️ **orchestrator 任务标签** — SessionEnd 区分 orchestrator 任务与普通任务

### 配置方式

在 `~/.claude/settings.json` 的 `hooks` 中添加：

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume",
        "hooks": [
          {
            "type": "command",
            "command": "C:\\Users\\<user>\\.claude\\hooks\\orchestrator\\win\\orchestrator-warmup.cmd",
            "timeout": 10
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "C:\\Users\\<user>\\.claude\\hooks\\orchestrator\\win\\orchestrator-classify.cmd",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

**注意**：失败语义必须区分。旁路通知/上下文注入 hook 可静默失败（fail-open），不得拖垮会话；强制门禁 hook（外发拦截、审批/证据/范围校验）必须 fail-closed：异常、超时、schema 缺失都拒绝并写 audit。不得把门禁 hook 写成异常 exit 0 放行。
