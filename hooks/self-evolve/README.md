# Self-Evolve Hooks

自进化流程的两个 hook：会话结束时把 transcript 入队，会话启动时提醒待确认候选。两者都是轻量动作，不调用模型、不写正式资产。

## Hooks

| 脚本 | 事件 | 输入 | 输出 / 动作 | 失败策略 |
|---|---|---|---|---|
| `distill-enqueue.sh` | `SessionEnd` | `{session_id, transcript_path, ...}` | 预过滤后追加 `~/.claude/self-evolve/queue/jobs.jsonl`，并 fire-and-forget 拉起 worker | 静默 `exit 0` |
| `distill-notify.sh` | `SessionStart` | 事件 JSON | staging 有待确认候选时输出 `additionalContext`；无候选静默 | 静默 `exit 0` |

## 安装

```bash
mkdir -p ~/.claude/hooks/self-evolve
cp hooks/self-evolve/*.sh ~/.claude/hooks/self-evolve/
cp -r skills/session-distiller ~/.claude/skills/
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

- **预过滤**：`transcript` 中 `tool_use` 少于 10 的会话不入队，避免蒸馏 worker 自己的内层会话自指入队。
- **快进快出**：`SessionEnd` 只做解析、计数和追加一行，不在 hook 内做蒸馏；重活交给后台 worker。
- **预算与锁**：worker 用 `mkdir` 原子锁去重，并按 `MAX_JOBS_PER_DAY`（默认 3）限流。
- **失败不阻塞会话**：两个 hook 都是旁路能力，异常时静默退出；不影响用户正常结束或启动会话。

## 验证

```bash
bash hooks/self-evolve/tests/run-tests.sh
```

测试用临时 `HOME`，不会碰到真实的 `~/.claude/self-evolve`。

## 回滚

从 `settings.json` 删除 `SessionEnd` / `SessionStart` 对应条目，删除 `~/.claude/hooks/self-evolve/`。若还要停止后台 worker，删除 `~/.claude/self-evolve/queue/.worker.lock` 并停止对应进程；已生成的 staging 候选可保留。

## 已知限制

- 参考实现的 `worker.sh` 尚未接入 `distill-state` 游标，长 session 可能被重复全量蒸馏；候选去重仍由 staging INDEX 兜底。详见 `flows/self-evolution/README.md`。
- worker 依赖本机 `claude` CLI；无 CLI 或模型不可用时，队列会保留，不影响会话。
