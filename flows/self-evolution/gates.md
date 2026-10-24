# 自进化流程卡点

本流程同时使用确定性检查和人工审批。确定性检查只判定可程序验证的条件；是否值得沉淀、分类是否正确、内容是否准确由人判断。

## 确定性检查

| 卡点 | 位置 | 检查内容 | 失败处理 |
|---|---|---|---|
| 入队预过滤 | `hooks/self-evolve/enqueue.py` | JSON 逐行解析、路径原样保留、`tools≥40 OR edits≥3 OR corrections≥2`、排除 meta-session | 不入队，写 `queue/enqueue.log` |
| 队列锁 | `worker.py` | 目录锁含 PID/host/时间；PID 不存在或超时（默认 2h）可恢复陈旧锁 | 活锁时退出；陈旧锁留日志后恢复 |
| 队列一致性 | `worker.py` | producer/consumer 共用 `.queue.lock`；append-only + 锁内压缩；处理期间新任务不丢 | 保留任务并记录失败 |
| 每日预算 | `worker.py` | `MAX_JOBS_PER_DAY`（默认 3）；超限任务标 held 并写 `queue/HOLD` | 任务保留；SessionStart 或调度器唤醒 |
| 模型失败 | `worker.py` | 必须 `returncode=0` 且输出合法 JSON 数组；超时/非零/空输出保留任务 | 记录 stderr；连续 3 次进 `dead-letter.jsonl` |
| dry-run | `worker.py` | 不调模型、不改队列、不写 staging、不消耗预算 | — |
| 游标/幂等 | `worker.py` | `distill-state/<sid>.json` 绑定 size/mtime/sha256；未变化不重复蒸馏 | 已完成后跳过 |
| 候选格式 | 候选落盘前 | lane 枚举、title/content/reason 非空、content 长度、frontmatter 序列化 | 不写候选；无有效候选时任务失败保留 |
| 脱敏 | 候选落盘前 | key/token/密码/私钥模式命中即拒绝该候选 | 不写候选并记日志 |
| 原始记录检查 | 候选落盘前 | 时间戳+级别、Speaker/说话人特征 ≥2 行即拒绝 | 不写候选 |
| 去重 | 候选落盘前 | 内容 hash 决定 candidate id；重复时累加 recurrence/source_sessions | 不生成重复文件 |
| provenance | 候选落盘 | frontmatter 含 source_sessions/recurrence/quality/content_hash | 缺项不落盘 |
| 写入范围 | 晋升前 | 只写批准的目标路径；不直接改 `settings.json`；资产库必须 git 化 | 拒绝写入，交人处理 |

## 人工卡点

| 卡点 | 谁批准 | 批准对象 | 未批准时 |
|---|---|---|---|
| 候选晋升 | 资产 owner / 提交人 | 候选表与目标位置 | 保留在 staging，不写正式资产 |
| hook / permissions 变更 | 用户 | 具体配置变更 | 只生成提案，不修改 `settings.json` |
| 公共级资产入库 | AI 平台团队 + 领域/组件 owner | 资产内容、owner、provenance | 不进入公共组件库 |
| 对外推送 / 发布 | 人 | 具体 commit / PR / 发布动作 | 不执行；只准备命令与说明（R3） |

## 质量门

一条候选进入正式资产库前，以下条件必须**同时满足**（AND，不得用 OR 降级）：

1. **跨 session 复现**：`recurrence >= 2`，且 `source_sessions` 至少两个不同会话；
2. **经验证成功**：有可复跑的测试/运行证据（命令、exit code、输出位置），不能只有自报结论；
3. **命名失败模式**：写清"不这样做会出什么错"，而不是只描述做法；
4. 有明确 owner、适用边界与失效条件；
5. 与现有资产做过语义去重（新增 / 合并 / supersedes 有结论）；
6. 内容已脱敏，且不是原始记录的搬运。

资产库 **必须 git 化**；没有 git 时晋升 blocked，不得跳过 commit 与回滚路径。

## 回滚

- 误晋升：删除正式文件/条目，保留 git 历史；更新 staging INDEX 与蒸馏游标。
- 错误规则导致行为异常：删除或回退对应 rule/skill，记录原因；若是 hook，先移除 settings 条目再删脚本。
- 候选本身有误但已写入：保留 `supersedes` 链，新增修订候选，不做静默覆盖。
