# 跨日唤醒调度（中文说明）

见 `README.md`。核心：每日预算用尽后任务不丢弃，写 `queue/HOLD`；SessionStart 会尝试唤醒，
但没有新会话时需要系统级定时任务（Windows Task Scheduler / cron）在次日调用 worker。
