# 跨日唤醒调度

worker 的每日预算 hold 会把任务留在 `~/.claude/self-evolve/queue/jobs.jsonl` 并写 `queue/HOLD`。
SessionStart hook 会尝试唤醒一次，但"第二天完全没有新会话"时仍需外部调度器。

## Windows（任务计划程序）

以当前用户创建每天 09:00 的任务，程序填 Git Bash：

```powershell
schtasks /Create /SC DAILY /ST 09:00 /TN "claude-self-evolve-wake" /TR "\"C:\Program Files\Git\bin\bash.exe\" -lc \"bash ~/.claude/skills/session-distiller/scripts/worker.sh\"" /F
```

删除：`schtasks /Delete /TN "claude-self-evolve-wake" /F`

## macOS / Linux（cron）

```cron
0 9 * * * /bin/bash "$HOME/.claude/skills/session-distiller/scripts/worker.sh" >> "$HOME/.claude/self-evolve/queue/worker.log" 2>&1
```

## 验证

1. 制造 `queue/HOLD` 与一条待处理任务；
2. 手动执行上面的 worker 命令；
3. 检查 `queue/worker.log` 出现 `ok`/`error`/`hold` 之一，且 `count-<date>` 更新；
4. 若当日预算仍满，任务应保留而非丢失。
