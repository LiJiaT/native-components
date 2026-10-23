# 自进化流程阶段

## 总览

```text
SessionEnd
  → ① 采集：预过滤 + 入队（确定性）
  → ② 蒸馏：后台 worker，L0 → L1 → L2 → L3（模型 + 脚本）
  → ③ 分诊：五车道 + staging 去重（模型判断 + 索引）
  → ④ 人工确认：候选表 → 批准/拒绝（人）
  → ⑤ 晋升：写正式资产 + provenance + git commit（人批准后执行）
  → ⑥ 召回与卫生：常驻加载 + 定期去重/过期（三期）
```

## 阶段明细

| 阶段 | 输入 | 执行者 | 输出 | 完成判定 |
|---|---|---|---|---|
| ① 采集 | `SessionEnd` 事件 JSON、transcript | `distill-enqueue.sh` | `queue/jobs.jsonl` 一行 | 解析成功、`tool_use` ≥10、入队成功 |
| ② 蒸馏 | 队列任务、transcript | `worker.sh` + `session-distiller` 脚本 | staging 候选 | worker 完成且候选落盘、INDEX 更新 |
| ③ 分诊 | 候选、现有资产、staging INDEX | 蒸馏技能 + 模型 | 候选表（新增/合并/supersedes/丢弃） | 每条候选有车道、去处、理由、recurrence |
| ④ 人工确认 | 候选表 | 人 | 批准/拒绝记录 | 明确批准；hooks 车道永远需确认 |
| ⑤ 晋升 | 已批准候选 | 人 + 写入脚本/技能 | 正式资产文件 + provenance | 文件写入、INDEX 状态更新、commit（若启用 git） |
| ⑥ 召回/卫生 | 资产库、使用记录 | curator（三期） | 去重/过期/修补结果 | 语义去重、30/45 天规则执行并留痕 |

## 五车道分诊

| 候选性质 | 个人期去处 | 组织期映射 |
|---|---|---|
| 多步流程，跨项目通用 | `~/.claude/skills/<name>/` | plugin marketplace skill |
| 多步流程，项目专属 | 项目 `.claude/skills/` | 项目仓库 `.claude/`（走 PR） |
| 只对特定文件/路径生效 | `.claude/rules/<topic>.md` + `paths:` | 打包进 marketplace skill |
| 每会话都要的指令 | `CLAUDE.md`（≤200 行） | managed CLAUDE.md / managed-settings |
| 必须确定性执行/禁止 | hook / permissions 提案 | managed settings / hooks |
| 环境/账号/工具事实 | 项目 memory（ADD-only） | 不下发，留个人 |
| 一次性细节 | 丢弃并注明原因 | — |

## 交接契约

- 采集到蒸馏：`{session_id, transcript_path, enqueued_at}`。
- 蒸馏到分诊：候选文件（frontmatter 含 `id/created/source_sessions/lane/status/supersedes/recurrence`）。
- 分诊到人工：候选表（`# / 候选 / 车道 / 去处 / 理由 / recurrence`）。
- 人工到晋升：批准记录（谁、何时、批准哪些候选）。
- 晋升到资产库：正式文件 + provenance 注释 + INDEX 状态。

## 失败与回滚

- worker 失败：任务保留在队列，日志写 `queue/worker.log`；修复后重跑。
- JSON 解析失败：候选不入库，保留任务，避免把半成品写进 staging。
- 误晋升：从资产库删除对应文件/条目，保留 git 历史作为回滚记录；同步更新 INDEX 与游标。
- hook 异常：旁路能力失败不阻塞会话；不影响已有资产。
