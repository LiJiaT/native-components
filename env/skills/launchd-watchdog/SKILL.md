---
user-invocable: false
name: launchd-watchdog
description: launchd 管理的长驻进程「假活」（进程在、不干活、KeepAlive 永不触发）的诊断与看门狗设计。触发场景：launchd 服务疑似挂了但 ps 显示进程存活、日志长时间停更、KeepAlive 没有拉起进程、设计长驻服务的心跳看门狗、进程内自杀式看门狗（os._exit 交 launchd 重启）、telegram-gateway/ptb 类异步服务静默故障、用户提到"假活"、"看门狗"、"KeepAlive 不触发"、"服务没反应但进程在"。
---

# launchd-watchdog — 长驻服务「假活」诊断与自杀式看门狗

场景：launchd 管理的长驻进程（如 telegram-gateway）进程在、但不干活，KeepAlive 永不触发。

## 假活四步取证链路

1. **进程存活**：`ps aux | grep <进程>` 确认 pid 存活与启动时间。注意 ps 的启动日期可能是干扰项，以日志里「启动」INFO 为准
2. **日志停更时刻**：`tail -100 logs/*.log` 找日志停更时刻 = 真实死亡点（之后的报错若后来又出现，说明自愈过）
3. **TCP 僵尸连接**：`lsof -p <pid> -i -a` 看连接状态，**CLOSED 僵尸连接 = 事件循环冻结铁证**
4. **框架层排查**：逐项核对超时配置（是否全阶段有界）、重试上限（会不会重试耗尽自杀）、有无阻塞式同步调用

## 进程内自杀式看门狗设计

用进程内看门狗而非外部监控：

- asyncio 循环里**每 60s 发一次全链路免费探测**（Telegram 用 `bot.get_me()`，走 proxy→API→token 完整链路；确认无缓存、零 LLM 消耗），每个实例独立记 last_ok
- 距上次成功超过阈值（如 300s，env 可覆盖；启动即计时，天然覆盖带宽限期）→ `log.critical` + `os._exit(1)` 自杀，交给 launchd KeepAlive 拉起
- **核心要点**：KeepAlive 只在进程退出时触发，所以唯一可靠的假活自救是**进程自己退出**；看门狗必须探测真实下游而非只看进程内状态

## dry-run 三场景验证

1. 持续失败 → 进程以退出码 1 退出
2. 持续健康 → 稳定循环
3. 抖动后恢复 → 出现恢复日志

<!-- 来源: session 763ea9db, cand-cc8c1d, 理由: 12 天假活排查走通的『进程在心跳停』取证链路与看门狗设计模式，多步且跨框架可迁移 -->
