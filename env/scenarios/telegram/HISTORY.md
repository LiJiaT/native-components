# Telegram 网关 · 时间线

> 追加式记录：决策、事故、里程碑。最新在下。当前状态见 `STATE.md`。

## 2026-09-24
- OpenClaw 停用（bootout），本体与配置保留作回滚保险（**至 2026-10 下旬**，到期归档）。

## 2026-10-08
- 四身份（travel/coach/alfred/overseer）全部迁至 cc-connect（brew 安装）；自研 gateway 同日全面停机。
- 旧 plist 与 .env 归档至 `~/.claude/telegram-gateway/backup-20261008/`（.env 0600）。

## 2026-10-12
- **事故复盘：`bootout` 停服不抗重启**。10-09 21:22 内核 panic 重启后 launchd 重载全部 plist，已 bootout 的旧 gateway 和 openclaw gateway 双双复活，与 cc-connect 同 token 抢 getUpdates，当日报 250 次 Conflict，消息延迟 10-15 分钟。
- 修复：`bootout` + `launchctl disable gui/$(id -u)/<label>`（disable 持久化、跨重启生效）。**铁律：下线 launchd 服务必须 bootout + disable 双保险，只 bootout 等于没拆**。
- 同日确认 pmset `sleep 1` 旧值导致 Mac 全天碎片化睡眠，已改 `pmset -c sleep 0`。
- overseer 改为项目级直通（IM 审批消息送不到用户手机时 bot 死等，实测挂 5h42m）。

## 2026-10-15
- 观察期 7 天无消息丢失、无手工重启、审批 UX 可接受，**迁移定论为成功**（对比基线：旧系统心跳探测失败 ~130 次/天）。
- Phase 5 深度清理完成：`.venv`/`__pycache__`/launchd 旧日志已清，`/tmp/cc-connect-spike` 已清，README/CONTEXT 标注退役。

## 2026-10-17
- **凭证注入自持**：launch.sh 改为 source `~/.cc-connect/.env`（0600，5 个 key 从 backup-20261008/.env 抽取）。起因：launch.sh 原指向旧 gateway `.env`，Phase 5 清理删除后路径失效——潜伏雷，此前服务自 10-08 起未重启所以没炸，kickstart 重启即暴露。**教训：删除被其他活跃组件 source 的文件前，先 grep 引用。**
- **`/model` 切模型启用**（两处配置缺一不可，详见 `STATE.md`）。

## 2026-10-18
- **回合挂死 + busy 锁死实战**：机理 / 鉴别 / 恢复三步见 `STATE.md` 故障模式节。

## 2026-10-19
- **看门狗上线**：`~/.cc-connect/watchdog.py` + launchd `com.lidaonian.cc-connect-watchdog`（每 5 分钟）。
- **图片 400 锁死复盘**：往纯文本模型发图片 → 400 → 会话锁不释放 → 消息永久排队（实测 alfred 挂 7.5 小时、3 条积压）。
- 起草 `~/.cc-connect/upstream-issue-draft.md`。
- **根因查清 + 上游评论**：忙锁泄漏是上游已知 bug（#1829，已关闭，修复 commit `0dd7357202`：generation 计数忙锁 + stale-break 自愈 + stop-path release），但**只进 v1.5.1-beta.2+，brew stable 1.5.0 没有**。已在 #1829 评论补充 v1.5.0 稳定版复现数据并请求 backport：<https://github.com/chenhg5/cc-connect/issues/1829#issuecomment-6266498429>。原「发新 issue」计划取消（避免重复）。同时修正此前错误结论：**v1.5.0 上 `/stop` 不能释放忙锁**。
- **升级 cc-connect v1.5.0 → v1.5.1-beta.3**：GitHub release 二进制放 `~/.cc-connect/bin/cc-connect`，launch.sh 指向它；brew 1.5.0 原样保留作回滚（`launch.sh.bak-pre-beta3`）。验证：4 bot 重连、命令数 62→88、webhook 自测回合 2.2s 完成、config 未被改写。看门狗保留作第二层保险。
