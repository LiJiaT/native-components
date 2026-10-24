# Self-Evolve Hooks

自进化流程的两个 hook：会话结束时把 transcript 入队，会话启动时提醒待确认候选。两者都是轻量动作，不调用模型、不写正式资产。

## Hooks

| 脚本 | 事件 | 输入 | 输出 / 动作 | 失败策略 |
|---|---|---|---|---|
| `distill-enqueue.sh` + `enqueue.py` | `SessionEnd` | `{session_id, transcript_path, ...}` | JSON 逐行解析、L0 阈值过滤、安全追加 `queue/jobs.jsonl`，fire-and-forget 拉起 worker | 静默 `exit 0` + `queue/enqueue.log` |
| `distill-notify.sh` | `SessionStart` | 事件 JSON | `queue/HOLD` 时尝试唤醒 worker；staging 有待确认候选时输出 `additionalContext` | 静默 `exit 0` |

## 安装

```bash
python -X utf8 tools/install.py --component self-evolve-hooks --component session-distiller
mkdir -p ~/.claude/self-evolve/{queue,staging,distill-state}
```

`distill-enqueue.sh` 依赖 `~/.claude/skills/session-distiller/scripts/worker.sh`。把 `settings.example.json` 的 `hooks` 配置合并进 `~/.claude/settings.json`。Windows 使用 `win/*.cmd` 包装器，并按其头部注释调整 Python / Git 路径。

运行时目录（不在本仓库分发）：

```text
~/.claude/self-evolve/
├── queue/jobs.jsonl          # 待蒸馏 session
├── queue/count-YYYY-MM-DD    # 每日预算计数
├── staging/                  # 候选与 INDEX.md
└── distill-state/            # 每个 session 的蒸馏游标
```

## 设计要点

- **安全解析**：`enqueue.py` 不 `eval` 任何字段；逐行解析 transcript 的 `message.content`，兼容空格、单行多工具、Windows 反斜杠/含空格路径。普通会话字段只当数据。
- **预过滤与 L0 同界**：`tools>=40 OR edits>=3 OR corrections>=2`；排除蒸馏 meta-session。不会把"编辑 3 次"的合格会话提前丢掉。
- **快进快出**：`SessionEnd` 只解析、计数、追加一行；重活交给 `worker.py`。
- **预算与锁**：worker 目录锁含 PID/host/时间，陈旧锁可恢复；`MAX_JOBS_PER_DAY` 默认 3，超限任务 held 并写 `queue/HOLD`。
- **失败保留**：模型非零/超时/空输出/非法 JSON 都保留任务并记 stderr；连续 3 次进 `dead-letter.jsonl`。
- **失败不阻塞会话**：两个 hook 都是旁路能力，异常时静默退出；不影响用户正常结束或启动会话。

## 验证

```bash
bash hooks/self-evolve/tests/run-tests.sh
```

测试用临时 `HOME`，不会碰到真实的 `~/.claude/self-evolve`。

## 回滚

从 `settings.json` 删除 `SessionEnd` / `SessionStart` 对应条目，删除 `~/.claude/hooks/self-evolve/`。若还要停止后台 worker，删除 `~/.claude/self-evolve/queue/.worker.lock` 并停止对应进程；已生成的 staging 候选可保留。

## 已知限制

- 跨日且完全没有新会话时，SessionStart 不会触发；需按 [`flows/self-evolution/scheduler/`](../../flows/self-evolution/scheduler/README.md) 配置 cron / Task Scheduler。
- worker 依赖本机 `claude` CLI；无 CLI 或模型不可用时，队列会保留，不影响会话。
- 后台模型只被要求不要读取 transcript 全文，但 `--allowedTools` 的权限边界仍依赖 harness；合成秘密 canary 的只读范围测试尚未自动化。
