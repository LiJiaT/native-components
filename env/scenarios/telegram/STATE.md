# Telegram 网关 · 当前状态

> 场景登记见同目录 `scenario.json`；按日期的时间线见 `HISTORY.md`。最后更新：2026-10-19

## 现役系统

**cc-connect v1.5.1-beta.3**（2026-10-19 从 brew 稳定版 1.5.0 升级；二进制在 `~/.cc-connect/bin/cc-connect`，GitHub release tarball，commit e27354b2）。升级原因：v1.5.0 有忙锁永久泄漏 bug（上游 #1829），beta.2+ 才带 stale-lock 自愈。brew 的 1.5.0 保留未动，**回滚 = 把 launch.sh 恢复为 `launch.sh.bak-pre-beta3`**。四身份 travel / coach / alfred / overseer 全部在线（2026-10-08 切换，2026-10-15 观察期 7 天通过）。自研 gateway 已退役，仅存档于 `~/.claude/telegram-gateway/`。

## 运维面

- 配置 `~/.cc-connect/config.toml`（0600，凭证全 `${ENV}` 占位符）
- 启动器 `~/.cc-connect/launch.sh`（source `~/.cc-connect/.env` 注入凭证）
- 日志 `~/.cc-connect/logs/cc-connect.log`
- launchd `com.lidaonian.cc-connect`（KeepAlive，kill 自愈实测 22s）
- 自测 webhook `127.0.0.1:9111`
- 工作区 `~/cc-personal/{alfred,fitness-coach,travel-planner,overseer}/`
- 机制细节见 skill `cc-connect-bridge`

## 看门狗（2026-10-19 上线）

`~/.cc-connect/watchdog.py` + launchd `com.lidaonian.cc-connect-watchdog`（每 5 分钟）。检测「消息排队 >10 分钟无人处理 **且** 无 turn complete **且** 子进程树无进展」→ TG 通知 + 自动重启，15 分钟冷却。
**注意：v1.5.0 上 `/stop` 救不了忙锁**——忙锁是独立的 `Session.busy`，由挂死回合持有；上游 #1829 实测只有重启能清。修复 commit `0dd7357202`（stale-lock 自愈 + stop-path release）只在 v1.5.1-beta.2+，brew 稳定版仍是 1.5.0。

## 关键配置事实

- 各 project `cmd = "claude --setting-sources project"` 屏蔽全局 settings——否则用户全局 allow-all（`Bash(*)`/`Write(*)`）会绕过 IM 审批。
- 审批 = 回复"允许/拒绝/允许所有"文字；`enable_reactions` ⚡ 收到确认。
- **overseer 2026-10-12 起改为项目级直通**（`~/cc-personal/overseer/.claude/settings.json` allow Bash/Write/Edit + 小 deny 清单）；travel/coach/alfred 仍逐次审批。
- **`/model` 切模型需两处配置缺一不可**：每个 project 的 `[projects.agent]` 显式 `provider_refs = ["ark"]` **且** `[projects.agent.options]` 写 `provider = "ark"`（`GetProviderModels` 只认 activeIdx，不写此项 activeIdx 恒 -1）。漏任一个 → `/model` 落到内置 Sonnet/Opus 兜底清单（鉴别标志）。日志确认标志：启动时 4 条 `claudecode: provider switched provider=ark`。
- ark provider 5 档模型（全部 1M 上下文带 `[1m]` 后缀）：flash(GLM-5.3-Flash) / glm(GLM-5.3) / minimax(MiniMax-M3) / dsv(DeepSeek-V4.1-Flash) / kimi(Kimi-K3)。

## 故障模式：回合挂死 + busy 锁死

- **表象**：bot 反复显示 typing、消息注入不生效。
- **机理**：claude 子进程的 ark 流被代理客户端重启掐断（无 TCP 连接、0% CPU），CLI 无超时兜底永不结束回合；cc-connect 会话锁 busy，后续消息全部 `queued for busy session` 无限排队。
- **鉴别**：日志有 `processing message` 但无 `session spawned`/`turn complete`；`ps` 查 claude 子进程 `lsof` 无 TCP。
- **恢复三步**：① kill 挂死的 claude 子进程（`--setting-sources project` 那个）；② cc-connect 的 busy 标志**不随子进程死亡清除**，必须重启 cc-connect 本体（launchd KeepAlive 自动拉起；重启后队列消息**不重放**，需手动重发）；③ webhook 自测 `turn complete` 收尾。
- **新触发源**：往**纯文本模型**发图片会 400（`Model only support text input`），该回合报错后会话锁**不释放**，之后消息永久排队（实测 alfred 挂 7.5 小时、3 条积压）。视觉可用：GLM-5.3-Flash / DeepSeek-V4.1-Flash / doubao 系列；**GLM-5.3（旗舰）是纯文本**。
- `reset_on_idle_mins` 救不了锁死——源码里 busy 分支在队列化后直接 return，`maybeAutoResetSessionOnIdle` 只在抢锁成功的路径上执行（core/engine.go ~3025-3048）。
- webhook 自测注意：测试 prompt 会落到正常 TG 会话里，用户看得见。

## 遗留待办

- **AMAP_API_KEY** 注入 cc-connect 环境变量（travel 的 personal-map 依赖；原 key 在 `~/.openclaw/openclaw.json` → `skills.entries.personal-map.apiKey`；memory 另记 key 已在 `~/.zshrc`，两处需核实统一）
- 语音条转写（方舟 `doubao-seed-asr-2.0`，走 `openspeech.bytedance.com` 独立端点）—— v1.1 候选
- 主动推送（行前提醒）—— v1.1 候选
- 核实 cc-personal git 基线提交（2026-10-07 已引用 commit `63af2b4`，疑已完成，核实后清除）

## 相关文档（细节下沉，勿在此重复维护）

- 自研 gateway 历史 / PTB 22.8 网络层事实 / 实测坑 / 系统性 review 结论：`~/.claude/telegram-gateway/docs/history-and-ptb-facts.md`
- 迁移执行记录与偏差：`~/.claude/telegram-gateway/docs/migration-cc-connect-plan.md`
- cc-connect 机制（config / launchd / webhook）：skill `cc-connect-bridge`
